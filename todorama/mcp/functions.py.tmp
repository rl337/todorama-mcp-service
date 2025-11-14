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
            "agent_id": {
                "type": "string",
                "description": "Your agent identifier. Must be a non-empty string (1-100 characters). Use the same agent_id you use for all task operations.",
                "minLength": 1,
                "maxLength": 100,
                "example": "cursor-agent"
            },
            "task_type": {
                "type": "string",
                "optional": True,
                "enum": ["concrete", "abstract", "epic"],
                "description": "Optional: Filter statistics by task type. Omit to see statistics for all task types. Use to analyze performance for specific task categories.",
                "enumDescriptions": {
                    "concrete": "Filter statistics to only concrete (implementable) tasks",
                    "abstract": "Filter statistics to only abstract (needs breakdown) tasks",
                    "epic": "Filter statistics to only epic (large feature) tasks"
                },
                "example": "concrete"
            }
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
        "name": "verify_task",
        "description": "Verify a task's completion. Marks verification_status from 'unverified' to 'verified' for tasks that are complete but not yet verified. This is used when a task has been completed but needs verification to confirm it meets all requirements. Use this for verification tasks (tasks showing needs_verification=True). Returns: Dictionary with success status and verification message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Task X is already verified...\"} if task is already verified. No action needed.\n- Returns {\"success\": False, \"error\": \"Failed to verify task X: ...\"} if verification fails (e.g., task not in complete status). Ensure task is complete before verifying.",
        "parameters": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to verify. Must be a positive integer. Task must be in 'complete' status.",
                "minimum": 1,
                "example": 123
            },
            "agent_id": {
                "type": "string",
                "description": "Your agent identifier. Used to track who verified the task. Must be a non-empty string (1-100 characters).",
                "minLength": 1,
                "maxLength": 100,
                "example": "cursor-agent"
            },
            "notes": {
                "type": "string",
                "optional": True,
                "description": "Optional notes about the verification. Helpful for documenting what was verified or any issues found.",
                "example": "Verification PASSED. All requirements met. Tests pass, functionality works as specified."
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
            "days_ahead": {
                "type": "integer",
                "optional": True,
                "default": 3,
                "description": "Number of days ahead to look for approaching deadlines. Tasks with due dates within this window are returned. Must be a positive integer if provided.",
                "minimum": 1,
                "maximum": 365,
                "example": 3
            },
            "limit": {
                "type": "integer",
                "optional": True,
                "default": 100,
                "description": "Maximum number of tasks to return. Must be between 1 and 1000 (default: 100).",
                "minimum": 1,
                "maximum": 1000,
                "example": 100
            }
        }
    },
    {
        "name": "create_tag",
        "description": "Create a new tag for categorizing tasks. If a tag with the same name already exists, returns the existing tag ID (no duplicate tags). Use tags to organize and filter tasks by categories, features, or attributes. Returns: Dictionary with success status, tag_id, and tag data.\n\nERROR HANDLING:\n- Parameter validation errors (empty tag name) are handled by framework validation before function is called.\n- Database errors (unique constraint violations handled internally - returns existing tag) are rare. If connection issues occur, retry with exponential backoff.\n- If tag with same name exists, function returns existing tag_id (no error) - this is expected behavior, not an error.",
        "parameters": {
            "name": {
                "type": "string",
                "description": "Tag name for categorizing tasks. Must be non-empty and unique. Common examples: 'backend', 'frontend', 'bug', 'feature', 'documentation', 'refactoring'. Use descriptive names that help organize tasks.",
                "minLength": 1,
                "example": "backend"
            }
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
            "task_id": {
                "type": "integer",
                "description": "ID of the task to tag. Must be a positive integer. Get task IDs from query_tasks(), list_available_tasks(), or search_tasks().",
                "minimum": 1,
                "example": 123
            },
            "tag_id": {
                "type": "integer",
                "description": "ID of the tag to assign. Must be a positive integer. Get tag IDs from list_tags() or create_tag().",
                "minimum": 1,
                "example": 5
            }
        }
    },
    {
        "name": "remove_tag_from_task",
        "description": "Remove a tag from a task. Use this to update task categorization when tags are no longer relevant. Returns: Dictionary with success status and confirmation message.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns {\"success\": False, \"error\": \"Tag X not found...\"} if tag_id doesn't exist. Verify tag_id is correct.\n- Returns {\"success\": False, \"error\": \"Failed to remove tag: ...\"} if removal fails. Usually safe to ignore if tag is already not assigned - operation is idempotent.",
        "parameters": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to remove tag from. Must be a positive integer.",
                "minimum": 1,
                "example": 123
            },
            "tag_id": {
                "type": "integer",
                "description": "ID of the tag to remove. Must be a positive integer.",
                "minimum": 1,
                "example": 5
            }
        }
    },
    {
        "name": "get_task_tags",
        "description": "Get all tags assigned to a specific task. Use this to see how a task is categorized or to check if a task already has certain tags. Returns: Dictionary with success status, task_id, and tags list.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Task X not found...\"} if task_id doesn't exist. Verify task_id is correct.\n- Returns tags list (empty if task has no tags) - this is expected, not an error.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to get tags for. Must be a positive integer.",
                "minimum": 1,
                "example": 123
            }
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
    },
    {
        "name": "list_projects",
        "description": "List all available projects in the system. Use this to discover projects before creating tasks or to find project IDs. Returns: Dictionary with success status, projects list, and count. This is critical when the service is external-only, as agents need to discover/manage projects via MCP instead of REST API.\n\nERROR HANDLING:\n- No errors typically returned - function returns success with projects list (empty if no projects exist).\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {}
    },
    {
        "name": "get_project",
        "description": "Get project details by ID. Use this to retrieve full project information including name, local_path, origin_url, and description. Returns: Dictionary with success status and project data.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Project X not found...\"} if project_id doesn't exist. Verify project_id is correct, use list_projects() to get valid project IDs.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "project_id": {"type": "integer", "description": "ID of the project to retrieve. Must be a positive integer. Get project IDs from list_projects().", "minimum": 1, "example": 1}
        }
    },
    {
        "name": "get_project_by_name",
        "description": "Get project by name (helpful for looking up project_id). Use this when you know the project name but need the project_id for creating tasks. Returns: Dictionary with success status and project data.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Project 'X' not found...\"} if project name doesn't exist. Verify the project name is correct, use list_projects() to see available project names.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "name": {"type": "string", "description": "Project name to search for. Must be non-empty. Project names are case-sensitive.", "minLength": 1, "example": "my-project"}
        }
    },
    {
        "name": "create_project",
        "description": "Create a new project. Use this to set up projects before creating tasks. Projects organize tasks and provide context (local_path, origin_url) for agents. Returns: Dictionary with success status, project_id, and created project data.\n\nERROR HANDLING:\n- Returns {\"success\": False, \"error\": \"Project with name 'X' already exists...\"} if a project with the same name already exists. Project names must be unique. Use a different name or get the existing project with get_project_by_name().\n- Returns {\"success\": False, \"error\": \"Failed to create project: ...\"} if creation fails (e.g., database constraint violation, invalid path). Fix parameters and retry.\n- Parameter validation errors (empty name, invalid path format) are handled by framework validation before function is called.\n- Database errors are rare; if connection issues occur, retry with exponential backoff.",
        "parameters": {
            "name": {"type": "string", "description": "Project name (must be unique). Should be concise and descriptive (e.g., 'my-project', 'todo-service').", "minLength": 1, "example": "my-project"},
            "local_path": {"type": "string", "description": "Local filesystem path to the project. Used by agents to locate project files and run commands in the project directory.", "minLength": 1, "example": "/path/to/project"},
            "origin_url": {"type": "string", "optional": True, "description": "Optional origin URL (e.g., GitHub repository URL). Useful for linking tasks to source code repositories.", "example": "https://github.com/user/repo"},
            "description": {"type": "string", "optional": True, "description": "Optional project description. Provides context about what the project is for.", "example": "My awesome project"}
        }
    }
]
