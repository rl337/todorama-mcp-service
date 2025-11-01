"""
Database schema and management for TODO service.
"""
import sqlite3
import os
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Task type enumeration."""
    CONCRETE = "concrete"
    ABSTRACT = "abstract"
    EPIC = "epic"


class TaskStatus(Enum):
    """Task status enumeration."""
    AVAILABLE = "available"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class VerificationStatus(Enum):
    """Verification status enumeration."""
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class RelationshipType(Enum):
    """Task relationship type enumeration."""
    SUBTASK = "subtask"
    BLOCKING = "blocking"
    BLOCKED_BY = "blocked_by"
    FOLLOWUP = "followup"
    RELATED = "related"


class TodoDatabase:
    """SQLite database for TODO management."""
    
    def __init__(self, db_path: str):
        """Initialize database connection and create schema if needed."""
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_schema()
    
    def _ensure_db_directory(self):
        """Ensure database directory exists."""
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign keys
        return conn
    
    def _init_schema(self):
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Projects table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    origin_url TEXT,
                    local_path TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tasks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    title TEXT NOT NULL,
                    task_type TEXT NOT NULL CHECK(task_type IN ('concrete', 'abstract', 'epic')),
                    task_instruction TEXT NOT NULL,
                    verification_instruction TEXT NOT NULL,
                    task_status TEXT NOT NULL DEFAULT 'available' 
                        CHECK(task_status IN ('available', 'in_progress', 'complete', 'blocked', 'cancelled')),
                    verification_status TEXT NOT NULL DEFAULT 'unverified'
                        CHECK(verification_status IN ('unverified', 'verified')),
                    assigned_agent TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    notes TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
                )
            """)
            
            # Task relationships table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_task_id INTEGER NOT NULL,
                    child_task_id INTEGER NOT NULL,
                    relationship_type TEXT NOT NULL
                        CHECK(relationship_type IN ('subtask', 'blocking', 'blocked_by', 'followup', 'related')),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (child_task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    UNIQUE(parent_task_id, child_task_id, relationship_type)
                )
            """)
            
            # Change history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS change_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    change_type TEXT NOT NULL
                        CHECK(change_type IN ('created', 'locked', 'unlocked', 'updated', 'completed', 'verified', 'status_changed', 'relationship_added')),
                    field_name TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    notes TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                )
            """)
            
            # Indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(task_status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_agent)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_parent ON task_relationships(parent_task_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_child ON task_relationships(child_task_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_change_history_task ON change_history(task_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_change_history_agent ON change_history(agent_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_change_history_created ON change_history(created_at)")
            
            conn.commit()
            logger.info(f"Database schema initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize schema: {e}")
            raise
        finally:
            conn.close()
    
    def create_project(
        self,
        name: str,
        local_path: str,
        origin_url: Optional[str] = None,
        description: Optional[str] = None
    ) -> int:
        """Create a new project and return its ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO projects (name, local_path, origin_url, description)
                VALUES (?, ?, ?, ?)
            """, (name, local_path, origin_url, description))
            project_id = cursor.lastrowid
            conn.commit()
            logger.info(f"Created project {project_id}: {name}")
            return project_id
        finally:
            conn.close()
    
    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get a project by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()
    
    def get_project_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a project by name."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()
    
    def list_projects(self) -> List[Dict[str, Any]]:
        """List all projects."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def create_task(
        self,
        title: str,
        task_type: str,
        task_instruction: str,
        verification_instruction: str,
        agent_id: str,
        project_id: Optional[int] = None,
        notes: Optional[str] = None
    ) -> int:
        """Create a new task and return its ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (title, task_type, task_instruction, verification_instruction, project_id, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (title, task_type, task_instruction, verification_instruction, project_id, notes))
            task_id = cursor.lastrowid
            
            # Record creation in history
            cursor.execute("""
                INSERT INTO change_history (task_id, agent_id, change_type, notes)
                VALUES (?, ?, 'created', ?)
            """, (task_id, agent_id, notes))
            
            conn.commit()
            logger.info(f"Created task {task_id}: {title} by agent {agent_id}")
            return task_id
        finally:
            conn.close()
    
    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get a task by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()
    
    def query_tasks(
        self,
        task_type: Optional[str] = None,
        task_status: Optional[str] = None,
        assigned_agent: Optional[str] = None,
        project_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query tasks with filters."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            if task_type:
                conditions.append("task_type = ?")
                params.append(task_type)
            if task_status:
                conditions.append("task_status = ?")
                params.append(task_status)
            if assigned_agent:
                conditions.append("assigned_agent = ?")
                params.append(assigned_agent)
            if project_id is not None:
                conditions.append("project_id = ?")
                params.append(project_id)
            
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            query = f"SELECT * FROM tasks {where_clause} ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def lock_task(self, task_id: int, agent_id: str) -> bool:
        """Lock a task for an agent (set to in_progress). Returns True if successful."""
        if not agent_id:
            raise ValueError("agent_id is required for locking tasks")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get current status for history
            cursor.execute("SELECT task_status, assigned_agent FROM tasks WHERE id = ?", (task_id,))
            current = cursor.fetchone()
            old_status = current["task_status"] if current else None
            
            # Only lock if task is available
            cursor.execute("""
                UPDATE tasks 
                SET task_status = 'in_progress', 
                    assigned_agent = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND task_status = 'available'
            """, (agent_id, task_id))
            success = cursor.rowcount > 0
            
            if success:
                # Record in history
                cursor.execute("""
                    INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                    VALUES (?, ?, 'locked', 'task_status', ?, 'in_progress')
                """, (task_id, agent_id, old_status))
            
            conn.commit()
            if success:
                logger.info(f"Task {task_id} locked by agent {agent_id}")
            return success
        finally:
            conn.close()
    
    def unlock_task(self, task_id: int, agent_id: str):
        """Unlock a task (set back to available)."""
        if not agent_id:
            raise ValueError("agent_id is required for unlocking tasks")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get current assigned agent for verification
            cursor.execute("SELECT assigned_agent, task_status FROM tasks WHERE id = ?", (task_id,))
            current = cursor.fetchone()
            if not current:
                raise ValueError(f"Task {task_id} not found")
            
            old_status = current["task_status"]
            old_agent = current["assigned_agent"]
            
            cursor.execute("""
                UPDATE tasks 
                SET task_status = 'available',
                    assigned_agent = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (task_id,))
            
            # Record in history
            cursor.execute("""
                INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                VALUES (?, ?, 'unlocked', 'task_status', ?, 'available')
            """, (task_id, agent_id, old_status))
            
            conn.commit()
            logger.info(f"Task {task_id} unlocked by agent {agent_id}")
        finally:
            conn.close()
    
    def complete_task(self, task_id: int, agent_id: str, notes: Optional[str] = None):
        """Mark a task as complete."""
        if not agent_id:
            raise ValueError("agent_id is required for completing tasks")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get current status for history
            cursor.execute("SELECT task_status FROM tasks WHERE id = ?", (task_id,))
            current = cursor.fetchone()
            old_status = current["task_status"] if current else None
            
            cursor.execute("""
                UPDATE tasks 
                SET task_status = 'complete',
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    notes = COALESCE(?, notes)
                WHERE id = ?
            """, (notes, task_id))
            
            # Record in history
            cursor.execute("""
                INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value, notes)
                VALUES (?, ?, 'completed', 'task_status', ?, 'complete', ?)
            """, (task_id, agent_id, old_status, notes))
            
            conn.commit()
            logger.info(f"Task {task_id} marked as complete by agent {agent_id}")
        finally:
            conn.close()
    
    def verify_task(self, task_id: int, agent_id: str) -> bool:
        """Mark a task as verified (verification check passed)."""
        if not agent_id:
            raise ValueError("agent_id is required for verifying tasks")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get current verification status for history
            cursor.execute("SELECT verification_status FROM tasks WHERE id = ?", (task_id,))
            current = cursor.fetchone()
            old_status = current["verification_status"] if current else None
            
            cursor.execute("""
                UPDATE tasks 
                SET verification_status = 'verified',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (task_id,))
            
            # Record in history
            cursor.execute("""
                INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                VALUES (?, ?, 'verified', 'verification_status', ?, 'verified')
            """, (task_id, agent_id, old_status))
            
            conn.commit()
            logger.info(f"Task {task_id} verified by agent {agent_id}")
            return True
        finally:
            conn.close()
    
    def create_relationship(
        self,
        parent_task_id: int,
        child_task_id: int,
        relationship_type: str,
        agent_id: str
    ) -> int:
        """Create a relationship between two tasks."""
        if not agent_id:
            raise ValueError("agent_id is required for creating relationships")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO task_relationships (parent_task_id, child_task_id, relationship_type)
                VALUES (?, ?, ?)
            """, (parent_task_id, child_task_id, relationship_type))
            rel_id = cursor.lastrowid
            
            # Record in history for both tasks
            cursor.execute("""
                INSERT INTO change_history (task_id, agent_id, change_type, field_name, new_value)
                VALUES (?, ?, 'relationship_added', 'relationship', ?)
            """, (parent_task_id, agent_id, f"{relationship_type}:{child_task_id}"))
            
            # Auto-update blocking status
            if relationship_type == "blocked_by":
                cursor.execute("""
                    UPDATE tasks SET task_status = 'blocked', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (parent_task_id,))
            
            conn.commit()
            logger.info(f"Created relationship {relationship_type} from task {parent_task_id} to {child_task_id} by agent {agent_id}")
            return rel_id
        finally:
            conn.close()
    
    def get_change_history(
        self,
        task_id: Optional[int] = None,
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get change history with optional filters."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            if task_id:
                conditions.append("task_id = ?")
                params.append(task_id)
            if agent_id:
                conditions.append("agent_id = ?")
                params.append(agent_id)
            
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            query = f"SELECT * FROM change_history {where_clause} ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_agent_stats(
        self,
        agent_id: str,
        task_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get statistics for an agent's performance."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Get completed tasks count
            completed_query = """
                SELECT COUNT(*) as count FROM change_history
                WHERE agent_id = ? AND change_type = 'completed'
            """
            params = [agent_id]
            if task_type:
                completed_query = """
                    SELECT COUNT(*) as count FROM change_history ch
                    JOIN tasks t ON ch.task_id = t.id
                    WHERE ch.agent_id = ? AND ch.change_type = 'completed' AND t.task_type = ?
                """
                params.append(task_type)
            
            cursor.execute(completed_query, params)
            completed = cursor.fetchone()["count"]
            
            # Get verified tasks count
            verified_query = """
                SELECT COUNT(*) as count FROM change_history
                WHERE agent_id = ? AND change_type = 'verified'
            """
            verified_params = [agent_id]
            if task_type:
                verified_query = """
                    SELECT COUNT(*) as count FROM change_history ch
                    JOIN tasks t ON ch.task_id = t.id
                    WHERE ch.agent_id = ? AND ch.change_type = 'verified' AND t.task_type = ?
                """
                verified_params.append(task_type)
            
            cursor.execute(verified_query, verified_params)
            verified = cursor.fetchone()["count"]
            
            # Get success rate (completed and verified)
            cursor.execute("""
                SELECT COUNT(DISTINCT ch1.task_id) as count FROM change_history ch1
                JOIN change_history ch2 ON ch1.task_id = ch2.task_id
                WHERE ch1.agent_id = ? AND ch1.change_type = 'completed'
                    AND ch2.agent_id = ? AND ch2.change_type = 'verified'
            """, (agent_id, agent_id))
            success_count = cursor.fetchone()["count"]
            
            return {
                "agent_id": agent_id,
                "tasks_completed": completed,
                "tasks_verified": verified,
                "success_rate": (success_count / completed * 100) if completed > 0 else 0.0,
                "task_type_filter": task_type
            }
        finally:
            conn.close()
    
    def get_related_tasks(self, task_id: int, relationship_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get tasks related to a given task."""
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
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_blocking_tasks(self, task_id: int) -> List[Dict[str, Any]]:
        """Get tasks that are blocking the given task."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.* FROM tasks t
                JOIN task_relationships tr ON t.id = tr.parent_task_id
                WHERE tr.child_task_id = ? AND tr.relationship_type = 'blocked_by'
            """, (task_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_available_tasks_for_agent(
        self,
        agent_type: str,
        project_id: Optional[int] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get available tasks for an agent type.
        
        - 'breakdown': Returns abstract/epic tasks that need to be broken down
        - 'implementation': Returns concrete tasks ready for implementation
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            project_filter = "AND t.project_id = ?" if project_id is not None else ""
            params = []
            
            if project_id is not None:
                params.append(project_id)
            
            if agent_type == "breakdown":
                # Abstract or epic tasks that are available and have no blocking tasks
                cursor.execute(f"""
                    SELECT t.* FROM tasks t
                    LEFT JOIN task_relationships tr ON t.id = tr.child_task_id 
                        AND tr.relationship_type = 'blocked_by'
                    WHERE t.task_status = 'available'
                        AND t.task_type IN ('abstract', 'epic')
                        AND tr.id IS NULL
                        {project_filter}
                    ORDER BY t.created_at ASC
                    LIMIT ?
                """, params + [limit])
            elif agent_type == "implementation":
                # Concrete tasks that are available and have no blocking tasks
                cursor.execute(f"""
                    SELECT t.* FROM tasks t
                    LEFT JOIN task_relationships tr ON t.id = tr.child_task_id 
                        AND tr.relationship_type = 'blocked_by'
                    WHERE t.task_status = 'available'
                        AND t.task_type = 'concrete'
                        AND tr.id IS NULL
                        {project_filter}
                    ORDER BY t.created_at ASC
                    LIMIT ?
                """, params + [limit])
            else:
                return []
            
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

