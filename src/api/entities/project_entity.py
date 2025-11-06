"""
Project entity with command pattern methods.
All project operations are exposed as methods that can be called via /api/Project/<method>
"""
from typing import Dict, Any, List, Optional
from fastapi import HTTPException

from api.entities.base_entity import BaseEntity
from models.project_models import ProjectCreate, ProjectResponse


class ProjectEntity(BaseEntity):
    """Project entity with command pattern methods."""
    
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
            
            project_id = self.db.create_project(
                name=project_create.name,
                local_path=project_create.local_path,
                origin_url=project_create.origin_url,
                description=project_create.description
            )
            created = self.db.get_project(project_id)
            if not created:
                raise HTTPException(status_code=500, detail="Failed to retrieve created project")
            return dict(created)
        except HTTPException:
            raise
        except Exception as e:
            self._handle_error(e, "Failed to create project")
    
    def get(self, project_id: int) -> Dict[str, Any]:
        """
        Get a project by ID.
        
        GET /api/Project/get?project_id=123
        """
        try:
            project = self.db.get_project(project_id)
            if not project:
                raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
            return dict(project)
        except Exception as e:
            self._handle_error(e, "Failed to get project")
    
    def get_by_name(self, project_name: str) -> Dict[str, Any]:
        """
        Get a project by name.
        
        GET /api/Project/get_by_name?name=MyProject
        """
        try:
            project = self.db.get_project_by_name(project_name.strip())
            if not project:
                raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
            return dict(project)
        except Exception as e:
            self._handle_error(e, "Failed to get project by name")
    
    def list(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        List all projects.
        
        GET /api/Project/list
        """
        try:
            projects = self.db.list_projects()
            return [dict(project) for project in projects]
        except Exception as e:
            self._handle_error(e, "Failed to list projects")

