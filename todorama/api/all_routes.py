"""
Single file containing all route definitions.
Route handlers are thin - they just call service layer methods.
"""
from fastapi import APIRouter, Path, Depends, Query, Body, HTTPException, Request
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging
import sqlite3

logger = logging.getLogger(__name__)

from todorama.models.task_models import TaskCreate, TaskResponse
from todorama.models.project_models import ProjectCreate, ProjectResponse
from todorama.auth.dependencies import verify_api_key, optional_api_key
from todorama.dependencies.services import get_db
from todorama.services.task_service import TaskService
from todorama.services.project_service import ProjectService
from todorama.services.tag_service import TagService

# Initialize router
router = APIRouter()


# ============================================================================
# Task Routes - Programmatic handler that delegates to entity system
# ============================================================================

@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(request: Request) -> TaskResponse:
    """
    Create a new task - delegates to TaskEntity.create().
    Programmatic handler using the same pattern as command router.
    """
    import json
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
    auth = {
        "key_id": key_info["id"],
        "project_id": key_info["project_id"],
        "is_admin": db.is_api_key_admin(key_info["id"])
    }
    
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


# NOTE: Specific routes like /tasks, /tasks/search, /tasks/overdue, /tasks/approaching-deadline
# must be defined BEFORE /tasks/{task_id} to avoid route matching issues.
# FastAPI matches routes in order, so specific routes must come before parameterized routes
@router.get("/tasks", response_model=List[TaskResponse])
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


@router.get("/tasks/search", response_model=List[TaskResponse])
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
@router.get("/tasks/activity-feed")
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
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to get activity feed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve activity feed")


@router.get("/tasks/overdue")
async def get_overdue_tasks(limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")):
    """Get tasks that are overdue (past due date and not complete)."""
    service = TaskService(get_db())
    overdue = service.get_overdue_tasks(limit=limit)
    return {"tasks": [TaskResponse(**task) for task in overdue]}


@router.get("/tasks/approaching-deadline")
async def get_tasks_approaching_deadline(
    days_ahead: int = Query(3, ge=1, le=365, description="Number of days ahead to look for approaching deadlines"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")
):
    """Get tasks that are approaching their deadline."""
    service = TaskService(get_db())
    approaching = service.get_tasks_approaching_deadline(days_ahead=days_ahead, limit=limit)
    return {"tasks": [TaskResponse(**task) for task in approaching]}


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int = Path(..., gt=0)) -> TaskResponse:
    """Get a task by ID."""
    service = TaskService(get_db())
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(**task)


@router.get("/tasks/{task_id}/relationships")
async def get_task_relationships(task_id: int = Path(..., gt=0)):
    """Get relationships for a task."""
    service = TaskService(get_db())
    try:
        relationships = service.get_task_relationships(task_id)
        return {"relationships": relationships}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================================
# Project Routes
# ============================================================================

@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(project: ProjectCreate) -> ProjectResponse:
    """Create a new project."""
    db = get_db()
    project_service = ProjectService(db)
    try:
        created = project_service.create_project(project)
        return ProjectResponse(**created)
    except ValueError as e:
        # ValueError from service indicates duplicate name or validation error
        raise HTTPException(
            status_code=409,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to create project: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e)}")


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    auth: Optional[Dict[str, Any]] = Depends(optional_api_key)
) -> List[ProjectResponse]:
    """List all projects."""
    db = get_db()
    project_service = ProjectService(db)
    projects = project_service.list_projects()
    return [ProjectResponse(**project) for project in projects]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int = Path(..., gt=0)) -> ProjectResponse:
    """Get a project by ID."""
    db = get_db()
    project_service = ProjectService(db)
    project = project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectResponse(**project)


@router.get("/projects/name/{project_name}", response_model=ProjectResponse)
async def get_project_by_name(project_name: str = Path(..., min_length=1)) -> ProjectResponse:
    """Get a project by name."""
    db = get_db()
    project_service = ProjectService(db)
    project = project_service.get_project_by_name(project_name)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
    return ProjectResponse(**project)


# ============================================================================
# Template Routes
# ============================================================================

