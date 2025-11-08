"""
GraphQL schema for TODO Service.
"""
import strawberry
from typing import Optional, List
from datetime import datetime

from mcp_api import get_db


@strawberry.type
class Project:
    """Project GraphQL type."""
    id: int
    name: str
    local_path: str
    origin_url: Optional[str]
    description: Optional[str]
    created_at: str
    updated_at: str


@strawberry.type
class Task:
    """Task GraphQL type."""
    id: int
    project_id: Optional[int]
    title: str
    task_type: str
    task_instruction: str
    verification_instruction: str
    task_status: str
    verification_status: str
    priority: str
    assigned_agent: Optional[str]
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    notes: Optional[str]
    due_date: Optional[str]
    estimated_hours: Optional[float]
    actual_hours: Optional[float]
    time_delta_hours: Optional[float]
    started_at: Optional[str]


@strawberry.type
class Relationship:
    """Task relationship GraphQL type."""
    id: int
    parent_task_id: int
    child_task_id: int
    relationship_type: str
    created_at: str


@strawberry.input
class TaskFilter:
    """Filter input for task queries."""
    task_type: Optional[str] = None
    task_status: Optional[str] = None
    assigned_agent: Optional[str] = None
    project_id: Optional[int] = None
    priority: Optional[str] = None
    tag_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None


@strawberry.input
class TaskOrderBy:
    """Ordering input for task queries."""
    field: str = "created_at"  # created_at, priority
    direction: str = "DESC"  # ASC, DESC


@strawberry.type
class PageInfo:
    """Pagination info."""
    limit: int
    has_more: bool


@strawberry.type
class TasksConnection:
    """Paginated tasks connection."""
    tasks: List[Task]
    page_info: PageInfo


@strawberry.type
class Query:
    """GraphQL Query root."""
    
    @strawberry.field
    def project(self, id: int) -> Optional[Project]:
        """Get a project by ID."""
        db = get_db()
        project = db.get_project(id)
        if not project:
            return None
        return Project(**project)
    
    @strawberry.field
    def projects(self, limit: int = 100) -> List[Project]:
        """List all projects."""
        db = get_db()
        projects = db.list_projects()
        # Apply limit manually since list_projects doesn't take limit
        if len(projects) > limit:
            projects = projects[:limit]
        return [Project(**project) for project in projects]
    
    @strawberry.field
    def task(self, id: int) -> Optional[Task]:
        """Get a task by ID."""
        db = get_db()
        task = db.get_task(id)
        if not task:
            return None
        # Filter task dict to only include fields in Task GraphQL type
        task_fields = {
            'id', 'project_id', 'title', 'task_type', 'task_instruction',
            'verification_instruction', 'task_status', 'verification_status',
            'priority', 'assigned_agent', 'created_at', 'updated_at',
            'completed_at', 'notes', 'due_date', 'estimated_hours',
            'actual_hours', 'time_delta_hours', 'started_at'
        }
        filtered_task = {k: v for k, v in task.items() if k in task_fields}
        return Task(**filtered_task)
    
    @strawberry.field
    def tasks(
        self,
        filter: Optional[TaskFilter] = None,
        order_by: Optional[TaskOrderBy] = None,
        limit: int = 100
    ) -> TasksConnection:
        """
        Query tasks with filtering, sorting, and pagination.
        
        Args:
            filter: Optional filter criteria
            order_by: Optional ordering (field and direction)
            limit: Maximum number of results (default 100, max 1000)
        """
        # Validate limit
        if limit < 1:
            limit = 1
        if limit > 1000:
            limit = 1000
        
        db = get_db()
        
        # Extract filter values
        task_type = filter.task_type if filter else None
        task_status = filter.task_status if filter else None
        assigned_agent = filter.assigned_agent if filter else None
        project_id = filter.project_id if filter else None
        priority = filter.priority if filter else None
        tag_id = filter.tag_id if filter else None
        tag_ids = filter.tag_ids if filter else None
        
        # Map order_by to database format
        order_by_str = None
        if order_by:
            if order_by.field == "priority":
                order_by_str = "priority" if order_by.direction == "DESC" else "priority_asc"
            elif order_by.field == "created_at":
                # Database defaults to created_at DESC, so only need to handle ascending
                if order_by.direction == "ASC":
                    # Note: database.py doesn't support created_at ASC directly,
                    # so we'll sort in memory if needed
                    pass
        
        # Query tasks from database (query one extra to check if there are more)
        tasks = db.query_tasks(
            task_type=task_type,
            task_status=task_status,
            assigned_agent=assigned_agent,
            project_id=project_id,
            priority=priority,
            tag_id=tag_id,
            tag_ids=tag_ids,
            order_by=order_by_str,
            limit=limit + 1  # Query one extra to check if there are more
        )
        
        # Check if there are more results
        has_more = len(tasks) > limit
        if has_more:
            tasks = tasks[:limit]
        
        # Handle created_at ASC ordering if requested (database defaults to DESC)
        if order_by and order_by.field == "created_at" and order_by.direction == "ASC":
            # Reverse the list since database returns DESC by default
            tasks = list(reversed(tasks))
        
        # Convert to GraphQL types
        # Filter task dicts to only include fields in Task GraphQL type
        task_fields = {
            'id', 'project_id', 'title', 'task_type', 'task_instruction',
            'verification_instruction', 'task_status', 'verification_status',
            'priority', 'assigned_agent', 'created_at', 'updated_at',
            'completed_at', 'notes', 'due_date', 'estimated_hours',
            'actual_hours', 'time_delta_hours', 'started_at'
        }
        task_objects = [Task(**{k: v for k, v in task.items() if k in task_fields}) for task in tasks]
        
        return TasksConnection(
            tasks=task_objects,
            page_info=PageInfo(
                limit=limit,
                has_more=has_more
            )
        )
    
    @strawberry.field
    def relationships(self, task_id: int) -> List[Relationship]:
        """Get relationships for a task."""
        db = get_db()
        # Query relationships directly from the database
        conn = db._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, parent_task_id, child_task_id, relationship_type, created_at
                FROM task_relationships
                WHERE parent_task_id = ? OR child_task_id = ?
                ORDER BY created_at DESC
            """, (task_id, task_id))
            rows = cursor.fetchall()
            relationships = []
            for row in rows:
                rel_dict = dict(row)
                relationships.append(Relationship(**rel_dict))
            return relationships
        finally:
            conn.close()


# Create GraphQL schema
schema = strawberry.Schema(query=Query)
