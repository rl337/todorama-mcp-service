"""Comment-related MCP handlers."""

from typing import Optional, List, Dict, Any

from todorama.mcp_api import get_db


def handle_create_comment(
    task_id: int,
    agent_id: str,
    content: str,
    parent_comment_id: Optional[int] = None,
    mentions: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Create a comment on a task.
    
    Args:
        task_id: Task ID
        agent_id: Agent ID creating the comment
        content: Comment content
        parent_comment_id: Optional parent comment ID for threaded replies
        mentions: Optional list of agent IDs mentioned in the comment
        
    Returns:
        Dictionary with comment ID and success status
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    if not content or not content.strip():
        return {
            "success": False,
            "error": "Comment content cannot be empty"
        }
    
    try:
        comment_id = get_db().create_comment(
            task_id=task_id,
            agent_id=agent_id,
            content=content,
            parent_comment_id=parent_comment_id,
            mentions=mentions
        )
        return {
            "success": True,
            "comment_id": comment_id,
            "task_id": task_id,
            "message": f"Comment created successfully on task {task_id}"
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to create comment: {str(e)}"
        }


def handle_get_task_comments(
    task_id: int,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Get all comments for a task.
    
    Args:
        task_id: Task ID
        limit: Maximum number of comments to return
        
    Returns:
        Dictionary with list of comments
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    comments = get_db().get_task_comments(task_id, limit=limit)
    return {
        "success": True,
        "task_id": task_id,
        "comments": [dict(c) for c in comments],
        "count": len(comments)
    }


def handle_get_comment_thread(
    comment_id: int
) -> Dict[str, Any]:
    """
    Get a comment thread (parent comment and all replies).
    
    Args:
        comment_id: Parent comment ID
        
    Returns:
        Dictionary with thread comments
    """
    comment = get_db().get_comment(comment_id)
    if not comment:
        return {
            "success": False,
            "error": f"Comment {comment_id} not found. Please verify the comment_id is correct."
        }
    
    thread = get_db().get_comment_thread(comment_id)
    return {
        "success": True,
        "comment_id": comment_id,
        "thread": [dict(c) for c in thread],
        "count": len(thread)
    }


def handle_update_comment(
    comment_id: int,
    agent_id: str,
    content: str
) -> Dict[str, Any]:
    """
    Update a comment.
    
    Args:
        comment_id: Comment ID
        agent_id: Agent ID (must be the comment owner)
        content: Updated comment content
        
    Returns:
        Dictionary with success status
    """
    comment = get_db().get_comment(comment_id)
    if not comment:
        return {
            "success": False,
            "error": f"Comment {comment_id} not found. Please verify the comment_id is correct."
        }
    
    if not content or not content.strip():
        return {
            "success": False,
            "error": "Comment content cannot be empty"
        }
    
    try:
        success = get_db().update_comment(comment_id, agent_id, content)
        if success:
            updated_comment = get_db().get_comment(comment_id)
            return {
                "success": True,
                "comment_id": comment_id,
                "comment": dict(updated_comment) if updated_comment else None,
                "message": f"Comment {comment_id} updated successfully"
            }
        else:
            return {
                "success": False,
                "error": "Failed to update comment"
            }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to update comment: {str(e)}"
        }


def handle_delete_comment(
    comment_id: int,
    agent_id: str
) -> Dict[str, Any]:
    """
    Delete a comment (cascades to replies).
    
    Args:
        comment_id: Comment ID
        agent_id: Agent ID (must be the comment owner)
        
    Returns:
        Dictionary with success status
    """
    comment = get_db().get_comment(comment_id)
    if not comment:
        return {
            "success": False,
            "error": f"Comment {comment_id} not found. Please verify the comment_id is correct."
        }
    
    try:
        success = get_db().delete_comment(comment_id, agent_id)
        if success:
            return {
                "success": True,
                "comment_id": comment_id,
                "message": f"Comment {comment_id} deleted successfully"
            }
        else:
            return {
                "success": False,
                "error": "Failed to delete comment"
            }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to delete comment: {str(e)}"
        }
