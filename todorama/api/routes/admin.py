"""
Admin API routes (analytics and API key management).
"""
from typing import List, Dict, Any, Optional
import logging

from todorama.adapters.http_framework import HTTPFrameworkAdapter
from todorama.dependencies.services import get_db
from todorama.auth.dependencies import optional_api_key, get_current_organization

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
Path = http_adapter.Path
Query = http_adapter.Query
Body = http_adapter.Body
HTTPException = http_adapter.HTTPException
Request = http_adapter.Request
Depends = http_adapter.Depends

# Create router using adapter, expose underlying router for compatibility
router_adapter = http_adapter.create_router(prefix="", tags=["admin"])
router = router_adapter.router

logger = logging.getLogger(__name__)


# ============================================================================
# Analytics Routes
# ============================================================================

@router.get("/analytics/metrics")
async def get_analytics_metrics(
    project_id: Optional[int] = Query(None, description="Filter by project ID")
) -> Dict[str, Any]:
    """Get analytics metrics including completion rates."""
    db = get_db()
    try:
        completion_rates = db.get_completion_rates(project_id=project_id)
        avg_time = db.get_average_time_to_complete(project_id=project_id)
        # Ensure average_hours is not None (convert to 0 if None)
        if avg_time and avg_time.get("average_hours") is None:
            avg_time["average_hours"] = 0.0
        return {
            "completion_rates": completion_rates,
            "average_time_to_complete": avg_time
        }
    except Exception as e:
        logger.error(f"Failed to get analytics metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get analytics metrics: {str(e)}")


@router.get("/analytics/bottlenecks")
async def get_bottlenecks(
    project_id: Optional[int] = Query(None, description="Filter by project ID")
) -> Dict[str, Any]:
    """Get task bottlenecks."""
    db = get_db()
    try:
        bottlenecks = db.get_bottlenecks()
        # Filter by project_id if provided (post-process since method doesn't support it)
        if project_id:
            for key in ["long_running_tasks", "blocking_tasks", "blocked_tasks"]:
                if key in bottlenecks:
                    bottlenecks[key] = [t for t in bottlenecks[key] if t.get("project_id") == project_id]
        return {
            "long_running_tasks": bottlenecks.get("long_running_tasks", []),
            "blocking_tasks": bottlenecks.get("blocking_tasks", []),
            "blocked_tasks": bottlenecks.get("blocked_tasks", [])
        }
    except Exception as e:
        logger.error(f"Failed to get bottlenecks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get bottlenecks: {str(e)}")


@router.get("/analytics/agents")
async def get_agent_analytics(
    project_id: Optional[int] = Query(None, description="Filter by project ID")
) -> Dict[str, Any]:
    """Get agent comparison analytics."""
    db = get_db()
    try:
        agent_data = db.get_agent_comparisons()
        agents = agent_data.get("agents", [])
        # Filter by project_id if provided (post-process)
        if project_id:
            # Note: get_agent_comparisons doesn't support project_id filter directly
            # Would need to filter by tasks in that project, but for now return all
            pass
        return {"agents": agents}
    except Exception as e:
        logger.error(f"Failed to get agent analytics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get agent analytics: {str(e)}")


@router.get("/analytics/visualization")
async def get_visualization_data(
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)")
) -> Dict[str, Any]:
    """Get visualization data for analytics."""
    db = get_db()
    try:
        # Get completion timeline data
        tasks = db.query_tasks(limit=1000)
        if start_date or end_date:
            from datetime import datetime
            filtered_tasks = []
            for task in tasks:
                if task.get("created_at"):
                    try:
                        created = datetime.fromisoformat(task["created_at"].replace('Z', '+00:00'))
                        if start_date:
                            start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                            if created < start:
                                continue
                        if end_date:
                            end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                            if created > end:
                                continue
                        filtered_tasks.append(task)
                    except (ValueError, AttributeError):
                        pass
            tasks = filtered_tasks
        
        # Build status distribution
        status_dist = {}
        for task in tasks:
            status = task.get("task_status", "available")
            status_dist[status] = status_dist.get(status, 0) + 1
        
        return {
            "status_distribution": status_dist,
            "completion_timeline": []  # Could be enhanced with time-series data
        }
    except Exception as e:
        logger.error(f"Failed to get visualization data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get visualization data: {str(e)}")


# ============================================================================
# API Key Management Routes
# ============================================================================

@router.post("/projects/{project_id}/api-keys", status_code=201)
async def create_api_key(
    request: Request,
    project_id: int = Path(..., gt=0),
    key_data: Dict[str, Any] = Body(default_factory=dict),
    auth: Optional[Dict[str, Any]] = Depends(optional_api_key)
) -> Dict[str, Any]:
    """Create a new API key for a project. Requires organization_id."""
    db = get_db()
    try:
        name = key_data.get("name")
        # Name is optional - if not provided, use default
        if name is None:
            name = "Test API Key"
        elif not name or not name.strip():
            # If provided but empty, reject
            raise HTTPException(status_code=422, detail="API key name cannot be empty")
        else:
            name = name.strip()
        
        # Get organization_id from request body, auth context, or project
        organization_id = key_data.get("organization_id")
        
        # If not in body, try to get from authenticated context
        if organization_id is None:
            org_id = await get_current_organization(request, auth, db)
            if org_id:
                organization_id = org_id
        
        # If still None, get from project (database.create_api_key will handle this)
        key_id, api_key = db.create_api_key(project_id, name, organization_id=organization_id)
        
        # Extract key prefix (first 8 characters)
        key_prefix = api_key[:8] if len(api_key) >= 8 else api_key
        return {
            "key_id": key_id,
            "api_key": api_key,
            "key_prefix": key_prefix,
            "name": name,
            "project_id": project_id,
            "organization_id": organization_id
        }
    except HTTPException:
        # Re-raise HTTP exceptions (like 422 for validation)
        raise
    except ValueError as e:
        # Check if it's a "not found" error
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required field: {e}")
    except Exception as e:
        logger.error(f"Failed to create API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create API key: {str(e)}")


@router.get("/api-keys")
async def list_api_keys(
    project_id: Optional[int] = Query(None, description="Filter by project ID")
) -> List[Dict[str, Any]]:
    """List API keys."""
    db = get_db()
    try:
        if project_id:
            keys = db.list_api_keys(project_id)
            # Add key_id field (database returns 'id')
            for key in keys:
                if "id" in key and "key_id" not in key:
                    key["key_id"] = key["id"]
        else:
            # List all keys (would need a method for this)
            keys = []
        return keys
    except Exception as e:
        logger.error(f"Failed to list API keys: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list API keys: {str(e)}")


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: int = Path(..., gt=0)) -> Dict[str, Any]:
    """Revoke an API key."""
    db = get_db()
    try:
        success = db.revoke_api_key(key_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"API key {key_id} not found")
        return {"success": True, "key_id": key_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revoke API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to revoke API key: {str(e)}")


@router.post("/api-keys/{key_id}/rotate", status_code=200)
async def rotate_api_key(key_id: int = Path(..., gt=0)) -> Dict[str, Any]:
    """Rotate an API key."""
    db = get_db()
    try:
        new_key_id, new_api_key = db.rotate_api_key(key_id)
        key_prefix = new_api_key[:8] if len(new_api_key) >= 8 else new_api_key
        return {
            "key_id": new_key_id,
            "api_key": new_api_key,
            "key_prefix": key_prefix
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to rotate API key: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to rotate API key: {str(e)}")
