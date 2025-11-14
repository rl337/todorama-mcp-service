"""Project-related MCP handlers."""

from typing import Optional, Dict, Any

from todorama.mcp_api import get_db
from todorama.tracing import trace_span, add_span_attribute
from todorama.services.project_service import ProjectService
from todorama.models.project_models import ProjectCreate


def handle_list_projects() -> Dict[str, Any]:
    """
    List all available projects.
    
    Returns:
        Dictionary with success status and list of projects
    """
    with trace_span("mcp.list_projects"):
        try:
            db = get_db()
            project_service = ProjectService(db)
            projects = project_service.list_projects()
            return {
                "success": True,
                "projects": projects,
                "count": len(projects)
            }
        except Exception as e:
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", str(e))
            return {
                "success": False,
                "error": f"Failed to list projects: {str(e)}"
            }


def handle_get_project(project_id: int) -> Dict[str, Any]:
    """
    Get project details by ID.
    
    Args:
        project_id: Project ID to retrieve
        
    Returns:
        Dictionary with success status and project data
    """
    with trace_span("mcp.get_project", attributes={"mcp.project_id": project_id}):
        try:
            db = get_db()
            project_service = ProjectService(db)
            project = project_service.get_project(project_id)
            if not project:
                add_span_attribute("mcp.success", False)
                add_span_attribute("mcp.error", "project_not_found")
                return {
                    "success": False,
                    "error": f"Project {project_id} not found. Please verify the project_id is correct."
                }
            
            add_span_attribute("mcp.success", True)
            return {
                "success": True,
                "project": project
            }
        except Exception as e:
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", str(e))
            return {
                "success": False,
                "error": f"Failed to get project: {str(e)}"
            }


def handle_get_project_by_name(name: str) -> Dict[str, Any]:
    """
    Get project by name (helpful for looking up project_id).
    
    Args:
        name: Project name to search for
        
    Returns:
        Dictionary with success status and project data
    """
    with trace_span("mcp.get_project_by_name", attributes={"mcp.project_name": name}):
        try:
            db = get_db()
            project_service = ProjectService(db)
            project = project_service.get_project_by_name(name)
            if not project:
                add_span_attribute("mcp.success", False)
                add_span_attribute("mcp.error", "project_not_found")
                return {
                    "success": False,
                    "error": f"Project '{name}' not found. Please verify the project name is correct."
                }
            
            add_span_attribute("mcp.success", True)
            return {
                "success": True,
                "project": project
            }
        except Exception as e:
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", str(e))
            return {
                "success": False,
                "error": f"Failed to get project by name: {str(e)}"
            }


def handle_create_project(
    name: str,
    local_path: str,
    origin_url: Optional[str] = None,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new project.
    
    Args:
        name: Project name (must be unique)
        local_path: Local filesystem path to the project
        origin_url: Optional origin URL (e.g., GitHub repository)
        description: Optional project description
        
    Returns:
        Dictionary with success status and created project data
    """
    with trace_span(
        "mcp.create_project",
        attributes={
            "mcp.project_name": name,
            "mcp.has_origin_url": origin_url is not None,
            "mcp.has_description": description is not None
        }
    ):
        try:
            db = get_db()
            project_service = ProjectService(db)
            project_create = ProjectCreate(
                name=name,
                local_path=local_path,
                origin_url=origin_url,
                description=description
            )
            created_project = project_service.create_project(project_create)
            
            add_span_attribute("mcp.success", True)
            add_span_attribute("mcp.project_id", created_project.get("id"))
            return {
                "success": True,
                "project_id": created_project.get("id"),
                "project": created_project
            }
        except ValueError as e:
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", str(e))
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", str(e))
            return {
                "success": False,
                "error": f"Failed to create project: {str(e)}"
            }
