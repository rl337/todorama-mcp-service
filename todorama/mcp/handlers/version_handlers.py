"""Task version-related MCP handlers."""

from typing import Dict, Any

from todorama.mcp_api import get_db


def handle_get_task_versions(task_id: int) -> Dict[str, Any]:
    """
    Get all versions for a task.
    
    Args:
        task_id: Task ID
        
    Returns:
        Dictionary with success status and list of versions
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    versions = get_db().get_task_versions(task_id)
    return {
        "success": True,
        "task_id": task_id,
        "versions": [dict(v) for v in versions],
        "count": len(versions)
    }


def handle_get_task_version(task_id: int, version_number: int) -> Dict[str, Any]:
    """
    Get a specific version of a task.
    
    Args:
        task_id: Task ID
        version_number: Version number to retrieve
        
    Returns:
        Dictionary with version data and success status
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    version = get_db().get_task_version(task_id, version_number)
    if not version:
        return {
            "success": False,
            "error": f"Version {version_number} for task {task_id} not found. Please verify the version_number is correct."
        }
    
    return {
        "success": True,
        "version": dict(version)
    }


def handle_get_latest_task_version(task_id: int) -> Dict[str, Any]:
    """
    Get the latest version of a task.
    
    Args:
        task_id: Task ID
        
    Returns:
        Dictionary with latest version data and success status
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    version = get_db().get_latest_task_version(task_id)
    if not version:
        return {
            "success": False,
            "error": f"No versions found for task {task_id}."
        }
    
    return {
        "success": True,
        "version": dict(version)
    }


def handle_diff_task_versions(
    task_id: int,
    version_number_1: int,
    version_number_2: int
) -> Dict[str, Any]:
    """
    Diff two task versions and return changed fields.
    
    Args:
        task_id: Task ID
        version_number_1: First version number (older)
        version_number_2: Second version number (newer)
        
    Returns:
        Dictionary with diff data and success status
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    try:
        diff = get_db().diff_task_versions(task_id, version_number_1, version_number_2)
        return {
            "success": True,
            "task_id": task_id,
            "version_1": version_number_1,
            "version_2": version_number_2,
            "diff": diff,
            "changed_fields": list(diff.keys())
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }
