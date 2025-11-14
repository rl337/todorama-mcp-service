"""Request handlers for JSON-RPC and SSE requests."""

from typing import Dict, Any

# Import MCPTodoAPI and MCP_FUNCTIONS - use late import to avoid circular dependency
def _get_mcp_api():
    """Lazy import to avoid circular dependency."""
    from todorama.mcp_api import MCPTodoAPI
    return MCPTodoAPI

from todorama.mcp.functions import MCP_FUNCTIONS


def handle_jsonrpc_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle JSON-RPC 2.0 request.
    
    Args:
        request: JSON-RPC request dictionary
        
    Returns:
        JSON-RPC response dictionary
    """
    jsonrpc = request.get("jsonrpc", "2.0")
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})
    
    if method == "initialize":
        return {
            "jsonrpc": jsonrpc,
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {
                    "name": "todo-mcp-service",
                    "version": "1.0.0"
                }
            }
        }
    elif method == "tools/list":
        # Return list of available tools
        tools = []
        for func_def in MCP_FUNCTIONS:
            tools.append({
                "name": func_def["name"],
                "description": func_def["description"],
                "inputSchema": {
                    "type": "object",
                    "properties": func_def.get("parameters", {}),
                    "required": [k for k, v in func_def.get("parameters", {}).items() if v.get("optional") is not True]
                }
            })
        return {
            "jsonrpc": jsonrpc,
            "id": request_id,
            "result": {
                "tools": tools
            }
        }
    elif method == "prompts/list":
        # Return empty list - todo service doesn't expose prompts
        return {
            "jsonrpc": jsonrpc,
            "id": request_id,
            "result": {
                "prompts": []
            }
        }
    elif method == "resources/list":
        # Return empty list - todo service doesn't expose resources
        return {
            "jsonrpc": jsonrpc,
            "id": request_id,
            "result": {
                "resources": []
            }
        }
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        # Map tool names to MCPTodoAPI methods
        MCPTodoAPI = _get_mcp_api()
        tool_map = {
            "list_available_tasks": lambda: MCPTodoAPI.list_available_tasks(
                arguments.get("agent_type", "implementation"),
                arguments.get("project_id"),
                arguments.get("limit", 10)
            ),
            "reserve_task": lambda: MCPTodoAPI.reserve_task(
                arguments.get("task_id"),
                arguments.get("agent_id")
            ),
            "complete_task": lambda: MCPTodoAPI.complete_task(
                arguments.get("task_id"),
                arguments.get("agent_id"),
                arguments.get("notes"),
                arguments.get("actual_hours"),
                arguments.get("followup_title"),
                arguments.get("followup_task_type"),
                arguments.get("followup_instruction"),
                arguments.get("followup_verification")
            ),
            "create_task": lambda: MCPTodoAPI.create_task(
                arguments.get("title"),
                arguments.get("task_type"),
                arguments.get("task_instruction"),
                arguments.get("verification_instruction"),
                arguments.get("agent_id"),
                project_id=arguments.get("project_id"),
                parent_task_id=arguments.get("parent_task_id"),
                relationship_type=arguments.get("relationship_type"),
                notes=arguments.get("notes"),
                priority=arguments.get("priority"),
                estimated_hours=arguments.get("estimated_hours"),
                due_date=arguments.get("due_date")
            ),
            "get_agent_performance": lambda: MCPTodoAPI.get_agent_performance(
                arguments.get("agent_id"),
                arguments.get("task_type")
            ),
            "unlock_task": lambda: MCPTodoAPI.unlock_task(
                arguments.get("task_id"),
                arguments.get("agent_id")
            ),
            "bulk_unlock_tasks": lambda: MCPTodoAPI.bulk_unlock_tasks(
                arguments.get("task_ids"),
                arguments.get("agent_id")
            ),
            "query_tasks": lambda: {"tasks": MCPTodoAPI.query_tasks(
                project_id=arguments.get("project_id"),
                task_type=arguments.get("task_type"),
                task_status=arguments.get("task_status"),
                agent_id=arguments.get("agent_id"),
                priority=arguments.get("priority"),
                tag_id=arguments.get("tag_id"),
                tag_ids=arguments.get("tag_ids"),
                order_by=arguments.get("order_by"),
                limit=arguments.get("limit", 100)
            )},
            "add_task_update": lambda: MCPTodoAPI.add_task_update(
                arguments.get("task_id"),
                arguments.get("agent_id"),
                arguments.get("content"),
                arguments.get("update_type"),
                arguments.get("metadata")
            ),
            "get_task_context": lambda: MCPTodoAPI.get_task_context(
                arguments.get("task_id")
            ),
            "search_tasks": lambda: {"tasks": MCPTodoAPI.search_tasks(
                arguments.get("query", ""),
                arguments.get("limit", 100)
            )},
            "verify_task": lambda: MCPTodoAPI.verify_task(
                arguments.get("task_id"),
                arguments.get("agent_id"),
                arguments.get("notes")
            ),
            "create_tag": lambda: MCPTodoAPI.create_tag(
                arguments.get("name")
            ),
            "query_stale_tasks": lambda: MCPTodoAPI.query_stale_tasks(
                arguments.get("hours")
            ),
            "get_task_statistics": lambda: MCPTodoAPI.get_task_statistics(
                project_id=arguments.get("project_id"),
                task_type=arguments.get("task_type"),
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date")
            ),
            "get_recent_completions": lambda: MCPTodoAPI.get_recent_completions(
                limit=arguments.get("limit", 10),
                project_id=arguments.get("project_id"),
                hours=arguments.get("hours")
            ),
            "get_task_summary": lambda: MCPTodoAPI.get_task_summary(
                project_id=arguments.get("project_id"),
                task_type=arguments.get("task_type"),
                task_status=arguments.get("task_status"),
                assigned_agent=arguments.get("assigned_agent"),
                priority=arguments.get("priority"),
                limit=arguments.get("limit", 100)
            )
        }
        
        if tool_name not in tool_map:
            return {
                "jsonrpc": jsonrpc,
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {tool_name}"
                }
            }
        
        try:
            result = tool_map[tool_name]()
            import json
            # Ensure result is a dict (some methods return lists)
            if not isinstance(result, dict):
                result = {"result": result}
            return {
                "jsonrpc": jsonrpc,
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result)
                        }
                    ]
                }
            }
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            return {
                "jsonrpc": jsonrpc,
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}",
                    "data": error_details
                }
            }
    else:
        return {
            "jsonrpc": jsonrpc,
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }


def handle_sse_request(request: Dict[str, Any]) -> str:
    """
    Handle SSE request (returns JSON-RPC response as SSE format string).
    
    Args:
        request: Request dictionary (may contain method, params, etc.)
        
    Returns:
        SSE-formatted string with JSON-RPC response
    """
    # For POST requests with JSON-RPC, process as JSON-RPC
    if "jsonrpc" in request or "method" in request:
        result = handle_jsonrpc_request(request)
        import json
        return f"data: {json.dumps(result)}\n\n"
    else:
        # For GET requests or simple method requests
        method = request.get("method", "list_functions")
        if method == "list_functions":
            import json
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "result": {
                    "functions": [f["name"] for f in MCP_FUNCTIONS]
                }
            }
            return f"data: {json.dumps(response)}\n\n"
        else:
            import json
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
            return f"data: {json.dumps(response)}\n\n"
