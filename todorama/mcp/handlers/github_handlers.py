"""GitHub-related MCP handlers."""

from typing import Dict, Any

from todorama.mcp_api import get_db


def handle_link_github_issue(task_id: int, github_url: str) -> Dict[str, Any]:
    """
    Link a GitHub issue to a task.
    
    Args:
        task_id: Task ID
        github_url: GitHub issue URL
        
    Returns:
        Dictionary with success status and linked URL
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    try:
        get_db().link_github_issue(task_id, github_url)
        links = get_db().get_github_links(task_id)
        return {
            "success": True,
            "task_id": task_id,
            "github_issue_url": links.get("github_issue_url"),
            "message": f"GitHub issue linked to task {task_id}"
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }


def handle_link_github_pr(task_id: int, github_url: str) -> Dict[str, Any]:
    """
    Link a GitHub PR to a task.
    
    Args:
        task_id: Task ID
        github_url: GitHub PR URL
        
    Returns:
        Dictionary with success status and linked URL
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    try:
        get_db().link_github_pr(task_id, github_url)
        links = get_db().get_github_links(task_id)
        return {
            "success": True,
            "task_id": task_id,
            "github_pr_url": links.get("github_pr_url"),
            "message": f"GitHub PR linked to task {task_id}"
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }


def handle_get_github_links(task_id: int) -> Dict[str, Any]:
    """
    Get GitHub issue and PR links for a task.
    
    Args:
        task_id: Task ID
        
    Returns:
        Dictionary with GitHub links and success status
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    try:
        links = get_db().get_github_links(task_id)
        return {
            "success": True,
            "task_id": task_id,
            "github_issue_url": links.get("github_issue_url"),
            "github_pr_url": links.get("github_pr_url")
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get GitHub links: {str(e)}"
        }
