"""
MCP (Model Context Protocol) API routes.
"""
from typing import Optional, List, Dict, Any
from todorama.adapters.http_framework import HTTPFrameworkAdapter
from todorama.mcp_api import MCPTodoAPI

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
Body = http_adapter.Body
HTTPException = http_adapter.HTTPException

# Create router using adapter, expose underlying router for compatibility
router_adapter = http_adapter.create_router(prefix="/mcp", tags=["mcp"])
router = router_adapter.router


@router.post("/create_task")
async def mcp_create_task(
    title: str = Body(..., embed=True),
    task_type: str = Body(..., embed=True),
    task_instruction: str = Body(..., embed=True),
    verification_instruction: str = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    project_id: Optional[int] = Body(None, embed=True),
    parent_task_id: Optional[int] = Body(None, embed=True),
    relationship_type: Optional[str] = Body(None, embed=True),
    notes: Optional[str] = Body(None, embed=True),
    priority: Optional[str] = Body(None, embed=True),
    estimated_hours: Optional[float] = Body(None, embed=True),
    due_date: Optional[str] = Body(None, embed=True)
):
    """MCP: Create a new task."""
    from fastapi import HTTPException
    result = MCPTodoAPI.create_task(
        title, task_type, task_instruction, verification_instruction, agent_id,
        project_id=project_id, parent_task_id=parent_task_id, relationship_type=relationship_type,
        notes=notes, priority=priority, estimated_hours=estimated_hours, due_date=due_date
    )
    if not result.get("success", True):
        error_msg = result.get("error", "Unknown error")
        # Check if it's a circular dependency or validation error
        if "circular" in error_msg.lower() or "dependency" in error_msg.lower():
            raise HTTPException(status_code=400, detail=error_msg)
        elif "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        else:
            raise HTTPException(status_code=400, detail=error_msg)
    return result


@router.post("/get_agent_performance")
async def mcp_get_agent_performance(
    agent_id: str = Body(..., embed=True),
    task_type: Optional[str] = Body(None, embed=True)
):
    """MCP: Get agent performance statistics."""
    stats = MCPTodoAPI.get_agent_performance(agent_id, task_type)
    return stats


@router.post("/unlock_task")
async def mcp_unlock_task(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True)
):
    """MCP: Unlock (release) a reserved task."""
    result = MCPTodoAPI.unlock_task(task_id, agent_id)
    return result


@router.post("/bulk_unlock_tasks")
async def mcp_bulk_unlock_tasks(
    task_ids: List[int] = Body(..., embed=True),
    agent_id: str = Body(..., embed=True)
):
    """MCP: Unlock multiple tasks atomically."""
    result = MCPTodoAPI.bulk_unlock_tasks(task_ids, agent_id)
    return result


@router.post("/query_tasks")
async def mcp_query_tasks(
    project_id: Optional[int] = Body(None, embed=True),
    task_type: Optional[str] = Body(None, embed=True),
    task_status: Optional[str] = Body(None, embed=True),
    agent_id: Optional[str] = Body(None, embed=True),
    priority: Optional[str] = Body(None, embed=True),
    tag_id: Optional[int] = Body(None, embed=True),
    tag_ids: Optional[List[int]] = Body(None, embed=True),
    order_by: Optional[str] = Body(None, embed=True),
    limit: int = Body(100, embed=True)
):
    """MCP: Query tasks by various criteria."""
    tasks = MCPTodoAPI.query_tasks(
        project_id=project_id,
        task_type=task_type,
        task_status=task_status,
        agent_id=agent_id,
        priority=priority,
        tag_id=tag_id,
        tag_ids=tag_ids,
        order_by=order_by,
        limit=limit
    )
    return {"tasks": tasks}


@router.post("/get_task_summary")
async def mcp_get_task_summary(
    project_id: Optional[int] = Body(None, embed=True),
    task_type: Optional[str] = Body(None, embed=True),
    task_status: Optional[str] = Body(None, embed=True),
    assigned_agent: Optional[str] = Body(None, embed=True),
    priority: Optional[str] = Body(None, embed=True),
    limit: int = Body(100, embed=True)
):
    """MCP: Get lightweight task summaries (essential fields only)."""
    result = MCPTodoAPI.get_task_summary(
        project_id=project_id,
        task_type=task_type,
        task_status=task_status,
        assigned_agent=assigned_agent,
        priority=priority,
        limit=limit
    )
    return result


@router.post("/add_task_update")
async def mcp_add_task_update(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
    update_type: str = Body(..., embed=True),
    metadata: Optional[Dict[str, Any]] = Body(None, embed=True)
):
    """MCP: Add a task update (progress, note, blocker, question, finding)."""
    result = MCPTodoAPI.add_task_update(task_id, agent_id, content, update_type, metadata)
    return result


@router.post("/get_task_context")
async def mcp_get_task_context(
    task_id: int = Body(..., embed=True)
):
    """MCP: Get full context for a task (project, ancestry, updates)."""
    result = MCPTodoAPI.get_task_context(task_id)
    return result


