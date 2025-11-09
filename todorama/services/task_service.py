"""
Task service - business logic for task operations.
This layer contains no HTTP framework dependencies.
Handles all business logic including notifications (webhooks, Slack, etc.).
"""
import logging
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC

from todorama.database import TodoDatabase
from todorama.models.task_models import TaskCreate, TaskUpdate, TaskResponse

logger = logging.getLogger(__name__)


class TaskService:
    """Service for task business logic."""
    
    def __init__(self, db: TodoDatabase):
        """Initialize task service with database dependency."""
        self.db = db
    
    def create_task(self, task_data: TaskCreate, auth_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new task and dispatch all related notifications.
        
        Args:
            task_data: Task creation data
            auth_info: Authentication information (contains project_id if authenticated)
            
        Returns:
            Created task data as dictionary
            
        Raises:
            ValueError: If project validation fails
            Exception: If task creation fails
        """
        # Verify project exists if provided
        if task_data.project_id is not None:
            project = self.db.get_project(task_data.project_id)
            if not project:
                raise ValueError(f"Project with ID {task_data.project_id} not found")
            
            # Verify API key is for this project
            if auth_info.get("project_id") != task_data.project_id:
                raise ValueError("API key is not authorized for this project")
        
        # Parse due_date if provided
        due_date_obj = None
        if task_data.due_date:
            try:
                # Try parsing with timezone first
                if task_data.due_date.endswith('Z'):
                    due_date_obj = datetime.fromisoformat(task_data.due_date.replace('Z', '+00:00'))
                else:
                    due_date_obj = datetime.fromisoformat(task_data.due_date)
            except ValueError as e:
                raise ValueError(
                    f"Invalid due_date format '{task_data.due_date}'. "
                    f"Must be ISO 8601 format (e.g., '2024-01-01T00:00:00' or '2024-01-01T00:00:00Z'). "
                    f"Error: {str(e)}"
                )
        
        # Create task
        try:
            task_id = self.db.create_task(
                title=task_data.title,
                task_type=task_data.task_type,
                task_instruction=task_data.task_instruction,
                verification_instruction=task_data.verification_instruction,
                agent_id=task_data.agent_id,
                project_id=task_data.project_id,
                notes=task_data.notes,
                priority=task_data.priority,
                estimated_hours=task_data.estimated_hours,
                due_date=due_date_obj if task_data.due_date else None
            )
        except Exception as e:
            logger.error(f"Failed to create task: {str(e)}", exc_info=True)
            raise Exception("Failed to create task. Please try again or contact support if the issue persists.")
        
        # Retrieve created task
        created_task = self.db.get_task(task_id)
        if not created_task:
            logger.error(f"Task {task_id} was created but could not be retrieved")
            raise Exception("Task was created but could not be retrieved. Please check task status.")
        
        created_task_dict = dict(created_task)
        
        # Dispatch notifications (webhooks, Slack, etc.)
        self._dispatch_task_created_notifications(created_task_dict, task_data.project_id)
        
        return created_task_dict
    
    def _dispatch_task_created_notifications(self, task_data: Dict[str, Any], project_id: Optional[int]):
        """Dispatch all notifications for task creation (webhooks, Slack, etc.)."""
        # Send webhook notifications
        try:
            from webhooks import notify_webhooks
            asyncio.create_task(notify_webhooks(
                self.db,
                project_id=project_id,
                event_type="task.created",
                payload={
                    "event": "task.created",
                    "task": task_data,
                    "timestamp": datetime.now(UTC).isoformat()
                }
            ))
        except Exception as e:
            logger.warning(f"Failed to dispatch webhook notification: {e}")
        
        # Send Slack notification
        try:
            from slack import send_task_notification
            project = self.db.get_project(project_id) if project_id else None
            
            async def send_slack_notif():
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    send_task_notification,
                    None,  # Use default channel from env
                    "task.created",
                    task_data,
                    dict(project) if project else None
                )
            asyncio.create_task(send_slack_notif())
        except Exception as e:
            logger.warning(f"Failed to dispatch Slack notification: {e}")
    
    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get a task by ID."""
        task = self.db.get_task(task_id)
        return dict(task) if task else None
    
    def get_task_for_webhook(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get task data formatted for webhook notifications."""
        task = self.get_task(task_id)
        if not task:
            return None
        return task
    
    def query_tasks(
        self,
        task_type: Optional[str] = None,
        task_status: Optional[str] = None,
        assigned_agent: Optional[str] = None,
        project_id: Optional[int] = None,
        priority: Optional[str] = None,
        tag_id: Optional[int] = None,
        tag_ids: Optional[List[int]] = None,
        order_by: Optional[str] = None,
        limit: int = 100,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        updated_after: Optional[str] = None,
        updated_before: Optional[str] = None,
        completed_after: Optional[str] = None,
        completed_before: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query tasks with filters including advanced date range and text search.
        
        Returns:
            List of task dictionaries
        """
        return self.db.query_tasks(
            task_type=task_type,
            task_status=task_status,
            assigned_agent=assigned_agent,
            project_id=project_id,
            priority=priority,
            tag_id=tag_id,
            tag_ids=tag_ids,
            order_by=order_by,
            limit=limit,
            created_after=created_after,
            created_before=created_before,
            updated_after=updated_after,
            updated_before=updated_before,
            completed_after=completed_after,
            completed_before=completed_before,
            search=search
        )
    
    def search_tasks(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Search tasks using full-text search across titles, instructions, and notes.
        
        Args:
            query: Search query string
            limit: Maximum number of results
            
        Returns:
            List of task dictionaries matching the search query
        """
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty or contain only whitespace")
        return self.db.search_tasks(query.strip(), limit=limit)
    
    def get_overdue_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get tasks that are overdue (past due date and not complete).
        
        Args:
            limit: Maximum number of results
            
        Returns:
            List of overdue task dictionaries
        """
        return self.db.get_overdue_tasks(limit=limit)
    
    def get_tasks_approaching_deadline(self, days_ahead: int = 3, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get tasks that are approaching their deadline.
        
        Args:
            days_ahead: Number of days ahead to look for approaching deadlines
            limit: Maximum number of results
            
        Returns:
            List of task dictionaries approaching deadline
        """
        return self.db.get_tasks_approaching_deadline(days_ahead=days_ahead, limit=limit)
    
    def get_activity_feed(
        self,
        task_id: Optional[int] = None,
        agent_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Get activity feed showing all task updates, completions, and relationship changes
        in chronological order.
        
        Args:
            task_id: Optional task ID to filter by
            agent_id: Optional agent ID to filter by
            start_date: Optional start date filter (ISO format string)
            end_date: Optional end date filter (ISO format string)
            limit: Maximum number of results
            
        Returns:
            List of activity entries in chronological order
        """
        return self.db.get_activity_feed(
            task_id=task_id,
            agent_id=agent_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
    
    def get_task_relationships(self, task_id: int, relationship_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get relationships for a task.
        
        Args:
            task_id: Task ID
            relationship_type: Optional relationship type filter
            
        Returns:
            List of relationship dictionaries
            
        Raises:
            ValueError: If task not found
        """
        # Verify task exists
        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        return self.db.get_related_tasks(task_id, relationship_type=relationship_type)

