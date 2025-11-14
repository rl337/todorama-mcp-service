"""Task-related MCP handlers."""

from typing import Optional, List, Dict, Any, Literal

from todorama.mcp_api import get_db
from todorama.tracing import trace_span, add_span_attribute
from todorama.mcp.helpers import add_computed_status_fields


def handle_list_available_tasks(
    agent_type: Literal["breakdown", "implementation"],
    project_id: Optional[int] = None,
    limit: int = 10,
    organization_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    List available tasks for an agent type.
    
    Args:
        agent_type: 'breakdown' for abstract/epic tasks, 'implementation' for concrete tasks
        project_id: Optional project ID to filter tasks
        limit: Maximum number of tasks to return
        organization_id: Optional organization ID to filter tasks (for multi-tenancy)
        
    Returns:
        List of task dictionaries
    """
    with trace_span(
        "mcp.list_available_tasks",
        attributes={
            "mcp.agent_type": agent_type,
            "mcp.project_id": project_id,
            "mcp.limit": limit,
            "mcp.organization_id": organization_id,
        }
    ):
        tasks = get_db().get_available_tasks_for_agent(
            agent_type, 
            project_id=project_id, 
            limit=limit,
            organization_id=organization_id
        )
        result = [add_computed_status_fields(dict(task)) for task in tasks]
        add_span_attribute("mcp.tasks_count", len(result))
        return result


def handle_reserve_task(task_id: int, agent_id: str) -> Dict[str, Any]:
    """
    Reserve (lock) a task for an agent.
    
    Args:
        task_id: Task ID to reserve
        agent_id: Agent ID reserving the task
        
    Returns:
        Task dictionary if successful, None if already locked
    """
    with trace_span(
        "mcp.reserve_task",
        attributes={
            "mcp.task_id": task_id,
            "mcp.agent_id": agent_id,
        }
    ) as span:
        # Check if task exists first
        task = get_db().get_task(task_id)
        if not task:
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", "task_not_found")
            return {
                "success": False,
                "error": f"Task {task_id} not found. Please verify the task_id is correct."
            }
        
        # Allow locking tasks in needs_verification state (complete but unverified)
        # These tasks should be lockable for verification work
        task_status = task.get("task_status", "unknown")
        verification_status = task.get("verification_status", "unverified")
        is_needs_verification = task_status == "complete" and verification_status == "unverified"
        
        # Only allow locking if task is available OR in needs_verification state
        if task_status != "available" and not is_needs_verification:
            assigned_to = task.get("assigned_agent", "none")
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", "cannot_lock")
            add_span_attribute("mcp.current_status", task_status)
            return {
                "success": False,
                "error": f"Task {task_id} cannot be locked. Current status: {task_status}, assigned to: {assigned_to}. Only tasks with status 'available' or in 'needs_verification' state (complete but unverified) can be locked."
            }
        
        success = get_db().lock_task(task_id, agent_id)
        if not success:
            assigned_to = task.get("assigned_agent", "none")
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", "cannot_lock")
            add_span_attribute("mcp.current_status", task_status)
            return {
                "success": False,
                "error": f"Task {task_id} cannot be locked. Task is assigned to: {assigned_to}. It may already be locked by another agent."
            }
        
        # Check for stale status - look for recent "finding" updates that indicate task was abandoned
        updates = get_db().get_task_updates(task_id, limit=10)
        stale_warning = None
        for update in updates:
            if update.get("change_type") == "finding":
                notes = update.get("notes", "")
                # Check if this is a stale/abandoned task finding
                if "stale" in notes.lower() or "abandoned" in notes.lower() or "unlocked due to timeout" in notes.lower():
                    stale_warning = {
                        "is_stale": True,
                        "previous_agent": update.get("agent_id", "unknown"),
                        "unlocked_at": update.get("created_at"),
                        "stale_finding": notes,
                        "warning": "⚠️ WARNING: This task was previously abandoned/stale and may have partially completed work. You MUST verify all previous work before continuing."
                    }
                    add_span_attribute("mcp.stale_task", True)
                    break
        
        # Refresh task data after locking
        updated_task = get_db().get_task(task_id)
        task_dict = add_computed_status_fields(dict(updated_task))
        result = {"success": True, "task": task_dict}
        if stale_warning:
            result["stale_warning"] = stale_warning
        add_span_attribute("mcp.success", True)
        return result


def handle_complete_task(
    task_id: int,
    agent_id: str,
    notes: Optional[str] = None,
    actual_hours: Optional[float] = None,
    followup_title: Optional[str] = None,
    followup_task_type: Optional[str] = None,
    followup_instruction: Optional[str] = None,
    followup_verification: Optional[str] = None
) -> Dict[str, Any]:
    """
    Complete a task and optionally create a followup task.
    
    Args:
        task_id: Task ID to complete
        agent_id: Agent ID completing the task
        notes: Optional notes about completion
        actual_hours: Optional actual hours spent on the task
        followup_title: Optional followup task title
        followup_task_type: Optional followup task type
        followup_instruction: Optional followup task instruction
        followup_verification: Optional followup verification instruction
        
    Returns:
        Dictionary with completion status and optional followup task ID
    """
    with trace_span(
        "mcp.complete_task",
        attributes={
            "mcp.task_id": task_id,
            "mcp.agent_id": agent_id,
            "mcp.has_notes": notes is not None,
            "mcp.has_followup": followup_title is not None,
        }
    ) as span:
        # Verify task exists and is locked by this agent
        task = get_db().get_task(task_id)
        if not task:
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", "task_not_found")
            return {
                "success": False,
                "error": f"Task {task_id} not found. Please verify the task_id is correct."
            }
        
        if task["assigned_agent"] != agent_id and task["task_status"] == "in_progress":
            current_agent = task.get("assigned_agent", "none")
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", "not_assigned")
            return {
                "success": False,
                "error": f"Task {task_id} is currently assigned to agent '{current_agent}'. Only the assigned agent can complete this task."
            }
        
        # Check if task is already complete but unverified - this means it's a verification task
        # A task needs verification if: it has a completed_at timestamp but verification_status is unverified
        # Note: The task might be in_progress (if it was reserved for verification) but still needs verification
        task_status = task.get("task_status")
        verification_status = task.get("verification_status", "unverified")
        completed_at = task.get("completed_at")
        
        # If task was previously completed (has completed_at) but is unverified, treat this as verification
        if completed_at and verification_status == "unverified":
            # This is a verification task - verify it instead of completing again
            try:
                get_db().verify_task(task_id, agent_id, notes=notes)
                add_span_attribute("mcp.success", True)
                add_span_attribute("mcp.action", "verified")
                return {
                    "success": True,
                    "task_id": task_id,
                    "verified": True,
                    "message": f"Task {task_id} verified by agent {agent_id}"
                }
            except Exception as e:
                add_span_attribute("mcp.success", False)
                add_span_attribute("mcp.error", str(e))
                return {
                    "success": False,
                    "error": f"Failed to verify task {task_id}: {str(e)}"
                }
        
        # Regular completion - complete the task
        get_db().complete_task(task_id, agent_id, notes=notes, actual_hours=actual_hours)
        
        result = {"success": True, "task_id": task_id, "completed": True}
        
        # Create followup if provided
        if followup_title and followup_task_type and followup_instruction and followup_verification:
            # Use the same project_id as the completed task
            completed_task = get_db().get_task(task_id)
            followup_project_id = completed_task.get("project_id") if completed_task else None
            
            followup_id = get_db().create_task(
                title=followup_title,
                task_type=followup_task_type,
                task_instruction=followup_instruction,
                verification_instruction=followup_verification,
                agent_id=agent_id,
                project_id=followup_project_id,
                notes=None
            )
            
            get_db().create_relationship(
                parent_task_id=task_id,
                child_task_id=followup_id,
                relationship_type="followup",
                agent_id=agent_id
            )
            
            result["followup_task_id"] = followup_id
            add_span_attribute("mcp.followup_task_id", followup_id)
        
        add_span_attribute("mcp.success", True)
        return result


def handle_create_task(
    title: str,
    task_type: Literal["concrete", "abstract", "epic"],
    task_instruction: str,
    verification_instruction: str,
    agent_id: str,
    project_id: Optional[int] = None,
    parent_task_id: Optional[int] = None,
    relationship_type: Optional[Literal["subtask", "blocking", "blocked_by", "related"]] = None,
    notes: Optional[str] = None,
    priority: Optional[Literal["low", "medium", "high", "critical"]] = None,
    estimated_hours: Optional[float] = None,
    due_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new task, optionally linked to a parent task.
    
    Args:
        title: Task title
        task_type: Task type (concrete, abstract, epic)
        task_instruction: What to do
        verification_instruction: How to verify completion
        agent_id: Agent ID creating the task
        project_id: Optional project ID
        parent_task_id: Optional parent task ID
        relationship_type: Optional relationship type to parent
        notes: Optional notes
        priority: Optional priority (low, medium, high, critical). Defaults to medium.
        estimated_hours: Optional estimated hours for the task
        due_date: Optional due date (ISO format timestamp)
        
    Returns:
        Dictionary with created task ID and optional relationship ID
    """
    with trace_span(
        "mcp.create_task",
        attributes={
            "mcp.agent_id": agent_id,
            "mcp.task_type": task_type,
            "mcp.project_id": project_id,
            "mcp.parent_task_id": parent_task_id,
            "mcp.has_relationship": relationship_type is not None,
            "mcp.has_priority": priority is not None,
        }
    ) as span:
        # Parse due_date if provided
        due_date_obj = None
        if due_date:
            from datetime import datetime
            try:
                due_date_obj = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
            except ValueError:
                due_date_obj = datetime.fromisoformat(due_date)
        
        try:
            task_id = get_db().create_task(
                title=title,
                task_type=task_type,
                task_instruction=task_instruction,
                verification_instruction=verification_instruction,
                agent_id=agent_id,
                project_id=project_id,
                notes=notes,
                priority=priority,
                estimated_hours=estimated_hours,
                due_date=due_date_obj
            )
            
            result = {"success": True, "task_id": task_id}
        except ValueError as e:
            # Handle validation errors (e.g., invalid priority)
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", "validation_error")
            return {
                "success": False,
                "error": str(e)
            }
        add_span_attribute("mcp.task_id", task_id)
        
        # Create relationship if provided
        if parent_task_id and relationship_type:
            # Verify parent exists
            parent = get_db().get_task(parent_task_id)
            if not parent:
                add_span_attribute("mcp.success", False)
                add_span_attribute("mcp.error", "parent_not_found")
                return {
                    "success": False,
                    "error": f"Parent task {parent_task_id} not found. Please verify the parent_task_id is correct."
                }
            
            try:
                rel_id = get_db().create_relationship(
                    parent_task_id=parent_task_id,
                    child_task_id=task_id,
                    relationship_type=relationship_type,
                    agent_id=agent_id
                )
                result["relationship_id"] = rel_id
                add_span_attribute("mcp.relationship_id", rel_id)
            except ValueError as e:
                # Handle circular dependency and other validation errors
                add_span_attribute("mcp.success", False)
                add_span_attribute("mcp.error", "relationship_validation_error")
                return {
                    "success": False,
                    "error": str(e)
                }
        
        add_span_attribute("mcp.success", True)
        return result


def handle_unlock_task(task_id: int, agent_id: str) -> Dict[str, Any]:
    """
    Unlock (release) a reserved task.
    
    Args:
        task_id: Task ID to unlock
        agent_id: Agent ID unlocking the task
        
    Returns:
        Dictionary with unlock status
    """
    task = get_db().get_task(task_id)
    if not task:
        return {
            "success": False,
            "error": f"Task {task_id} not found. Please verify the task_id is correct."
        }
    
    # Check if task is actually locked by this agent
    if task.get("assigned_agent") != agent_id:
        current_agent = task.get("assigned_agent", "none")
        return {
            "success": False,
            "error": f"Task {task_id} is assigned to agent '{current_agent}', not '{agent_id}'. Only the assigned agent can unlock this task."
        }
    
    try:
        get_db().unlock_task(task_id, agent_id)
        return {"success": True, "task_id": task_id, "message": f"Task {task_id} unlocked successfully"}
    except ValueError as e:
        return {
            "success": False,
            "error": f"Cannot unlock task {task_id}: {str(e)}"
        }


def handle_verify_task(task_id: int, agent_id: str, notes: Optional[str] = None) -> Dict[str, Any]:
    """
    Verify a task's completion. Marks verification_status from 'unverified' to 'verified'.
    This is exposed as an MCP tool and can be called via MCP protocol.
    
    Args:
        task_id: Task ID to verify
        agent_id: Agent ID verifying the task
        notes: Optional notes about verification
        
    Returns:
        Dictionary with verification status
    """
    with trace_span(
        "mcp.verify_task",
        attributes={
            "mcp.task_id": task_id,
            "mcp.agent_id": agent_id,
        }
    ) as span:
        task = get_db().get_task(task_id)
        if not task:
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", "task_not_found")
            return {
                "success": False,
                "error": f"Task {task_id} not found. Please verify the task_id is correct."
            }
        
        # Check if task is already verified
        if task.get("verification_status") == "verified":
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", "already_verified")
            return {
                "success": False,
                "error": f"Task {task_id} is already verified. No action needed."
            }
        
        # Verify the task
        try:
            get_db().verify_task(task_id, agent_id, notes=notes)
            add_span_attribute("mcp.success", True)
            return {
                "success": True,
                "task_id": task_id,
                "message": f"Task {task_id} verified by agent {agent_id}"
            }
        except Exception as e:
            add_span_attribute("mcp.success", False)
            add_span_attribute("mcp.error", str(e))
            return {
                "success": False,
                "error": f"Failed to verify task {task_id}: {str(e)}"
            }


def handle_add_task_update(
    task_id: int,
    agent_id: str,
    content: str,
    update_type: Literal["progress", "note", "blocker", "question", "finding"],
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Add a task update (progress, note, blocker, question, finding).
    
    Args:
        task_id: Task ID
        agent_id: Agent ID making the update
        content: Update content
        update_type: Type of update (progress, note, blocker, question, finding)
        metadata: Optional metadata dictionary
        
    Returns:
        Dictionary with update ID and success status
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
            "error": "Update content cannot be empty"
        }
    
    try:
        update_id = get_db().add_task_update(
            task_id=task_id,
            agent_id=agent_id,
            content=content,
            update_type=update_type,
            metadata=metadata
        )
        return {
            "success": True,
            "update_id": update_id,
            "task_id": task_id,
            "message": f"Update added successfully to task {task_id}"
        }
    except ValueError as e:
        return {
            "success": False,
            "error": f"Cannot add update to task {task_id}: {str(e)}"
        }
    except Exception as e:
        # Catch database errors (IntegrityError, OperationalError, etc.) and return meaningful error
        import sqlite3
        error_type = type(e).__name__
        error_message = str(e)
        
        # Provide more specific error messages for common database errors
        if isinstance(e, sqlite3.IntegrityError):
            if "CHECK constraint" in error_message:
                return {
                    "success": False,
                    "error": f"Database constraint error when adding update to task {task_id}: {error_message}. This may indicate a schema mismatch - please check database migration status.",
                    "error_type": "database_constraint_error",
                    "error_details": error_message
                }
            else:
                return {
                    "success": False,
                    "error": f"Database integrity error when adding update to task {task_id}: {error_message}",
                    "error_type": "database_integrity_error",
                    "error_details": error_message
                }
        else:
            return {
                "success": False,
                "error": f"Failed to add update to task {task_id}: {error_type}: {error_message}",
                "error_type": error_type,
                "error_details": error_message
            }


def handle_get_task_context(task_id: int) -> Dict[str, Any]:
    """
    Get full context for a task including project, ancestry, and updates.
    
    Args:
        task_id: Task ID
        
    Returns:
        Dictionary with task, project, updates, ancestry, and recent changes
    """
    try:
        task = get_db().get_task(task_id)
        if not task:
            return {
                "success": False,
                "error": f"Task {task_id} not found. Please verify the task_id is correct."
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to retrieve task {task_id}: {str(e)}"
        }
    
    try:
        # Get project if task has one
        project = None
        if task.get("project_id"):
            try:
                project = get_db().get_project(task["project_id"])
            except Exception as e:
                # Log error but continue - project not critical for context
                # Project will remain None
                pass
        
        # Get task updates
        try:
            updates = get_db().get_task_updates(task_id, limit=100)
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to retrieve updates for task {task_id}: {str(e)}"
            }
        
        # Check for stale status - look for "finding" updates indicating task was abandoned/stale
        stale_info = None
        for update in updates:
            if update.get("change_type") == "finding":
                notes = update.get("notes", "")
                # Check if this is a stale/abandoned task finding
                if "stale" in notes.lower() or "abandoned" in notes.lower() or "unlocked due to timeout" in notes.lower():
                    stale_info = {
                        "is_stale": True,
                        "previous_agent": update.get("agent_id", "unknown"),
                        "unlocked_at": update.get("created_at"),
                        "stale_finding": notes,
                        "warning": "⚠️ WARNING: This task was previously abandoned/stale and may have partially completed work. You MUST verify all previous work before continuing."
                    }
                    break
        
        # Get ancestry (parent tasks via relationships)
        # Get all relationships where this task is involved
        try:
            relationships = get_db().get_related_tasks(task_id)
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to retrieve relationships for task {task_id}: {str(e)}"
            }
        
        ancestry = []
        for rel in relationships:
            # If this task is a child, then rel["parent_task_id"] is the parent
            if rel["child_task_id"] == task_id:
                try:
                    parent_task = get_db().get_task(rel["parent_task_id"])
                    if parent_task:
                        ancestry.append(dict(parent_task))
                except Exception:
                    # Skip invalid parent task references
                    pass
        
        # Get recent change history (excluding updates which are already included)
        try:
            change_history = get_db().get_change_history(task_id=task_id, limit=50)
        except Exception as e:
            # Change history is not critical, continue with empty list
            change_history = []
        
        # Filter out update types we already have
        recent_changes = [
            ch for ch in change_history 
            if ch["change_type"] not in ["progress", "note", "blocker", "question", "finding"]
        ]
        
        result = {
            "success": True,
            "task": add_computed_status_fields(dict(task)),
            "project": dict(project) if project else None,
            "updates": [dict(u) for u in updates],
            "ancestry": [add_computed_status_fields(dict(t)) for t in ancestry],
            "recent_changes": [dict(ch) for ch in recent_changes[:10]]  # Last 10 non-update changes
        }
        
        # Include stale info prominently at the top if present
        if stale_info:
            result["stale_info"] = stale_info
        
        return result
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get task context for task {task_id}: {str(e)}"
        }
