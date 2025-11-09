"""
Recurring task service - business logic for recurring task operations.
This layer contains no HTTP framework dependencies.
Handles all business logic including validation, recurrence scheduling, and instance creation.
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import calendar
import json

from todorama.database import TodoDatabase

logger = logging.getLogger(__name__)


class RecurringTaskService:
    """Service for recurring task business logic."""
    
    def __init__(self, db: TodoDatabase):
        """Initialize recurring task service with database dependency."""
        self.db = db
    
    def create_recurring_task(
        self,
        task_id: int,
        recurrence_type: str,
        next_occurrence: datetime,
        recurrence_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a recurring task pattern.
        
        Args:
            task_id: ID of the base task to recur
            recurrence_type: 'daily', 'weekly', or 'monthly'
            next_occurrence: When to create the next instance
            recurrence_config: Optional recurrence config
                - For weekly: {'day_of_week': 0-6} (0=Monday for weekly)
                - For monthly: {'day_of_month': 1-31}
            
        Returns:
            Created recurring task data as dictionary
            
        Raises:
            ValueError: If validation fails (invalid recurrence_type, task not found, etc.)
        """
        # Validate recurrence_type
        if recurrence_type not in ["daily", "weekly", "monthly"]:
            raise ValueError(
                f"Invalid recurrence_type: {recurrence_type}. "
                f"Must be 'daily', 'weekly', or 'monthly'"
            )
        
        # Verify task exists
        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        # Validate recurrence_config based on type
        config = recurrence_config or {}
        if recurrence_type == "weekly":
            if "day_of_week" in config:
                day_of_week = config["day_of_week"]
                if not isinstance(day_of_week, int) or day_of_week < 0 or day_of_week > 6:
                    raise ValueError(
                        f"Invalid day_of_week: {day_of_week}. "
                        f"Must be integer between 0 (Monday) and 6 (Sunday)"
                    )
        elif recurrence_type == "monthly":
            if "day_of_month" in config:
                day_of_month = config["day_of_month"]
                if not isinstance(day_of_month, int) or day_of_month < 1 or day_of_month > 31:
                    raise ValueError(
                        f"Invalid day_of_month: {day_of_month}. "
                        f"Must be integer between 1 and 31"
                    )
        
        # Validate next_occurrence is in the future
        if next_occurrence <= datetime.now():
            logger.warning(
                f"next_occurrence {next_occurrence} is in the past. "
                f"Recurring task will be created but may trigger immediately."
            )
        
        # Create recurring task
        try:
            recurring_id = self.db.create_recurring_task(
                task_id=task_id,
                recurrence_type=recurrence_type,
                recurrence_config=config,
                next_occurrence=next_occurrence
            )
        except Exception as e:
            logger.error(f"Failed to create recurring task: {str(e)}", exc_info=True)
            raise ValueError(f"Failed to create recurring task: {str(e)}")
        
        # Retrieve created recurring task
        recurring = self.db.get_recurring_task(recurring_id)
        if not recurring:
            logger.error(f"Recurring task {recurring_id} was created but could not be retrieved")
            raise ValueError("Recurring task was created but could not be retrieved")
        
        return dict(recurring)
    
    def get_recurring_task(self, recurring_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a recurring task by ID.
        
        Args:
            recurring_id: Recurring task ID
            
        Returns:
            Recurring task dictionary or None if not found
        """
        recurring = self.db.get_recurring_task(recurring_id)
        if recurring:
            return dict(recurring)
        return None
    
    def list_recurring_tasks(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """
        List all recurring tasks.
        
        Args:
            active_only: If True, only return active recurring tasks
            
        Returns:
            List of recurring task dictionaries
        """
        recurring_tasks = self.db.list_recurring_tasks(active_only=active_only)
        return [dict(task) for task in recurring_tasks]
    
    def update_recurring_task(
        self,
        recurring_id: int,
        recurrence_type: Optional[str] = None,
        recurrence_config: Optional[Dict[str, Any]] = None,
        next_occurrence: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Update a recurring task.
        
        Args:
            recurring_id: Recurring task ID
            recurrence_type: Optional new recurrence type
            recurrence_config: Optional new recurrence config
            next_occurrence: Optional new next occurrence date
            
        Returns:
            Updated recurring task data as dictionary
            
        Raises:
            ValueError: If validation fails or recurring task not found
        """
        # Verify recurring task exists
        recurring = self.db.get_recurring_task(recurring_id)
        if not recurring:
            raise ValueError(f"Recurring task {recurring_id} not found")
        
        # Validate recurrence_type if provided
        if recurrence_type is not None:
            if recurrence_type not in ["daily", "weekly", "monthly"]:
                raise ValueError(
                    f"Invalid recurrence_type: {recurrence_type}. "
                    f"Must be 'daily', 'weekly', or 'monthly'"
                )
        
        # Validate recurrence_config if provided
        if recurrence_config is not None:
            if recurrence_type or recurring["recurrence_type"]:
                effective_type = recurrence_type or recurring["recurrence_type"]
                if effective_type == "weekly":
                    if "day_of_week" in recurrence_config:
                        day_of_week = recurrence_config["day_of_week"]
                        if not isinstance(day_of_week, int) or day_of_week < 0 or day_of_week > 6:
                            raise ValueError(
                                f"Invalid day_of_week: {day_of_week}. "
                                f"Must be integer between 0 (Monday) and 6 (Sunday)"
                            )
                elif effective_type == "monthly":
                    if "day_of_month" in recurrence_config:
                        day_of_month = recurrence_config["day_of_month"]
                        if not isinstance(day_of_month, int) or day_of_month < 1 or day_of_month > 31:
                            raise ValueError(
                                f"Invalid day_of_month: {day_of_month}. "
                                f"Must be integer between 1 and 31"
                            )
        
        # Update recurring task
        try:
            self.db.update_recurring_task(
                recurring_id=recurring_id,
                recurrence_type=recurrence_type,
                recurrence_config=recurrence_config,
                next_occurrence=next_occurrence
            )
        except Exception as e:
            logger.error(f"Failed to update recurring task {recurring_id}: {str(e)}", exc_info=True)
            raise ValueError(f"Failed to update recurring task: {str(e)}")
        
        # Retrieve updated recurring task
        updated = self.db.get_recurring_task(recurring_id)
        if not updated:
            logger.error(f"Recurring task {recurring_id} was updated but could not be retrieved")
            raise ValueError("Recurring task was updated but could not be retrieved")
        
        return dict(updated)
    
    def deactivate_recurring_task(self, recurring_id: int) -> Dict[str, Any]:
        """
        Deactivate a recurring task (stop creating new instances).
        
        Args:
            recurring_id: Recurring task ID
            
        Returns:
            Deactivated recurring task data as dictionary
            
        Raises:
            ValueError: If recurring task not found
        """
        # Verify recurring task exists
        recurring = self.db.get_recurring_task(recurring_id)
        if not recurring:
            raise ValueError(f"Recurring task {recurring_id} not found")
        
        # Deactivate recurring task
        try:
            self.db.deactivate_recurring_task(recurring_id)
        except Exception as e:
            logger.error(f"Failed to deactivate recurring task {recurring_id}: {str(e)}", exc_info=True)
            raise ValueError(f"Failed to deactivate recurring task: {str(e)}")
        
        # Retrieve deactivated recurring task
        deactivated = self.db.get_recurring_task(recurring_id)
        if not deactivated:
            logger.error(f"Recurring task {recurring_id} was deactivated but could not be retrieved")
            raise ValueError("Recurring task was deactivated but could not be retrieved")
        
        return dict(deactivated)
    
    def create_recurring_instance(self, recurring_id: int) -> Dict[str, Any]:
        """
        Create a new task instance from a recurring task pattern.
        Updates next_occurrence based on recurrence type.
        
        Args:
            recurring_id: Recurring task ID
            
        Returns:
            Dictionary with created task instance ID and updated recurring task data
            
        Raises:
            ValueError: If validation fails (recurring task not found, not active, etc.)
        """
        # Verify recurring task exists and is active
        recurring = self.db.get_recurring_task(recurring_id)
        if not recurring:
            raise ValueError(f"Recurring task {recurring_id} not found")
        
        if recurring["is_active"] != 1:
            raise ValueError(f"Recurring task {recurring_id} is not active")
        
        # Create instance
        try:
            instance_id = self.db.create_recurring_instance(recurring_id)
        except Exception as e:
            logger.error(
                f"Failed to create recurring instance for {recurring_id}: {str(e)}",
                exc_info=True
            )
            raise ValueError(f"Failed to create recurring instance: {str(e)}")
        
        # Retrieve updated recurring task
        updated = self.db.get_recurring_task(recurring_id)
        if not updated:
            logger.warning(f"Recurring task {recurring_id} was updated but could not be retrieved")
            updated = recurring  # Fallback to original
        
        return {
            "instance_id": instance_id,
            "recurring_task": dict(updated)
        }
