"""
Repository for task relationship operations.

This module extracts relationship-related database operations from TodoDatabase
to improve separation of concerns and maintainability.
"""
import logging
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)


class RelationshipRepository:
    """Repository for task relationship operations."""
    
    def __init__(
        self,
        db_type: str,
        get_connection: Callable[[], Any],
        adapter: Any,
        execute_insert: Callable[[Any, str, tuple], int],
        execute_with_logging: Callable[[Any, str, tuple], Any]
    ):
        """
        Initialize RelationshipRepository.
        
        Args:
            db_type: Database type ('sqlite' or 'postgresql')
            get_connection: Function to get database connection
            adapter: Database adapter (for closing connections)
            execute_insert: Function to execute INSERT queries and return ID
            execute_with_logging: Function to execute queries with logging
        """
        self.db_type = db_type
        self._get_connection = get_connection
        self.adapter = adapter
        self._execute_insert = execute_insert
        self._execute_with_logging = execute_with_logging
    
    def _check_circular_dependency(
        self,
        cursor: Any,
        blocker_task_id: int,
        blocked_task_id: int,
        exclude_parent_task_id: Optional[int] = None,
        exclude_child_task_id: Optional[int] = None
    ) -> bool:
        """
        Check if creating a blocked_by relationship from blocked_task_id to blocker_task_id
        would create a circular dependency.
        
        Args:
            cursor: Database cursor
            blocker_task_id: The task that would block blocked_task_id
            blocked_task_id: The task that would be blocked by blocker_task_id
            exclude_parent_task_id: Optional parent task ID to exclude from the check
            exclude_child_task_id: Optional child task ID to exclude from the check
        
        Returns:
            True if a circular dependency would be created, False otherwise
        """
        # Use BFS to check if blocker_task_id (or anything it's blocked by) can reach blocked_task_id
        visited = set()
        queue = [blocker_task_id]
        
        while queue:
            current_task_id = queue.pop(0)
            
            # If we reach the blocked task, we have a cycle
            if current_task_id == blocked_task_id:
                return True
            
            if current_task_id in visited:
                continue
            visited.add(current_task_id)
            
            # Find all tasks that this task is blocked by
            # For blocked_by: parent is blocked by child
            # So if A is blocked by B: parent=A, child=B means B blocks A
            # To find what blocks current_task_id, look for relationships where
            # parent_task_id = current_task_id, which gives us child_task_id (the blocker)
            # Exclude the relationship we're checking if provided
            if exclude_parent_task_id is not None and exclude_child_task_id is not None:
                query = """
                    SELECT child_task_id
                    FROM task_relationships
                    WHERE parent_task_id = ? AND relationship_type = 'blocked_by'
                    AND NOT (parent_task_id = ? AND child_task_id = ?)
                """
                params = (current_task_id, exclude_parent_task_id, exclude_child_task_id)
            else:
                query = """
                    SELECT child_task_id
                    FROM task_relationships
                    WHERE parent_task_id = ? AND relationship_type = 'blocked_by'
                """
                params = (current_task_id,)
            
            self._execute_with_logging(cursor, query, params)
            blocking_tasks = [row[0] for row in cursor.fetchall()]
            
            # Also find what current_task_id blocks (tasks that are blocked by current_task_id)
            # Look for relationships where child_task_id = current_task_id
            # This gives us parent_task_id (tasks blocked by current_task_id)
            if exclude_parent_task_id is not None and exclude_child_task_id is not None:
                query = """
                    SELECT parent_task_id
                    FROM task_relationships
                    WHERE child_task_id = ? AND relationship_type = 'blocked_by'
                    AND NOT (parent_task_id = ? AND child_task_id = ?)
                """
                params = (current_task_id, exclude_parent_task_id, exclude_child_task_id)
            else:
                query = """
                    SELECT parent_task_id
                    FROM task_relationships
                    WHERE child_task_id = ? AND relationship_type = 'blocked_by'
                """
                params = (current_task_id,)
            
            self._execute_with_logging(cursor, query, params)
            # Tasks blocked by current_task_id (current_task_id blocks these)
            blocked_by_current = [row[0] for row in cursor.fetchall()]
            
            # Also check for "blocking" relationships (which are inverse of blocked_by)
            # Exclude the relationship we're checking if provided
            if exclude_parent_task_id is not None and exclude_child_task_id is not None:
                query = """
                    SELECT parent_task_id
                    FROM task_relationships
                    WHERE child_task_id = ? AND relationship_type = 'blocking'
                    AND NOT (parent_task_id = ? AND child_task_id = ?)
                """
                params = (current_task_id, exclude_parent_task_id, exclude_child_task_id)
            else:
                query = """
                    SELECT parent_task_id
                    FROM task_relationships
                    WHERE child_task_id = ? AND relationship_type = 'blocking'
                """
                params = (current_task_id,)
            
            self._execute_with_logging(cursor, query, params)
            # "blocking" relationship means: if A blocks B, then B is blocked_by A
            blocking_from_blocking = [row[0] for row in cursor.fetchall()]
            
            # Add all blocking tasks to the queue (what blocks current, and what current blocks)
            for task_id in blocking_tasks + blocked_by_current + blocking_from_blocking:
                if task_id not in visited:
                    queue.append(task_id)
        
        return False
    
    def create(
        self,
        parent_task_id: int,
        child_task_id: int,
        relationship_type: str,
        agent_id: str
    ) -> int:
        """
        Create a relationship between two tasks.
        
        Args:
            parent_task_id: Parent task ID
            child_task_id: Child task ID
            relationship_type: Relationship type (subtask, blocking, blocked_by, followup, related)
            agent_id: Agent ID creating the relationship
        
        Returns:
            Relationship ID
        
        Raises:
            ValueError: If agent_id is missing or circular dependency detected
        """
        if not agent_id:
            raise ValueError("agent_id is required for creating relationships")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Check for circular dependencies for blocking relationships FIRST
            # This ensures we catch circular dependencies before checking if relationship exists
            if relationship_type in ("blocked_by", "blocking"):
                # First, check if the inverse relationship already exists (direct cycle)
                if relationship_type == "blocked_by":
                    # Check if the inverse (blocking) relationship exists with same parent/child
                    query = """
                        SELECT id FROM task_relationships
                        WHERE parent_task_id = ? AND child_task_id = ? AND relationship_type = 'blocking'
                    """
                    params = (parent_task_id, child_task_id)
                    self._execute_with_logging(cursor, query, params)
                    if cursor.fetchone():
                        raise ValueError(
                            f"Circular dependency detected: Cannot create blocked_by relationship "
                            f"from task {parent_task_id} to task {child_task_id}. "
                            f"Task {parent_task_id} already blocks task {child_task_id} (inverse relationship exists)."
                        )
                    # Also check if the inverse (blocking) relationship exists: child blocks parent
                    query = """
                        SELECT id FROM task_relationships
                        WHERE parent_task_id = ? AND child_task_id = ? AND relationship_type = 'blocking'
                    """
                    params = (child_task_id, parent_task_id)
                    self._execute_with_logging(cursor, query, params)
                    if cursor.fetchone():
                        raise ValueError(
                            f"Circular dependency detected: Cannot create blocked_by relationship "
                            f"from task {parent_task_id} to task {child_task_id}. "
                            f"Task {child_task_id} already blocks task {parent_task_id} (inverse relationship exists)."
                        )
                    # Check if child_task_id (or anything blocking it) can reach parent_task_id
                    if self._check_circular_dependency(cursor, child_task_id, parent_task_id, 
                                                       exclude_parent_task_id=parent_task_id, 
                                                       exclude_child_task_id=child_task_id):
                        raise ValueError(
                            f"Circular dependency detected: Cannot create blocked_by relationship "
                            f"from task {parent_task_id} to task {child_task_id}. "
                            f"Task {child_task_id} (or something blocking it) already blocks task {parent_task_id}."
                        )
                elif relationship_type == "blocking":
                    # Check if the inverse (blocked_by) relationship exists with same parent/child
                    query = """
                        SELECT id FROM task_relationships
                        WHERE parent_task_id = ? AND child_task_id = ? AND relationship_type = 'blocked_by'
                    """
                    params = (parent_task_id, child_task_id)
                    self._execute_with_logging(cursor, query, params)
                    if cursor.fetchone():
                        raise ValueError(
                            f"Circular dependency detected: Cannot create blocking relationship "
                            f"from task {parent_task_id} to task {child_task_id}. "
                            f"Task {parent_task_id} is already blocked by task {child_task_id} (inverse relationship exists)."
                        )
                    # Also check if the inverse (blocked_by) relationship exists: child is blocked_by parent
                    query = """
                        SELECT id FROM task_relationships
                        WHERE parent_task_id = ? AND child_task_id = ? AND relationship_type = 'blocked_by'
                    """
                    params = (child_task_id, parent_task_id)
                    self._execute_with_logging(cursor, query, params)
                    if cursor.fetchone():
                        raise ValueError(
                            f"Circular dependency detected: Cannot create blocking relationship "
                            f"from task {parent_task_id} to task {child_task_id}. "
                            f"Task {child_task_id} is already blocked by task {parent_task_id} (inverse relationship exists)."
                        )
                    # Check if parent_task_id (or anything blocking it) can reach child_task_id
                    if self._check_circular_dependency(cursor, parent_task_id, child_task_id,
                                                       exclude_parent_task_id=parent_task_id,
                                                       exclude_child_task_id=child_task_id):
                        raise ValueError(
                            f"Circular dependency detected: Cannot create blocking relationship "
                            f"from task {parent_task_id} to task {child_task_id}. "
                            f"Task {parent_task_id} (or something blocking it) already blocks task {child_task_id}."
                        )
            
            # Check if relationship already exists (idempotent behavior)
            # Only check after circular dependency validation passes
            query = """
                SELECT id FROM task_relationships
                WHERE parent_task_id = ? AND child_task_id = ? AND relationship_type = ?
            """
            params = (parent_task_id, child_task_id, relationship_type)
            self._execute_with_logging(cursor, query, params)
            existing = cursor.fetchone()
            
            # If relationship already exists and passed circular dependency check, return existing ID
            if existing:
                # Relationship already exists, return existing ID (don't record in history again)
                rel_id = existing[0]
                logger.info(f"Relationship {relationship_type} from task {parent_task_id} to task {child_task_id} already exists (ID: {rel_id})")
                conn.commit()
                return rel_id
            
            rel_id = self._execute_insert(cursor, """
                INSERT INTO task_relationships (parent_task_id, child_task_id, relationship_type)
                VALUES (?, ?, ?)
            """, (parent_task_id, child_task_id, relationship_type))
            
            # Record in history for both tasks
            query = """
                INSERT INTO change_history (task_id, agent_id, change_type, field_name, new_value)
                VALUES (?, ?, 'relationship_added', 'relationship', ?)
            """
            params = (parent_task_id, agent_id, f"{relationship_type}:{child_task_id}")
            self._execute_with_logging(cursor, query, params)
            
            # Auto-update blocking status
            if relationship_type == "blocked_by":
                query = """
                    UPDATE tasks SET task_status = 'blocked', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """
                params = (parent_task_id,)
                self._execute_with_logging(cursor, query, params)
            
            conn.commit()
            logger.info(f"Created relationship {relationship_type} from task {parent_task_id} to {child_task_id} by agent {agent_id}")
            return rel_id
        finally:
            self.adapter.close(conn)
    
    def get_related_tasks(
        self,
        task_id: int,
        relationship_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get tasks related to a given task.
        
        Args:
            task_id: Task ID
            relationship_type: Optional relationship type filter
        
        Returns:
            List of relationship dictionaries with task information
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = ["(parent_task_id = ? OR child_task_id = ?)"]
            params = [task_id, task_id]
            
            if relationship_type:
                conditions.append("relationship_type = ?")
                params.append(relationship_type)
            
            query = f"""
                SELECT tr.*, 
                       t1.title as parent_title,
                       t2.title as child_title
                FROM task_relationships tr
                JOIN tasks t1 ON tr.parent_task_id = t1.id
                JOIN tasks t2 ON tr.child_task_id = t2.id
                WHERE {' AND '.join(conditions)}
            """
            self._execute_with_logging(cursor, query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def get_blocking_tasks(self, task_id: int) -> List[Dict[str, Any]]:
        """
        Get tasks that are blocking the given task.
        
        Args:
            task_id: Task ID
        
        Returns:
            List of task dictionaries that are blocking this task
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = """
                SELECT t.* FROM tasks t
                JOIN task_relationships tr ON t.id = tr.parent_task_id
                WHERE tr.child_task_id = ? AND tr.relationship_type = 'blocked_by'
            """
            params = (task_id,)
            self._execute_with_logging(cursor, query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
