"""
Project API routes.
"""
from typing import List, Dict, Any, Optional

from todorama.adapters.http_framework import HTTPFrameworkAdapter
from todorama.models.project_models import ProjectCreate, ProjectResponse
from todorama.dependencies.services import get_db
from todorama.services.project_service import ProjectService
from todorama.auth.dependencies import optional_api_key

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
Path = http_adapter.Path
Depends = http_adapter.Depends
HTTPException = http_adapter.HTTPException

# Create router using adapter, expose underlying router for compatibility
router_adapter = http_adapter.create_router(prefix="/projects", tags=["projects"])
router = router_adapter.router

import logging
logger = logging.getLogger(__name__)


@router.post("", response_model=ProjectResponse, status_code=201)
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


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    auth: Optional[Dict[str, Any]] = Depends(optional_api_key)
) -> List[ProjectResponse]:
    """List all projects."""
    db = get_db()
    project_service = ProjectService(db)
    projects = project_service.list_projects()
    return [ProjectResponse(**project) for project in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int = Path(..., gt=0)) -> ProjectResponse:
    """Get a project by ID."""
    db = get_db()
    project_service = ProjectService(db)
    project = project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectResponse(**project)


@router.get("/name/{project_name}", response_model=ProjectResponse)
async def get_project_by_name(project_name: str = Path(..., min_length=1)) -> ProjectResponse:
    """Get a project by name."""
    db = get_db()
    project_service = ProjectService(db)
    project = project_service.get_project_by_name(project_name)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
    return ProjectResponse(**project)
