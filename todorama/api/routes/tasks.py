"""
Task API routes.
"""
from typing import List, Optional
import json
import logging

from todorama.adapters.http_framework import HTTPFrameworkAdapter
from todorama.models.task_models import TaskResponse
from todorama.dependencies.services import get_db
from todorama.services.task_service import TaskService
from todorama.auth.permissions import TASK_CREATE

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
Path = http_adapter.Path
Query = http_adapter.Query
Body = http_adapter.Body
HTTPException = http_adapter.HTTPException
Request = http_adapter.Request

# Create router using adapter, expose underlying router for compatibility
router_adapter = http_adapter.create_router(prefix="/tasks", tags=["tasks"])
router = router_adapter.router

logger = logging.getLogger(__name__)


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(request: Request) -> TaskResponse:
    """
    Create a new task - delegates to TaskEntity.create().
    Programmatic handler using the same pattern as command router.
    """
    from todorama.api.entities.task_entity import TaskEntity
    
    # Manually verify API key (same pattern as command router)
    # For /tasks endpoint, auth is required
    # Parse Authorization header manually for Bearer token support
    api_key = None
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        api_key = api_key_header
    
    # Try Authorization: Bearer token
    if not api_key:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header[7:]
    
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required. Provide X-API-Key header or Authorization: Bearer token.")
    
    # Verify the key using the database
    db = get_db()
    key_hash = db._hash_api_key(api_key)
    key_info = db.get_api_key_by_hash(key_hash)
    
    if not key_info or key_info["enabled"] != 1:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    
    # Update last used timestamp
    db.update_api_key_last_used(key_info["id"])
    
    # Create auth dict
    is_admin = db.is_api_key_admin(key_info["id"])
    auth = {
        "key_id": key_info["id"],
        "project_id": key_info["project_id"],
        "is_admin": is_admin
    }
    
    # Check permission: TASK_CREATE required (admin bypasses)
    if not is_admin:
        # For API key auth, we need to check permissions via project's organization
        project = db.get_project(key_info["project_id"])
        if project and project.get("organization_id"):
            # Get API key's user (if it has one) or check via project context
            # For now, if not admin, require organization context
            # This is a simplified check - in full implementation, API keys would be linked to users
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {TASK_CREATE} required"
            )
    
    # Parse body manually
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    
    # Delegate to TaskEntity (same as command router does)
    db = get_db()
    entity = TaskEntity(db, auth_info=auth)
    
    try:
        task_data = entity.create(**body)
        return TaskResponse(**task_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


# NOTE: Specific routes like /tasks/search, /tasks/overdue, /tasks/approaching-deadline, /tasks/activity-feed
# must be defined BEFORE /tasks/{task_id} to avoid route matching issues.
# FastAPI matches routes in order, so specific routes must come before parameterized routes
@router.get("", response_model=List[TaskResponse])
async def query_tasks(
    task_type: Optional[str] = Query(None, description="Filter by task type"),
    task_status: Optional[str] = Query(None, description="Filter by task status"),
    assigned_agent: Optional[str] = Query(None, description="Filter by assigned agent"),
    project_id: Optional[int] = Query(None, description="Filter by project ID", gt=0),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    tag_id: Optional[int] = Query(None, description="Filter by tag ID (single tag)", gt=0),
    tag_ids: Optional[str] = Query(None, description="Filter by multiple tag IDs (comma-separated)"),
    order_by: Optional[str] = Query(None, description="Order by: priority, priority_asc, or created_at (default)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    # Advanced filtering: date ranges
    created_after: Optional[str] = Query(None, description="Filter by created_at >= date (ISO format)"),
    created_before: Optional[str] = Query(None, description="Filter by created_at <= date (ISO format)"),
    updated_after: Optional[str] = Query(None, description="Filter by updated_at >= date (ISO format)"),
    updated_before: Optional[str] = Query(None, description="Filter by updated_at <= date (ISO format)"),
    completed_after: Optional[str] = Query(None, description="Filter by completed_at >= date (ISO format)"),
    completed_before: Optional[str] = Query(None, description="Filter by completed_at <= date (ISO format)"),
    # Advanced filtering: text search
    search: Optional[str] = Query(None, description="Search in title and task_instruction (case-insensitive)")
) -> List[TaskResponse]:
    """Query tasks with filters including advanced date range and text search."""
    if task_type and task_type not in ["concrete", "abstract", "epic"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type '{task_type}'. Must be one of: concrete, abstract, epic"
        )
    if task_status and task_status not in ["available", "in_progress", "complete", "blocked", "cancelled"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_status '{task_status}'. Must be one of: available, in_progress, complete, blocked, cancelled"
        )
    if priority and priority not in ["low", "medium", "high", "critical"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority '{priority}'. Must be one of: low, medium, high, critical"
        )
    if order_by and order_by not in ["priority", "priority_asc"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid order_by '{order_by}'. Must be one of: priority, priority_asc"
        )
    
    # Parse tag_ids if provided
    tag_ids_list = None
    if tag_ids:
        try:
            tag_ids_list = [int(tid.strip()) for tid in tag_ids.split(",") if tid.strip()]
            # Validate all tag IDs are positive
            for tid in tag_ids_list:
                if tid <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid tag_id '{tid}' in tag_ids. All tag IDs must be positive integers"
                    )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tag_ids format '{tag_ids}'. Must be comma-separated positive integers (e.g., '1,2,3'). Error: {str(e)}"
            )
    
    # Validate and normalize date strings to SQLite format
    # SQLite stores dates as 'YYYY-MM-DD HH:MM:SS' (space, not T) or 'YYYY-MM-DDTHH:MM:SS'
    # We need to normalize to match SQLite's format for proper lexicographic comparison
    from datetime import datetime
    date_filters = {}
    for date_param, date_value in [
        ("created_after", created_after),
        ("created_before", created_before),
        ("updated_after", updated_after),
        ("updated_before", updated_before),
        ("completed_after", completed_after),
        ("completed_before", completed_before),
    ]:
        if date_value:
            try:
                # Parse ISO format datetime
                if date_value.endswith('Z'):
                    parsed_date = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
                else:
                    parsed_date = datetime.fromisoformat(date_value)
                
                # Convert to SQLite-compatible format: 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DDTHH:MM:SS'
                # SQLite's CURRENT_TIMESTAMP uses 'YYYY-MM-DD HH:MM:SS' format
                # Normalize to 'YYYY-MM-DD HH:MM:SS' format for consistent comparison
                sqlite_format = parsed_date.strftime('%Y-%m-%d %H:%M:%S')
                if parsed_date.microsecond > 0:
                    # Include microseconds if present
                    sqlite_format += f".{parsed_date.microsecond:06d}"
                date_filters[date_param] = sqlite_format
            except (ValueError, AttributeError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid date format for {date_param}: '{date_value}'. Expected ISO format (e.g., '2025-01-01T00:00:00'). Error: {str(e)}"
                )
    
    service = TaskService(get_db())
    tasks = service.query_tasks(
        task_type=task_type,
        task_status=task_status,
        assigned_agent=assigned_agent,
        project_id=project_id,
        priority=priority,
        tag_id=tag_id,
        tag_ids=tag_ids_list,
        order_by=order_by,
        limit=limit,
        created_after=date_filters.get("created_after"),
        created_before=date_filters.get("created_before"),
        updated_after=date_filters.get("updated_after"),
        updated_before=date_filters.get("updated_before"),
        completed_after=date_filters.get("completed_after"),
        completed_before=date_filters.get("completed_before"),
        search=search
    )
    return [TaskResponse(**task) for task in tasks]