@router.post("/search_tasks")
async def mcp_search_tasks(
    query: str = Body(..., embed=True),
    limit: int = Body(100, embed=True)
):
    """MCP: Search tasks using full-text search."""
    tasks = MCPTodoAPI.search_tasks(query, limit)
    return {"tasks": tasks}


@router.post("/link_github_issue")
async def mcp_link_github_issue(
    task_id: int = Body(..., embed=True),
    github_url: str = Body(..., embed=True)
):
    """MCP: Link a GitHub issue to a task."""
    result = MCPTodoAPI.link_github_issue(task_id, github_url)
    return result


@router.post("/link_github_pr")
async def mcp_link_github_pr(
    task_id: int = Body(..., embed=True),
    github_url: str = Body(..., embed=True)
):
    """MCP: Link a GitHub pull request to a task."""
    result = MCPTodoAPI.link_github_pr(task_id, github_url)
    return result


@router.post("/get_github_links")
async def mcp_get_github_links(
    task_id: int = Body(..., embed=True)
):
    """MCP: Get GitHub issue and PR links for a task."""
    result = MCPTodoAPI.get_github_links(task_id)
    return result


@router.post("/create_comment")
async def mcp_create_comment(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
    parent_comment_id: Optional[int] = Body(None, embed=True),
    mentions: Optional[List[str]] = Body(None, embed=True)
):
    """MCP: Create a comment on a task."""
    result = MCPTodoAPI.create_comment(task_id, agent_id, content, parent_comment_id, mentions)
    return result


@router.post("/get_task_comments")
async def mcp_get_task_comments(
    task_id: int = Body(..., embed=True),
    limit: int = Body(100, embed=True)
):
    """MCP: Get all top-level comments for a task."""
    result = MCPTodoAPI.get_task_comments(task_id, limit)
    return result


@router.post("/get_comment_thread")
async def mcp_get_comment_thread(
    comment_id: int = Body(..., embed=True)
):
    """MCP: Get a complete comment thread."""
    result = MCPTodoAPI.get_comment_thread(comment_id)
    return result


@router.post("/update_comment")
async def mcp_update_comment(
    comment_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    content: str = Body(..., embed=True)
):
    """MCP: Update a comment."""
    result = MCPTodoAPI.update_comment(comment_id, agent_id, content)
    return result


@router.post("/delete_comment")
async def mcp_delete_comment(
    comment_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True)
):
    """MCP: Delete a comment."""
    result = MCPTodoAPI.delete_comment(comment_id, agent_id)
    return result


@router.post("/get_tasks_approaching_deadline")
async def mcp_get_tasks_approaching_deadline(
    days_ahead: int = Body(3, embed=True),
    limit: int = Body(100, embed=True)
):
    """MCP: Get tasks with due dates approaching."""
    result = MCPTodoAPI.get_tasks_approaching_deadline(days_ahead, limit)
    return result


@router.post("/create_tag")
async def mcp_create_tag(
    name: str = Body(..., embed=True)
):
    """MCP: Create a new tag."""
    result = MCPTodoAPI.create_tag(name)
    return result


@router.post("/list_tags")
async def mcp_list_tags():
    """MCP: List all available tags."""
    result = MCPTodoAPI.list_tags()
    return result


@router.post("/assign_tag_to_task")
async def mcp_assign_tag_to_task(
    task_id: int = Body(..., embed=True),
    tag_id: int = Body(..., embed=True)
):
    """MCP: Assign a tag to a task."""
    result = MCPTodoAPI.assign_tag_to_task(task_id, tag_id)
    return result


@router.post("/remove_tag_from_task")
async def mcp_remove_tag_from_task(
    task_id: int = Body(..., embed=True),
    tag_id: int = Body(..., embed=True)
):
    """MCP: Remove a tag from a task."""
    result = MCPTodoAPI.remove_tag_from_task(task_id, tag_id)
    return result


@router.post("/get_task_tags")
async def mcp_get_task_tags(
    task_id: int = Body(..., embed=True)
):
    """MCP: Get all tags assigned to a task."""
    result = MCPTodoAPI.get_task_tags(task_id)
    return result


@router.post("/create_template")
async def mcp_create_template(
    name: str = Body(..., embed=True),
    task_type: str = Body(..., embed=True),
    task_instruction: str = Body(..., embed=True),
    verification_instruction: str = Body(..., embed=True),
    description: Optional[str] = Body(None, embed=True),
    priority: Optional[str] = Body(None, embed=True),
    estimated_hours: Optional[float] = Body(None, embed=True),
    notes: Optional[str] = Body(None, embed=True)
):
    """MCP: Create a reusable task template."""
    result = MCPTodoAPI.create_template(
        name, task_type, task_instruction, verification_instruction,
        description=description, priority=priority, estimated_hours=estimated_hours, notes=notes
    )
    return result


