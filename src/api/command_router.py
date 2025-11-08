"""
Command pattern router for /api/<Entity>/<action> endpoints.
Dynamically routes to entity methods based on URL path.
"""
from fastapi import APIRouter, Request, Depends, Query, Body, HTTPException
from fastapi.responses import Response
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


# Special route for actions with sub-paths like export/json or export/csv
# This must come before the generic route to match first
@router.get("/{entity_name}/export/{format}")
async def entity_export(
    entity_name: str,
    format: str,
    request: Request
):
    """Handle export actions with format: /api/Task/export/json or /api/Task/export/csv"""
    try:
        # Manually verify API key
        try:
            auth = await optional_api_key(request)
        except Exception:
            auth = None
        
        # Get entity class
        entity_class = get_entity_class(entity_name)
        
        # Get database
        db = get_db()
        
        # Create entity instance with auth info
        if entity_name == "Backup":
            backup_manager = get_backup_manager()
            entity = entity_class(db, backup_manager, auth_info=auth)
        else:
            entity = entity_class(db, auth_info=auth)
        
        # Get export method
        if not hasattr(entity, "export"):
            raise HTTPException(
                status_code=404,
                detail=f"Export not supported for entity '{entity_name}'"
            )
        
        action_method = getattr(entity, "export")
        
        # Parse query params as filters
        query_params = dict(request.query_params)
        params = {}
        for key, value in query_params.items():
            try:
                if value.isdigit():
                    params[key] = int(value)
                elif '.' in value and value.replace('.', '').isdigit():
                    params[key] = float(value)
                else:
                    params[key] = value
            except:
                params[key] = value
        
        # Call export method with format and filters
        result = action_method(format=format, filters=params)
        
        # If result is already a Response object, return it directly
        if isinstance(result, Response):
            return result
        else:
            return response_context.render_success(result)
        
    except HTTPException as e:
        return response_context.render_from_exception(e)
    except Exception as e:
        logger.error(f"Error in entity export {entity_name}.export/{format}: {e}", exc_info=True)
        return response_context.render_server_error(f"Internal server error: {str(e)}")