@router.get("/search", response_model=List[TaskResponse])
async def search_tasks(
    q: str = Query(..., description="Search query"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")
) -> List[TaskResponse]:
    """Search tasks using full-text search across titles, instructions, and notes."""
    service = TaskService(get_db())
    try:
        tasks = service.search_tasks(q, limit=limit)
        return [TaskResponse(**task) for task in tasks]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# IMPORTANT: /tasks/activity-feed must come BEFORE /tasks/{task_id} to avoid route conflicts
# FastAPI matches routes in order, so specific routes must come before parameterized routes
@router.get("/activity-feed")
async def get_activity_feed(
    task_id: Optional[int] = Query(None, description="Filter by task ID", gt=0),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum number of results")
):
    """
    Get activity feed showing all task updates, completions, and relationship changes
    in chronological order. Supports filtering by task, agent, or date range.
    """
    from datetime import datetime
    
    # Validate date formats if provided
    if start_date:
        try:
            if start_date.endswith('Z'):
                datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            else:
                datetime.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid start_date format '{start_date}'. Must be ISO 8601 format."
            )
    
    if end_date:
        try:
            if end_date.endswith('Z'):
                datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            else:
                datetime.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid end_date format '{end_date}'. Must be ISO 8601 format."
            )
    
    try:
        service = TaskService(get_db())
        feed = service.get_activity_feed(
            task_id=task_id,
            agent_id=agent_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        return {
            "feed": feed,
            "count": len(feed),
            "filters": {
                "task_id": task_id,
                "agent_id": agent_id,
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit
            }
        }
    except Exception as e:
        logger.error(f"Failed to get activity feed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve activity feed")


@router.get("/overdue")
async def get_overdue_tasks(limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")):
    """Get tasks that are overdue (past due date and not complete)."""
    service = TaskService(get_db())
    overdue = service.get_overdue_tasks(limit=limit)
    return {"tasks": [TaskResponse(**task) for task in overdue]}


@router.get("/approaching-deadline")
async def get_tasks_approaching_deadline(
    days_ahead: int = Query(3, ge=1, le=365, description="Number of days ahead to look for approaching deadlines"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")
):
    """Get tasks that are approaching their deadline."""
    service = TaskService(get_db())
    approaching = service.get_tasks_approaching_deadline(days_ahead=days_ahead, limit=limit)
    return {"tasks": [TaskResponse(**task) for task in approaching]}


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int = Path(..., gt=0)) -> TaskResponse:
    """Get a task by ID."""
    service = TaskService(get_db())
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(**task)


@router.get("/{task_id}/relationships")
async def get_task_relationships(task_id: int = Path(..., gt=0)):
    """Get relationships for a task."""
    service = TaskService(get_db())
    try:
        relationships = service.get_task_relationships(task_id)
        return {"relationships": relationships}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
