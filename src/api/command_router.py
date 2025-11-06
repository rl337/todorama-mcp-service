"""
Command pattern router for /api/<Entity>/<action> endpoints.
Dynamically routes to entity methods based on URL path.
"""
from fastapi import APIRouter, Request, Depends, Query, Body, HTTPException, Response
from typing import Dict, Any, Optional, List
import logging

from api.entities.task_entity import TaskEntity
from api.entities.project_entity import ProjectEntity
from api.entities.backup_entity import BackupEntity
from auth.dependencies import verify_api_key, optional_api_key
from dependencies.services import get_db, get_backup_manager
from api.response_strategy import response_context

logger = logging.getLogger(__name__)

# Map entity names to entity classes
ENTITY_MAP = {
    "Task": TaskEntity,
    "Project": ProjectEntity,
    "Backup": BackupEntity,
}

# Initialize router with /api prefix
router = APIRouter(prefix="/api")


def get_entity_class(entity_name: str):
    """Get entity class by name."""
    entity_class = ENTITY_MAP.get(entity_name)
    if not entity_class:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_name}' not found")
    return entity_class


@router.post("/{entity_name}/{action}")
@router.get("/{entity_name}/{action}")
@router.patch("/{entity_name}/{action}")
async def entity_command(
    entity_name: str,
    action: str,
    request: Request
):
    """
    Generic command endpoint: /api/<Entity>/<action>
    
    Examples:
    - POST /api/Task/create - Create a task
    - GET /api/Task/get?task_id=123 - Get a task
    - GET /api/Task/list?task_type=concrete - List tasks
    - POST /api/Project/create - Create a project
    """
    try:
        # Manually verify API key (avoid FastAPI body validation issues)
        try:
            auth = await optional_api_key(request)
        except Exception:
            auth = None
        
        # Get entity class
        entity_class = get_entity_class(entity_name)
        
        # Get database
        db = get_db()
        
        # Create entity instance with auth info
        # BackupEntity needs backup_manager, others just need db
        if entity_name == "Backup":
            backup_manager = get_backup_manager()
            entity = entity_class(db, backup_manager, auth_info=auth)
        else:
            entity = entity_class(db, auth_info=auth)
        
        # Handle actions with sub-paths like "export/json" or "export/csv"
        # Extract format from action if it contains a slash
        actual_action = action
        format_param = None
        if "/" in action:
            parts = action.split("/", 1)
            actual_action = parts[0]
            format_param = parts[1] if len(parts) > 1 else None
        
        # Convert hyphens to underscores for method names (e.g., "approaching-deadline" -> "approaching_deadline")
        method_name = actual_action.replace("-", "_")
        
        # Get action method - try both with and without underscore conversion
        if hasattr(entity, method_name):
            action_method = getattr(entity, method_name)
            actual_action = method_name  # Use the method name for routing logic
        elif hasattr(entity, actual_action):
            action_method = getattr(entity, actual_action)
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Action '{action}' not found on entity '{entity_name}'. Available actions: {[m for m in dir(entity) if not m.startswith('_') and callable(getattr(entity, m))]}"
            )
        
        # Parse request body for POST/PATCH or query params for GET
        if request.method in ["POST", "PATCH"]:
            try:
                body = await request.json()
            except Exception:
                # If no body, use empty dict
                body = {}
            # For PATCH on "get" action, treat as update
            if request.method == "PATCH" and actual_action == "get":
                # PATCH /api/Task/get?task_id=123 with body should update the task
                # Extract task_id from query params
                query_params = dict(request.query_params)
                task_id = None
                for key, value in query_params.items():
                    if key == "task_id":
                        try:
                            task_id = int(value)
                        except ValueError:
                            pass
                        break
                if task_id:
                    # Call update method with task_id and body
                    if hasattr(entity, "update"):
                        result = entity.update(task_id=task_id, update_data=body)
                    else:
                        raise HTTPException(
                            status_code=405,
                            detail=f"Update not supported for entity '{entity_name}'"
                        )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="task_id parameter required for PATCH /api/{entity_name}/get"
                    )
            else:
                # Call method with body as kwargs
                result = action_method(**body)
        else:
            # GET request - use query params
            query_params = dict(request.query_params)
            # Convert single values to appropriate types
            params = {}
            for key, value in query_params.items():
                # Try to convert to int if numeric
                try:
                    if value.isdigit():
                        params[key] = int(value)
                    elif '.' in value and value.replace('.', '').isdigit():
                        params[key] = float(value)
                    else:
                        params[key] = value
                except:
                    params[key] = value
            
            # For GET, pass params as filters or direct args
            # If action is 'list', wrap in filters dict
            # Exception: BackupEntity.list() doesn't accept filters
            if actual_action == "list":
                if entity_name == "Backup":
                    # BackupEntity.list() doesn't accept any parameters
                    result = action_method()
                else:
                    result = action_method(filters=params)
            elif actual_action == "search":
                result = action_method(query=params.get("query", ""), limit=int(params.get("limit", 100)))
            elif actual_action == "export" and format_param:
                # For export, pass format and filters
                result = action_method(format=format_param, filters=params)
            elif actual_action == "overdue":
                result = action_method(filters=params)
            elif actual_action == "approaching-deadline" or actual_action == "approaching_deadline":
                # Handle both formats
                result = action_method(days_ahead=int(params.get("days_ahead", 3)), filters=params)
            elif actual_action == "get_stale":
                # Handle get_stale with hours parameter
                result = action_method(hours=params.get("hours"))
            else:
                # For other GET actions, pass params as kwargs
                result = action_method(**params)
        
        # Determine response strategy based on action type
        # Create actions return 201, others return 200
        if actual_action == "create":
            return response_context.render_created(result)
        else:
            return response_context.render_success(result)
        
    except HTTPException as e:
        # Use response strategy for HTTP exceptions
        return response_context.render_from_exception(e)
    except Exception as e:
        logger.error(f"Error in entity command {entity_name}.{action}: {e}", exc_info=True)
        return response_context.render_server_error(f"Internal server error: {str(e)}")


@router.get("/{entity_name}")
async def entity_info(entity_name: str):
    """
    Get information about an entity and its available actions.
    
    GET /api/Task - List available actions for Task entity
    """
    try:
        entity_class = get_entity_class(entity_name)
        
        # Get all public methods (not starting with _)
        methods = [m for m in dir(entity_class) 
                  if not m.startswith('_') 
                  and callable(getattr(entity_class, m))
                  and m not in ['db', 'auth_info', 'service']]
        
        return {
            "entity": entity_name,
            "available_actions": methods,
            "description": entity_class.__doc__ or f"{entity_name} entity"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting entity info for {entity_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

