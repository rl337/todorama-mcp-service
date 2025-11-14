"""Template-related MCP handlers."""

from typing import Optional, Dict, Any, Literal
from datetime import datetime

from todorama.mcp_api import get_db


def handle_create_template(
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


def handle_list_templates(task_type: Optional[Literal["concrete", "abstract", "epic"]] = None) -> Dict[str, Any]:
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


def handle_get_template(template_id: int) -> Dict[str, Any]:
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


def handle_create_task_from_template(
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
