"""
Tests for MCP API functionality.
"""
import pytest
import os
import tempfile
import shutil
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main import app
from database import TodoDatabase
from backup import BackupManager
from mcp_api import MCPTodoAPI


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    backups_dir = os.path.join(temp_dir, "backups")
    
    db = TodoDatabase(db_path)
    backup_manager = BackupManager(db_path, backups_dir)
    
    import main
    main.db = db
    main.backup_manager = backup_manager
    
    yield db, db_path, backups_dir
    
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    return TestClient(app)


def test_mcp_list_available_tasks(client):
    """Test MCP list available tasks."""
    # Create tasks of different types
    client.post("/tasks", json={
        "title": "Abstract Task",
        "task_type": "abstract",
        "task_instruction": "Break down",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    client.post("/tasks", json={
        "title": "Concrete Task",
        "task_type": "concrete",
        "task_instruction": "Do it",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    
    # Test breakdown agent
    response = client.post("/mcp/list_available_tasks", json={
        "agent_type": "breakdown",
        "limit": 10
    })
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert any(t["task_type"] == "abstract" for t in tasks)
    
    # Test implementation agent
    response = client.post("/mcp/list_available_tasks", json={
        "agent_type": "implementation",
        "limit": 10
    })
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert any(t["task_type"] == "concrete" for t in tasks)


def test_mcp_reserve_task(client):
    """Test MCP reserve task."""
    # Create task
    create_response = client.post("/tasks", json={
        "title": "Reserve Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Reserve task
    reserve_response = client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    assert reserve_response.status_code == 200
    result = reserve_response.json()
    assert result["success"] is True
    assert result["task"]["task_status"] == "in_progress"
    assert result["task"]["assigned_agent"] == "agent-1"
    
    # Try to reserve again (should fail)
    reserve_response2 = client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert reserve_response2.status_code == 200
    result2 = reserve_response2.json()
    assert result2["success"] is False


def test_mcp_complete_task_with_followup(client):
    """Test MCP complete task with followup."""
    # Create and reserve task
    create_response = client.post("/tasks", json={
        "title": "Complete Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    
    # Complete with followup
    complete_response = client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "agent-1",
        "notes": "Done!",
        "followup_title": "Followup Task",
        "followup_task_type": "concrete",
        "followup_instruction": "Do followup",
        "followup_verification": "Verify followup"
    })
    assert complete_response.status_code == 200
    result = complete_response.json()
    assert result["success"] is True
    assert result["completed"] is True
    assert "followup_task_id" in result
    
    # Verify followup was created
    followup_id = result["followup_task_id"]
    followup_response = client.get(f"/tasks/{followup_id}")
    assert followup_response.status_code == 200
    followup = followup_response.json()
    assert followup["title"] == "Followup Task"


def test_mcp_create_task(client):
    """Test MCP create task."""
    response = client.post("/mcp/create_task", json={
        "title": "MCP Created Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "task_id" in result
    
    # Verify task was created
    task_id = result["task_id"]
    get_response = client.get(f"/tasks/{task_id}")
    assert get_response.status_code == 200
    task = get_response.json()
    assert task["title"] == "MCP Created Task"


def test_mcp_create_task_with_due_date(client):
    """Test MCP create task with due date."""
    from datetime import datetime, timedelta
    
    due_date = (datetime.now() + timedelta(days=7)).isoformat()
    response = client.post("/mcp/create_task", json={
        "title": "MCP Task with Due Date",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent",
        "due_date": due_date
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "task_id" in result
    
    # Verify task was created with due date
    task_id = result["task_id"]
    get_response = client.get(f"/tasks/{task_id}")
    assert get_response.status_code == 200
    task = get_response.json()
    assert task["title"] == "MCP Task with Due Date"
    assert task["due_date"] is not None
    # due_date should be stored and returned
    assert task["due_date"] == due_date or task["due_date"].startswith(due_date[:10])  # Allow for timezone differences


def test_mcp_post_tools_call_create_task_with_due_date(client):
    """Test MCP tools/call for create_task with due_date - CRITICAL for MCP integration."""
    from datetime import datetime, timedelta
    
    due_date = (datetime.now() + timedelta(days=7)).isoformat()
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "create_task",
            "arguments": {
                "title": "MCP Created Task with Due Date",
                "task_type": "concrete",
                "task_instruction": "Do something",
                "verification_instruction": "Verify it",
                "agent_id": "mcp-test-agent",
                "due_date": due_date
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 7
    
    # Parse and verify
    import json
    content_text = result["result"]["content"][0]["text"]
    create_result = json.loads(content_text)
    assert create_result["success"] is True
    assert "task_id" in create_result
    
    # Verify task exists in database with due date
    task_id = create_result["task_id"]
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["title"] == "MCP Created Task with Due Date"
    assert task["due_date"] is not None
    assert task["due_date"] == due_date or task["due_date"].startswith(due_date[:10])


def test_mcp_get_agent_performance(client):
    """Test MCP get agent performance."""
    # Create and complete some tasks
    for i in range(3):
        create_response = client.post("/tasks", json={
            "title": f"Task {i}",
            "task_type": "concrete",
            "task_instruction": "Do it",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
        task_id = create_response.json()["id"]
        client.post("/tasks/{task_id}/lock", json={"agent_id": "test-agent"})
        client.post(f"/tasks/{task_id}/complete", json={"agent_id": "test-agent"})
    
    # Get performance
    response = client.post("/mcp/get_agent_performance", json={
        "agent_id": "test-agent"
    })
    assert response.status_code == 200
    stats = response.json()
    assert stats["agent_id"] == "test-agent"
    assert stats["tasks_completed"] >= 3


# ============================================================================
# MCP Protocol Tests - Critical for data integrity
# ============================================================================

def test_mcp_sse_endpoint_connectivity(client):
    """Test MCP SSE endpoint returns proper JSON-RPC format."""
    response = client.get("/mcp/sse")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    
    # Read first few lines
    content = response.text
    assert "event: message" in content
    assert "jsonrpc" in content
    assert "2.0" in content


def test_mcp_post_initialize(client):
    """Test MCP POST initialize request - CRITICAL for connection."""
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    })
    assert response.status_code == 200
    result = response.json()
    
    # Verify JSON-RPC structure
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 1
    assert "result" in result
    
    # Verify initialize result structure
    init_result = result["result"]
    assert "protocolVersion" in init_result
    assert "capabilities" in init_result
    assert "serverInfo" in init_result
    assert init_result["protocolVersion"] == "2024-11-05"
    assert init_result["serverInfo"]["name"] == "todo-mcp-service"


def test_mcp_post_tools_list(client):
    """Test MCP POST tools/list request - CRITICAL for tool discovery."""
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    })
    assert response.status_code == 200
    result = response.json()
    
    # Verify JSON-RPC structure
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 2
    assert "result" in result
    assert "tools" in result["result"]
    
    # Verify all tools are present (should include search_tasks and verify_task)
    tools = result["result"]["tools"]
    tool_names = [tool["name"] for tool in tools]
    assert "list_available_tasks" in tool_names
    assert "reserve_task" in tool_names
    assert "complete_task" in tool_names
    assert "create_task" in tool_names
    assert "get_agent_performance" in tool_names
    assert "unlock_task" in tool_names
    assert "query_tasks" in tool_names
    assert "add_task_update" in tool_names
    assert "get_task_context" in tool_names
    assert "search_tasks" in tool_names
    assert "verify_task" in tool_names, "verify_task should be exposed as MCP tool"
    assert len(tools) >= 11  # At least 11 tools (verify_task added)
    
    # Verify tool structure
    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


def test_mcp_post_tools_call_list_available_tasks(client):
    """Test MCP tools/call for list_available_tasks - CRITICAL for data access."""
    # Create test task
    create_response = client.post("/tasks", json={
        "title": "MCP Test Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Call via MCP protocol
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "list_available_tasks",
            "arguments": {
                "agent_type": "implementation",
                "limit": 10
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 3
    assert "result" in result
    assert "content" in result["result"]
    
    # Parse the content (JSON string)
    import json
    content_text = result["result"]["content"][0]["text"]
    tasks = json.loads(content_text)
    assert isinstance(tasks, list)
    assert len(tasks) > 0
    assert any(t["id"] == task_id for t in tasks)


def test_mcp_post_tools_call_reserve_task(client):
    """Test MCP tools/call for reserve_task - CRITICAL for task locking."""
    # Create test task
    create_response = client.post("/tasks", json={
        "title": "Reserve MCP Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Reserve via MCP protocol
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "reserve_task",
            "arguments": {
                "task_id": task_id,
                "agent_id": "mcp-test-agent"
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 4
    assert "result" in result
    
    # Parse and verify
    import json
    content_text = result["result"]["content"][0]["text"]
    reserve_result = json.loads(content_text)
    assert reserve_result["success"] is True
    assert reserve_result["task"]["task_status"] == "in_progress"
    assert reserve_result["task"]["assigned_agent"] == "mcp-test-agent"
    
    # Verify task is actually locked in database
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["task_status"] == "in_progress"
    assert task["assigned_agent"] == "mcp-test-agent"


def test_mcp_post_tools_call_complete_task(client):
    """Test MCP tools/call for complete_task - CRITICAL for task completion."""
    # Create and reserve task
    create_response = client.post("/tasks", json={
        "title": "Complete MCP Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "mcp-test-agent"
    })
    
    # Complete via MCP protocol
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "complete_task",
            "arguments": {
                "task_id": task_id,
                "agent_id": "mcp-test-agent",
                "notes": "Completed via MCP"
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 5
    
    # Parse and verify
    import json
    content_text = result["result"]["content"][0]["text"]
    complete_result = json.loads(content_text)
    assert complete_result["success"] is True
    assert complete_result["completed"] is True
    
    # Verify task is actually completed in database
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["task_status"] == "complete"
    assert task["completed_at"] is not None


def test_mcp_post_tools_call_verify_task(client):
    """Test MCP tools/call for verify_task - CRITICAL for task verification."""
    # Create, reserve, and complete task
    create_response = client.post("/tasks", json={
        "title": "Verify MCP Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "mcp-test-agent"
    })
    
    client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "mcp-test-agent",
        "notes": "Completed via MCP"
    })
    
    # Verify task status is complete but unverified
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["task_status"] == "complete"
    assert task["verification_status"] == "unverified"
    
    # Verify via MCP protocol
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "verify_task",
            "arguments": {
                "task_id": task_id,
                "agent_id": "mcp-test-agent"
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 6
    
    # Parse and verify
    import json
    content_text = result["result"]["content"][0]["text"]
    verify_result = json.loads(content_text)
    assert verify_result["success"] is True
    assert verify_result["task_id"] == task_id
    
    # Verify task is actually verified in database
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["verification_status"] == "verified"


def test_mcp_post_tools_call_create_task(client):
    """Test MCP tools/call for create_task - CRITICAL for task creation."""
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "create_task",
            "arguments": {
                "title": "MCP Created Task",
                "task_type": "concrete",
                "task_instruction": "Do something",
                "verification_instruction": "Verify it",
                "agent_id": "mcp-test-agent"
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 6
    
    # Parse and verify
    import json
    content_text = result["result"]["content"][0]["text"]
    create_result = json.loads(content_text)
    assert create_result["success"] is True
    assert "task_id" in create_result
    
    # Verify task exists in database
    task_id = create_result["task_id"]
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["title"] == "MCP Created Task"


def test_mcp_full_workflow_integrity(client):
    """Test complete workflow through MCP - CRITICAL for data integrity."""
    # 1. Initialize
    init_response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 10,
        "method": "initialize",
        "params": {}
    })
    assert init_response.status_code == 200
    
    # 2. Get tools list
    tools_response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/list",
        "params": {}
    })
    assert tools_response.status_code == 200
    tools = tools_response.json()["result"]["tools"]
    assert len(tools) >= 10  # At least 10 tools (includes search_tasks)
    
    # 3. Create task via MCP
    import json
    create_response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {
            "name": "create_task",
            "arguments": {
                "title": "Workflow Test Task",
                "task_type": "concrete",
                "task_instruction": "Complete workflow",
                "verification_instruction": "Verify workflow",
                "agent_id": "workflow-agent"
            }
        }
    })
    create_result = json.loads(create_response.json()["result"]["content"][0]["text"])
    task_id = create_result["task_id"]
    
    # 4. List tasks via MCP
    list_response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 13,
        "method": "tools/call",
        "params": {
            "name": "list_available_tasks",
            "arguments": {
                "agent_type": "implementation",
                "limit": 10
            }
        }
    })
    list_result = json.loads(list_response.json()["result"]["content"][0]["text"])
    assert any(t["id"] == task_id for t in list_result)
    
    # 5. Reserve task via MCP
    reserve_response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 14,
        "method": "tools/call",
        "params": {
            "name": "reserve_task",
            "arguments": {
                "task_id": task_id,
                "agent_id": "workflow-agent"
            }
        }
    })
    reserve_result = json.loads(reserve_response.json()["result"]["content"][0]["text"])
    assert reserve_result["success"] is True
    
    # 6. Complete task via MCP
    complete_response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 15,
        "method": "tools/call",
        "params": {
            "name": "complete_task",
            "arguments": {
                "task_id": task_id,
                "agent_id": "workflow-agent",
                "notes": "Workflow completed successfully"
            }
        }
    })
    complete_result = json.loads(complete_response.json()["result"]["content"][0]["text"])
    assert complete_result["success"] is True
    assert complete_result["completed"] is True
    
    # 7. Verify final state in database
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["task_status"] == "complete"
    assert task["completed_at"] is not None
    assert task["notes"] == "Workflow completed successfully"


def test_mcp_error_handling_invalid_method(client):
    """Test MCP error handling for invalid methods."""
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 20,
        "method": "invalid_method",
        "params": {}
    })
    assert response.status_code == 200
    result = response.json()
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 20
    assert "error" in result
    assert result["error"]["code"] == -32601  # Method not found


def test_mcp_error_handling_invalid_tool(client):
    """Test MCP error handling for invalid tool names."""
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {
            "name": "invalid_tool",
            "arguments": {}
        }
    })
    assert response.status_code == 200
    result = response.json()
    assert "error" in result
    assert result["error"]["code"] == -32601


def test_mcp_error_handling_missing_parameters(client):
    """Test MCP error handling for missing required parameters."""
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {
            "name": "reserve_task",
            "arguments": {
                "task_id": 999  # Missing agent_id
            }
        }
    })
    assert response.status_code == 200
    # Should handle gracefully
    result = response.json()
    assert "error" in result or "result" in result


def test_mcp_error_handling_task_not_found(client):
    """Test MCP error handling when task not found."""
    response = client.post("/mcp/reserve_task", json={
        "task_id": 99999,
        "agent_id": "agent-1"
    })
    assert response.status_code == 200
    result = response.json()
    assert "success" in result
    assert result["success"] is False
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_mcp_error_handling_reserve_already_locked(client):
    """Test MCP error handling when reserving already locked task."""
    # Create and reserve task
    create_response = client.post("/tasks", json={
        "title": "Already Locked",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    
    # Try to reserve again
    response = client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert response.status_code == 200
    result = response.json()
    assert "success" in result
    assert result["success"] is False
    assert "error" in result
    assert "cannot be locked" in result["error"].lower() or "not available" in result["error"].lower()


def test_mcp_error_handling_complete_wrong_agent(client):
    """Test MCP error handling when wrong agent tries to complete task."""
    # Create and reserve task
    create_response = client.post("/tasks", json={
        "title": "Wrong Agent Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    
    # Try to complete with wrong agent
    response = client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert response.status_code == 200
    result = response.json()
    assert "success" in result
    assert result["success"] is False
    assert "error" in result
    assert "assigned" in result["error"].lower() or "agent" in result["error"].lower()


def test_mcp_error_handling_empty_update_content(client):
    """Test MCP error handling for empty update content."""
    # Create task
    create_response = client.post("/tasks", json={
        "title": "Update Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Try to add empty update
    response = client.post("/mcp/add_task_update", json={
        "task_id": task_id,
        "agent_id": "test-agent",
        "content": "",
        "update_type": "progress"
    })
    assert response.status_code == 200
    result = response.json()
    assert "success" in result
    assert result["success"] is False
    assert "error" in result
    assert "cannot be empty" in result["error"].lower()


def test_mcp_error_handling_unlock_wrong_agent(client):
    """Test MCP error handling when wrong agent tries to unlock task."""
    # Create and reserve task
    create_response = client.post("/tasks", json={
        "title": "Unlock Wrong Agent",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    
    # Try to unlock with wrong agent
    response = client.post("/mcp/unlock_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert response.status_code == 200
    result = response.json()
    assert "success" in result
    assert result["success"] is False
    assert "error" in result
    assert "assigned" in result["error"].lower() or "agent" in result["error"].lower()


def test_mcp_unlock_task(client):
    """Test MCP unlock_task function."""
    # Create and reserve task
    create_response = client.post("/tasks", json={
        "title": "Unlock Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "test-agent"
    })
    
    # Unlock via MCP
    response = client.post("/mcp/unlock_task", json={
        "task_id": task_id,
        "agent_id": "test-agent"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    
    # Verify task is unlocked
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["task_status"] == "available"
    assert task["assigned_agent"] is None


def test_mcp_query_tasks(client):
    """Test MCP query_tasks function."""
    # Create tasks with different types and statuses
    client.post("/tasks", json={
        "title": "Concrete Task 1",
        "task_type": "concrete",
        "task_instruction": "Do it",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = client.post("/tasks", json={
        "title": "Abstract Task",
        "task_type": "abstract",
        "task_instruction": "Break down",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    }).json()["id"]
    
    # Query by task_type
    response = client.post("/mcp/query_tasks", json={
        "task_type": "concrete",
        "limit": 10
    })
    assert response.status_code == 200
    result = response.json()
    assert "tasks" in result
    tasks = result["tasks"]
    assert all(t["task_type"] == "concrete" for t in tasks)
    
    # Query by task_status
    response = client.post("/mcp/query_tasks", json={
        "task_status": "available",
        "limit": 10
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert all(t["task_status"] == "available" for t in tasks)


def test_mcp_add_task_update(client):
    """Test MCP add_task_update function."""
    # Create task
    create_response = client.post("/tasks", json={
        "title": "Update Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Add progress update
    response = client.post("/mcp/add_task_update", json={
        "task_id": task_id,
        "agent_id": "test-agent",
        "content": "Making progress on this task",
        "update_type": "progress"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "update_id" in result
    
    # Add blocker update
    response = client.post("/mcp/add_task_update", json={
        "task_id": task_id,
        "agent_id": "test-agent",
        "content": "Blocked by dependency",
        "update_type": "blocker"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True


def test_mcp_get_task_context(client):
    """Test MCP get_task_context function."""
    # Create project
    project_response = client.post("/projects", json={
        "name": "Test Project",
        "local_path": "/test/path",
        "origin_url": "https://test.com"
    })
    project_id = project_response.json()["id"]
    
    # Create parent task
    parent_response = client.post("/tasks", json={
        "title": "Parent Task",
        "task_type": "abstract",
        "task_instruction": "Parent",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    parent_id = parent_response.json()["id"]
    
    # Create child task
    child_response = client.post("/tasks", json={
        "title": "Child Task",
        "task_type": "concrete",
        "task_instruction": "Child",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    child_id = child_response.json()["id"]
    
    # Create relationship
    client.post(f"/tasks/{parent_id}/relationships", json={
        "child_task_id": child_id,
        "relationship_type": "subtask",
        "agent_id": "test-agent"
    })
    
    # Add update to child
    client.post("/mcp/add_task_update", json={
        "task_id": child_id,
        "agent_id": "test-agent",
        "content": "Working on it",
        "update_type": "progress"
    })
    
    # Get context
    response = client.post("/mcp/get_task_context", json={
        "task_id": child_id
    })
    assert response.status_code == 200
    result = response.json()
    assert "task" in result
    assert "project" in result
    assert "updates" in result
    assert "ancestry" in result
    assert result["task"]["id"] == child_id
    assert result["project"]["id"] == project_id
    assert len(result["updates"]) > 0
    assert len(result["ancestry"]) > 0  # Should include parent


def test_mcp_get_task_context_missing_task(client):
    """Test MCP get_task_context with missing task ID."""
    response = client.post("/mcp/get_task_context", json={
        "task_id": 99999  # Non-existent task
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is False
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_mcp_get_tasks_approaching_deadline(client):
    """Test MCP get_tasks_approaching_deadline function."""
    from datetime import datetime, timedelta
    
    # Create task due in 2 days
    soon_date = (datetime.now() + timedelta(days=2)).isoformat()
    create_response = client.post("/tasks", json={
        "title": "Soon Task",
        "task_type": "concrete",
        "task_instruction": "Due soon",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "due_date": soon_date
    })
    soon_task_id = create_response.json()["id"]
    
    # Create task due in 5 days
    later_date = (datetime.now() + timedelta(days=5)).isoformat()
    create_response = client.post("/tasks", json={
        "title": "Later Task",
        "task_type": "concrete",
        "task_instruction": "Due later",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "due_date": later_date
    })
    
    # Query tasks approaching deadline (3 days)
    response = client.post("/mcp/get_tasks_approaching_deadline", json={
        "days_ahead": 3
    })
    assert response.status_code == 200
    result = response.json()
    assert "success" in result
    assert result["success"] is True
    assert "tasks" in result
    approaching_ids = [t["id"] for t in result["tasks"]]
    assert soon_task_id in approaching_ids


# ============================================================================
# MCP Search tests
# ============================================================================

def test_mcp_search_tasks_by_title(client):
    """Test MCP search_tasks by title."""
    # Create tasks
    create_response1 = client.post("/tasks", json={
        "title": "Implement user authentication",
        "task_type": "concrete",
        "task_instruction": "Add login functionality",
        "verification_instruction": "Verify login works",
        "agent_id": "test-agent"
    })
    task1_id = create_response1.json()["id"]
    
    create_response2 = client.post("/tasks", json={
        "title": "Add database migrations",
        "task_type": "concrete",
        "task_instruction": "Create migration system",
        "verification_instruction": "Verify migrations",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json()["id"]
    
    # Search for "authentication"
    response = client.post("/mcp/search_tasks", json={
        "query": "authentication",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    assert "tasks" in result
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id
    
    # Search for "database"
    response = client.post("/mcp/search_tasks", json={
        "query": "database",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task2_id


def test_mcp_search_tasks_by_instruction(client):
    """Test MCP search_tasks by task_instruction."""
    create_response1 = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Implement REST API endpoints",
        "verification_instruction": "Test endpoints",
        "agent_id": "test-agent"
    })
    task1_id = create_response1.json()["id"]
    
    create_response2 = client.post("/tasks", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Create database schema",
        "verification_instruction": "Verify schema",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json()["id"]
    
    # Search for "REST"
    response = client.post("/mcp/search_tasks", json={
        "query": "REST",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id
    
    # Search for "schema"
    response = client.post("/mcp/search_tasks", json={
        "query": "schema",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task2_id


def test_mcp_search_tasks_by_notes(client):
    """Test MCP search_tasks by notes."""
    create_response1 = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "notes": "High priority bug fix needed"
    })
    task1_id = create_response1.json()["id"]
    
    create_response2 = client.post("/tasks", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Do something else",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "notes": "Performance optimization"
    })
    task2_id = create_response2.json()["id"]
    
    # Search for "bug"
    response = client.post("/mcp/search_tasks", json={
        "query": "bug",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id
    
    # Search for "performance"
    response = client.post("/mcp/search_tasks", json={
        "query": "performance",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task2_id


def test_mcp_search_tasks_with_limit(client):
    """Test that MCP search_tasks respects limit parameter."""
    # Create multiple tasks
    for i in range(10):
        client.post("/tasks", json={
            "title": f"Searchable Task {i}",
            "task_type": "concrete",
            "task_instruction": "Searchable content",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
    
    # Search with limit
    response = client.post("/mcp/search_tasks", json={
        "query": "Searchable",
        "limit": 5
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 5


def test_mcp_search_tasks_ranks_by_relevance(client):
    """Test that MCP search_tasks results are ranked by relevance."""
    create_response1 = client.post("/tasks", json={
        "title": "API endpoint",
        "task_type": "concrete",
        "task_instruction": "Create API endpoint for user management",
        "verification_instruction": "Verify API",
        "agent_id": "test-agent",
        "notes": "API endpoint implementation"
    })
    task1_id = create_response1.json()["id"]
    
    create_response2 = client.post("/tasks", json={
        "title": "Database schema",
        "task_type": "concrete",
        "task_instruction": "Design database schema",
        "verification_instruction": "Verify schema",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json()["id"]
    
    create_response3 = client.post("/tasks", json={
        "title": "API documentation",
        "task_type": "concrete",
        "task_instruction": "Write API documentation",
        "verification_instruction": "Verify docs",
        "agent_id": "test-agent"
    })
    task3_id = create_response3.json()["id"]
    
    # Search for "API" - task1 should rank highest (multiple mentions)
    response = client.post("/mcp/search_tasks", json={
        "query": "API",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) >= 2  # Should find task1 and task3
    # First result should be task1 (most relevant)
    assert tasks[0]["id"] == task1_id


def test_mcp_search_tasks_with_special_characters(client):
    """Test that MCP search_tasks handles special characters gracefully."""
    create_response = client.post("/tasks", json={
        "title": "Task with special chars: test@example.com",
        "task_type": "concrete",
        "task_instruction": "Handle special characters",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Search should handle special characters
    response = client.post("/mcp/search_tasks", json={
        "query": "test@example",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task_id


def test_mcp_search_tasks_multiple_keywords(client):
    """Test MCP search_tasks with multiple keywords."""
    create_response1 = client.post("/tasks", json={
        "title": "Authentication system",
        "task_type": "concrete",
        "task_instruction": "Implement user authentication and authorization",
        "verification_instruction": "Verify auth works",
        "agent_id": "test-agent"
    })
    task1_id = create_response1.json()["id"]
    
    create_response2 = client.post("/tasks", json={
        "title": "Database backup",
        "task_type": "concrete",
        "task_instruction": "Create backup system",
        "verification_instruction": "Verify backup",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json()["id"]
    
    # Search for multiple keywords (FTS5 supports space-separated terms)
    response = client.post("/mcp/search_tasks", json={
        "query": "authentication user",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    # Should find task1 which contains both terms
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids


def test_mcp_post_tools_call_search_tasks(client):
    """Test MCP tools/call for search_tasks - CRITICAL for MCP integration."""
    # Create test task
    create_response = client.post("/tasks", json={
        "title": "Search MCP Test Task",
        "task_type": "concrete",
        "task_instruction": "Test search functionality",
        "verification_instruction": "Verify search",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Call via MCP protocol
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 25,
        "method": "tools/call",
        "params": {
            "name": "search_tasks",
            "arguments": {
                "query": "Search MCP",
                "limit": 10
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 25
    assert "result" in result
    assert "content" in result["result"]
    
    # Parse the content (JSON string)
    import json
    content_text = result["result"]["content"][0]["text"]
    tasks = json.loads(content_text)
    assert isinstance(tasks, list)
    assert len(tasks) > 0
    assert any(t["id"] == task_id for t in tasks)


# ============================================================================
# MCP Tag tests
# ============================================================================

def test_mcp_create_tag(client):
    """Test MCP create_tag function."""
    response = client.post("/mcp/create_tag", json={"name": "bug"})
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "tag_id" in result
    assert result["tag"]["name"] == "bug"


def test_mcp_list_tags(client):
    """Test MCP list_tags function."""
    # Create some tags
    client.post("/mcp/create_tag", json={"name": "feature"})
    client.post("/mcp/create_tag", json={"name": "urgent"})
    
    # List tags
    response = client.post("/mcp/list_tags")
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "tags" in result
    tag_names = [t["name"] for t in result["tags"]]
    assert "feature" in tag_names
    assert "urgent" in tag_names


def test_mcp_assign_tag_to_task(client):
    """Test MCP assign_tag_to_task function."""
    # Create task and tag
    create_response = client.post("/tasks", json={
        "title": "Tag Test Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    tag_response = client.post("/mcp/create_tag", json={"name": "test-tag"})
    tag_id = tag_response.json()["tag_id"]
    
    # Assign tag
    response = client.post("/mcp/assign_tag_to_task", json={
        "task_id": task_id,
        "tag_id": tag_id
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["task_id"] == task_id
    assert result["tag_id"] == tag_id
    
    # Verify tag is assigned
    get_response = client.post("/mcp/get_task_tags", json={"task_id": task_id})
    tags = get_response.json()["tags"]
    assert len(tags) == 1
    assert tags[0]["id"] == tag_id


def test_mcp_get_task_tags(client):
    """Test MCP get_task_tags function."""
    # Create task and tags
    create_response = client.post("/tasks", json={
        "title": "Multi-Tag Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    tag1_response = client.post("/mcp/create_tag", json={"name": "tag1"})
    tag1_id = tag1_response.json()["tag_id"]
    tag2_response = client.post("/mcp/create_tag", json={"name": "tag2"})
    tag2_id = tag2_response.json()["tag_id"]
    
    # Assign multiple tags
    client.post("/mcp/assign_tag_to_task", json={"task_id": task_id, "tag_id": tag1_id})
    client.post("/mcp/assign_tag_to_task", json={"task_id": task_id, "tag_id": tag2_id})
    
    # Get task tags
    response = client.post("/mcp/get_task_tags", json={"task_id": task_id})
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert len(result["tags"]) == 2
    tag_ids = {t["id"] for t in result["tags"]}
    assert tag_ids == {tag1_id, tag2_id}


def test_mcp_remove_tag_from_task(client):
    """Test MCP remove_tag_from_task function."""
    # Create task and tag
    create_response = client.post("/tasks", json={
        "title": "Remove Tag Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    tag_response = client.post("/mcp/create_tag", json={"name": "to-remove"})
    tag_id = tag_response.json()["tag_id"]
    
    # Assign tag
    client.post("/mcp/assign_tag_to_task", json={"task_id": task_id, "tag_id": tag_id})
    
    # Remove tag
    response = client.post("/mcp/remove_tag_from_task", json={
        "task_id": task_id,
        "tag_id": tag_id
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    
    # Verify tag is removed
    get_response = client.post("/mcp/get_task_tags", json={"task_id": task_id})
    tags = get_response.json()["tags"]
    assert len(tags) == 0


def test_mcp_query_tasks_by_tag(client):
    """Test querying tasks by tag via MCP."""
    # Create tasks
    task1_response = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do 1",
        "verification_instruction": "Verify 1",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    
    task2_response = client.post("/tasks", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Do 2",
        "verification_instruction": "Verify 2",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json()["id"]
    
    # Create tag
    tag_response = client.post("/mcp/create_tag", json={"name": "query-tag"})
    tag_id = tag_response.json()["tag_id"]
    
    # Assign tag to task1 only
    client.post("/mcp/assign_tag_to_task", json={"task_id": task1_id, "tag_id": tag_id})
    
    # Query by tag
    response = client.post("/mcp/query_tasks", json={"tag_id": tag_id})
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    task_ids = {t["id"] for t in tasks}
    assert task1_id in task_ids
    assert task2_id not in task_ids


def test_mcp_query_tasks_by_multiple_tags(client):
    """Test querying tasks by multiple tags via MCP."""
    # Create tasks
    task1_response = client.post("/tasks", json={
        "title": "Multi-Tag Task",
        "task_type": "concrete",
        "task_instruction": "Do 1",
        "verification_instruction": "Verify 1",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    
    task2_response = client.post("/tasks", json={
        "title": "Single Tag Task",
        "task_type": "concrete",
        "task_instruction": "Do 2",
        "verification_instruction": "Verify 2",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json()["id"]
    
    # Create tags
    tag1_response = client.post("/mcp/create_tag", json={"name": "tag1"})
    tag1_id = tag1_response.json()["tag_id"]
    tag2_response = client.post("/mcp/create_tag", json={"name": "tag2"})
    tag2_id = tag2_response.json()["tag_id"]
    
    # Assign tags: task1 has both, task2 has only tag1
    client.post("/mcp/assign_tag_to_task", json={"task_id": task1_id, "tag_id": tag1_id})
    client.post("/mcp/assign_tag_to_task", json={"task_id": task1_id, "tag_id": tag2_id})
    client.post("/mcp/assign_tag_to_task", json={"task_id": task2_id, "tag_id": tag1_id})
    
    # Query by both tags (should return only task1)
    response = client.post("/mcp/query_tasks", json={"tag_ids": [tag1_id, tag2_id]})
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    task_ids = {t["id"] for t in tasks}
    assert task1_id in task_ids
    assert task2_id not in task_ids


def test_mcp_post_tools_call_create_tag(client):
    """Test MCP tools/call for create_tag - CRITICAL for MCP integration."""
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {
            "name": "create_tag",
            "arguments": {
                "name": "mcp-tag"
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 30
    assert "result" in result
    
    # Parse the content
    import json
    content_text = result["result"]["content"][0]["text"]
    create_result = json.loads(content_text)
    assert create_result["success"] is True
    assert "tag_id" in create_result
    assert create_result["tag"]["name"] == "mcp-tag"


def test_mcp_post_tools_call_query_tasks_by_tag(client):
    """Test MCP tools/call for query_tasks with tag filtering."""
    # Create task and tag
    create_response = client.post("/tasks", json={
        "title": "Tag Query Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    tag_response = client.post("/mcp/create_tag", json={"name": "query-filter"})
    tag_id = tag_response.json()["tag_id"]
    
    client.post("/mcp/assign_tag_to_task", json={"task_id": task_id, "tag_id": tag_id})
    
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 33,
        "method": "tools/call",
        "params": {
            "name": "query_tasks",
            "arguments": {
                "tag_id": tag_id,
                "limit": 10
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    import json
    content_text = result["result"]["content"][0]["text"]
    tasks = json.loads(content_text)
    assert isinstance(tasks, list)
    assert len(tasks) > 0
    assert any(t["id"] == task_id for t in tasks)



# ============================================================================
# Circular Dependency Validation Tests
# ============================================================================

def test_mcp_prevent_circular_blocked_by_dependency_direct(client):
    """Test that MCP API prevents direct circular blocked_by dependencies with clear error messages."""
    # Create two tasks
    task_a_response = client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    # Create Task A blocked_by Task B
    client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    
    # Try to create Task B blocked_by Task A (should fail - circular dependency)
    response = client.post("/relationships", json={
        "parent_task_id": task_b_id,
        "child_task_id": task_a_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    error_msg = response.json()["detail"].lower()
    assert "circular" in error_msg or "dependency" in error_msg
    assert str(task_a_id) in response.json()["detail"] or str(task_b_id) in response.json()["detail"]


def test_mcp_prevent_circular_blocked_by_dependency_via_create_task(client):
    """Test that MCP create_task with relationship prevents circular dependencies."""
    # Create first task
    task_a_response = client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    # Create Task B blocked by Task A
    task_b_response = client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent",
        "parent_task_id": task_a_id,
        "relationship_type": "blocked_by"
    })
    assert task_b_response.status_code == 200
    task_b_id = task_b_response.json()["task_id"]
    
    # Try to create Task C that would create cycle: A -> B -> C -> A
    # First, create Task C blocked by Task B
    task_c_response = client.post("/mcp/create_task", json={
        "title": "Task C",
        "task_type": "concrete",
        "task_instruction": "Task C",
        "verification_instruction": "Verify C",
        "agent_id": "test-agent",
        "parent_task_id": task_b_id,
        "relationship_type": "blocked_by"
    })
    assert task_c_response.status_code == 200
    task_c_id = task_c_response.json()["task_id"]
    
    # Now try to create relationship Task A blocked by Task C (should fail - creates cycle)
    response = client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_c_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    error_msg = response.json()["detail"].lower()
    assert "circular" in error_msg or "dependency" in error_msg


def test_mcp_prevent_circular_blocked_by_dependency_indirect(client):
    """Test that MCP API prevents indirect circular blocked_by dependencies."""
    # Create three tasks
    task_a_response = client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    task_c_response = client.post("/mcp/create_task", json={
        "title": "Task C",
        "task_type": "concrete",
        "task_instruction": "Task C",
        "verification_instruction": "Verify C",
        "agent_id": "test-agent"
    })
    task_c_id = task_c_response.json()["task_id"]
    
    # Create chain: A blocked_by B, B blocked_by C
    client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    client.post("/relationships", json={
        "parent_task_id": task_b_id,
        "child_task_id": task_c_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    
    # Try to create C blocked_by A (should fail - creates cycle A->B->C->A)
    response = client.post("/relationships", json={
        "parent_task_id": task_c_id,
        "child_task_id": task_a_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    error_msg = response.json()["detail"].lower()
    assert "circular" in error_msg or "dependency" in error_msg
    # Verify error message mentions the tasks involved
    assert str(task_a_id) in response.json()["detail"] or str(task_c_id) in response.json()["detail"]


def test_mcp_prevent_circular_blocking_dependency(client):
    """Test that MCP API prevents circular blocking dependencies (blocking is inverse of blocked_by)."""
    # Create two tasks
    task_a_response = client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    # Task A blocks Task B (equivalent to B blocked_by A)
    client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocking",
        "agent_id": "test-agent"
    })
    
    # Try to create Task B blocks Task A (should fail - circular dependency)
    response = client.post("/relationships", json={
        "parent_task_id": task_b_id,
        "child_task_id": task_a_id,
        "relationship_type": "blocking",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    error_msg = response.json()["detail"].lower()
    assert "circular" in error_msg or "dependency" in error_msg


def test_mcp_prevent_mixed_blocking_blocked_by_circular_dependency(client):
    """Test that mixing blocking and blocked_by relationships properly detects circular dependencies."""
    # Create two tasks
    task_a_response = client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    # Task A blocks Task B (B blocked_by A)
    client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocking",
        "agent_id": "test-agent"
    })
    
    # Try to create Task A blocked_by Task B (should fail - circular: A blocks B, but B blocks A)
    response = client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    error_msg = response.json()["detail"].lower()
    assert "circular" in error_msg or "dependency" in error_msg


def test_mcp_allow_non_blocking_relationships_without_circular_checks(client):
    """Test that non-blocking relationship types (subtask, related) can be created without circular checks."""
    # Create two tasks
    task_a_response = client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "abstract",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    # These should work without circular dependency checks
    response1 = client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "subtask",
        "agent_id": "test-agent"
    })
    assert response1.status_code == 200
    
    response2 = client.post("/relationships", json={
        "parent_task_id": task_b_id,
        "child_task_id": task_a_id,
        "relationship_type": "related",
        "agent_id": "test-agent"
    })
    assert response2.status_code == 200


def test_mcp_circular_dependency_error_message_clarity(client):
    """Test that circular dependency error messages are clear and informative."""
    # Create two tasks
    task_a_response = client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    # Create initial relationship
    client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    
    # Try to create circular relationship
    response = client.post("/relationships", json={
        "parent_task_id": task_b_id,
        "child_task_id": task_a_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    
    error_detail = response.json()["detail"]
    # Error message should:
    # 1. Mention "circular dependency"
    assert "circular" in error_detail.lower() or "dependency" in error_detail.lower()
    # 2. Include task IDs
    assert str(task_a_id) in error_detail or str(task_b_id) in error_detail
    # 3. Explain what relationship type is causing the issue
    assert "blocked_by" in error_detail.lower() or "blocking" in error_detail.lower()


def test_mcp_create_task_with_subtask_relationship(client):
    """Test that creating a task with parent_task_id and relationship_type creates the relationship."""
    # Create a parent task
    parent_response = client.post("/mcp/create_task", json={
        "title": "Parent Task",
        "task_type": "abstract",
        "task_instruction": "Parent task instruction",
        "verification_instruction": "Verify parent",
        "agent_id": "test-agent"
    })
    assert parent_response.status_code == 200
    parent_result = parent_response.json()
    assert parent_result["success"] is True
    parent_id = parent_result["task_id"]
    
    # Create a child task with parent_task_id and relationship_type
    child_response = client.post("/mcp/create_task", json={
        "title": "Child Task",
        "task_type": "concrete",
        "task_instruction": "Child task instruction",
        "verification_instruction": "Verify child",
        "agent_id": "test-agent",
        "parent_task_id": parent_id,
        "relationship_type": "subtask"
    })
    assert child_response.status_code == 200
    child_result = child_response.json()
    assert child_result["success"] is True
    child_id = child_result["task_id"]
    assert "relationship_id" in child_result, "Relationship should be created and relationship_id should be in response"
    relationship_id = child_result["relationship_id"]
    assert isinstance(relationship_id, int), "relationship_id should be an integer"
    
    # Verify the relationship exists by querying relationships for the parent task
    relationships_response = client.get(f"/tasks/{parent_id}/relationships")
    assert relationships_response.status_code == 200
    relationships_data = relationships_response.json()
    assert "relationships" in relationships_data
    relationships = relationships_data["relationships"]
    
    # Find the subtask relationship where parent is the parent task and child is the child task
    subtask_relationships = [r for r in relationships if r["relationship_type"] == "subtask" and r["parent_task_id"] == parent_id and r["child_task_id"] == child_id]
    assert len(subtask_relationships) == 1, "Exactly one subtask relationship should exist"
    assert subtask_relationships[0]["id"] == relationship_id, "Relationship ID should match"
    assert subtask_relationships[0]["parent_task_id"] == parent_id, "Parent task ID should match"
    assert subtask_relationships[0]["child_task_id"] == child_id, "Child task ID should match"
    
    # Also verify by querying relationships for the child task
    child_relationships_response = client.get(f"/tasks/{child_id}/relationships")
    assert child_relationships_response.status_code == 200
    child_relationships_data = child_relationships_response.json()
    assert "relationships" in child_relationships_data
    child_relationships = child_relationships_data["relationships"]
    
    # The child should show the relationship too (bidirectional view - task is child in relationship)
    child_subtask_relationships = [r for r in child_relationships if r["relationship_type"] == "subtask" and r["parent_task_id"] == parent_id and r["child_task_id"] == child_id]
    assert len(child_subtask_relationships) == 1, "Child task should also show the relationship"


def test_mcp_query_stale_tasks(client):
    """Test MCP query_stale_tasks function."""
    from datetime import datetime, timedelta
    import json
    
    # Create and lock a task
    create_response = client.post("/tasks", json={
        "title": "Stale Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Lock the task
    client.post(f"/tasks/{task_id}/lock", json={"agent_id": "agent-1"})
    
    # Manually update task to be stale
    import main
    conn = main.db._get_connection()
    try:
        cursor = conn.cursor()
        old_time = datetime.utcnow() - timedelta(hours=25)
        if main.db.db_type == "sqlite":
            cursor.execute("""
                UPDATE tasks 
                SET updated_at = ?
                WHERE id = ?
            """, (old_time.isoformat(), task_id))
        else:
            cursor.execute("""
                UPDATE tasks 
                SET updated_at = ?
                WHERE id = ?
            """, (old_time, task_id))
        conn.commit()
    finally:
        main.db.adapter.close(conn)
    
    # Query stale tasks via MCP
    response = client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 100,
        "method": "tools/call",
        "params": {
            "name": "query_stale_tasks",
            "arguments": {
                "hours": 24
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    assert result["jsonrpc"] == "2.0"
    
    # Parse result
    content_text = result["result"]["content"][0]["text"]
    stale_result = json.loads(content_text)
    assert stale_result["success"] is True
    assert "stale_tasks" in stale_result
    stale_task_ids = [t["id"] for t in stale_result["stale_tasks"]]
    assert task_id in stale_task_ids