@router.post("/{entity_name}/{action:path}")
@router.get("/{entity_name}/{action:path}")
@router.patch("/{entity_name}/{action:path}")
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
        
        # Handle actions with sub-paths like "export/json", "import/json", "bulk/complete"
        # Also handle path parameters like "{task_id}/relationships"
        # Extract sub-path parts from action if it contains a slash
        actual_action = action
        sub_path = None
        path_param = None
        
        if "/" in action:
            parts = action.split("/", 1)
            actual_action = parts[0]
            sub_path = parts[1] if len(parts) > 1 else None
            
            # Check if actual_action is a numeric ID (path parameter)
            # Pattern: /api/Task/{task_id}/relationships -> action="123/relationships"
            try:
                path_param = int(actual_action)
                # If it's a number, treat it as a path parameter and use sub_path as the action
                if sub_path:
                    # For GET requests, try "get_{sub_path}" first, then just sub_path
                    # For POST/PATCH, use sub_path directly
                    actual_action = sub_path.replace("-", "_")
                    sub_path = None  # Clear sub_path since we're using it as the action
            except (ValueError, TypeError):
                # Not a number, treat as normal action
                pass
        
        # Special handling for actions with sub-paths that map to specific methods
        # For import/json -> import_json, bulk/complete -> bulk_complete, etc.
        if actual_action == "import" and sub_path:
            # Directly call import_json or import_csv
            import_method_name = f"import_{sub_path}"
            if hasattr(entity, import_method_name):
                # Will be handled in POST/PATCH section
                action_method = None  # Special case, handled separately
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"Import format '{sub_path}' not supported. Use 'json' or 'csv'."
                )
        elif actual_action == "bulk" and sub_path:
            # Directly call bulk_complete, bulk_assign, etc.
            bulk_method_name = f"bulk_{sub_path.replace('-', '_')}"
            if hasattr(entity, bulk_method_name):
                # Will be handled in POST/PATCH section
                action_method = None  # Special case, handled separately
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"Bulk action '{sub_path}' not found on entity '{entity_name}'"
                )
        else:
            # If we detected a path parameter, try to find the method now
            if path_param is not None:
                # Try "get_{action}" first for GET requests, then just "{action}"
                get_method_name = f"get_{actual_action}"
                if hasattr(entity, get_method_name):
                    action_method = getattr(entity, get_method_name)
                elif hasattr(entity, actual_action):
                    action_method = getattr(entity, actual_action)
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Action '{actual_action}' not found for path parameter '{path_param}' on entity '{entity_name}'"
                    )
            else:
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
        # This must be outside the else block so it executes for import/bulk actions too
        if request.method in ["POST", "PATCH"]:
            # Check if this is a multipart/form-data request (for CSV import)
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
                # For CSV import, parse form data
                from fastapi import Form, File, UploadFile
                try:
                    form = await request.form()
                    body = {}
                    # Extract file content if present
                    if "file" in form:
                        file = form["file"]
                        # Handle UploadFile or SpooledTemporaryFile
                        if hasattr(file, "read"):
                            file_content = await file.read()
                            if isinstance(file_content, bytes):
                                body["content"] = file_content.decode("utf-8")
                            else:
                                body["content"] = file_content
                        elif hasattr(file, "file"):
                            # SpooledTemporaryFile
                            file.file.seek(0)
                            body["content"] = file.file.read().decode("utf-8")
                        else:
                            body["content"] = str(file)
                    # Extract other form fields
                    for key, value in form.items():
                        if key != "file":
                            body[key] = value
                except Exception as e:
                    # If form parsing fails, try JSON
                    try:
                        body = await request.json()
                    except Exception:
                        body = {}
            else:
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
            elif actual_action == "import" and sub_path:
                # For import, call the specific import method (import_json or import_csv)
                import_method_name = f"import_{sub_path}"
                import_method = getattr(entity, import_method_name)
                result = import_method(format=sub_path, **body)
            elif actual_action == "bulk" and sub_path:
                # For bulk operations, pass the sub-action and body
                # Convert sub_path like "complete" to method call
                bulk_method_name = f"bulk_{sub_path.replace('-', '_')}"
                bulk_method = getattr(entity, bulk_method_name)
                result = bulk_method(**body)
            elif action_method:
                # If we have a path parameter (like task_id from /api/Task/1/relationships)
                # pass it as the first argument to the method
                if path_param is not None:
                    # Check method signature to see if it accepts task_id as first param
                    import inspect
                    sig = inspect.signature(action_method)
                    params = list(sig.parameters.keys())
                    if params and params[0] not in ['self', 'kwargs']:
                        # Method expects a positional parameter, pass path_param
                        result = action_method(path_param, **body)
                    else:
                        # Method expects it in kwargs, add to body
                        body['task_id'] = path_param
                        result = action_method(**body)
                else:
                    # Call method with body as kwargs
                    result = action_method(**body)
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"Action '{action}' not properly handled"
                )
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
            
            # If we have a path parameter (like task_id from /api/Task/1/relationships)
            # pass it to the method and return early
            if path_param is not None and action_method:
                import inspect
                sig = inspect.signature(action_method)
                method_params = list(sig.parameters.keys())
                if method_params and method_params[0] not in ['self', 'kwargs']:
                    # Method expects a positional parameter, pass path_param
                    result = action_method(path_param)
                    return response_context.render_success(result)
                else:
                    # Method expects it in query params, add it
                    params['task_id'] = path_param
                    result = action_method(**params)
                    return response_context.render_success(result)
            
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
                # Accept both 'q' and 'query' parameters for search
                query = params.get("q") or params.get("query", "")
                result = action_method(query=query, limit=int(params.get("limit", 100)))
            elif actual_action == "export" and sub_path:
                # For export, pass format and filters
                result = action_method(format=sub_path, filters=params)
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
        # If result is already a Response object (e.g., from export), return it directly
        # Ensure result is defined (should be set in POST/PATCH or GET branches above)
        if 'result' not in locals():
            raise HTTPException(
                status_code=500,
                detail=f"Internal error: result not set for action '{action}'"
            )
        if isinstance(result, Response):
            return result
        elif actual_action == "create":
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

