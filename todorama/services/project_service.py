"""
Project service - business logic for project operations.
This layer contains no HTTP framework dependencies.
Handles all business logic including notifications (webhooks, Slack, etc.).
"""
import logging
import asyncio
import sqlite3
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC

from todorama.database import TodoDatabase
from todorama.models.project_models import ProjectCreate

logger = logging.getLogger(__name__)


class ProjectService:
    """Service for project business logic."""
    
    def __init__(self, db: TodoDatabase):
        """Initialize project service with database dependency."""
        self.db = db
    
    def create_project(self, project_data: ProjectCreate) -> Dict[str, Any]:
        """
        Create a new project and dispatch all related notifications.
        
        Args:
            project_data: Project creation data
            
        Returns:
            Created project data as dictionary
            
        Raises:
            ValueError: If project name already exists
            Exception: If project creation fails
        """
        # Check if project with same name already exists
        existing = self.db.get_project_by_name(project_data.name)
        if existing:
            raise ValueError(f"Project with name '{project_data.name}' already exists")
        
        # Create project
        try:
            project_id = self.db.create_project(
                name=project_data.name,
                local_path=project_data.local_path,
                origin_url=project_data.origin_url,
                description=project_data.description
            )
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "unique constraint" in error_msg and "projects.name" in error_msg:
                raise ValueError(f"Project with name '{project_data.name}' already exists")
            logger.error(f"Database integrity error creating project: {str(e)}", exc_info=True)
            raise Exception("Failed to create project due to database constraint violation")
        except Exception as e:
            logger.error(f"Failed to create project: {str(e)}", exc_info=True)
            raise Exception("Failed to create project. Please try again or contact support if the issue persists.")
        
        # Retrieve created project
        created_project = self.db.get_project(project_id)
        if not created_project:
            logger.error(f"Project {project_id} was created but could not be retrieved")
            raise Exception("Project was created but could not be retrieved. Please check project status.")
        
        created_project_dict = dict(created_project)
        
        # Dispatch notifications (webhooks, Slack, etc.)
        self._dispatch_project_created_notifications(created_project_dict, project_id)
        
        return created_project_dict
    
    def _dispatch_project_created_notifications(self, project_data: Dict[str, Any], project_id: int):
        """Dispatch all notifications for project creation (webhooks, Slack, etc.)."""
        # Send webhook notifications
        try:
            from webhooks import notify_webhooks
            asyncio.create_task(notify_webhooks(
                self.db,
                project_id=project_id,
                event_type="project.created",
                payload={
                    "event": "project.created",
                    "project": project_data,
                    "timestamp": datetime.now(UTC).isoformat()
                }
            ))
        except Exception as e:
            logger.warning(f"Failed to dispatch webhook notification: {e}")
        
        # Send Slack notification
        try:
            from slack import send_task_notification
            # Note: send_task_notification is designed for tasks, but we can reuse it
            # or create a project-specific notification function later
            
            async def send_slack_notif():
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    send_task_notification,
                    None,  # Use default channel from env
                    "project.created",
                    project_data,
                    project_data  # Pass project as both task and project data
                )
            asyncio.create_task(send_slack_notif())
        except Exception as e:
            logger.warning(f"Failed to dispatch Slack notification: {e}")
    
    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get a project by ID."""
        project = self.db.get_project(project_id)
        return dict(project) if project else None
    
    def get_project_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a project by name."""
        project = self.db.get_project_by_name(name.strip())
        return dict(project) if project else None
    
    def list_projects(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        List all projects.
        
        Args:
            filters: Optional filters (currently not used, reserved for future use)
            
        Returns:
            List of project dictionaries
        """
        projects = self.db.list_projects()
        return [dict(project) for project in projects]
