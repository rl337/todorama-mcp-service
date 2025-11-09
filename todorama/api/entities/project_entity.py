"""
Project entity with command pattern methods.
All project operations are exposed as methods that can be called via /api/Project/<method>
"""
from typing import Dict, Any, List, Optional
from fastapi import HTTPException

from todorama.api.entities.base_entity import BaseEntity
from todorama.models.project_models import ProjectCreate, ProjectResponse
from todorama.services.project_service import ProjectService


class ProjectEntity(BaseEntity):
    """Project entity with command pattern methods."""
    
    def __init__(self, db, auth_info: Optional[Dict[str, Any]] = None):
        """Initialize project entity."""
        super().__init__(db, auth_info)
        self.service = ProjectService(db)
    
    def create(self, **kwargs) -> Dict[str, Any]:
        """
        Create a new project.
        
        POST /api/Project/create
        Body: ProjectCreate model fields directly (name, local_path, etc.)
        """
        try:
            # Extract project data from kwargs (allow both direct fields and project_data wrapper)
            if "project_data" in kwargs:
                project_data = kwargs["project_data"]
            else:
                project_data = kwargs
            
            # Convert dict to ProjectCreate model - catch validation errors
            from pydantic import ValidationError
            try:
                project_create = ProjectCreate(**project_data)
            except ValidationError as e:
                # Convert Pydantic validation errors to 422 HTTPException
                errors = []
                for error in e.errors():
                    errors.append({
                        "loc": list(error["loc"]),
                        "msg": error["msg"],
                        "type": error["type"]
                    })
                raise HTTPException(
                    status_code=422,
                    detail=errors  # FastAPI format: list of error objects
                )
            
            # Use ProjectService instead of calling database directly
            created = self.service.create_project(project_create)
            return created
        except HTTPException:
            raise
        except ValueError as e:
            # ValueError from service indicates duplicate name or validation error
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:
            self._handle_error(e, "Failed to create project")
    
    def get(self, project_id: int) -> Dict[str, Any]:
        """
        Get a project by ID.
        
        GET /api/Project/get?project_id=123
        """
        try:
            project = self.service.get_project(project_id)
            if not project:
                raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
            return project
        except Exception as e:
            self._handle_error(e, "Failed to get project")
    
    def get_by_name(self, project_name: str) -> Dict[str, Any]:
        """
        Get a project by name.
        
        GET /api/Project/get_by_name?name=MyProject
        """
        try:
            project = self.service.get_project_by_name(project_name)
            if not project:
                raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
            return project
        except Exception as e:
            self._handle_error(e, "Failed to get project by name")
    
    def list(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        List all projects.
        
        GET /api/Project/list
        """
        try:
            projects = self.service.list_projects(filters=filters)
            return projects
        except Exception as e:
            self._handle_error(e, "Failed to list projects")