@router.post("/templates", status_code=201)
async def create_template(
    template_data: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    """Create a new task template."""
    db = get_db()
    try:
        template_id = db.create_template(
            name=template_data["name"],
            task_type=template_data["task_type"],
            task_instruction=template_data["task_instruction"],
            verification_instruction=template_data["verification_instruction"],
            description=template_data.get("description"),
            priority=template_data.get("priority"),
            estimated_hours=template_data.get("estimated_hours"),
            notes=template_data.get("notes")
        )
        template = db.get_template(template_id)
        if not template:
            raise HTTPException(status_code=500, detail="Failed to retrieve created template")
        return template
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required field: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create template")


@router.get("/templates")
async def list_templates(
    task_type: Optional[str] = Query(None, description="Filter by task type")
) -> List[Dict[str, Any]]:
    """List all templates, optionally filtered by task_type."""
    db = get_db()
    templates = db.list_templates(task_type=task_type)
    return templates


@router.get("/templates/{template_id}")
async def get_template(template_id: int = Path(..., gt=0)) -> Dict[str, Any]:
    """Get a template by ID."""
    db = get_db()
    template = db.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    return template


class CreateTaskFromTemplateRequest(BaseModel):
    """Request model for creating task from template."""
    title: Optional[str] = None
    project_id: Optional[int] = None
    notes: Optional[str] = None
    priority: Optional[str] = None
    estimated_hours: Optional[float] = None
    due_date: Optional[str] = None

@router.post("/templates/{template_id}/create-task", status_code=201)
async def create_task_from_template(
    template_id: int = Path(..., gt=0),
    task_data: Optional[CreateTaskFromTemplateRequest] = Body(default=None),
    auth: Dict[str, Any] = Depends(optional_api_key)
) -> Dict[str, Any]:
    """Create a task from a template."""
    db = get_db()
    
    # Verify template exists
    template = db.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    
    # Get agent_id from auth or use default
    agent_id = auth.get("agent_id") if auth else "system"
    
    # Handle case where task_data might be None
    if task_data is None:
        task_data = CreateTaskFromTemplateRequest()
    
    # Create task from template with optional overrides
    try:
        # Use title from task_data if provided, otherwise use template name
        task_title = task_data.title if task_data.title else None
        # Only use template name if title is explicitly None or empty string
        if not task_title or (isinstance(task_title, str) and task_title.strip() == ""):
            task_title = template["name"]
        
        # Parse due_date if provided
        due_date_obj = None
        if task_data.due_date:
            from datetime import datetime
            try:
                if task_data.due_date.endswith('Z'):
                    due_date_obj = datetime.fromisoformat(task_data.due_date.replace('Z', '+00:00'))
                else:
                    due_date_obj = datetime.fromisoformat(task_data.due_date)
            except ValueError:
                pass  # Invalid date format, ignore
        
        task_id = db.create_task_from_template(
            template_id=template_id,
            agent_id=agent_id,
            title=task_title,
            project_id=task_data.project_id,
            notes=task_data.notes,
            priority=task_data.priority or template.get("priority"),
            estimated_hours=task_data.estimated_hours or template.get("estimated_hours"),
            due_date=due_date_obj
        )
        
        # Get the created task
        task = db.get_task(task_id)
        if not task:
            raise HTTPException(status_code=500, detail="Failed to retrieve created task")
        return task
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create task from template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create task from template")


# ============================================================================
# Tag Routes
# ============================================================================

@router.post("/tags", status_code=201)
async def create_tag(
    tag_data: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    """Create a new tag."""
    tag_service = TagService(get_db())
    try:
        if "name" not in tag_data:
            raise HTTPException(status_code=422, detail=[{
                "loc": ["body", "name"],
                "msg": "Tag name is required",
                "type": "value_error.missing"
            }])
        tag = tag_service.create_tag(tag_data["name"])
        return tag
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=[{
            "loc": ["body", "name"],
            "msg": str(e),
            "type": "value_error"
        }])
    except Exception as e:
        logger.error(f"Failed to create tag: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create tag")


# Note: Task import and bulk operations are now handled by TaskEntity methods
# via the command router: /api/Task/import/json, /api/Task/bulk/complete, etc.
# No FastAPI routes needed here - entities handle routing programmatically.

# ============================================================================
# Analytics Routes
# ============================================================================

@router.get("/analytics/metrics")
async def get_analytics_metrics(
    project_id: Optional[int] = Query(None, description="Filter by project ID")
) -> Dict[str, Any]:
    """Get analytics metrics including completion rates."""
    db = get_db()
    try:
        completion_rates = db.get_completion_rates(project_id=project_id)
        avg_time = db.get_average_time_to_complete(project_id=project_id)
        # Ensure average_hours is not None (convert to 0 if None)
        if avg_time and avg_time.get("average_hours") is None:
            avg_time["average_hours"] = 0.0
        return {
            "completion_rates": completion_rates,
            "average_time_to_complete": avg_time
        }
    except Exception as e:
        logger.error(f"Failed to get analytics metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get analytics metrics: {str(e)}")


@router.get("/analytics/bottlenecks")
async def get_bottlenecks(
    project_id: Optional[int] = Query(None, description="Filter by project ID")
) -> Dict[str, Any]:
    """Get task bottlenecks."""
    db = get_db()
    try:
        bottlenecks = db.get_bottlenecks()
        # Filter by project_id if provided (post-process since method doesn't support it)
        if project_id:
            for key in ["long_running_tasks", "blocking_tasks", "blocked_tasks"]:
                if key in bottlenecks:
                    bottlenecks[key] = [t for t in bottlenecks[key] if t.get("project_id") == project_id]
        return {
            "long_running_tasks": bottlenecks.get("long_running_tasks", []),
            "blocking_tasks": bottlenecks.get("blocking_tasks", []),
            "blocked_tasks": bottlenecks.get("blocked_tasks", [])
        }
    except Exception as e:
        logger.error(f"Failed to get bottlenecks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get bottlenecks: {str(e)}")


@router.get("/analytics/agents")
async def get_agent_analytics(
    project_id: Optional[int] = Query(None, description="Filter by project ID")
) -> Dict[str, Any]:
    """Get agent comparison analytics."""
    db = get_db()
    try:
        agent_data = db.get_agent_comparisons()
        agents = agent_data.get("agents", [])
        # Filter by project_id if provided (post-process)
        if project_id:
            # Note: get_agent_comparisons doesn't support project_id filter directly
            # Would need to filter by tasks in that project, but for now return all
            pass
        return {"agents": agents}
    except Exception as e:
        logger.error(f"Failed to get agent analytics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get agent analytics: {str(e)}")


@router.get("/analytics/visualization")
async def get_visualization_data(
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)")
) -> Dict[str, Any]:
    """Get visualization data for analytics."""
    db = get_db()
    try:
        # Get completion timeline data
        tasks = db.query_tasks(limit=1000)
        if start_date or end_date:
            from datetime import datetime
            filtered_tasks = []
            for task in tasks:
                if task.get("created_at"):
                    try:
                        created = datetime.fromisoformat(task["created_at"].replace('Z', '+00:00'))
                        if start_date:
                            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                            if created < start:
                                continue
                        if end_date:
                            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                            if created > end:
                                continue
                        filtered_tasks.append(task)
                    except (ValueError, AttributeError):
                        pass
            tasks = filtered_tasks
        
        # Build status distribution
        status_dist = {}
        for task in tasks:
            status = task.get("task_status", "available")
            status_dist[status] = status_dist.get(status, 0) + 1
        
        return {
            "status_distribution": status_dist,
            "completion_timeline": []  # Could be enhanced with time-series data
        }
    except Exception as e:
        logger.error(f"Failed to get visualization data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get visualization data: {str(e)}")


# ============================================================================
# API Key Management Routes
# ============================================================================

@router.post("/projects/{project_id}/api-keys", status_code=201)
async def create_api_key(
    project_id: int = Path(..., gt=0),
    key_data: Dict[str, Any] = Body(default_factory=dict)
) -> Dict[str, Any]:
    """Create a new API key for a project."""
    db = get_db()
    try:
        name = key_data.get("name")
        # Name is optional - if not provided, use default
        if name is None:
            name = "Test API Key"
        elif not name or not name.strip():
            # If provided but empty, reject
            raise HTTPException(status_code=422, detail="API key name cannot be empty")
        else:
            name = name.strip()
        key_id, api_key = db.create_api_key(project_id, name)
        # Extract key prefix (first 8 characters)
        key_prefix = api_key[:8] if len(api_key) >= 8 else api_key
        return {
            "key_id": key_id,
            "api_key": api_key,
            "key_prefix": key_prefix,
            "name": name,
            "project_id": project_id
        }
    except HTTPException:
        # Re-raise HTTP exceptions (like 422 for validation)
        raise
    except ValueError as e:
        # Check if it's a "not found" error
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required field: {e}")
    except Exception as e:
        logger.error(f"Failed to create API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create API key: {str(e)}")


@router.get("/api-keys")
async def list_api_keys(
    project_id: Optional[int] = Query(None, description="Filter by project ID")
) -> List[Dict[str, Any]]:
    """List API keys."""
    db = get_db()
    try:
        if project_id:
            keys = db.list_api_keys(project_id)
            # Add key_id field (database returns 'id')
            for key in keys:
                if "id" in key and "key_id" not in key:
                    key["key_id"] = key["id"]
        else:
            # List all keys (would need a method for this)
            keys = []
        return keys
    except Exception as e:
        logger.error(f"Failed to list API keys: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list API keys: {str(e)}")


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: int = Path(..., gt=0)) -> Dict[str, Any]:
    """Revoke an API key."""
    db = get_db()
    try:
        success = db.revoke_api_key(key_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"API key {key_id} not found")
        return {"success": True, "key_id": key_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to revoke API key: {str(e)}")


@router.post("/api-keys/{key_id}/rotate", status_code=200)
async def rotate_api_key(key_id: int = Path(..., gt=0)) -> Dict[str, Any]:
    """Rotate an API key."""
    db = get_db()
    try:
        new_key_id, new_api_key = db.rotate_api_key(key_id)
        key_prefix = new_api_key[:8] if len(new_api_key) >= 8 else new_api_key
        return {
            "key_id": new_key_id,
            "api_key": new_api_key,
            "key_prefix": key_prefix
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to rotate API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to rotate API key: {str(e)}")

