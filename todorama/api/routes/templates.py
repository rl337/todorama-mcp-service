"""
Template API routes.
"""
from typing import List, Dict, Any, Optional
import logging

from pydantic import BaseModel

from todorama.adapters.http_framework import HTTPFrameworkAdapter
from todorama.dependencies.services import get_db
from todorama.services.template_service import TemplateService
from todorama.auth.dependencies import optional_api_key

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
Path = http_adapter.Path
Query = http_adapter.Query
Body = http_adapter.Body
HTTPException = http_adapter.HTTPException
Depends = http_adapter.Depends

# Create router using adapter, expose underlying router for compatibility
router_adapter = http_adapter.create_router(prefix="/templates", tags=["templates"])
router = router_adapter.router

logger = logging.getLogger(__name__)


class CreateTaskFromTemplateRequest(BaseModel):
    """Request model for creating task from template."""
    title: Optional[str] = None
    project_id: Optional[int] = None
    notes: Optional[str] = None
    priority: Optional[str] = None
    estimated_hours: Optional[float] = None
    due_date: Optional[str] = None


@router.post("", status_code=201)
async def create_template(
    template_data: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    """Create a new task template."""
    db = get_db()
    template_service = TemplateService(db)
    try:
        template = template_service.create_template(
            name=template_data["name"],
            task_type=template_data["task_type"],
            task_instruction=template_data["task_instruction"],
            verification_instruction=template_data["verification_instruction"],
            description=template_data.get("description"),
            priority=template_data.get("priority"),
            estimated_hours=template_data.get("estimated_hours"),
            notes=template_data.get("notes")
        )
        return template
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required field: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create template")


@router.get("")
async def list_templates(
    task_type: Optional[str] = Query(None, description="Filter by task type")
) -> List[Dict[str, Any]]:
    """List all templates, optionally filtered by task_type."""
    db = get_db()
    template_service = TemplateService(db)
    try:
        templates = template_service.list_templates(task_type=task_type)
        return templates
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{template_id}")
async def get_template(template_id: int = Path(..., gt=0)) -> Dict[str, Any]:
    """Get a template by ID."""
    db = get_db()
    template_service = TemplateService(db)
    template = template_service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    return template


@router.post("/{template_id}/create-task", status_code=201)
async def create_task_from_template(
    template_id: int = Path(..., gt=0),
    task_data: Optional[CreateTaskFromTemplateRequest] = Body(default=None),
    auth: Dict[str, Any] = Depends(optional_api_key)
) -> Dict[str, Any]:
    """Create a task from a template."""
    db = get_db()
    template_service = TemplateService(db)
    
    # Get agent_id from auth or use default
    agent_id = auth.get("agent_id") if auth else "system"
    
    # Handle case where task_data might be None
    if task_data is None:
        task_data = CreateTaskFromTemplateRequest()
    
    # Create task from template with optional overrides
    try:
        task = template_service.create_task_from_template(
            template_id=template_id,
            agent_id=agent_id,
            title=task_data.title,
            project_id=task_data.project_id,
            notes=task_data.notes,
            priority=task_data.priority,
            estimated_hours=task_data.estimated_hours,
            due_date=task_data.due_date
        )
        return task
    except ValueError as e:
        # Return 404 for "not found" errors, 400 for validation errors
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        logger.error(f"Failed to create task from template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create task from template")
