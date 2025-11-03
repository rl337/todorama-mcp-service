"""
Minimal MCP (Model Context Protocol) API for TODO service.

Provides 4-5 core functions for agent interaction:
1. list_available_tasks - Get tasks available for agent type
2. reserve_task - Lock and reserve a task for an agent
3. complete_task - Mark task as complete and optionally add followup
4. create_task - Create a new task (for breakdown agents)
5. get_agent_performance - Get agent statistics
"""
import os
from typing import Optional, List, Dict, Any, Literal
from fastapi import HTTPException

from database import TodoDatabase
from tracing import trace_span, add_span_attribute

# Database instance (set by set_db)
_db_instance: Optional[TodoDatabase] = None


def set_db(db: TodoDatabase):
    """Set the database instance for MCP API."""
    global _db_instance
    _db_instance = db


def get_db() -> TodoDatabase:
    """Get the database instance."""
    global _db_instance
    if _db_instance is None:
        # Fallback: create default instance
        db_path = os.getenv("TODO_DB_PATH", "/app/data/todos.db")
        _db_instance = TodoDatabase(db_path)
    return _db_instance


def _add_computed_status_fields(task_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add computed status fields to a task dictionary.
    
    Adds:
    - needs_verification: True if task is complete but unverified
    - effective_status: Display status (needs_verification or actual task_status)
    """
    task_dict = dict(task_dict)  # Make a copy
    if task_dict.get("task_status") == "complete" and task_dict.get("verification_status") == "unverified":
        task_dict["needs_verification"] = True
        task_dict["effective_status"] = "needs_verification"
    else:
        task_dict["needs_verification"] = False
        task_dict["effective_status"] = task_dict.get("task_status", "available")
    return task_dict


class MCPTodoAPI:
    """Minimal MCP API for TODO service."""
    
    @staticmethod
    def list_available_tasks(
        agent_type: Literal["breakdown", "implementation"],
        project_id: Optional[int] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        List available tasks for an agent type.
        
        Args:
            agent_type: 'breakdown' for abstract/epic tasks, 'implementation' for concrete tasks
            project_id: Optional project ID to filter tasks
            limit: Maximum number of tasks to return
            
        Returns:
            List of task dictionaries
        """
        with trace_span(
            "mcp.list_available_tasks",
            attributes={
                "mcp.agent_type": agent_type,
                "mcp.project_id": project_id,
                "mcp.limit": limit,
            }
        ):
            tasks = get_db().get_available_tasks_for_agent(agent_type, project_id=project_id, limit=limit)
            result = [_add_computed_status_fields(dict(task)) for task in tasks]
            add_span_attribute("mcp.tasks_count", len(result))
            return result
    
    @staticmethod
    def reserve_task(task_id: int, agent_id: str) -> Dict[str, Any]:
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
            task_dict = _add_computed_status_fields(dict(updated_task))
            result = {"success": True, "task": task_dict}
            if stale_warning:
                result["stale_warning"] = stale_warning
            add_span_attribute("mcp.success", True)
            return result
    
    @staticmethod
    def complete_task(
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
    
    @staticmethod
    def create_task(
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
    
    @staticmethod
    def get_agent_performance(
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
    
    @staticmethod
    def unlock_task(task_id: int, agent_id: str) -> Dict[str, Any]:
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
    
    @staticmethod
    def verify_task(task_id: int, agent_id: str, notes: Optional[str] = None) -> Dict[str, Any]:
        """
        Verify a task's completion. This is used internally and via REST API, but not exposed as an MCP tool.
        Agents should use complete_task() instead, which handles verification automatically.
        
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
    
    @staticmethod
    def query_tasks(
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
        return [_add_computed_status_fields(dict(task)) for task in tasks]
    
    @staticmethod
    def query_stale_tasks(hours: Optional[int] = None) -> Dict[str, Any]:
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
            "stale_tasks": [_add_computed_status_fields(dict(task)) for task in stale_tasks],
            "count": len(stale_tasks),
            "timeout_hours": timeout_hours
        }
    
    @staticmethod
    def add_task_update(
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
    
    @staticmethod
    def get_task_context(task_id: int) -> Dict[str, Any]:
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
                "task": _add_computed_status_fields(dict(task)),
                "project": dict(project) if project else None,
                "updates": [dict(u) for u in updates],
                "ancestry": [_add_computed_status_fields(dict(t)) for t in ancestry],
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
    
    @staticmethod
    def search_tasks(query: str, limit: int = 100) -> List[Dict[str, Any]]:
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
    
    @staticmethod
    def get_activity_feed(
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
    
    @staticmethod
    def get_tasks_approaching_deadline(
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
            "tasks": [_add_computed_status_fields(dict(task)) for task in tasks],
            "days_ahead": days_ahead
        }
    
    @staticmethod
    def create_tag(name: str) -> Dict[str, Any]:
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
    
    @staticmethod
    def list_tags() -> Dict[str, Any]:
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
    
    @staticmethod
    def assign_tag_to_task(task_id: int, tag_id: int) -> Dict[str, Any]:
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
    
    @staticmethod
    def remove_tag_from_task(task_id: int, tag_id: int) -> Dict[str, Any]:
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
    
    @staticmethod
    def get_task_tags(task_id: int) -> Dict[str, Any]:
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
    
    @staticmethod
    def create_template(
        name: str,
        task_type: Literal["concrete", "abstract", "epic"],
        task_instruction: str,
        verification_instruction: str,
        description: Optional[str] = None,
        priority: Optional[Literal["low", "medium", "high", "critical"]] = None,
        estimated_hours: Optional[float] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a task template.
        
        Args:
            name: Template name (must be unique)
            task_type: Task type (concrete, abstract, epic)
            task_instruction: What to do
            verification_instruction: How to verify completion
            description: Optional template description
            priority: Optional priority (low, medium, high, critical). Defaults to medium.
            estimated_hours: Optional estimated hours for the task
            notes: Optional notes
            
        Returns:
            Dictionary with template ID and success status
        """
        if not name or not name.strip():
            return {
                "success": False,
                "error": "Template name cannot be empty"
            }
        
        try:
            template_id = get_db().create_template(
                name=name.strip(),
                description=description,
                task_type=task_type,
                task_instruction=task_instruction,
                verification_instruction=verification_instruction,
                priority=priority,
                estimated_hours=estimated_hours,
                notes=notes
            )
            template = get_db().get_template(template_id)
            return {
                "success": True,
                "template_id": template_id,
                "template": dict(template) if template else None
            }
        except ValueError as e:
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create template: {str(e)}"
            }
    
    @staticmethod
    def list_templates(task_type: Optional[Literal["concrete", "abstract", "epic"]] = None) -> Dict[str, Any]:
        """
        List all templates, optionally filtered by task type.
        
        Args:
            task_type: Optional filter by task type
            
        Returns:
            Dictionary with list of template dictionaries
        """
        templates = get_db().list_templates(task_type=task_type)
        return {
            "success": True,
            "templates": [dict(template) for template in templates]
        }
    
    @staticmethod
    def get_template(template_id: int) -> Dict[str, Any]:
        """
        Get a template by ID.
        
        Args:
            template_id: Template ID
            
        Returns:
            Dictionary with template data and success status
        """
        template = get_db().get_template(template_id)
        if not template:
            return {
                "success": False,
                "error": f"Template {template_id} not found. Please verify the template_id is correct."
            }
        
        return {
            "success": True,
            "template": dict(template)
        }
    
    @staticmethod
    def create_task_from_template(
        template_id: int,
        agent_id: str,
        title: Optional[str] = None,
        project_id: Optional[int] = None,
        notes: Optional[str] = None,
        priority: Optional[Literal["low", "medium", "high", "critical"]] = None,
        estimated_hours: Optional[float] = None,
        due_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a task from a template with pre-filled instructions.
        
        Args:
            template_id: Template ID to use
            agent_id: Agent ID creating the task
            title: Optional task title (defaults to template name)
            project_id: Optional project ID
            notes: Optional notes (combined with template notes)
            priority: Optional priority override
            estimated_hours: Optional estimated hours override
            due_date: Optional due date (ISO format timestamp)
            
        Returns:
            Dictionary with task ID and success status
        """
        # Parse due_date if provided
        due_date_obj = None
        if due_date:
            from datetime import datetime
            try:
                due_date_obj = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
            except ValueError:
                due_date_obj = datetime.fromisoformat(due_date)
        
        try:
            task_id = get_db().create_task_from_template(
                template_id=template_id,
                agent_id=agent_id,
                title=title,
                project_id=project_id,
                notes=notes,
                priority=priority,
                estimated_hours=estimated_hours,
                due_date=due_date_obj if due_date else None
            )
            return {
                "success": True,
                "task_id": task_id
            }
        except ValueError as e:
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create task from template: {str(e)}"
            }
    
    @staticmethod
    def create_comment(
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
    
    @staticmethod
    def get_task_comments(
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
    
    @staticmethod
    def get_comment_thread(
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
    
    @staticmethod
    def update_comment(
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
    
    @staticmethod
    def delete_comment(
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

    @staticmethod
    def create_recurring_task(
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
        from datetime import datetime
        
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
    
    @staticmethod
    def list_recurring_tasks(
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
    
    @staticmethod
    def get_recurring_task(recurring_id: int) -> Dict[str, Any]:
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
    
    @staticmethod
    def get_task_statistics(
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
            
        ERROR HANDLING:
        - No errors typically returned - function always returns success with statistics (zeros if no tasks match filters)
        - Parameter validation errors (invalid date format, invalid task_type enum) are handled by framework validation before function is called
        - Database errors are rare; if connection issues occur, retry with exponential backoff
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
    
    @staticmethod
    def get_recent_completions(
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
            
        ERROR HANDLING:
        - No errors typically returned - function always returns success with tasks list (empty if none found)
        - Parameter validation errors (invalid limit, negative hours) are handled by framework validation before function is called
        - Database errors are rare; if connection issues occur, retry with exponential backoff
        """
        completions = get_db().get_recent_completions(
            limit=limit,
            project_id=project_id,
            hours=hours
        )
        return {
            "success": True,
            "tasks": [_add_computed_status_fields(dict(task)) for task in completions],
            "count": len(completions)
        }
    
    @staticmethod
    def get_task_summary(
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
            
        ERROR HANDLING:
        - No errors typically returned - function always returns success with tasks list (empty if none match filters)
        - Parameter validation errors (invalid enum values, invalid limit) are handled by framework validation before function is called
        - Database errors are rare; if connection issues occur, retry with exponential backoff
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
    
    @staticmethod
    def bulk_unlock_tasks(
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
            
        ERROR HANDLING:
        - Returns {"success": True, "failed_count": N, "failed_task_ids": [...]} if some tasks fail to unlock
        - Each failed task includes error message (e.g., "Task not found", "Task not in_progress")
        - Parameter validation errors (empty agent_id) are handled by framework validation before function is called
        - Database transaction errors will rollback all unlocks; check "failed_task_ids" for details
        """
        result = get_db().bulk_unlock_tasks(task_ids=task_ids, agent_id=agent_id)
        return result
    
    @staticmethod
    def update_recurring_task(
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
        from datetime import datetime
        
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
    
    @staticmethod
    def deactivate_recurring_task(recurring_id: int) -> Dict[str, Any]:
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
    
    @staticmethod
    def get_task_versions(task_id: int) -> Dict[str, Any]:
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
    
    @staticmethod
    def get_task_version(task_id: int, version_number: int) -> Dict[str, Any]:
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
    
    @staticmethod
    def get_latest_task_version(task_id: int) -> Dict[str, Any]:
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
    
    @staticmethod
    def diff_task_versions(
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
    
    @staticmethod
    def create_recurring_instance(recurring_id: int) -> Dict[str, Any]:
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
    
    @staticmethod
    def link_github_issue(task_id: int, github_url: str) -> Dict[str, Any]:
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
    
    @staticmethod
    def link_github_pr(task_id: int, github_url: str) -> Dict[str, Any]:
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
    
    @staticmethod
    def get_github_links(task_id: int) -> Dict[str, Any]:
        """
        Get GitHub issue and PR links for a task.
        
        Args:
            task_id: Task ID
            
        Returns:
            Dictionary with GitHub links
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
        except ValueError as e:
            return {
                "success": False,
                "error": str(e)
            }


# MCP function definitions (for documentation/registration)
MCP_FUNCTIONS = [
    {
        "name": "list_available_tasks",
        "description": "List available tasks for your agent type. Use this to find tasks you can work on. 'breakdown' agents see abstract/epic tasks that need to be broken down. 'implementation' agents see concrete tasks ready for implementation. Returns a list of task dictionaries with all task details. Always call this before reserving a task to see what's available. Example: Use agent_type='implementation' with project_id=1 to get concrete implementation tasks for project 1.\n\nERROR HANDLING:\n- No errors typically returned - function returns empty list [] if no tasks match criteria.\n- Parameter validation errors (invalid agent_type, invalid project_id, limit out of range) will be handled by the framework before function is called.\n- Database errors are rare but would appear as exceptions; retry with exponential backoff if database connection issues occur.",
        "parameters": {
            "agent_type": {
                "type": "string",
                "enum": ["breakdown", "implementation"],
                "description": "Your agent type determines which tasks you can see. 'breakdown': for agents that break down abstract/epic tasks into smaller subtasks. 'implementation': for agents that implement concrete tasks.",
                "enumDescriptions": {
                    "breakdown": "Breakdown agents work on abstract or epic tasks, decomposing them into smaller, concrete tasks",
                    "implementation": "Implementation agents work on concrete tasks that are ready for direct implementation"
                },
                "example": "implementation"
            },
            "project_id": {
                "type": "integer",
                "optional": True,
                "description": "Filter tasks by project ID. Must be a positive integer if provided. Omit to see tasks from all projects.",
                "minimum": 1,
                "example": 1
            },
            "limit": {
                "type": "integer",
                "default": 10,
                "description": "Maximum number of tasks to return. Must be between 1 and 1000 (default: 10). Use smaller values for faster responses.",
                "minimum": 1,
                "maximum": 1000,
                "example": 10
            }
        }
    },
    {
        "name": "reserve_task",
        "description": "CRITICAL: Reserve (lock) a task before working on it. This prevents other agents from working on the same task simultaneously. Returns full task context including project, ancestry, and updates. If the task was previously abandoned (stale), includes a stale_warning with details. Always call reserve_task before starting work. MANDATORY: You must either complete_task() or unlock_task() when done - never leave a task reserved. Returns: Dictionary with success status, task data, and optional stale_warning.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct, use list_available_tasks() or query_tasks() to get valid task IDs.\n- Returns {\"success\": False, \"error\": \"Task X cannot be locked. Current status: Y, assigned to: Z...\"} if task is not available (already locked, completed, or in wrong status). Only tasks with status 'available' can be reserved. Wait for task to become available or find another task.\n- If stale_warning is present in response, the task was previously abandoned - you MUST verify all previous work before continuing.\n- Retry not recommended for these errors - they indicate permanent state issues that require different action.",
        "parameters": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to reserve. Must be a positive integer. Get task IDs from list_available_tasks() or query_tasks(). Only tasks with status 'available' can be reserved.",
                "minimum": 1,
                "example": 123
            },
            "agent_id": {
                "type": "string",
                "description": "Your unique agent identifier. Used to track who reserved the task. Must be a non-empty string (typically 1-100 characters). This must match the agent_id used in complete_task() or unlock_task().",
                "minLength": 1,
                "maxLength": 100,
                "example": "cursor-agent"
            }
        }
    },
    {
        "name": "complete_task",
        "description": "CRITICAL: Mark a task as complete when finished. This is MANDATORY - you must call this or unlock_task() when done working. Optionally create a followup task that will be automatically linked. Use notes to document completion details. Returns: Dictionary with success status and optional followup_task_id if a followup was created. Example: After finishing implementation, call with notes='Implemented feature X with tests passing'.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Task X is currently assigned to agent 'Y'...\"} if task is assigned to a different agent. Only the agent that reserved the task can complete it. Ensure you're using the same agent_id that reserved the task.\n- If followup task creation fails (validation errors on followup fields), the main task is still completed but followup_task_id is not returned. Check followup parameter validation if followup creation needed.\n- Database errors during completion are rare; if they occur, verify task status separately to confirm completion state.",
        "parameters": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to complete. Must be a positive integer and the task must be reserved by you (assigned to your agent_id).",
                "minimum": 1,
                "example": 123
            },
            "agent_id": {
                "type": "string",
                "description": "Your agent identifier. Must match the agent_id that reserved this task. Used to verify you have permission to complete it.",
                "minLength": 1,
                "maxLength": 100,
                "example": "cursor-agent"
            },
            "notes": {
                "type": "string",
                "optional": True,
                "description": "Completion notes describing what was accomplished, any issues encountered, or important details. Helpful for future reference and verification.",
                "example": "Implemented feature X with all tests passing. Added comprehensive error handling and documentation."
            },
            "actual_hours": {
                "type": "number",
                "optional": True,
                "description": "Actual hours spent on the task. Used for tracking time estimation accuracy. Must be a positive number if provided.",
                "minimum": 0.1,
                "example": 3.5
            },
            "followup_title": {
                "type": "string",
                "optional": True,
                "description": "Title for a followup task to create automatically after completion. Required if creating a followup. Must be 3-100 characters.",
                "minLength": 3,
                "maxLength": 100,
                "example": "Add feature X documentation"
            },
            "followup_task_type": {
                "type": "string",
                "optional": True,
                "enum": ["concrete", "abstract", "epic"],
                "description": "Type for the followup task. Required if creating a followup. Must be provided along with followup_instruction and followup_verification.",
                "enumDescriptions": {
                    "concrete": "Implementable followup task ready for direct implementation",
                    "abstract": "Followup task that needs to be broken down further",
                    "epic": "Large followup feature or initiative"
                },
                "example": "concrete"
            },
            "followup_instruction": {
                "type": "string",
                "optional": True,
                "description": "Instructions for the followup task. Required if creating a followup. Must be at least 10 characters. Must be provided along with followup_task_type and followup_verification.",
                "minLength": 10,
                "example": "Create comprehensive documentation for feature X including API docs, usage examples, and integration guide."
            },
            "followup_verification": {
                "type": "string",
                "optional": True,
                "description": "Verification instructions for the followup task. Required if creating a followup. Must be at least 10 characters. Must be provided along with followup_task_type and followup_instruction.",
                "minLength": 10,
                "example": "Verify documentation is complete, accurate, and includes all required sections. Test examples work correctly."
            }
        }
    },
    {
        "name": "create_task",
        "description": "Create a new task. Use this when breaking down abstract tasks (breakdown agents) or creating related tasks. Optionally link to a parent task using relationship_type to establish task relationships. task_type: 'concrete'=implementable, 'abstract'=needs breakdown, 'epic'=large feature. relationship_type options: 'subtask'=part of parent, 'blocking'=this blocks parent, 'blocked_by'=parent blocks this, 'related'=loosely related. Returns: Dictionary with success status, task_id, and optional relationship_id if linked to parent.\n\nERROR HANDLING:\n- Parameter validation errors (empty title, invalid task_type, insufficient instruction length) are handled by framework validation before function is called. Ensure all required fields meet minimum length requirements.\n- Returns {\"success\": False, \"error\": \"Parent task X not found...\"} if parent_task_id is provided but doesn't exist. Verify parent_task_id is correct or omit if task has no parent.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if relationship creation fails (e.g., circular dependency detected, invalid relationship). Fix relationship configuration and retry without the problematic relationship.\n- Task is still created even if relationship fails - check response for task_id vs relationship_id success status separately.",
        "parameters": {
            "title": {
                "type": "string",
                "description": "Brief, descriptive title for the task. Should be concise (3-100 characters) and clearly describe what needs to be done. Use title case.",
                "minLength": 3,
                "maxLength": 100,
                "example": "Add user authentication"
            },
            "task_type": {
                "type": "string",
                "enum": ["concrete", "abstract", "epic"],
                "description": "Type of task being created. Determines which agent types can work on it and its lifecycle.",
                "enumDescriptions": {
                    "concrete": "Implementable task ready for direct implementation by implementation agents. Has clear, actionable instructions.",
                    "abstract": "High-level task that needs to be broken down into smaller concrete tasks by breakdown agents before implementation.",
                    "epic": "Large feature or initiative that spans multiple tasks. Typically broken down into abstract or concrete subtasks."
                },
                "example": "concrete"
            },
            "task_instruction": {
                "type": "string",
                "description": "Detailed instructions explaining what to do, how to do it, and why. Should be comprehensive enough for an agent to understand and execute. Minimum 10 characters.",
                "minLength": 10,
                "example": "Implement user authentication using JWT tokens. Create login endpoint, validate credentials, generate tokens, and return user session."
            },
            "verification_instruction": {
                "type": "string",
                "description": "How to verify the task is complete. Include specific tests, checks, validation steps, or acceptance criteria. Minimum 10 characters.",
                "minLength": 10,
                "example": "Verify login endpoint accepts credentials, validates against database, returns JWT token. Test with valid and invalid credentials."
            },
            "agent_id": {
                "type": "string",
                "description": "Your agent identifier (who created this task). Used for tracking and attribution. Must be a non-empty string (1-100 characters).",
                "minLength": 1,
                "maxLength": 100,
                "example": "cursor-agent"
            },
            "project_id": {
                "type": "integer",
                "optional": True,
                "description": "Associate task with a specific project. Must be a positive integer if provided. Omit if task is not project-specific.",
                "minimum": 1,
                "example": 1
            },
            "parent_task_id": {
                "type": "integer",
                "optional": True,
                "description": "Link this task to a parent task to establish hierarchy. Must be a positive integer if provided. Requires relationship_type to be set.",
                "minimum": 1,
                "example": 50
            },
            "relationship_type": {
                "type": "string",
                "optional": True,
                "enum": ["subtask", "blocking", "blocked_by", "related"],
                "description": "How this task relates to the parent task (if parent_task_id is provided). Required if parent_task_id is set.",
                "enumDescriptions": {
                    "subtask": "This task is a component/part of the parent task. Completing this contributes to parent completion.",
                    "blocking": "This task blocks the parent task from completion. Parent cannot be completed until this is done.",
                    "blocked_by": "This task is blocked by the parent task. This task cannot proceed until parent is complete.",
                    "related": "Tasks are related but not directly dependent. Used for loose associations or cross-references."
                },
                "example": "subtask"
            },
            "notes": {
                "type": "string",
                "optional": True,
                "description": "Additional context, background information, or notes about the task. Optional but helpful for providing context.",
                "example": "This builds on previous authentication work. See related tasks for reference."
            },
            "priority": {
                "type": "string",
                "optional": True,
                "enum": ["low", "medium", "high", "critical"],
                "description": "Task priority level. Defaults to 'medium' if not specified. Higher priority tasks should be handled first.",
                "enumDescriptions": {
                    "low": "Low priority - can be deferred without significant impact",
                    "medium": "Medium priority - normal priority (default if not specified)",
                    "high": "High priority - should be addressed soon",
                    "critical": "Critical priority - urgent, blocking other work or production issues"
                },
                "default": "medium",
                "example": "high"
            },
            "estimated_hours": {
                "type": "number",
                "optional": True,
                "description": "Estimated time to complete the task in hours. Used for planning and scheduling. Must be a positive number if provided.",
                "minimum": 0.1,
                "example": 4.5
            },
            "due_date": {
                "type": "string",
                "optional": True,
                "description": "Due date for task completion in ISO 8601 format. Must include timezone (use 'Z' for UTC or offset like '+00:00'). Example: '2025-12-31T23:59:59Z'",
                "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(Z|[+-]\\d{2}:\\d{2})$",
                "example": "2025-12-31T23:59:59Z"
            }
        }
    },
    {
        "name": "get_agent_performance",
        "description": "Get your performance statistics including tasks completed, average completion time, success rate. Use this to track your productivity and identify areas for improvement. Optionally filter by task_type to see stats for specific task types. Returns: Dictionary with completion counts, average hours, success rate, and other metrics.\n\nERROR HANDLING:\n- No errors typically returned - function returns statistics dictionary even if agent_id has no history (returns zeros/defaults).\n- Parameter validation errors (invalid task_type enum) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "agent_id": {"type": "string", "description": "Your agent identifier"},
            "task_type": {"type": "string", "optional": True, "enum": ["concrete", "abstract", "epic"], "description": "Optional: Filter statistics by task type (omit to see all types)"}
        }
    },
    {
        "name": "unlock_task",
        "description": "CRITICAL: Release a reserved task if you cannot complete it. This is MANDATORY if you cannot finish a task - never leave tasks locked. Use this when encountering blockers you cannot resolve, errors you cannot fix, or when the task requirements are unclear. Returns: Dictionary with success status. Important: Always unlock tasks you cannot complete so other agents can pick them up.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Task X is assigned to agent 'Y', not 'Z'...\"} if task is assigned to a different agent. Only the agent that reserved the task can unlock it. Ensure you're using the same agent_id that reserved the task.\n- Returns {\"success\": False, \"error\": \"Cannot unlock task X: ...\"} with ValueError message if unlock operation fails (e.g., task already unlocked, invalid state). Check task status to confirm current state.\n- Always ensure unlock_task() is called in error handling paths (try/except/finally blocks) to prevent tasks from remaining locked.",
        "parameters": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to unlock. Must be a positive integer and the task must be reserved by you (assigned to your agent_id).",
                "minimum": 1,
                "example": 123
            },
            "agent_id": {
                "type": "string",
                "description": "Your agent identifier. Must match the agent_id that reserved this task. Used to verify you have permission to unlock it.",
                "minLength": 1,
                "maxLength": 100,
                "example": "cursor-agent"
            }
        }
    },
    {
        "name": "query_tasks",
        "description": "Query tasks using flexible filtering criteria. Use this to find specific tasks by status, type, agent, priority, tags, or project. More powerful than list_available_tasks - can query any tasks, not just available ones. Returns: List of task dictionaries matching criteria. Example: query_tasks(task_status='in_progress', task_type='concrete') finds all in-progress concrete tasks.\n\nERROR HANDLING:\n- No errors typically returned - function returns empty list [] if no tasks match criteria.\n- Parameter validation errors (invalid enum values, invalid IDs, limit out of range) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "project_id": {
                "type": "integer",
                "optional": True,
                "description": "Filter tasks by project ID. Must be a positive integer if provided.",
                "minimum": 1,
                "example": 1
            },
            "task_type": {
                "type": "string",
                "optional": True,
                "enum": ["concrete", "abstract", "epic"],
                "description": "Filter by task type. Returns only tasks matching the specified type.",
                "enumDescriptions": {
                    "concrete": "Implementable tasks ready for direct implementation",
                    "abstract": "High-level tasks that need breakdown",
                    "epic": "Large features or initiatives spanning multiple tasks"
                },
                "example": "concrete"
            },
            "task_status": {
                "type": "string",
                "optional": True,
                "enum": ["available", "in_progress", "complete", "blocked", "cancelled"],
                "description": "Filter by task status. Returns only tasks in the specified status.",
                "enumDescriptions": {
                    "available": "Task is available and ready to be worked on by any agent",
                    "in_progress": "Task is currently being worked on by an assigned agent",
                    "complete": "Task has been completed successfully",
                    "blocked": "Task cannot proceed due to dependencies or external blockers",
                    "cancelled": "Task was cancelled and will not be completed"
                },
                "example": "in_progress"
            },
            "agent_id": {
                "type": "string",
                "optional": True,
                "description": "Filter by assigned agent ID. Returns only tasks assigned to this agent. Must be a non-empty string if provided.",
                "minLength": 1,
                "maxLength": 100,
                "example": "cursor-agent"
            },
            "priority": {
                "type": "string",
                "optional": True,
                "enum": ["low", "medium", "high", "critical"],
                "description": "Filter by priority level. Returns only tasks with the specified priority.",
                "enumDescriptions": {
                    "low": "Low priority tasks",
                    "medium": "Medium priority tasks (default)",
                    "high": "High priority tasks",
                    "critical": "Critical priority tasks"
                },
                "example": "high"
            },
            "tag_id": {
                "type": "integer",
                "optional": True,
                "description": "Filter tasks that have this tag. Returns tasks with the specified tag ID. Must be a positive integer if provided.",
                "minimum": 1,
                "example": 5
            },
            "tag_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "optional": True,
                "description": "Filter tasks that have ALL of these tags. Returns only tasks that have every tag in the array. All tag IDs must be positive integers.",
                "example": [1, 2, 3]
            },
            "order_by": {
                "type": "string",
                "optional": True,
                "description": "Sort order for results. Use 'priority' for high-to-low priority, 'priority_asc' for low-to-high priority. Default is no specific ordering.",
                "example": "priority"
            },
            "limit": {
                "type": "integer",
                "default": 100,
                "description": "Maximum number of results to return. Must be between 1 and 1000 (default: 100).",
                "minimum": 1,
                "maximum": 1000,
                "example": 100
            }
        }
    },
    {
        "name": "query_stale_tasks",
        "description": "Query tasks that have been in_progress longer than the timeout period (default 24 hours). Use this for monitoring system health and identifying tasks that may have been abandoned. Stale tasks are automatically unlocked after timeout, but monitoring helps identify systemic issues. Returns: Dictionary with stale_tasks list, count, and timeout_hours used.\n\nERROR HANDLING:\n- No errors typically returned - function always returns success with stale_tasks list (empty if none found).\n- Parameter validation errors (invalid hours value) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "hours": {
                "type": "integer",
                "optional": True,
                "description": "Hours threshold for stale tasks. Tasks in_progress longer than this are considered stale. Defaults to TASK_TIMEOUT_HOURS environment variable or 24 if not set. Must be a positive integer if provided.",
                "minimum": 1,
                "example": 24
            }
        }
    },
    {
        "name": "get_task_statistics",
        "description": "Get aggregated statistics about tasks without requiring Python post-processing. Returns total count, counts by status (available/in_progress/complete/blocked/cancelled), counts by task_type (concrete/abstract/epic), counts by project_id, and completion rate percentage. Use this instead of querying all tasks and counting in Python. Supports optional filters: project_id, task_type, date_range. Returns: Dictionary with total, by_status, by_type, by_project, and completion_rate.\n\nERROR HANDLING:\n- No errors typically returned - function always returns success with statistics (zeros if no tasks match filters).\n- Parameter validation errors (invalid date format, invalid task_type enum) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "project_id": {
                "type": "integer",
                "optional": True,
                "description": "Filter statistics by project ID. If provided, statistics are scoped to this project only. Must be a positive integer if provided.",
                "minimum": 1,
                "example": 1
            },
            "task_type": {
                "type": "string",
                "optional": True,
                "enum": ["concrete", "abstract", "epic"],
                "description": "Filter statistics by task type. If provided, statistics are scoped to this task type only.",
                "example": "concrete"
            },
            "start_date": {
                "type": "string",
                "optional": True,
                "description": "Filter statistics for tasks created on or after this date. ISO 8601 format timestamp (e.g., '2025-01-01T00:00:00Z').",
                "example": "2025-01-01T00:00:00Z"
            },
            "end_date": {
                "type": "string",
                "optional": True,
                "description": "Filter statistics for tasks created on or before this date. ISO 8601 format timestamp (e.g., '2025-12-31T23:59:59Z').",
                "example": "2025-12-31T23:59:59Z"
            }
        }
    },
    {
        "name": "get_recent_completions",
        "description": "Get recently completed tasks sorted by completion time (most recent first). Returns lightweight summaries with task_id, title, completed_at, agent_id, project_id. Use this to see what was recently finished without fetching full task objects. Supports optional filters: project_id, hours (completions within last N hours). Returns: Dictionary with success status, tasks list, and count.\n\nERROR HANDLING:\n- No errors typically returned - function always returns success with tasks list (empty if none found).\n- Parameter validation errors (invalid limit, negative hours) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "limit": {
                "type": "integer",
                "optional": True,
                "default": 10,
                "description": "Maximum number of completed tasks to return. Must be between 1 and 1000 (default: 10).",
                "minimum": 1,
                "maximum": 1000,
                "example": 10
            },
            "project_id": {
                "type": "integer",
                "optional": True,
                "description": "Filter completions by project ID. Returns only completed tasks for this project. Must be a positive integer if provided.",
                "minimum": 1,
                "example": 1
            },
            "hours": {
                "type": "integer",
                "optional": True,
                "description": "Filter for completions within the last N hours. Returns only tasks completed within this time window. Must be a positive integer if provided.",
                "minimum": 1,
                "example": 24
            }
        }
    },
    {
        "name": "get_task_summary",
        "description": "Get lightweight task summaries (essential fields only) instead of full task objects. Returns only: id, title, task_type, task_status, assigned_agent, project_id, priority, created_at, updated_at, completed_at. Faster than get_task_context() for bulk queries. Supports same filters as query_tasks(). Use this when you need basic info about many tasks without full task details. Returns: Dictionary with success status, tasks list (summaries), and count.\n\nERROR HANDLING:\n- No errors typically returned - function always returns success with tasks list (empty if none match filters).\n- Parameter validation errors (invalid enum values, invalid limit) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "project_id": {
                "type": "integer",
                "optional": True,
                "description": "Filter tasks by project ID. Must be a positive integer if provided.",
                "minimum": 1,
                "example": 1
            },
            "task_type": {
                "type": "string",
                "optional": True,
                "enum": ["concrete", "abstract", "epic"],
                "description": "Filter by task type.",
                "example": "concrete"
            },
            "task_status": {
                "type": "string",
                "optional": True,
                "enum": ["available", "in_progress", "complete", "blocked", "cancelled"],
                "description": "Filter by task status.",
                "example": "in_progress"
            },
            "assigned_agent": {
                "type": "string",
                "optional": True,
                "description": "Filter by assigned agent ID. Returns only tasks assigned to this agent. Must be a non-empty string if provided.",
                "minLength": 1,
                "maxLength": 100,
                "example": "cursor-agent"
            },
            "priority": {
                "type": "string",
                "optional": True,
                "enum": ["low", "medium", "high", "critical"],
                "description": "Filter by priority level.",
                "example": "high"
            },
            "limit": {
                "type": "integer",
                "optional": True,
                "default": 100,
                "description": "Maximum number of results to return. Must be between 1 and 1000 (default: 100).",
                "minimum": 1,
                "maximum": 1000,
                "example": 100
            }
        }
    },
    {
        "name": "bulk_unlock_tasks",
        "description": "Unlock multiple tasks atomically in a single operation. Use this instead of calling unlock_task() multiple times. Benefits: Single operation instead of multiple API calls, atomic transaction (all succeed or all fail), better for system maintenance. Use case: 'Unlock all stale tasks' or 'Unlock all tasks assigned to agent X'. Returns: Dictionary with success status, unlocked_count, unlocked_task_ids, failed_count, and failed_task_ids (with error messages for each failed task).\n\nERROR HANDLING:\n- Returns {\"success\": True, \"failed_count\": N, \"failed_task_ids\": [...]} if some tasks fail to unlock. Each failed task includes error message (e.g., 'Task not found', 'Task not in_progress'). Check failed_task_ids for details.\n- Parameter validation errors (empty agent_id) are handled by framework validation before function is called.\n- Database transaction errors will rollback all unlocks; check 'failed_task_ids' for details.",
        "parameters": {
            "task_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of task IDs to unlock. All IDs must be positive integers. Tasks must be in_progress to be unlocked.",
                "minItems": 1,
                "example": [94, 86, 83, 19, 8]
            },
            "agent_id": {
                "type": "string",
                "description": "Agent ID performing the unlock (for logging). Must be a non-empty string (1-100 characters).",
                "minLength": 1,
                "maxLength": 100,
                "example": "cursor-agent"
            }
        }
    },
    {
        "name": "add_task_update",
        "description": "Add progress updates, findings, blockers, questions, or notes while working on a task. Use this throughout your work to document progress and communicate status. update_type: 'progress'=work updates, 'note'=general notes, 'blocker'=blocking issues, 'question'=questions needing answers, 'finding'=important discoveries. Returns: Dictionary with success status and update_id. Example: Use 'blocker' when you hit an issue that prevents progress.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Update content cannot be empty\"} if content is empty or whitespace-only. Ensure content has meaningful text (minimum 1 character).\n- Returns {\"success\": False, \"error\": \"Cannot add update to task X: ...\"} with ValueError message if update creation fails (e.g., invalid update_type, database constraint violation). Fix parameters and retry.",
        "parameters": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to update. Must be a positive integer. The task does not need to be reserved by you to add updates.",
                "minimum": 1,
                "example": 123
            },
            "agent_id": {
                "type": "string",
                "description": "Your agent identifier. Used to track who made the update. Must be a non-empty string (1-100 characters).",
                "minLength": 1,
                "maxLength": 100,
                "example": "cursor-agent"
            },
            "content": {
                "type": "string",
                "description": "Update content describing the progress, blocker, question, or finding. Must be non-empty (minimum 1 character). Be clear and descriptive.",
                "minLength": 1,
                "example": "Implemented authentication endpoint. Currently testing edge cases."
            },
            "update_type": {
                "type": "string",
                "enum": ["progress", "note", "blocker", "question", "finding"],
                "description": "Type of update. Determines how the update is categorized and displayed.",
                "enumDescriptions": {
                    "progress": "Work progress updates - what has been accomplished, current status, next steps",
                    "note": "General notes, observations, or contextual information",
                    "blocker": "Blocking issues preventing progress - needs attention or resolution",
                    "question": "Questions needing answers or clarification",
                    "finding": "Important discoveries, insights, or unexpected behaviors that should be documented"
                },
                "example": "progress"
            },
            "metadata": {
                "type": "object",
                "optional": True,
                "description": "Additional structured data to include with the update. Can contain error details, links, related IDs, or other metadata. Useful for programmatic processing.",
                "example": {"error_code": "AUTH_001", "related_task_id": 456, "link": "https://example.com/doc"}
            }
        }
    },
    {
        "name": "get_task_context",
        "description": "Get comprehensive context for a task including the task itself, project information, parent tasks (ancestry), all updates, and recent changes. Use this when you need full context before working on a task or when picking up a stale/abandoned task. Returns: Dictionary with task, project, updates list, ancestry list (parent tasks), recent_changes, and optional stale_info warning if the task was previously abandoned.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Failed to retrieve task X: ...\"} if database error occurs during task retrieval. Retry with exponential backoff if temporary database issue.\n- Returns {\"success\": False, \"error\": \"Failed to retrieve updates for task X: ...\"} if updates cannot be retrieved (task exists but updates query fails). Context may be partial - task and project info may still be available.\n- If stale_info is present in response, the task was previously abandoned - you MUST verify all previous work before continuing.",
        "parameters": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to get context for. Must be a positive integer. Returns comprehensive context including project, updates, ancestry, and recent changes.",
                "minimum": 1,
                "example": 123
            }
        }
    },
    {
        "name": "search_tasks",
        "description": "Full-text search across task titles, instructions, and notes. Use this to find tasks by keywords when you know what you're looking for but not the exact task ID. More flexible than query_tasks for keyword-based discovery. Returns: List of task dictionaries ranked by relevance. Example: search_tasks('authentication') finds all tasks mentioning authentication.\n\nERROR HANDLING:\n- No errors typically returned - function returns empty list [] if no tasks match search query.\n- Parameter validation errors (empty query string, invalid limit) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "query": {
                "type": "string",
                "description": "Search query string to search for in task titles, instructions, and notes. Must be non-empty (minimum 1 character). Searches are case-insensitive and support partial matches.",
                "minLength": 1,
                "example": "authentication"
            },
            "limit": {
                "type": "integer",
                "optional": True,
                "default": 100,
                "description": "Maximum number of results to return. Must be between 1 and 1000 (default: 100). Results are ranked by relevance.",
                "minimum": 1,
                "maximum": 1000,
                "example": 100
            }
        }
    },
    {
        "name": "get_tasks_approaching_deadline",
        "description": "Get tasks with due dates approaching within the specified number of days. Use this for deadline monitoring and prioritization. Returns: Dictionary with success status, tasks list, and days_ahead value used. Useful for scheduling and deadline management.\n\nERROR HANDLING:\n- No errors typically returned - function returns success with tasks list (empty if none approaching deadline).\n- Parameter validation errors (invalid days_ahead, invalid limit) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "days_ahead": {"type": "integer", "optional": True, "default": 3, "description": "Number of days ahead to look for approaching deadlines (default: 3 days)"},
            "limit": {"type": "integer", "optional": True, "default": 100, "description": "Maximum number of results (default: 100)"}
        }
    },
    {
        "name": "create_tag",
        "description": "Create a new tag for categorizing tasks. If a tag with the same name already exists, returns the existing tag ID (no duplicate tags). Use tags to organize and filter tasks by categories, features, or attributes. Returns: Dictionary with success status, tag_id, and tag data.\n\nERROR HANDLING:\n- Parameter validation errors (empty tag name) are handled by framework validation before function is called.\n- Database errors (unique constraint violations handled internally - returns existing tag) are rare. If connection issues occur, retry with exponential backoff.\n- If tag with same name exists, function returns existing tag_id (no error) - this is expected behavior, not an error.",
        "parameters": {
            "name": {"type": "string", "description": "Tag name (e.g., 'backend', 'frontend', 'bug', 'feature'). Must be unique."}
        }
    },
    {
        "name": "list_tags",
        "description": "List all available tags in the system. Use this to see existing tags before creating new ones or to find tag IDs for assigning to tasks. Returns: Dictionary with success status and tags list (each with tag_id and name).\n\nERROR HANDLING:\n- No errors typically returned - function returns success with tags list (empty if no tags exist).\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {}
    },
    {
        "name": "assign_tag_to_task",
        "description": "Assign a tag to a task for categorization. A task can have multiple tags. Use this to organize tasks by features, areas, priorities, or other dimensions. Returns: Dictionary with success status and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Tag X not found...\"} if tag_id doesn't exist. Verify tag_id is correct, use list_tags() or create_tag() to get valid tag IDs.\n- Returns {\"success\": False, \"error\": \"Failed to assign tag: ...\"} if assignment fails (e.g., tag already assigned, database constraint violation). Usually safe to ignore if tag is already assigned - operation is idempotent.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to tag"},
            "tag_id": {"type": "integer", "description": "ID of the tag to assign (get from create_tag or list_tags)"}
        }
    },
    {
        "name": "remove_tag_from_task",
        "description": "Remove a tag from a task. Use this to update task categorization when tags are no longer relevant. Returns: Dictionary with success status and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Tag X not found...\"} if tag_id doesn't exist. Verify tag_id is correct.\n- Returns {\"success\": False, \"error\": \"Failed to remove tag: ...\"} if removal fails. Usually safe to ignore if tag is already not assigned - operation is idempotent.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to remove tag from"},
            "tag_id": {"type": "integer", "description": "ID of the tag to remove"}
        }
    },
    {
        "name": "get_task_tags",
        "description": "Get all tags assigned to a specific task. Use this to see how a task is categorized or to check if a task already has certain tags. Returns: Dictionary with success status, task_id, and tags list.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns tags list (empty if task has no tags) - this is expected, not an error.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to get tags for"}
        }
    },
    {
        "name": "create_template",
        "description": "Create a reusable task template with pre-defined instructions and verification steps. Templates help standardize common task patterns. When creating tasks from templates (via create_task_from_template), the template's instructions are automatically filled in. Returns: Dictionary with success status, template_id, and template data.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Template name cannot be empty\"} if template name is empty or whitespace-only. Ensure name has meaningful text.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if template creation fails (e.g., duplicate template name, invalid task_type). Fix parameters and retry.\n- Returns {\"success\": False, \"error\": \"Failed to create template: ...\"} if unexpected database error occurs. Retry with exponential backoff if temporary database issue.",
        "parameters": {
            "name": {"type": "string", "description": "Template name (must be unique, e.g., 'Bug Fix Template', 'Feature Template')"},
            "task_type": {"type": "string", "enum": ["concrete", "abstract", "epic"], "description": "Task type this template creates: 'concrete'=implementable, 'abstract'=needs breakdown, 'epic'=large feature"},
            "task_instruction": {"type": "string", "description": "Template instruction text (can include placeholders for customization)"},
            "verification_instruction": {"type": "string", "description": "Template verification steps (how to verify tasks created from this template)"},
            "description": {"type": "string", "optional": True, "description": "Optional template description explaining when to use this template"},
            "priority": {"type": "string", "optional": True, "enum": ["low", "medium", "high", "critical"], "description": "Optional default priority for tasks created from this template"},
            "estimated_hours": {"type": "number", "optional": True, "description": "Optional default estimated hours for tasks from this template"},
            "notes": {"type": "string", "optional": True, "description": "Optional additional template notes"}
        }
    },
    {
        "name": "list_templates",
        "description": "List all available task templates. Use this to find templates before creating tasks from them. Optionally filter by task_type to see only templates for specific task types. Returns: Dictionary with success status and templates list.\n\nERROR HANDLING:\n- No errors typically returned - function returns success with templates list (empty if no templates exist).\n- Parameter validation errors (invalid task_type enum) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_type": {"type": "string", "optional": True, "enum": ["concrete", "abstract", "epic"], "description": "Optional: Filter templates by task type"}
        }
    },
    {
        "name": "get_template",
        "description": "Get detailed information about a specific template by ID. Use this to review template instructions before creating a task from it. Returns: Dictionary with success status and template data including all fields.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Template X not found...\"} if template_id doesn't exist. Verify template_id is correct, use list_templates() to get valid template IDs.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "template_id": {"type": "integer", "description": "ID of the template to retrieve (get from list_templates)"}
        }
    },
    {
        "name": "create_task_from_template",
        "description": "Create a new task using a template, automatically filling in the template's instructions and verification steps. Faster than create_task when using standard patterns. You can override template values (priority, estimated_hours, etc.) or use template defaults. Returns: Dictionary with success status and task_id of the created task.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if template_id doesn't exist or template is invalid. Verify template_id is correct, use list_templates() or get_template() to verify template exists.\n- Returns {\"success\": False, \"error\": \"Failed to create task from template: ...\"} if task creation fails (e.g., invalid due_date format, database constraint violation). Fix parameters (especially due_date ISO format) and retry.\n- Parameter validation errors (invalid priority enum, invalid estimated_hours) are handled by framework validation before function is called.",
        "parameters": {
            "template_id": {"type": "integer", "description": "ID of the template to use (get from list_templates)"},
            "agent_id": {"type": "string", "description": "Your agent identifier (who created this task)"},
            "title": {"type": "string", "optional": True, "description": "Optional: Task title (defaults to template name if not provided)"},
            "project_id": {"type": "integer", "optional": True, "description": "Optional: Associate task with a project"},
            "notes": {"type": "string", "optional": True, "description": "Optional: Additional notes (combined with template notes)"},
            "priority": {"type": "string", "optional": True, "enum": ["low", "medium", "high", "critical"], "description": "Optional: Override template priority"},
            "estimated_hours": {"type": "number", "optional": True, "description": "Optional: Override template estimated hours"},
            "due_date": {"type": "string", "optional": True, "description": "Optional: Due date in ISO format (e.g., '2025-12-31T23:59:59Z')"}
        }
    },
    {
        "name": "get_activity_feed",
        "description": "Get chronological activity feed showing all task updates, completions, relationship changes, and other events. Use this for monitoring project activity, tracking changes, or auditing task history. Can filter by task_id, agent_id, or date range. Returns: Dictionary with success status, feed list (chronological), and count.\n\nERROR HANDLING:\n- No errors typically returned - function returns success with feed list (empty if no activity matches criteria).\n- Parameter validation errors (invalid date format, invalid limit) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {"type": "integer", "optional": True, "description": "Optional: Filter activity for a specific task"},
            "agent_id": {"type": "string", "optional": True, "description": "Optional: Filter activity by a specific agent"},
            "start_date": {"type": "string", "optional": True, "description": "Optional: Filter activity after this date (ISO format, e.g., '2025-01-01T00:00:00Z')"},
            "end_date": {"type": "string", "optional": True, "description": "Optional: Filter activity before this date (ISO format)"},
            "limit": {"type": "integer", "optional": True, "default": 1000, "description": "Maximum number of activity entries (default: 1000)"}
        }
    },
    {
        "name": "create_comment",
        "description": "Create a comment on a task for discussion and collaboration. Supports threaded replies (use parent_comment_id) and mentions (use mentions array to notify other agents). Comments are different from updates (add_task_update) - use comments for discussion, updates for progress tracking. Returns: Dictionary with success status, comment_id, task_id, and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Comment content cannot be empty\"} if content is empty or whitespace-only. Ensure content has meaningful text.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if comment creation fails (e.g., invalid parent_comment_id, database constraint violation). Fix parameters and retry.\n- Returns {\"success\": False, \"error\": \"Failed to create comment: ...\"} if unexpected database error occurs. Retry with exponential backoff if temporary database issue.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to comment on"},
            "agent_id": {"type": "string", "description": "Your agent identifier"},
            "content": {"type": "string", "description": "Comment content/text"},
            "parent_comment_id": {"type": "integer", "optional": True, "description": "Optional: ID of parent comment for threaded replies"},
            "mentions": {"type": "array", "items": {"type": "string"}, "optional": True, "description": "Optional: List of agent IDs to mention/notify (e.g., ['agent-1', 'agent-2'])"}
        }
    },
    {
        "name": "get_task_comments",
        "description": "Get all top-level comments for a task (excludes threaded replies - use get_comment_thread for those). Use this to see discussion and feedback on a task. Returns: Dictionary with success status, task_id, comments list, and count.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns comments list (empty if task has no comments) - this is expected, not an error.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to get comments for"},
            "limit": {"type": "integer", "optional": True, "default": 100, "description": "Maximum number of comments (default: 100)"}
        }
    },
    {
        "name": "get_comment_thread",
        "description": "Get a complete comment thread including the parent comment and all replies. Use this to see threaded discussions. Returns: Dictionary with success status, comment_id, thread list (parent + replies), and count.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Comment X not found...\"} if comment_id doesn't exist. Verify comment_id is correct.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "comment_id": {"type": "integer", "description": "ID of the parent comment (get from get_task_comments or create_comment)"}
        }
    },
    {
        "name": "update_comment",
        "description": "Update a comment you created. Only the comment owner (agent_id must match comment creator) can update. Use this to correct mistakes or update information. Returns: Dictionary with success status, comment_id, updated comment data, and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Comment X not found...\"} if comment_id doesn't exist. Verify comment_id is correct.\n- Returns {\"success\": False, \"error\": \"Comment content cannot be empty\"} if content is empty or whitespace-only. Ensure content has meaningful text.\n- Returns {\"success\": False, \"error\": \"Failed to update comment\"} if agent_id doesn't match comment owner (permission denied). Only the comment creator can update it.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if update fails (e.g., permission issue, database constraint). Fix parameters and retry.\n- Returns {\"success\": False, \"error\": \"Failed to update comment: ...\"} if unexpected database error occurs. Retry with exponential backoff if temporary database issue.",
        "parameters": {
            "comment_id": {"type": "integer", "description": "ID of the comment to update (must be your comment)"},
            "agent_id": {"type": "string", "description": "Your agent identifier (must match comment creator)"},
            "content": {"type": "string", "description": "Updated comment content"}
        }
    },
    {
        "name": "delete_comment",
        "description": "Delete a comment you created. Only the comment owner can delete. Deletion cascades to all replies - deleting a parent comment deletes its entire thread. Use with caution. Returns: Dictionary with success status, comment_id, and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Comment X not found...\"} if comment_id doesn't exist. Verify comment_id is correct.\n- Returns {\"success\": False, \"error\": \"Failed to delete comment\"} if agent_id doesn't match comment owner (permission denied). Only the comment creator can delete it.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if deletion fails (e.g., permission issue). Fix parameters and retry.\n- Returns {\"success\": False, \"error\": \"Failed to delete comment: ...\"} if unexpected database error occurs. Retry with exponential backoff if temporary database issue.\n- WARNING: Deletion cascades to all replies - this cannot be undone.",
        "parameters": {
            "comment_id": {"type": "integer", "description": "ID of the comment to delete (must be your comment)"},
            "agent_id": {"type": "string", "description": "Your agent identifier (must match comment creator)"}
        }
    },
    {
        "name": "create_recurring_task",
        "description": "Create a recurring task pattern that automatically generates task instances on a schedule. Use this for tasks that repeat regularly (daily standups, weekly reviews, monthly reports). recurrence_type: 'daily'=every day, 'weekly'=every week (use recurrence_config.day_of_week), 'monthly'=every month (use recurrence_config.day_of_month). Returns: Dictionary with success status and recurring_task_id.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Invalid next_occurrence format. Must be ISO format timestamp.\"} if next_occurrence is not valid ISO format. Use format like '2025-11-02T09:00:00Z'.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if recurring task creation fails (e.g., invalid recurrence_config, task already has recurring pattern). Fix parameters and retry.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the base task template to recur (create this task first, then make it recurring)"},
            "recurrence_type": {"type": "string", "enum": ["daily", "weekly", "monthly"], "description": "How often to create instances: 'daily'=every day, 'weekly'=every week, 'monthly'=every month"},
            "next_occurrence": {"type": "string", "description": "When to create the next instance (ISO format timestamp, e.g., '2025-11-02T09:00:00Z')"},
            "recurrence_config": {"type": "object", "optional": True, "description": "Optional: Additional config. For 'weekly': {'day_of_week': 0-6 (Mon=0)}. For 'monthly': {'day_of_month': 1-31}."}
        }
    },
    {
        "name": "list_recurring_tasks",
        "description": "List all recurring task patterns in the system. Use this to see active and inactive recurring tasks. Set active_only=true to see only patterns currently generating instances. Returns: Dictionary with success status and recurring_tasks list.\n\nERROR HANDLING:\n- No errors typically returned - function returns success with recurring_tasks list (empty if none exist).\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "active_only": {"type": "boolean", "optional": True, "default": False, "description": "If true, only return active recurring tasks (default: false, returns all)"}
        }
    },
    {
        "name": "get_recurring_task",
        "description": "Get detailed information about a specific recurring task pattern. Use this to review recurrence schedule and configuration. Returns: Dictionary with success status and recurring_task data including schedule, config, and status.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Recurring task X not found...\"} if recurring_id doesn't exist. Verify recurring_id is correct, use list_recurring_tasks() to get valid IDs.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "recurring_id": {"type": "integer", "description": "ID of the recurring task pattern (get from list_recurring_tasks)"}
        }
    },
    {
        "name": "update_recurring_task",
        "description": "Update a recurring task's schedule or configuration. Use this to change recurrence frequency, adjust next occurrence date, or modify recurrence_config (e.g., change day of week for weekly tasks). Returns: Dictionary with success status and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Invalid next_occurrence format. Must be ISO format timestamp.\"} if next_occurrence is provided but not valid ISO format. Use format like '2025-11-02T09:00:00Z'.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if update fails (e.g., recurring_id doesn't exist, invalid recurrence_config). Verify recurring_id and fix parameters, then retry.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "recurring_id": {"type": "integer", "description": "ID of the recurring task to update"},
            "recurrence_type": {"type": "string", "optional": True, "enum": ["daily", "weekly", "monthly"], "description": "Optional: New recurrence frequency"},
            "recurrence_config": {"type": "object", "optional": True, "description": "Optional: Updated recurrence config (see create_recurring_task for format)"},
            "next_occurrence": {"type": "string", "optional": True, "description": "Optional: New next occurrence date (ISO format)"}
        }
    },
    {
        "name": "deactivate_recurring_task",
        "description": "Deactivate a recurring task pattern to stop it from creating new instances. The pattern remains in the system but stops generating tasks. Use this to pause recurring tasks temporarily. Returns: Dictionary with success status and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Recurring task X not found...\"} if recurring_id doesn't exist. Verify recurring_id is correct.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "recurring_id": {"type": "integer", "description": "ID of the recurring task to deactivate"}
        }
    },
    {
        "name": "create_recurring_instance",
        "description": "Manually trigger creation of the next task instance from a recurring pattern. Normally instances are created automatically, but use this to force immediate creation or test the pattern. Returns: Dictionary with success status, instance_id (the created task ID), and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Recurring task X not found...\"} if recurring_id doesn't exist. Verify recurring_id is correct.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if instance creation fails (e.g., recurring task is deactivated, invalid state). Verify recurring task status and retry.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "recurring_id": {"type": "integer", "description": "ID of the recurring task pattern to create instance from"}
        }
    },
    {
        "name": "get_task_versions",
        "description": "Get all version history for a task. Tasks are automatically versioned when key fields change (title, instructions, status, etc.). Use this to see the change history and track how a task evolved. Returns: Dictionary with success status, task_id, versions list (ordered newest first), and count.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns versions list (empty if task has no version history yet) - this is expected for new tasks, not an error.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to get version history for"}
        }
    },
    {
        "name": "get_task_version",
        "description": "Get a specific historical version of a task by version number. Use this to see what a task looked like at a particular point in time. Version numbers start at 1 and increment with each change. Returns: Dictionary with success status and version data (all task fields at that version).\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Version X for task Y not found...\"} if version_number doesn't exist for the task. Verify version_number is correct, use get_task_versions() to see available versions.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task"},
            "version_number": {"type": "integer", "description": "Version number to retrieve (get from get_task_versions)"}
        }
    },
    {
        "name": "get_latest_task_version",
        "description": "Get the most recent version of a task. Useful for seeing the current state with version metadata. Returns: Dictionary with success status and version data (same as current task but includes version_number).\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"No versions found for task X.\"} if task has no version history yet (new task). This is expected for brand new tasks, not an error.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to get latest version for"}
        }
    },
    {
        "name": "diff_task_versions",
        "description": "Compare two task versions and see what changed. Use this to understand differences between versions, review changes, or audit modifications. Returns: Dictionary with success status, task_id, version numbers, diff object (field-by-field changes), and changed_fields list.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if version comparison fails (e.g., version_number_1 or version_number_2 doesn't exist, version_number_2 <= version_number_1). Ensure version_number_2 > version_number_1 and both versions exist (use get_task_versions() to verify).\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to diff"},
            "version_number_1": {"type": "integer", "description": "Older version number (e.g., 1)"},
            "version_number_2": {"type": "integer", "description": "Newer version number (e.g., 2). Must be > version_number_1."}
        }
    },
    {
        "name": "link_github_issue",
        "description": "Link a GitHub issue URL to a task for traceability. Use this to connect tasks with GitHub issues for cross-referencing. A task can have one linked issue. Returns: Dictionary with success status, task_id, github_issue_url, and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if linking fails (e.g., invalid GitHub URL format, database constraint violation). Ensure URL is a valid GitHub issue URL format (e.g., 'https://github.com/org/repo/issues/123'). Fix URL format and retry.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to link issue to"},
            "github_url": {"type": "string", "description": "Full GitHub issue URL (e.g., 'https://github.com/org/repo/issues/123')"}
        }
    },
    {
        "name": "link_github_pr",
        "description": "Link a GitHub pull request URL to a task for traceability. Use this to connect tasks with PRs that implement or relate to the task. A task can have one linked PR. Returns: Dictionary with success status, task_id, github_pr_url, and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if linking fails (e.g., invalid GitHub URL format, database constraint violation). Ensure URL is a valid GitHub PR URL format (e.g., 'https://github.com/org/repo/pull/456'). Fix URL format and retry.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to link PR to"},
            "github_url": {"type": "string", "description": "Full GitHub PR URL (e.g., 'https://github.com/org/repo/pull/456')"}
        }
    },
    {
        "name": "get_github_links",
        "description": "Get GitHub issue and PR links for a task. Use this to see what GitHub resources are associated with a task. Returns: Dictionary with success status, task_id, github_issue_url (or null), and github_pr_url (or null).\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns github_issue_url and github_pr_url as null if task has no GitHub links - this is expected, not an error.\n- Returns {\"success\": False, \"error\": \"...\"} with ValueError message if retrieval fails. Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {"type": "integer", "description": "ID of the task to get GitHub links for"}
        }
    }
]

