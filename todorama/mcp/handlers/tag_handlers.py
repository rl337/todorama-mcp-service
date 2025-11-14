"""Tag-related MCP handlers."""

from typing import Dict, Any

from todorama.mcp_api import get_db


def handle_create_tag(name: str) -> Dict[str, Any]:
    """
    Create a tag (or return existing tag ID if name already exists).
    
    Args:
        name: Tag name
        
    Returns:
        Dictionary with tag ID and success status
    """
    if not name or not name.strip():
        return {
            "success": False,
            "error": "Tag name cannot be empty"
        }
    
    try:
        tag_id = get_db().create_tag(name=name.strip())
        tag = get_db().get_tag(tag_id)
        return {
            "success": True,
            "tag_id": tag_id,
            "tag": dict(tag) if tag else None
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to create tag: {str(e)}"
        }


def handle_list_tags() -> Dict[str, Any]:
    """
    List all tags.
    
    Returns:
        Dictionary with list of tag dictionaries
    """
    tags = get_db().list_tags()
    return {
        "success": True,
        "tags": [dict(tag) for tag in tags]
    }


def handle_assign_tag_to_task(task_id: int, tag_id: int) -> Dict[str, Any]:
    """
    Assign a tag to a task.
    
    Args:
        task_id: Task ID
        tag_id: Tag ID
        
    Returns:
        Dictionary with success status
    """
    # Verify task exists
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    # Verify tag exists
    tag = get_db().get_tag(tag_id)
    if not tag:
        return {
            "success": False,
            "error": f"Tag {tag_id} not found. Please verify the tag_id is correct."
        }
    
    try:
        get_db().assign_tag_to_task(task_id, tag_id)
        return {
            "success": True,
            "task_id": task_id,
            "tag_id": tag_id,
            "message": f"Tag {tag_id} assigned to task {task_id}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to assign tag: {str(e)}"
        }


def handle_remove_tag_from_task(task_id: int, tag_id: int) -> Dict[str, Any]:
    """
    Remove a tag from a task.
    
    Args:
        task_id: Task ID
        tag_id: Tag ID
        
    Returns:
        Dictionary with success status
    """
    # Verify task exists
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    try:
        get_db().remove_tag_from_task(task_id, tag_id)
        return {
            "success": True,
            "task_id": task_id,
            "tag_id": tag_id,
            "message": f"Tag {tag_id} removed from task {task_id}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to remove tag: {str(e)}"
        }


def handle_get_task_tags(task_id: int) -> Dict[str, Any]:
    """
    Get all tags assigned to a task.
    
    Args:
        task_id: Task ID
        
    Returns:
        Dictionary with list of tag dictionaries
    """
    # Verify task exists
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    tags = get_db().get_task_tags(task_id)
    return {
        "success": True,
        "task_id": task_id,
        "tags": [dict(tag) for tag in tags]
    }
