"""Helper functions for MCP API operations."""

from typing import Dict, Any


def add_computed_status_fields(task_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add computed status fields to a task dictionary.
    
    Adds:
    - needs_verification: True if task is complete but unverified
    - effective_status: Display status (available for both available and verification tasks)
    
    Args:
        task_dict: Task dictionary to enhance
        
    Returns:
        Enhanced task dictionary with computed fields
    """
    task_dict = dict(task_dict)  # Make a copy
    if task_dict.get("task_status") == "complete" and task_dict.get("verification_status") == "unverified":
        task_dict["needs_verification"] = True
        task_dict["effective_status"] = "available"  # Verification tasks show as available
    else:
        task_dict["needs_verification"] = False
        task_dict["effective_status"] = task_dict.get("task_status", "available")
    return task_dict
