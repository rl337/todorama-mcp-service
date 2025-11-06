"""
Single file containing all route definitions.
Route handlers are thin - they just call service layer methods.
"""
from fastapi import APIRouter, Path, Depends, Query, Body, HTTPException
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging

from models.task_models import TaskCreate, TaskResponse
from models.project_models import ProjectCreate, ProjectResponse
from auth.dependencies import verify_api_key, optional_api_key
from dependencies.services import get_db
from services.task_service import TaskService

# Initialize router
router = APIRouter()


# ============================================================================
# Task Routes
# ============================================================================

@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    task: TaskCreate,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> TaskResponse:
    """Create a new task."""
    service = TaskService(get_db())
    try:
        task_data = service.create_task(task, auth)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        elif "not authorized" in error_msg.lower():
            raise HTTPException(status_code=403, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to create task")
    return TaskResponse(**task_data)


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
    
    db = get_db()
    tasks = db.query_tasks(
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
    from database import TodoDatabase
    db = get_db()
    if not q or not q.strip():
        raise HTTPException(
            status_code=400,
            detail="Search query cannot be empty or contain only whitespace. Please provide a valid search term."
        )
    tasks = db.search_tasks(q.strip(), limit=limit)
    return [TaskResponse(**task) for task in tasks]


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
    db = get_db()
    
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
        feed = db.get_activity_feed(
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
    from database import TodoDatabase
    db = get_db()
    overdue = db.get_overdue_tasks(limit=limit)
    return {"tasks": [TaskResponse(**task) for task in overdue]}


@router.get("/tasks/approaching-deadline")
async def get_tasks_approaching_deadline(
    days_ahead: int = Query(3, ge=1, le=365, description="Number of days ahead to look for approaching deadlines"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")
):
    """Get tasks that are approaching their deadline."""
    from database import TodoDatabase
    db = get_db()
    approaching = db.get_tasks_approaching_deadline(days_ahead=days_ahead, limit=limit)
    return {"tasks": [TaskResponse(**task) for task in approaching]}


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int = Path(..., gt=0)) -> TaskResponse:
    """Get a task by ID."""
    service = TaskService(get_db())
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(**task)


# ============================================================================
# Project Routes
# ============================================================================

@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(project: ProjectCreate) -> ProjectResponse:
    """Create a new project."""
    db = get_db()
    project_id = db.create_project(
        name=project.name,
        local_path=project.local_path,
        origin_url=project.origin_url,
        description=project.description
    )
    created = db.get_project(project_id)
    if not created:
        raise HTTPException(status_code=500, detail="Failed to retrieve created project")
    return ProjectResponse(**created)


@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    auth: Optional[Dict[str, Any]] = Depends(optional_api_key)
) -> List[ProjectResponse]:
    """List all projects."""
    db = get_db()
    projects = db.list_projects()
    return [ProjectResponse(**project) for project in projects]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int = Path(..., gt=0)) -> ProjectResponse:
    """Get a project by ID."""
    db = get_db()
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectResponse(**project)


@router.get("/projects/name/{project_name}", response_model=ProjectResponse)
async def get_project_by_name(project_name: str = Path(..., min_length=1)) -> ProjectResponse:
    """Get a project by name."""
    db = get_db()
    project = db.get_project_by_name(project_name.strip())
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
    return ProjectResponse(**project)