@router.post("/list_templates")
async def mcp_list_templates(
    task_type: Optional[str] = Body(None, embed=True)
):
    """MCP: List all available task templates."""
    result = MCPTodoAPI.list_templates(task_type)
    return result


@router.post("/get_template")
async def mcp_get_template(
    template_id: int = Body(..., embed=True)
):
    """MCP: Get detailed information about a specific template."""
    result = MCPTodoAPI.get_template(template_id)
    return result


@router.post("/create_task_from_template")
async def mcp_create_task_from_template(
    template_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    title: Optional[str] = Body(None, embed=True),
    project_id: Optional[int] = Body(None, embed=True),
    notes: Optional[str] = Body(None, embed=True),
    priority: Optional[str] = Body(None, embed=True),
    estimated_hours: Optional[float] = Body(None, embed=True),
    due_date: Optional[str] = Body(None, embed=True)
):
    """MCP: Create a new task using a template."""
    result = MCPTodoAPI.create_task_from_template(
        template_id, agent_id,
        title=title, project_id=project_id, notes=notes,
        priority=priority, estimated_hours=estimated_hours, due_date=due_date
    )
    return result


@router.get("/functions")
async def mcp_functions():
    """List all available MCP functions."""
    from todorama.mcp_api import MCP_FUNCTIONS
    return {"functions": MCP_FUNCTIONS}


@router.post("")
async def mcp_jsonrpc(request: dict = Body(...)):
    """Generic JSON-RPC 2.0 endpoint for MCP."""
    from todorama.mcp_api import handle_jsonrpc_request
    result = handle_jsonrpc_request(request)
    return result


@router.post("/sse")
async def mcp_sse_post(request: dict = Body(...)):
    """Server-Sent Events endpoint for MCP (POST)."""
    from todorama.mcp_api import handle_jsonrpc_request
    # POST requests with JSON-RPC should return JSON, not SSE stream
    result = handle_jsonrpc_request(request)
    return result


@router.get("/sse")
async def mcp_sse_get():
    """Server-Sent Events endpoint for MCP (GET)."""
    from todorama.mcp_api import handle_sse_request
    from todorama.adapters.http_framework import HTTPFrameworkAdapter
    http_adapter = HTTPFrameworkAdapter()
    StreamingResponse = http_adapter.StreamingResponse
    # GET endpoint with no params returns list of available functions
    result = handle_sse_request({"method": "list_functions"})
    return StreamingResponse(content=result, media_type="text/event-stream")


@router.post("/list_available_tasks")
async def mcp_list_available_tasks(
    agent_type: str = Body(..., embed=True),
    project_id: Optional[int] = Body(None, embed=True),
    limit: int = Body(10, embed=True)
):
    """MCP: List available tasks for an agent type."""
    tasks = MCPTodoAPI.list_available_tasks(agent_type, project_id, limit)
    return {"tasks": tasks}


@router.post("/reserve_task")
async def mcp_reserve_task(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True)
):
    """MCP: Reserve (lock) a task for an agent."""
    result = MCPTodoAPI.reserve_task(task_id, agent_id)
    return result


@router.post("/complete_task")
async def mcp_complete_task(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    notes: Optional[str] = Body(None, embed=True),
    actual_hours: Optional[float] = Body(None, embed=True),
    followup_title: Optional[str] = Body(None, embed=True),
    followup_task_type: Optional[str] = Body(None, embed=True),
    followup_instruction: Optional[str] = Body(None, embed=True),
    followup_verification: Optional[str] = Body(None, embed=True)
):
    """MCP: Mark a task as complete."""
    result = MCPTodoAPI.complete_task(
        task_id, agent_id,
        notes=notes, actual_hours=actual_hours,
        followup_title=followup_title, followup_task_type=followup_task_type,
        followup_instruction=followup_instruction, followup_verification=followup_verification
    )
    return result


@router.post("/verify_task")
async def mcp_verify_task(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True)
):
    """MCP: Mark a task as verified."""
    result = MCPTodoAPI.verify_task(task_id, agent_id)
    return result


@router.post("/list_projects")
async def mcp_list_projects():
    """MCP: List all available projects."""
    result = MCPTodoAPI.list_projects()
    return result


@router.post("/get_project")
async def mcp_get_project(
    project_id: int = Body(..., embed=True)
):
    """MCP: Get project details by ID."""
    result = MCPTodoAPI.get_project(project_id)
    return result


@router.post("/get_project_by_name")
async def mcp_get_project_by_name(
    name: str = Body(..., embed=True)
):
    """MCP: Get project by name."""
    result = MCPTodoAPI.get_project_by_name(name)
    return result


@router.post("/create_project")
async def mcp_create_project(
    name: str = Body(..., embed=True),
    local_path: str = Body(..., embed=True),
    origin_url: Optional[str] = Body(None, embed=True),
    description: Optional[str] = Body(None, embed=True)
):
    """MCP: Create a new project."""
    result = MCPTodoAPI.create_project(name, local_path, origin_url, description)
    return result

