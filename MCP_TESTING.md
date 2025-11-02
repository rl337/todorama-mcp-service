# MCP Interface Testing - Critical for Data Integrity

## Overview

The MCP (Model Context Protocol) interface is **CRITICAL** for data integrity. Any failures in the MCP interface can result in:
- Loss of task data
- Incorrect task status updates
- Locked tasks that can't be released
- Corruption of task relationships

We encountered several critical issues during initial setup that could have caused data loss:
1. SSE endpoint JSON-RPC format errors (id: null, missing method)
2. Missing POST endpoint handler for /mcp/sse
3. Incorrect tool execution response format
4. Missing initialize and tools/list handlers

## Test Coverage

All MCP tests are in `tests/test_mcp_api.py` and include:

### Protocol-Level Tests (CRITICAL)

1. **`test_mcp_sse_endpoint_connectivity`** - Verifies SSE endpoint returns proper JSON-RPC format
   - Tests Server-Sent Events format
   - Verifies JSON-RPC structure in messages

2. **`test_mcp_post_initialize`** - Tests MCP initialize handshake
   - CRITICAL: Cursor must be able to initialize connection
   - Verifies protocol version, capabilities, server info
   - Must return proper JSON-RPC response with valid id

3. **`test_mcp_post_tools_list`** - Tests tool discovery
   - CRITICAL: Cursor must discover all 5 tools
   - Verifies all tools are present (list_available_tasks, reserve_task, complete_task, create_task, get_agent_performance)
   - Verifies tool schema structure

### Tool Execution Tests (CRITICAL)

4. **`test_mcp_post_tools_call_list_available_tasks`** - Tests listing tasks via MCP
   - CRITICAL: Must be able to read task data
   - Verifies JSON-RPC tools/call format
   - Validates task data is correctly returned

5. **`test_mcp_post_tools_call_reserve_task`** - Tests task locking via MCP
   - CRITICAL: Must prevent concurrent access
   - Verifies task status changes to "in_progress"
   - Validates task is actually locked in database

6. **`test_mcp_post_tools_call_complete_task`** - Tests task completion via MCP
   - CRITICAL: Must persist task completion
   - Verifies task status changes to "complete"
   - Validates completion timestamp is set

7. **`test_mcp_post_tools_call_create_task`** - Tests task creation via MCP
   - CRITICAL: Must persist new tasks correctly
   - Verifies task is created with correct data
   - Validates task appears in database

### End-to-End Workflow Test (CRITICAL)

8. **`test_mcp_full_workflow_integrity`** - Tests complete workflow through MCP
   - CRITICAL: Tests entire lifecycle (initialize → tools/list → create → list → reserve → complete)
   - Verifies data integrity at each step
   - Ensures no data loss or corruption during workflow

### Error Handling Tests

9. **`test_mcp_error_handling_invalid_method`** - Tests invalid method handling
10. **`test_mcp_error_handling_invalid_tool`** - Tests invalid tool name handling
11. **`test_mcp_error_handling_missing_parameters`** - Tests missing parameter handling

## Running Tests

```bash
# Run all MCP tests
python3 -m pytest tests/test_mcp_api.py -v

# Run specific critical tests
python3 -m pytest tests/test_mcp_api.py::test_mcp_full_workflow_integrity -v
python3 -m pytest tests/test_mcp_api.py::test_mcp_post_initialize -v
python3 -m pytest tests/test_mcp_api.py::test_mcp_post_tools_list -v

# Run full test suite
./run_checks.sh
```

## Before Any MCP Changes

**MANDATORY**: Run all MCP tests before committing any changes to:
- `/mcp/sse` endpoint
- `/mcp` POST endpoint
- MCP tool handlers
- JSON-RPC message format
- Tool execution logic

## Known Failure Modes (Prevented by Tests)

1. **JSON-RPC Format Errors**
   - `id: null` instead of proper id value
   - Missing `method` field in notifications
   - Invalid `result` structure
   - **Prevented by**: `test_mcp_post_initialize`, `test_mcp_post_tools_list`

2. **Missing Endpoints**
   - POST handler missing for `/mcp/sse`
   - HTTP 405 errors
   - **Prevented by**: `test_mcp_post_initialize`

3. **Tool Execution Failures**
   - Tools not callable via `tools/call`
   - Incorrect response format
   - Data not persisted
   - **Prevented by**: All `test_mcp_post_tools_call_*` tests

4. **Data Integrity Issues**
   - Task status not updated
   - Tasks created but not in database
   - Locks not working
   - **Prevented by**: `test_mcp_full_workflow_integrity`, all tool execution tests

## Continuous Integration

These tests MUST pass in CI before any MCP-related code can be merged. Any failures indicate potential data loss risks.

