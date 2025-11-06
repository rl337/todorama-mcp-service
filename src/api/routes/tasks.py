"""
Task-related API routes.
Thin HTTP layer that delegates to service layer.
"""
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Path, Depends, HTTPException, Query
from models.task_models import TaskCreate, TaskResponse
from auth.dependencies import verify_api_key
from dependencies.services import get_db
from services.task_service import TaskService
from adapters.http_framework import HTTPFrameworkAdapter
import asyncio
from datetime import datetime, UTC
from webhooks import notify_webhooks
from slack import send_task_notification

logger = logging.getLogger(__name__)

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
HTTPException = http_adapter.HTTPException
Request = http_adapter.Request

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_task_service() -> TaskService:
    """Get task service instance."""
    return TaskService(get_db())


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    task: TaskCreate,
    auth: Dict[str, Any] = Depends(verify_api_key),
    task_service: TaskService = Depends(get_task_service)
):
    """Create a new task."""
    try:
        # Use service layer for business logic
        created_task_data = task_service.create_task(task, auth)
    except ValueError as e:
        # Business logic validation errors -> 400/404
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        elif "not authorized" in error_msg.lower():
            raise HTTPException(status_code=403, detail=error_msg)
        else:
            raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        # Unexpected errors -> 500
        logger.error(f"Unexpected error creating task: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to create task. Please try again or contact support if the issue persists."
        )
    
    # Send async notifications (webhooks, Slack)
    project_id = task.project_id
    asyncio.create_task(notify_webhooks(
        get_db(),
        project_id=project_id,
        event_type="task.created",
        payload={
            "event": "task.created",
            "task": created_task_data,
            "timestamp": datetime.now(UTC).isoformat()  # Use timezone-aware datetime
        }
    ))
    
    # Send Slack notification (async wrapper for sync function)
    project = get_db().get_project(project_id) if project_id else None
    async def send_slack_notif():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            send_task_notification,
            None,  # Use default channel from env
            "task.created",
            created_task_data,
            dict(project) if project else None
        )
    asyncio.create_task(send_slack_notif())
    
    return TaskResponse(**created_task_data)


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
):
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
    
    # Validate and parse date strings
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
                # Handle both with and without timezone
                if date_value.endswith('Z'):
                    parsed_date = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
                else:
                    parsed_date = datetime.fromisoformat(date_value)
                # Convert to ISO format string for database query (SQLite stores as text)
                date_filters[date_param] = parsed_date.isoformat()
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


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int = Path(..., gt=0, description="Task ID"),
    task_service: TaskService = Depends(get_task_service)
):
    """Get a task by ID."""
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    return TaskResponse(**task)

