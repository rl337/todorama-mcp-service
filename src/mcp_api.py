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

# Initialize database
db_path = os.getenv("TODO_DB_PATH", "/home/rlee/june_data/todo_service/todos.db")
db = TodoDatabase(db_path)


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
        tasks = db.get_available_tasks_for_agent(agent_type, project_id=project_id, limit=limit)
        return [dict(task) for task in tasks]
    
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
        success = db.lock_task(task_id, agent_id)
        if not success:
            return {"success": False, "error": "Task is not available (already locked or different status)"}
        
        task = db.get_task(task_id)
        return {"success": True, "task": dict(task)}
    
    @staticmethod
    def complete_task(
        task_id: int,
        agent_id: str,
        notes: Optional[str] = None,
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
            followup_title: Optional followup task title
            followup_task_type: Optional followup task type
            followup_instruction: Optional followup task instruction
            followup_verification: Optional followup verification instruction
            
        Returns:
            Dictionary with completion status and optional followup task ID
        """
        # Verify task exists and is locked by this agent
        task = db.get_task(task_id)
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}
        
        if task["assigned_agent"] != agent_id and task["task_status"] == "in_progress":
            return {"success": False, "error": f"Task {task_id} is assigned to different agent"}
        
        # Complete the task
        db.complete_task(task_id, agent_id, notes=notes)
        
        result = {"success": True, "task_id": task_id, "completed": True}
        
        # Create followup if provided
        if followup_title and followup_task_type and followup_instruction and followup_verification:
            followup_id = db.create_task(
                title=followup_title,
                task_type=followup_task_type,
                task_instruction=followup_instruction,
                verification_instruction=followup_verification,
                agent_id=agent_id,
                notes=None
            )
            
            db.create_relationship(
                parent_task_id=task_id,
                child_task_id=followup_id,
                relationship_type="followup",
                agent_id=agent_id
            )
            
            result["followup_task_id"] = followup_id
        
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
        notes: Optional[str] = None
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
            
        Returns:
            Dictionary with created task ID and optional relationship ID
        """
        task_id = db.create_task(
            title=title,
            task_type=task_type,
            task_instruction=task_instruction,
            verification_instruction=verification_instruction,
            agent_id=agent_id,
            project_id=project_id,
            notes=notes
        )
        
        result = {"success": True, "task_id": task_id}
        
        # Create relationship if provided
        if parent_task_id and relationship_type:
            # Verify parent exists
            parent = db.get_task(parent_task_id)
            if not parent:
                return {"success": False, "error": f"Parent task {parent_task_id} not found"}
            
            rel_id = db.create_relationship(
                parent_task_id=parent_task_id,
                child_task_id=task_id,
                relationship_type=relationship_type,
                agent_id=agent_id
            )
            result["relationship_id"] = rel_id
        
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
        stats = db.get_agent_stats(agent_id, task_type)
        return stats


# MCP function definitions (for documentation/registration)
MCP_FUNCTIONS = [
    {
        "name": "list_available_tasks",
        "description": "List available tasks for an agent type (breakdown or implementation)",
        "parameters": {
            "agent_type": {"type": "string", "enum": ["breakdown", "implementation"]},
            "project_id": {"type": "integer", "optional": True},
            "limit": {"type": "integer", "default": 10}
        }
    },
    {
        "name": "reserve_task",
        "description": "Reserve (lock) a task for an agent to prevent concurrent access",
        "parameters": {
            "task_id": {"type": "integer"},
            "agent_id": {"type": "string"}
        }
    },
    {
        "name": "complete_task",
        "description": "Mark a task as complete and optionally create a followup task",
        "parameters": {
            "task_id": {"type": "integer"},
            "agent_id": {"type": "string"},
            "notes": {"type": "string", "optional": True},
            "followup_title": {"type": "string", "optional": True},
            "followup_task_type": {"type": "string", "optional": True},
            "followup_instruction": {"type": "string", "optional": True},
            "followup_verification": {"type": "string", "optional": True}
        }
    },
    {
        "name": "create_task",
        "description": "Create a new task, optionally linked to a parent task",
        "parameters": {
            "title": {"type": "string"},
            "task_type": {"type": "string", "enum": ["concrete", "abstract", "epic"]},
            "task_instruction": {"type": "string"},
            "verification_instruction": {"type": "string"},
            "agent_id": {"type": "string"},
            "project_id": {"type": "integer", "optional": True},
            "parent_task_id": {"type": "integer", "optional": True},
            "relationship_type": {"type": "string", "optional": True, "enum": ["subtask", "blocking", "blocked_by", "related"]},
            "notes": {"type": "string", "optional": True}
        }
    },
    {
        "name": "get_agent_performance",
        "description": "Get performance statistics for an agent",
        "parameters": {
            "agent_id": {"type": "string"},
            "task_type": {"type": "string", "optional": True, "enum": ["concrete", "abstract", "epic"]}
        }
    }
]

