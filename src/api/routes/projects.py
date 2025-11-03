"""
Project-related API routes.
"""
import sqlite3
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Path
from models.project_models import ProjectCreate, ProjectResponse
from auth.dependencies import verify_api_key, optional_api_key
from dependencies.services import get_db
from adapters.http_framework import HTTPFrameworkAdapter

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
HTTPException = http_adapter.HTTPException
Request = http_adapter.Request

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(project: ProjectCreate):
    """Create a new project."""
    db = get_db()
    import sqlite3
    try:
        project_id = db.create_project(
            name=project.name,
            local_path=project.local_path,
            origin_url=project.origin_url,
            description=project.description
        )
        created_project = db.get_project(project_id)
        if not created_project:
            raise HTTPException(status_code=500, detail="Failed to retrieve created project")
        return ProjectResponse(**created_project)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Project with name '{project.name}' already exists")


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    request: Request,
    auth: Optional[Dict[str, Any]] = Depends(optional_api_key)
):
    """List all projects."""
    db = get_db()
    # If authenticated, filter by project scope
    if auth:
        # For now, allow listing all projects even with auth
        # Can be restricted to user's project later
        projects = db.list_projects()
    else:
        # Without auth, return all projects (backward compatibility)
        projects = db.list_projects()
    return [ProjectResponse(**project) for project in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int = Path(..., gt=0, description="Project ID")):
    """Get a project by ID."""
    db = get_db()
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project {project_id} not found. Please verify the project_id is correct."
        )
    return ProjectResponse(**project)


@router.get("/name/{project_name}", response_model=ProjectResponse)
async def get_project_by_name(project_name: str = Path(..., min_length=1, description="Project name")):
    """Get a project by name."""
    db = get_db()
    # Validate project_name is not empty or whitespace
    if not project_name or not project_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Project name cannot be empty or contain only whitespace. Please provide a valid project name."
        )
    
    project = db.get_project_by_name(project_name.strip())
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{project_name}' not found. Please verify the project name is correct and try again."
        )
    return ProjectResponse(**project)

