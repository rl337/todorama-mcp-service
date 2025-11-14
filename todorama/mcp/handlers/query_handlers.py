"""Query and search handlers for MCP API."""

import os
from typing import Optional, List, Dict, Any, Literal

from todorama.mcp_api import get_db
from todorama.mcp.helpers import add_computed_status_fields


def handle_query_tasks(
    project_id: Optional[int] = None,
    task_type: Optional[Literal["concrete", "abstract", "epic"]] = None,
    task_status: Optional[Literal["available", "in_progress", "complete", "blocked", "cancelled"]] = None,
    agent_id: Optional[str] = None,
    priority: Optional[Literal["low", "medium", "high", "critical"]] = None,
    tag_id: Optional[int] = None,
    tag_ids: Optional[List[int]] = None,
    order_by: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Query tasks by various criteria.
    
    Args:
        project_id: Optional project ID filter
        task_type: Optional task type filter
        task_status: Optional task status filter
        agent_id: Optional assigned agent filter
        priority: Optional priority filter
        tag_id: Optional single tag ID filter
        tag_ids: Optional list of tag IDs filter (tasks must have all tags)
        order_by: Optional ordering (priority, priority_asc)
        limit: Maximum number of results
        
    Returns:
        List of task dictionaries
    """
    tasks = get_db().query_tasks(
        task_type=task_type,
        task_status=task_status,
        assigned_agent=agent_id,
        project_id=project_id,
        priority=priority,
        tag_id=tag_id,
        tag_ids=tag_ids,
        order_by=order_by,
        limit=limit
    )
    return [add_computed_status_fields(dict(task)) for task in tasks]


def handle_search_tasks(query: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Search tasks using full-text search across titles, instructions, and notes.
    
    Args:
        query: Search query string
        limit: Maximum number of results to return
        
    Returns:
        List of task dictionaries ranked by relevance
    """
    tasks = get_db().search_tasks(query, limit=limit)
    return [dict(task) for task in tasks]


def handle_query_stale_tasks(hours: Optional[int] = None) -> Dict[str, Any]:
    """
    Query stale tasks (tasks in_progress longer than timeout).
    
    Args:
        hours: Hours threshold for stale tasks (defaults to TASK_TIMEOUT_HOURS env var or 24)
        
    Returns:
        Dictionary with stale_tasks list and count
    """
    stale_tasks = get_db().get_stale_tasks(hours=hours)
    timeout_hours = hours if hours is not None else int(os.getenv("TASK_TIMEOUT_HOURS", "24"))
    
    return {
        "success": True,
        "stale_tasks": [add_computed_status_fields(dict(task)) for task in stale_tasks],
        "count": len(stale_tasks),
        "timeout_hours": timeout_hours
    }


def handle_get_tasks_approaching_deadline(
    days_ahead: int = 3,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Get tasks that are approaching their deadline.
    
    Args:
        days_ahead: Number of days ahead to look for approaching deadlines (default: 3)
        limit: Maximum number of results to return
        
    Returns:
        Dictionary with success status and list of task dictionaries
    """
    tasks = get_db().get_tasks_approaching_deadline(days_ahead=days_ahead, limit=limit)
    return {
        "success": True,
        "tasks": [add_computed_status_fields(dict(task)) for task in tasks],
        "days_ahead": days_ahead
    }


def handle_get_activity_feed(
    task_id: Optional[int] = None,
    agent_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 1000
) -> Dict[str, Any]:
    """
    Get activity feed showing all task updates, completions, and relationship changes
    in chronological order.
    
    Args:
        task_id: Optional task ID to filter by (None for all tasks)
        agent_id: Optional agent ID to filter by
        start_date: Optional start date filter (ISO format string)
        end_date: Optional end date filter (ISO format string)
        limit: Maximum number of results to return
        
    Returns:
        Dictionary with success status and list of activity entries
    """
    try:
        feed = get_db().get_activity_feed(
            task_id=task_id,
            agent_id=agent_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        return {
            "success": True,
            "feed": [dict(entry) for entry in feed],
            "count": len(feed)
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get activity feed: {str(e)}"
        }
