"""Analytics and statistics handlers for MCP API."""

from typing import Optional, List, Dict, Any, Literal

from todorama.mcp_api import get_db
from todorama.mcp.helpers import add_computed_status_fields


def handle_get_agent_performance(
    agent_id: str,
    task_type: Optional[Literal["concrete", "abstract", "epic"]] = None
) -> Dict[str, Any]:
    """
    Get performance statistics for an agent.
    
    Args:
        agent_id: Agent ID
        task_type: Optional filter by task type
        
    Returns:
        Dictionary with agent performance statistics
    """
    stats = get_db().get_agent_stats(agent_id, task_type)
    return stats


def handle_get_task_statistics(
    project_id: Optional[int] = None,
    task_type: Optional[Literal["concrete", "abstract", "epic"]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get aggregated statistics about tasks without requiring Python post-processing.
    
    Returns:
    - Total task count
    - Counts by status (available, in_progress, complete, blocked, cancelled)
    - Counts by project_id (if project_id parameter provided, otherwise all projects)
    - Counts by task_type (concrete, abstract, epic)
    - Completion rate (percentage)
    
    Args:
        project_id: Optional project filter
        task_type: Optional task type filter
        start_date: Optional start date filter (ISO format timestamp)
        end_date: Optional end date filter (ISO format timestamp)
        
    Returns:
        Dictionary with statistics including counts by status, type, project, and completion rate
    """
    stats = get_db().get_task_statistics(
        project_id=project_id,
        task_type=task_type,
        start_date=start_date,
        end_date=end_date
    )
    return {
        "success": True,
        **stats
    }


def handle_get_recent_completions(
    limit: int = 10,
    project_id: Optional[int] = None,
    hours: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get recently completed tasks sorted by completion time.
    
    Parameters:
    - limit: number of tasks to return (default: 10)
    - project_id: optional filter by project
    - hours: optional filter for completions within last N hours
    
    Returns lightweight summaries (task_id, title, completed_at, agent_id, project_id).
    
    Args:
        limit: Maximum number of tasks to return (default: 10)
        project_id: Optional project filter
        hours: Optional filter for completions within last N hours
        
    Returns:
        Dictionary with success status and list of completed tasks (lightweight format)
    """
    completions = get_db().get_recent_completions(
        limit=limit,
        project_id=project_id,
        hours=hours
    )
    return {
        "success": True,
        "tasks": [add_computed_status_fields(dict(task)) for task in completions],
        "count": len(completions)
    }


def handle_get_task_summary(
    project_id: Optional[int] = None,
    task_type: Optional[Literal["concrete", "abstract", "epic"]] = None,
    task_status: Optional[Literal["available", "in_progress", "complete", "blocked", "cancelled"]] = None,
    assigned_agent: Optional[str] = None,
    priority: Optional[Literal["low", "medium", "high", "critical"]] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Get lightweight task summaries (key fields only) instead of full task objects.
    
    Returns only essential fields: task_id, title, status, assigned_agent, project_id, 
    updated_at, created_at, completed_at. Not the full task with all fields.
    
    Parameters: Same as query_tasks() but returns only essential fields.
    Benefits: Faster queries, less data transfer, easier to parse, better for bulk operations.
    
    Args:
        project_id: Optional project filter
        task_type: Optional task type filter
        task_status: Optional status filter
        assigned_agent: Optional agent filter
        priority: Optional priority filter
        limit: Maximum number of results (default: 100)
        
    Returns:
        Dictionary with success status and list of task summaries (essential fields only)
    """
    summaries = get_db().get_task_summaries(
        project_id=project_id,
        task_type=task_type,
        task_status=task_status,
        assigned_agent=assigned_agent,
        priority=priority,
        limit=limit
    )
    return {
        "success": True,
        "tasks": summaries,
        "count": len(summaries)
    }


def handle_bulk_unlock_tasks(
    task_ids: List[int],
    agent_id: str
) -> Dict[str, Any]:
    """
    Unlock multiple tasks atomically in a single operation.
    
    Parameters:
    - task_ids: list of task IDs to unlock
    - agent_id: agent performing the unlock (for logging)
    
    Benefits: Single operation instead of multiple API calls, atomic transaction 
    (all succeed or all fail), better for system maintenance operations.
    
    Use case: "Unlock all stale tasks" or "Unlock all tasks assigned to agent X"
    
    Args:
        task_ids: List of task IDs to unlock
        agent_id: Agent ID performing the unlock (for logging)
        
    Returns:
        Dictionary with success status, unlocked_count, unlocked_task_ids, 
        failed_count, and failed_task_ids (with error messages)
    """
    result = get_db().bulk_unlock_tasks(task_ids=task_ids, agent_id=agent_id)
    return result
