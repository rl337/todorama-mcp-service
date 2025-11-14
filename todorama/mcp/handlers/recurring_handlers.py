"""Recurring task-related MCP handlers."""

from typing import Optional, Dict, Any, Literal
from datetime import datetime

from todorama.mcp_api import get_db


def handle_create_recurring_task(
    task_id: int,
    recurrence_type: Literal["daily", "weekly", "monthly"],
    next_occurrence: str,
    recurrence_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a recurring task pattern.
    
    Args:
        task_id: ID of the base task to recur
        recurrence_type: 'daily', 'weekly', or 'monthly'
        next_occurrence: When to create the next instance (ISO format timestamp)
        recurrence_config: Optional recurrence config (day_of_week for weekly, day_of_month for monthly)
        
    Returns:
        Dictionary with recurring task ID and success status
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    try:
        next_occurrence_obj = datetime.fromisoformat(next_occurrence.replace('Z', '+00:00'))
    except ValueError:
        return {
            "success": False,
            "error": "Invalid next_occurrence format. Must be ISO format timestamp."
        }
    
    try:
        recurring_id = get_db().create_recurring_task(
            task_id=task_id,
            recurrence_type=recurrence_type,
            recurrence_config=recurrence_config or {},
            next_occurrence=next_occurrence_obj
        )
        return {
            "success": True,
            "recurring_task_id": recurring_id
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }


def handle_list_recurring_tasks(
    active_only: bool = False
) -> Dict[str, Any]:
    """
    List all recurring tasks.
    
    Args:
        active_only: If True, only return active recurring tasks
        
    Returns:
        Dictionary with list of recurring task dictionaries
    """
    recurring_tasks = get_db().list_recurring_tasks(active_only=active_only)
    return {
        "success": True,
        "recurring_tasks": recurring_tasks
    }


def handle_get_recurring_task(recurring_id: int) -> Dict[str, Any]:
    """
    Get a recurring task by ID.
    
    Args:
        recurring_id: Recurring task ID
        
    Returns:
        Dictionary with recurring task data and success status
    """
    recurring = get_db().get_recurring_task(recurring_id)
    if not recurring:
        return {
            "success": False,
            "error": f"Recurring task {recurring_id} not found. Please verify the recurring_id is correct."
        }
    
    return {
        "success": True,
        "recurring_task": recurring
    }


def handle_update_recurring_task(
    recurring_id: int,
    recurrence_type: Optional[Literal["daily", "weekly", "monthly"]] = None,
    recurrence_config: Optional[Dict[str, Any]] = None,
    next_occurrence: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update a recurring task.
    
    Args:
        recurring_id: Recurring task ID
        recurrence_type: Optional new recurrence type
        recurrence_config: Optional new recurrence config
        next_occurrence: Optional new next occurrence date (ISO format timestamp)
        
    Returns:
        Dictionary with success status
    """
    next_occurrence_obj = None
    if next_occurrence:
        try:
            next_occurrence_obj = datetime.fromisoformat(next_occurrence.replace('Z', '+00:00'))
        except ValueError:
            return {
                "success": False,
                "error": "Invalid next_occurrence format. Must be ISO format timestamp."
            }
    
    try:
        get_db().update_recurring_task(
            recurring_id=recurring_id,
            recurrence_type=recurrence_type,
            recurrence_config=recurrence_config,
            next_occurrence=next_occurrence_obj
        )
        return {
            "success": True,
            "recurring_task_id": recurring_id,
            "message": f"Recurring task {recurring_id} updated successfully"
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }


def handle_deactivate_recurring_task(recurring_id: int) -> Dict[str, Any]:
    """
    Deactivate a recurring task (stop creating new instances).
    
    Args:
        recurring_id: Recurring task ID
        
    Returns:
        Dictionary with success status
    """
    recurring = get_db().get_recurring_task(recurring_id)
    if not recurring:
        return {
            "success": False,
            "error": f"Recurring task {recurring_id} not found. Please verify the recurring_id is correct."
        }
    
    get_db().deactivate_recurring_task(recurring_id)
    return {
        "success": True,
        "recurring_task_id": recurring_id,
        "message": f"Recurring task {recurring_id} deactivated successfully"
    }


def handle_create_recurring_instance(recurring_id: int) -> Dict[str, Any]:
    """
    Manually create the next instance from a recurring task.
    
    Args:
        recurring_id: Recurring task ID
        
    Returns:
        Dictionary with instance ID and success status
    """
    try:
        instance_id = get_db().create_recurring_instance(recurring_id)
        return {
            "success": True,
            "instance_id": instance_id,
            "recurring_task_id": recurring_id,
            "message": f"Instance {instance_id} created successfully"
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }
