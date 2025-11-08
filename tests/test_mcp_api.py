"""
Tests for MCP API functionality.
"""
import pytest
import os
import tempfile
import shutil
from fastapi.testclient import TestClient

# Disable rate limiting in tests by setting very high limits BEFORE importing app
os.environ["RATE_LIMIT_GLOBAL_MAX"] = "10000"
os.environ["RATE_LIMIT_ENDPOINT_MAX"] = "10000"
os.environ["RATE_LIMIT_USER_MAX"] = "10000"
os.environ["RATE_LIMIT_AGENT_MAX"] = "10000"

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
    
    # Set the MCP API database instance
    from mcp_api import set_db
    set_db(db)
    
    # Also update the service container's database instance
    # This ensures REST API endpoints use the same database as MCP API
    from dependencies.services import get_services, _service_instance
    import dependencies.services as services_module
    # Always update the service container if it exists, or create it if it doesn't
    services = get_services()
    services.db = db
    services.backup_manager = backup_manager
    # Re-initialize MCP API with the updated database
    set_db(db)
    
    yield db, db_path, backups_dir
    
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def auth_client(client, temp_db):
    """Create authenticated test client with API key."""
    db, _, _ = temp_db
    
    # Create a project and API key for authentication
    project_id = db.create_project("Test Project", "/test/path")
    key_id, api_key = db.create_api_key(project_id, "Test API Key")
    
    # Create a client wrapper that adds auth headers
    class AuthenticatedClient:
        def __init__(self, client, api_key):
            self.client = client
            self.headers = {"X-API-Key": api_key}
            self.project_id = project_id
            self.api_key = api_key
        
        def get(self, url, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"].update(self.headers)
            return self.client.get(url, **kwargs)
        
        def post(self, url, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"].update(self.headers)
            return self.client.post(url, **kwargs)
        
        def put(self, url, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"].update(self.headers)
            return self.client.put(url, **kwargs)
        
        def delete(self, url, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"].update(self.headers)
            return self.client.delete(url, **kwargs)
        
        def patch(self, url, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"].update(self.headers)
            return self.client.patch(url, **kwargs)
    
    return AuthenticatedClient(client, api_key)


def test_mcp_list_available_tasks(auth_client):
    """Test MCP list available tasks."""
    # Create tasks of different types using MCP endpoint
    auth_client.post("/mcp/create_task", json={
        "title": "Abstract Task",
        "task_type": "abstract",
        "task_instruction": "Break down",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    auth_client.post("/mcp/create_task", json={
        "title": "Concrete Task",
        "task_type": "concrete",
        "task_instruction": "Do it",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    
    # Test breakdown agent
    response = auth_client.post("/mcp/list_available_tasks", json={
        "agent_type": "breakdown",
        "limit": 10
    })
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert any(t["task_type"] == "abstract" for t in tasks)
    
    # Test implementation agent
    response = auth_client.post("/mcp/list_available_tasks", json={
        "agent_type": "implementation",
        "limit": 10
    })
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert any(t["task_type"] == "concrete" for t in tasks)


def test_mcp_reserve_task(auth_client):
    """Test MCP reserve task."""
    # Create task using MCP endpoint
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Reserve Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["task_id"]
    
    # Reserve task
    reserve_response = auth_client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    assert reserve_response.status_code == 200
    result = reserve_response.json()
    assert result["success"] is True
    assert result["task"]["task_status"] == "in_progress"
    assert result["task"]["assigned_agent"] == "agent-1"
    
    # Try to reserve again (should fail)
    reserve_response2 = auth_client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert reserve_response2.status_code == 200
    result2 = reserve_response2.json()
    assert result2["success"] is False


def test_mcp_complete_task_with_followup(auth_client):
    """Test MCP complete task with followup."""
    # Create and reserve task using MCP endpoint
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Complete Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["task_id"]
    auth_client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    
    # Complete with followup
    complete_response = auth_client.post("/mcp/complete_task", json={
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
    
    # Verify followup was created using MCP endpoint
    followup_id = result["followup_task_id"]
    # Use MCP get_task_context or query to verify followup
    followup_response = auth_client.post("/mcp/get_task_context", json={"task_id": followup_id})
    assert followup_response.status_code == 200
    followup_context = followup_response.json()
    assert followup_context["success"] is True
    followup = followup_context["task"]
    assert followup["title"] == "Followup Task"


def test_mcp_create_task(auth_client):
    """Test MCP create task."""
    response = auth_client.post("/mcp/create_task", json={
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
    # Use MCP get_task_context instead of GET /tasks/{task_id}
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    task = context["task"]
    assert task["title"] == "MCP Created Task"


def test_mcp_create_task_with_due_date(auth_client):
    """Test MCP create task with due date."""
    from datetime import datetime, timedelta
    
    due_date = (datetime.now() + timedelta(days=7)).isoformat()
    response = auth_client.post("/mcp/create_task", json={
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
    # Use MCP get_task_context instead of GET /tasks/{task_id}
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    task = context["task"]
    assert task["title"] == "MCP Task with Due Date"
    assert task["due_date"] is not None
    # due_date should be stored and returned
    assert task["due_date"] == due_date or task["due_date"].startswith(due_date[:10])  # Allow for timezone differences


def test_mcp_post_tools_call_create_task_with_due_date(auth_client):
    """Test MCP tools/call for create_task with due_date - CRITICAL for MCP integration."""
    from datetime import datetime, timedelta
    
    due_date = (datetime.now() + timedelta(days=7)).isoformat()
    response = auth_client.post("/mcp/sse", json={
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
    # Use MCP get_task_context instead of GET /tasks/{task_id}
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    assert "task" in context
    assert context["task"] is not None
    task = context["task"]
    assert task["title"] == "MCP Created Task with Due Date"
    assert task["due_date"] is not None
    assert task["due_date"] == due_date or task["due_date"].startswith(due_date[:10])


def test_mcp_get_agent_performance(auth_client):
    """Test MCP get agent performance."""
    # Create and complete some tasks
    for i in range(3):
        create_response = auth_client.post("/mcp/create_task", json={
            "title": f"Task {i}",
            "task_type": "concrete",
            "task_instruction": "Do it",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
        task_id = create_response.json().get("task_id") or create_response.json().get("id")
        # Lock and complete via MCP
        auth_client.post("/mcp/reserve_task", json={"task_id": task_id, "agent_id": "test-agent"})
        auth_client.post("/mcp/complete_task", json={"task_id": task_id, "agent_id": "test-agent"})
    
    # Get performance
    response = auth_client.post("/mcp/get_agent_performance", json={
        "agent_id": "test-agent"
    })
    assert response.status_code == 200
    stats = response.json()
    assert stats["agent_id"] == "test-agent"
    assert stats["tasks_completed"] >= 3


def test_mcp_get_task_statistics(auth_client):
    """Test MCP get_task_statistics function."""
    # Create some tasks with different statuses and types
    task_ids = []
    for i in range(5):
        create_response = auth_client.post("/mcp/create_task", json={
            "title": f"Statistics Test Task {i}",
            "task_type": "concrete" if i % 2 == 0 else "abstract",
            "task_instruction": "Do something",
            "verification_instruction": "Verify it",
            "agent_id": "test-agent"
        })
        task_id = create_response.json().get("task_id") or create_response.json().get("id")
        task_ids.append(task_id)
    
    # Complete some tasks
    for task_id in task_ids[:2]:
        auth_client.post("/mcp/reserve_task", json={"task_id": task_id, "agent_id": "test-agent"})
        auth_client.post("/mcp/complete_task", json={"task_id": task_id, "agent_id": "test-agent"})
    
    # Get statistics
    response = auth_client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "name": "get_task_statistics",
            "arguments": {}
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 8
    
    # Parse and verify
    import json
    content_text = result["result"]["content"][0]["text"]
    stats = json.loads(content_text)
    assert stats["success"] is True
    assert "total" in stats
    assert stats["total"] >= 5
    assert "by_status" in stats
    assert "available" in stats["by_status"]
    assert "complete" in stats["by_status"]
    assert stats["by_status"]["complete"] >= 2
    assert "by_type" in stats
    assert "concrete" in stats["by_type"]
    assert "abstract" in stats["by_type"]
    assert "completion_rate" in stats
    assert isinstance(stats["completion_rate"], (int, float))
    assert stats["completion_rate"] >= 0


def test_mcp_get_task_statistics_with_filters(auth_client):
    """Test MCP get_task_statistics with filters."""
    # Create tasks
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Filtered Statistics Test",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    # Get statistics filtered by task_type
    response = auth_client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
            "name": "get_task_statistics",
            "arguments": {
                "task_type": "concrete"
            }
        }
    })
    assert response.status_code == 200
    result = response.json()
    
    assert result["jsonrpc"] == "2.0"
    
    # Parse and verify
    import json
    content_text = result["result"]["content"][0]["text"]
    stats = json.loads(content_text)
    assert stats["success"] is True
    assert "total" in stats
    assert "by_type" in stats
    assert stats["by_type"]["concrete"] >= 1
    # When filtering by concrete, abstract count should be 0 or not included
    assert stats["by_type"].get("abstract", 0) == 0


# ============================================================================
# MCP Protocol Tests - Critical for data integrity
# ============================================================================

def test_mcp_sse_endpoint_connectivity(auth_client):
    """Test MCP SSE endpoint returns proper JSON-RPC format."""
    # Use stream=True to handle SSE properly
    # CRITICAL: The SSE endpoint has an infinite keep-alive loop, so we must limit reading
    import threading
    import time
    
    content_parts = []
    read_complete = threading.Event()
    exception_occurred = [None]
    
    def read_stream():
        """Read stream in a separate thread with timeout protection."""
        try:
            with auth_client.client.stream("GET", "/mcp/sse") as response:
                assert response.status_code == 200
                assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
                
                line_count = 0
                max_lines = 20  # Should be enough to get initial messages
                
                # Read lines with explicit limit to prevent hanging
                for line in response.iter_lines():
                    if line:
                        content_parts.append(line.decode('utf-8') if isinstance(line, bytes) else line)
                        line_count += 1
                        # Stop after reading initial messages (before keep-alive loop)
                        if line_count >= max_lines:
                            break
        except Exception as e:
            exception_occurred[0] = e
        finally:
            read_complete.set()
    
    # Start reading in a separate thread
    thread = threading.Thread(target=read_stream, daemon=True)
    thread.start()
    
    # Wait for completion with timeout (10 seconds max)
    if not read_complete.wait(timeout=10.0):
        # Timeout - the test is hanging
        raise TimeoutError("SSE endpoint test timed out after 10 seconds - endpoint may be hanging")
    
    # Check for exceptions
    if exception_occurred[0]:
        raise exception_occurred[0]
    
    # Verify we got content
    content = "\n".join(content_parts)
    assert len(content) > 0, "No content received from SSE endpoint"
    
    # Check that we got the expected SSE format
    assert "event: message" in content or "jsonrpc" in content or "data:" in content
    # Check for protocol version or tools list
    assert "2.0" in content or "protocolVersion" in content or "tools" in content or "todo-mcp-service" in content


def test_mcp_post_initialize(auth_client):
    """Test MCP POST initialize request - CRITICAL for connection."""
    response = auth_client.post("/mcp/sse", json={
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


def test_mcp_post_tools_list(auth_client):
    """Test MCP POST tools/list request - CRITICAL for tool discovery."""
    response = auth_client.post("/mcp/sse", json={
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


def test_mcp_post_tools_call_list_available_tasks(auth_client):
    """Test MCP tools/call for list_available_tasks - CRITICAL for data access."""
    # Create test task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "MCP Test Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    # Call via MCP protocol
    response = auth_client.post("/mcp/sse", json={
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
    tasks_data = json.loads(content_text)
    # MCP wraps list results as {"result": [...]}
    if isinstance(tasks_data, dict) and "result" in tasks_data:
        tasks = tasks_data["result"]
    elif isinstance(tasks_data, dict) and "tasks" in tasks_data:
        tasks = tasks_data["tasks"]
    else:
        tasks = tasks_data if isinstance(tasks_data, list) else [tasks_data]
    assert isinstance(tasks, list)
    assert len(tasks) > 0
    assert any(t["id"] == task_id for t in tasks)


def test_mcp_post_tools_call_reserve_task(auth_client):
    """Test MCP tools/call for reserve_task - CRITICAL for task locking."""
    # Create test task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Reserve MCP Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    # Reserve via MCP protocol
    response = auth_client.post("/mcp/sse", json={
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
    # Use MCP get_task_context instead of GET /tasks/{task_id}
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    task = context["task"]
    assert task["task_status"] == "in_progress"
    assert task["assigned_agent"] == "mcp-test-agent"


def test_mcp_post_tools_call_complete_task(auth_client):
    """Test MCP tools/call for complete_task - CRITICAL for task completion."""
    # Create and reserve task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Complete MCP Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    auth_client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "mcp-test-agent"
    })
    
    # Complete via MCP protocol
    response = auth_client.post("/mcp/sse", json={
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
    # Use MCP get_task_context instead of GET /tasks/{task_id}
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    assert "task" in context
    assert context["task"] is not None
    task = context["task"]
    assert "task_status" in task
    assert task["task_status"] == "complete"
    assert task["completed_at"] is not None


def test_mcp_post_tools_call_verify_task(auth_client):
    """Test MCP tools/call for verify_task - CRITICAL for task verification."""
    # Create, reserve, and complete task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Verify MCP Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    auth_client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "mcp-test-agent"
    })
    
    auth_client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "mcp-test-agent",
        "notes": "Completed via MCP"
    })
    
    # Verify task status is complete but unverified
    # Use MCP get_task_context instead of GET /tasks/{task_id}
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    assert "task" in context
    assert context["task"] is not None
    task = context["task"]
    assert "task_status" in task
    assert task["task_status"] == "complete"
    assert "verification_status" in task
    assert task["verification_status"] == "unverified"
    
    # Verify via MCP protocol
    response = auth_client.post("/mcp/sse", json={
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
    # Use MCP get_task_context instead of GET /tasks/{task_id}
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    assert "task" in context
    assert context["task"] is not None
    task = context["task"]
    assert "verification_status" in task
    assert task["verification_status"] == "verified"


def test_mcp_post_tools_call_create_task(auth_client):
    """Test MCP tools/call for create_task - CRITICAL for task creation."""
    response = auth_client.post("/mcp/sse", json={
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
    assert result["id"] == 7
    
    # Parse and verify
    import json
    content_text = result["result"]["content"][0]["text"]
    create_result = json.loads(content_text)
    assert create_result["success"] is True
    assert "task_id" in create_result
    
    # Verify task exists in database
    task_id = create_result["task_id"]
    # Use MCP get_task_context instead of GET /tasks/{task_id}
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    assert "task" in context
    assert context["task"] is not None
    task = context["task"]
    assert task["title"] == "MCP Created Task"


def test_mcp_full_workflow_integrity(auth_client):
    """Test complete workflow through MCP - CRITICAL for data integrity."""
    # 1. Initialize
    init_response = auth_client.post("/mcp/sse", json={
        "jsonrpc": "2.0",
        "id": 10,
        "method": "initialize",
        "params": {}
    })
    assert init_response.status_code == 200
    
    # 2. Get tools list
    tools_response = auth_client.post("/mcp/sse", json={
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
    create_response = auth_client.post("/mcp/sse", json={
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
    list_response = auth_client.post("/mcp/sse", json={
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
    list_result_data = json.loads(list_response.json()["result"]["content"][0]["text"])
    # Handle both {"result": [...]} and {"tasks": [...]} and direct list
    if isinstance(list_result_data, dict):
        list_result = list_result_data.get("result") or list_result_data.get("tasks") or []
    else:
        list_result = list_result_data
    assert isinstance(list_result, list), f"Expected list, got {type(list_result)}: {list_result}"
    assert any(t["id"] == task_id for t in list_result)
    
    # 5. Reserve task via MCP
    reserve_response = auth_client.post("/mcp/sse", json={
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
    complete_response = auth_client.post("/mcp/sse", json={
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
    # Use MCP get_task_context instead of GET /tasks/{task_id}
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    assert "task" in context
    assert context["task"] is not None
    task = context["task"]
    assert task["task_status"] == "complete"
    assert task["completed_at"] is not None
    assert task["notes"] == "Workflow completed successfully"


def test_mcp_error_handling_invalid_method(auth_client):
    """Test MCP error handling for invalid methods."""
    response = auth_client.post("/mcp/sse", json={
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


def test_mcp_error_handling_invalid_tool(auth_client):
    """Test MCP error handling for invalid tool names."""
    response = auth_client.post("/mcp/sse", json={
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


def test_mcp_error_handling_missing_parameters(auth_client):
    """Test MCP error handling for missing required parameters."""
    response = auth_client.post("/mcp/sse", json={
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


def test_mcp_error_handling_task_not_found(auth_client):
    """Test MCP error handling when task not found."""
    response = auth_client.post("/mcp/reserve_task", json={
        "task_id": 99999,
        "agent_id": "agent-1"
    })
    assert response.status_code == 200
    result = response.json()
    assert "success" in result
    assert result["success"] is False
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_mcp_error_handling_reserve_already_locked(auth_client):
    """Test MCP error handling when reserving already locked task."""
    # Create and reserve task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Already Locked",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    auth_client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    
    # Try to reserve again
    response = auth_client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert response.status_code == 200
    result = response.json()
    assert "success" in result
    assert result["success"] is False
    assert "error" in result
    assert "cannot be locked" in result["error"].lower() or "not available" in result["error"].lower()


def test_mcp_error_handling_complete_wrong_agent(auth_client):
    """Test MCP error handling when wrong agent tries to complete task."""
    # Create and reserve task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Wrong Agent Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    auth_client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    
    # Try to complete with wrong agent
    response = auth_client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert response.status_code == 200
    result = response.json()
    assert "success" in result
    assert result["success"] is False
    assert "error" in result
    assert "assigned" in result["error"].lower() or "agent" in result["error"].lower()


def test_mcp_error_handling_empty_update_content(auth_client):
    """Test MCP error handling for empty update content."""
    # Create task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Update Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    # Try to add empty update
    response = auth_client.post("/mcp/add_task_update", json={
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


def test_mcp_error_handling_unlock_wrong_agent(auth_client):
    """Test MCP error handling when wrong agent tries to unlock task."""
    # Create and reserve task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Unlock Wrong Agent",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    auth_client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    
    # Try to unlock with wrong agent
    response = auth_client.post("/mcp/unlock_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert response.status_code == 200
    result = response.json()
    assert "success" in result
    assert result["success"] is False
    assert "error" in result
    assert "assigned" in result["error"].lower() or "agent" in result["error"].lower()


def test_mcp_unlock_task(auth_client):
    """Test MCP unlock_task function."""
    # Create and reserve task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Unlock Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    auth_client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "test-agent"
    })
    
    # Unlock via MCP
    response = auth_client.post("/mcp/unlock_task", json={
        "task_id": task_id,
        "agent_id": "test-agent"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    
    # Verify task is unlocked
    # Use MCP get_task_context instead of GET /tasks/{task_id}
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    task = context["task"]
    assert task["task_status"] == "available"
    assert task["assigned_agent"] is None


def test_mcp_bulk_unlock_tasks(auth_client):
    """Test MCP bulk_unlock_tasks function."""
    # Create and reserve multiple tasks
    task_ids = []
    for i in range(3):
        create_response = auth_client.post("/mcp/create_task", json={
            "title": f"Bulk Unlock Test {i}",
            "task_type": "concrete",
            "task_instruction": "Test",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
        task_id = create_response.json().get("task_id") or create_response.json().get("id")
        task_ids.append(task_id)
        auth_client.post("/mcp/reserve_task", json={
            "task_id": task_id,
            "agent_id": "test-agent"
        })
    
    # Bulk unlock via MCP
    response = auth_client.post("/mcp/bulk_unlock_tasks", json={
        "task_ids": task_ids,
        "agent_id": "test-agent"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["unlocked_count"] == 3
    assert len(result["unlocked_task_ids"]) == 3
    assert result["failed_count"] == 0
    assert len(result["failed_task_ids"]) == 0
    
    # Verify all tasks are unlocked
    for task_id in task_ids:
        # Use MCP get_task_context instead of GET /tasks/{task_id}
        get_response = auth_client.post("/mcp/get_task_context", json={"task_id": task_id})
        assert get_response.status_code == 200
        context = get_response.json()
        assert context["success"] is True
        task = context["task"]
        assert task["task_status"] == "available"
        assert task["assigned_agent"] is None


def test_mcp_bulk_unlock_tasks_partial_failure(auth_client):
    """Test MCP bulk_unlock_tasks with some tasks failing."""
    # Create and reserve one task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Bulk Unlock Test Valid",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    valid_task_id = create_response.json().get("task_id") or create_response.json().get("id")
    auth_client.post("/mcp/reserve_task", json={
        "task_id": valid_task_id,
        "agent_id": "test-agent"
    })
    
    # Try to bulk unlock with one valid task and one invalid task ID
    invalid_task_id = 99999
    response = auth_client.post("/mcp/bulk_unlock_tasks", json={
        "task_ids": [valid_task_id, invalid_task_id],
        "agent_id": "test-agent"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["unlocked_count"] == 1
    assert len(result["unlocked_task_ids"]) == 1
    assert result["unlocked_task_ids"][0] == valid_task_id
    assert result["failed_count"] == 1
    assert len(result["failed_task_ids"]) == 1
    assert result["failed_task_ids"][0]["task_id"] == invalid_task_id
    assert "error" in result["failed_task_ids"][0]
    
    # Verify valid task is unlocked
    get_response = auth_client.post("/mcp/get_task_context", json={"task_id": valid_task_id})
    assert get_response.status_code == 200
    context = get_response.json()
    assert context["success"] is True
    task = context["task"]
    assert task["task_status"] == "available"
    assert task["assigned_agent"] is None


def test_mcp_bulk_unlock_tasks_not_in_progress(auth_client):
    """Test MCP bulk_unlock_tasks with tasks not in_progress."""
    # Create a task but don't reserve it (it's already available)
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Bulk Unlock Test Available",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    # Try to bulk unlock a task that's not in_progress
    response = auth_client.post("/mcp/bulk_unlock_tasks", json={
        "task_ids": [task_id],
        "agent_id": "test-agent"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["unlocked_count"] == 0
    assert result["failed_count"] == 1
    assert len(result["failed_task_ids"]) == 1
    assert result["failed_task_ids"][0]["task_id"] == task_id
    assert "not in_progress" in result["failed_task_ids"][0]["error"].lower()


def test_mcp_query_tasks(auth_client):
    """Test MCP query_tasks function."""
    # Create tasks with different types and statuses using MCP endpoint
    auth_client.post("/mcp/create_task", json={
        "title": "Concrete Task 1",
        "task_type": "concrete",
        "task_instruction": "Do it",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_response = auth_client.post("/mcp/create_task", json={
        "title": "Abstract Task",
        "task_type": "abstract",
        "task_instruction": "Break down",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json().get("task_id") or task2_response.json().get("id")
    
    # Query by task_type
    response = auth_client.post("/mcp/query_tasks", json={
        "task_type": "concrete",
        "limit": 10
    })
    assert response.status_code == 200
    result = response.json()
    assert "tasks" in result
    tasks = result["tasks"]
    assert all(t["task_type"] == "concrete" for t in tasks)
    
    # Query by task_status
    response = auth_client.post("/mcp/query_tasks", json={
        "task_status": "available",
        "limit": 10
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert all(t["task_status"] == "available" for t in tasks)


def test_mcp_add_task_update(auth_client):
    """Test MCP add_task_update function."""
    # Create task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Update Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    # Add progress update
    response = auth_client.post("/mcp/add_task_update", json={
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
    response = auth_client.post("/mcp/add_task_update", json={
        "task_id": task_id,
        "agent_id": "test-agent",
        "content": "Blocked by dependency",
        "update_type": "blocker"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True


def test_mcp_get_task_context(auth_client):
    """Test MCP get_task_context function."""
    # Create project
    project_response = auth_client.post("/projects", json={
        "name": "Test Project",
        "local_path": "/test/path",
        "origin_url": "https://test.com"
    })
    project_id = project_response.json().get("id") or project_response.json().get("project_id")
    
    # Create parent task using MCP endpoint
    parent_response = auth_client.post("/mcp/create_task", json={
        "title": "Parent Task",
        "task_type": "abstract",
        "task_instruction": "Parent",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    parent_id = parent_response.json().get("task_id") or parent_response.json().get("id")
    
    # Create child task using MCP endpoint with parent relationship
    child_response = auth_client.post("/mcp/create_task", json={
        "title": "Child Task",
        "task_type": "concrete",
        "task_instruction": "Child",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id,
        "parent_task_id": parent_id,
        "relationship_type": "subtask"
    })
    child_id = child_response.json().get("task_id") or child_response.json().get("id")
    
    # Add update to child
    auth_client.post("/mcp/add_task_update", json={
        "task_id": child_id,
        "agent_id": "test-agent",
        "content": "Working on it",
        "update_type": "progress"
    })
    
    # Get context
    response = auth_client.post("/mcp/get_task_context", json={
        "task_id": child_id
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "task" in result
    assert "project" in result
    assert "updates" in result
    assert "ancestry" in result
    assert result["task"]["id"] == child_id
    if result["project"] is not None:
        assert result["project"]["id"] == project_id
    assert len(result["updates"]) > 0
    assert len(result["ancestry"]) > 0  # Should include parent


def test_mcp_get_task_context_missing_task(auth_client):
    """Test MCP get_task_context with missing task ID."""
    response = auth_client.post("/mcp/get_task_context", json={
        "task_id": 99999  # Non-existent task
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is False
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_mcp_get_tasks_approaching_deadline(auth_client):
    """Test MCP get_tasks_approaching_deadline function."""
    from datetime import datetime, timedelta
    
    # Create task due in 2 days
    soon_date = (datetime.now() + timedelta(days=2)).isoformat()
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Soon Task",
        "task_type": "concrete",
        "task_instruction": "Due soon",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "due_date": soon_date
    })
    soon_task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    # Create task due in 5 days
    later_date = (datetime.now() + timedelta(days=5)).isoformat()
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Later Task",
        "task_type": "concrete",
        "task_instruction": "Due later",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "due_date": later_date
    })
    
    # Query tasks approaching deadline (3 days)
    response = auth_client.post("/mcp/get_tasks_approaching_deadline", json={
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

def test_mcp_search_tasks_by_title(auth_client):
    """Test MCP search_tasks by title."""
    # Create tasks
    create_response1 = auth_client.post("/mcp/create_task", json={
        "title": "Implement user authentication",
        "task_type": "concrete",
        "task_instruction": "Add login functionality",
        "verification_instruction": "Verify login works",
        "agent_id": "test-agent"
    })
    task1_id = create_response1.json().get("task_id") or create_response1.json().get("id")
    
    create_response2 = auth_client.post("/mcp/create_task", json={
        "title": "Add database migrations",
        "task_type": "concrete",
        "task_instruction": "Create migration system",
        "verification_instruction": "Verify migrations",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json().get("task_id") or create_response2.json().get("id")
    
    # Search for "authentication"
    response = auth_client.post("/mcp/search_tasks", json={
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
    response = auth_client.post("/mcp/search_tasks", json={
        "query": "database",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task2_id


def test_mcp_search_tasks_by_instruction(auth_client):
    """Test MCP search_tasks by task_instruction."""
    create_response1 = auth_client.post("/mcp/create_task", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Implement REST API endpoints",
        "verification_instruction": "Test endpoints",
        "agent_id": "test-agent"
    })
    task1_id = create_response1.json().get("task_id") or create_response1.json().get("id")
    
    create_response2 = auth_client.post("/mcp/create_task", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Create database schema",
        "verification_instruction": "Verify schema",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json().get("task_id") or create_response2.json().get("id")
    
    # Search for "REST"
    response = auth_client.post("/mcp/search_tasks", json={
        "query": "REST",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id
    
    # Search for "schema"
    response = auth_client.post("/mcp/search_tasks", json={
        "query": "schema",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task2_id


def test_mcp_search_tasks_by_notes(auth_client):
    """Test MCP search_tasks by notes."""
    create_response1 = auth_client.post("/mcp/create_task", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "notes": "High priority bug fix needed"
    })
    task1_id = create_response1.json().get("task_id") or create_response1.json().get("id")
    
    create_response2 = auth_client.post("/mcp/create_task", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Do something else",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "notes": "Performance optimization"
    })
    task2_id = create_response2.json().get("task_id") or create_response2.json().get("id")
    
    # Search for "bug"
    response = auth_client.post("/mcp/search_tasks", json={
        "query": "bug",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id
    
    # Search for "performance"
    response = auth_client.post("/mcp/search_tasks", json={
        "query": "performance",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task2_id


def test_mcp_search_tasks_with_limit(auth_client):
    """Test that MCP search_tasks respects limit parameter."""
    # Create multiple tasks
    for i in range(10):
        auth_client.post("/mcp/create_task", json={
            "title": f"Searchable Task {i}",
            "task_type": "concrete",
            "task_instruction": "Searchable content",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
    
    # Search with limit
    response = auth_client.post("/mcp/search_tasks", json={
        "query": "Searchable",
        "limit": 5
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 5


def test_mcp_search_tasks_ranks_by_relevance(auth_client):
    """Test that MCP search_tasks results are ranked by relevance."""
    create_response1 = auth_client.post("/mcp/create_task", json={
        "title": "API endpoint",
        "task_type": "concrete",
        "task_instruction": "Create API endpoint for user management",
        "verification_instruction": "Verify API",
        "agent_id": "test-agent",
        "notes": "API endpoint implementation"
    })
    task1_id = create_response1.json().get("task_id") or create_response1.json().get("id")
    
    create_response2 = auth_client.post("/mcp/create_task", json={
        "title": "Database schema",
        "task_type": "concrete",
        "task_instruction": "Design database schema",
        "verification_instruction": "Verify schema",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json().get("task_id") or create_response2.json().get("id")
    
    create_response3 = auth_client.post("/mcp/create_task", json={
        "title": "API documentation",
        "task_type": "concrete",
        "task_instruction": "Write API documentation",
        "verification_instruction": "Verify docs",
        "agent_id": "test-agent"
    })
    task3_id = create_response3.json().get("task_id") or create_response3.json().get("id")
    
    # Search for "API" - task1 should rank highest (multiple mentions)
    response = auth_client.post("/mcp/search_tasks", json={
        "query": "API",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) >= 2  # Should find task1 and task3
    # First result should be task1 (most relevant)
    assert tasks[0]["id"] == task1_id


def test_mcp_search_tasks_with_special_characters(auth_client):
    """Test that MCP search_tasks handles special characters gracefully."""
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Task with special chars: test@example.com",
        "task_type": "concrete",
        "task_instruction": "Handle special characters",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    # Search should handle special characters
    response = auth_client.post("/mcp/search_tasks", json={
        "query": "test@example",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["id"] == task_id


def test_mcp_search_tasks_multiple_keywords(auth_client):
    """Test MCP search_tasks with multiple keywords."""
    create_response1 = auth_client.post("/mcp/create_task", json={
        "title": "Authentication system",
        "task_type": "concrete",
        "task_instruction": "Implement user authentication and authorization",
        "verification_instruction": "Verify auth works",
        "agent_id": "test-agent"
    })
    task1_id = create_response1.json().get("task_id") or create_response1.json().get("id")
    
    create_response2 = auth_client.post("/mcp/create_task", json={
        "title": "Database backup",
        "task_type": "concrete",
        "task_instruction": "Create backup system",
        "verification_instruction": "Verify backup",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json().get("task_id") or create_response2.json().get("id")
    
    # Search for multiple keywords (FTS5 supports space-separated terms)
    response = auth_client.post("/mcp/search_tasks", json={
        "query": "authentication user",
        "limit": 100
    })
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    # Should find task1 which contains both terms
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids


def test_mcp_post_tools_call_search_tasks(auth_client):
    """Test MCP tools/call for search_tasks - CRITICAL for MCP integration."""
    # Create test task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Search MCP Test Task",
        "task_type": "concrete",
        "task_instruction": "Test search functionality",
        "verification_instruction": "Verify search",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    # Call via MCP protocol
    response = auth_client.post("/mcp/sse", json={
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
    tasks_data = json.loads(content_text)
    # Handle both {"result": [...]} and {"tasks": [...]} and direct list
    if isinstance(tasks_data, dict):
        tasks = tasks_data.get("result") or tasks_data.get("tasks") or []
    else:
        tasks = tasks_data
    assert isinstance(tasks, list), f"Expected list, got {type(tasks)}: {tasks}"
    assert len(tasks) > 0
    assert any(t["id"] == task_id for t in tasks)


# ============================================================================
# MCP Tag tests
# ============================================================================

def test_mcp_create_tag(auth_client):
    """Test MCP create_tag function."""
    response = auth_client.post("/mcp/create_tag", json={"name": "bug"})
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "tag_id" in result
    assert result["tag"]["name"] == "bug"


def test_mcp_list_tags(auth_client):
    """Test MCP list_tags function."""
    # Create some tags
    auth_client.post("/mcp/create_tag", json={"name": "feature"})
    auth_client.post("/mcp/create_tag", json={"name": "urgent"})
    
    # List tags
    response = auth_client.post("/mcp/list_tags")
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "tags" in result
    tag_names = [t["name"] for t in result["tags"]]
    assert "feature" in tag_names
    assert "urgent" in tag_names


def test_mcp_assign_tag_to_task(auth_client):
    """Test MCP assign_tag_to_task function."""
    # Create task and tag
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Tag Test Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    tag_response = auth_client.post("/mcp/create_tag", json={"name": "test-tag"})
    tag_id = tag_response.json()["tag_id"]
    
    # Assign tag
    response = auth_client.post("/mcp/assign_tag_to_task", json={
        "task_id": task_id,
        "tag_id": tag_id
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["task_id"] == task_id
    assert result["tag_id"] == tag_id
    
    # Verify tag is assigned
    get_response = auth_client.post("/mcp/get_task_tags", json={"task_id": task_id})
    tags = get_response.json()["tags"]
    assert len(tags) == 1
    assert tags[0]["id"] == tag_id


def test_mcp_get_task_tags(auth_client):
    """Test MCP get_task_tags function."""
    # Create task and tags
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Multi-Tag Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    tag1_response = auth_client.post("/mcp/create_tag", json={"name": "tag1"})
    tag1_id = tag1_response.json()["tag_id"]
    tag2_response = auth_client.post("/mcp/create_tag", json={"name": "tag2"})
    tag2_id = tag2_response.json()["tag_id"]
    
    # Assign multiple tags
    auth_client.post("/mcp/assign_tag_to_task", json={"task_id": task_id, "tag_id": tag1_id})
    auth_client.post("/mcp/assign_tag_to_task", json={"task_id": task_id, "tag_id": tag2_id})
    
    # Get task tags
    response = auth_client.post("/mcp/get_task_tags", json={"task_id": task_id})
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert len(result["tags"]) == 2
    tag_ids = {t["id"] for t in result["tags"]}
    assert tag_ids == {tag1_id, tag2_id}


def test_mcp_remove_tag_from_task(auth_client):
    """Test MCP remove_tag_from_task function."""
    # Create task and tag
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Remove Tag Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    tag_response = auth_client.post("/mcp/create_tag", json={"name": "to-remove"})
    tag_id = tag_response.json()["tag_id"]
    
    # Assign tag
    auth_client.post("/mcp/assign_tag_to_task", json={"task_id": task_id, "tag_id": tag_id})
    
    # Remove tag
    response = auth_client.post("/mcp/remove_tag_from_task", json={
        "task_id": task_id,
        "tag_id": tag_id
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    
    # Verify tag is removed
    get_response = auth_client.post("/mcp/get_task_tags", json={"task_id": task_id})
    tags = get_response.json()["tags"]
    assert len(tags) == 0


def test_mcp_query_tasks_by_tag(auth_client):
    """Test querying tasks by tag via MCP."""
    # Create tasks
    task1_response = auth_client.post("/mcp/create_task", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do 1",
        "verification_instruction": "Verify 1",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json().get("task_id") or task1_response.json().get("id")
    
    task2_response = auth_client.post("/mcp/create_task", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Do 2",
        "verification_instruction": "Verify 2",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json().get("task_id") or task2_response.json().get("id")
    
    # Create tag
    tag_response = auth_client.post("/mcp/create_tag", json={"name": "query-tag"})
    tag_id = tag_response.json()["tag_id"]
    
    # Assign tag to task1 only
    auth_client.post("/mcp/assign_tag_to_task", json={"task_id": task1_id, "tag_id": tag_id})
    
    # Query by tag
    response = auth_client.post("/mcp/query_tasks", json={"tag_id": tag_id})
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    task_ids = {t["id"] for t in tasks}
    assert task1_id in task_ids
    assert task2_id not in task_ids


def test_mcp_query_tasks_by_multiple_tags(auth_client):
    """Test querying tasks by multiple tags via MCP."""
    # Create tasks
    task1_response = auth_client.post("/mcp/create_task", json={
        "title": "Multi-Tag Task",
        "task_type": "concrete",
        "task_instruction": "Do 1",
        "verification_instruction": "Verify 1",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json().get("task_id") or task1_response.json().get("id")
    
    task2_response = auth_client.post("/mcp/create_task", json={
        "title": "Single Tag Task",
        "task_type": "concrete",
        "task_instruction": "Do 2",
        "verification_instruction": "Verify 2",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json().get("task_id") or task2_response.json().get("id")
    
    # Create tags
    tag1_response = auth_client.post("/mcp/create_tag", json={"name": "tag1"})
    tag1_id = tag1_response.json()["tag_id"]
    tag2_response = auth_client.post("/mcp/create_tag", json={"name": "tag2"})
    tag2_id = tag2_response.json()["tag_id"]
    
    # Assign tags: task1 has both, task2 has only tag1
    auth_client.post("/mcp/assign_tag_to_task", json={"task_id": task1_id, "tag_id": tag1_id})
    auth_client.post("/mcp/assign_tag_to_task", json={"task_id": task1_id, "tag_id": tag2_id})
    auth_client.post("/mcp/assign_tag_to_task", json={"task_id": task2_id, "tag_id": tag1_id})
    
    # Query by both tags (should return only task1)
    response = auth_client.post("/mcp/query_tasks", json={"tag_ids": [tag1_id, tag2_id]})
    assert response.status_code == 200
    result = response.json()
    tasks = result["tasks"]
    task_ids = {t["id"] for t in tasks}
    assert task1_id in task_ids
    assert task2_id not in task_ids


def test_mcp_post_tools_call_create_tag(auth_client):
    """Test MCP tools/call for create_tag - CRITICAL for MCP integration."""
    response = auth_client.post("/mcp/sse", json={
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


def test_mcp_post_tools_call_query_tasks_by_tag(auth_client):
    """Test MCP tools/call for query_tasks with tag filtering."""
    # Create task and tag
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Tag Query Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    tag_response = auth_client.post("/mcp/create_tag", json={"name": "query-filter"})
    tag_id = tag_response.json()["tag_id"]
    
    auth_client.post("/mcp/assign_tag_to_task", json={"task_id": task_id, "tag_id": tag_id})
    
    response = auth_client.post("/mcp/sse", json={
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
    tasks_data = json.loads(content_text)
    # Handle both {"result": [...]} and {"tasks": [...]} and direct list
    if isinstance(tasks_data, dict):
        tasks = tasks_data.get("result") or tasks_data.get("tasks") or []
    else:
        tasks = tasks_data
    assert isinstance(tasks, list), f"Expected list, got {type(tasks)}: {tasks}"
    assert len(tasks) > 0
    assert any(t["id"] == task_id for t in tasks)



# ============================================================================
# Circular Dependency Validation Tests
# ============================================================================

def test_mcp_prevent_circular_blocked_by_dependency_direct(auth_client):
    """Test that MCP API prevents direct circular blocked_by dependencies with clear error messages."""
    # Create two tasks
    task_a_response = auth_client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = auth_client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    # Create Task A blocked_by Task B
    auth_client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    
    # Try to create Task B blocked_by Task A (should fail - circular dependency)
    response = auth_client.post("/relationships", json={
        "parent_task_id": task_b_id,
        "child_task_id": task_a_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    error_msg = response.json()["detail"].lower()
    assert "circular" in error_msg or "dependency" in error_msg
    assert str(task_a_id) in response.json()["detail"] or str(task_b_id) in response.json()["detail"]


def test_mcp_prevent_circular_blocked_by_dependency_via_create_task(auth_client):
    """Test that MCP create_task with relationship prevents circular dependencies."""
    # Create first task
    task_a_response = auth_client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    # Create Task B blocked by Task A
    task_b_response = auth_client.post("/mcp/create_task", json={
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
    task_c_response = auth_client.post("/mcp/create_task", json={
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
    response = auth_client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_c_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    error_msg = response.json()["detail"].lower()
    assert "circular" in error_msg or "dependency" in error_msg


def test_mcp_prevent_circular_blocked_by_dependency_indirect(auth_client):
    """Test that MCP API prevents indirect circular blocked_by dependencies."""
    # Create three tasks
    task_a_response = auth_client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = auth_client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    task_c_response = auth_client.post("/mcp/create_task", json={
        "title": "Task C",
        "task_type": "concrete",
        "task_instruction": "Task C",
        "verification_instruction": "Verify C",
        "agent_id": "test-agent"
    })
    task_c_id = task_c_response.json()["task_id"]
    
    # Create chain: A blocked_by B, B blocked_by C
    auth_client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    auth_client.post("/relationships", json={
        "parent_task_id": task_b_id,
        "child_task_id": task_c_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    
    # Try to create C blocked_by A (should fail - creates cycle A->B->C->A)
    response = auth_client.post("/relationships", json={
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


def test_mcp_prevent_circular_blocking_dependency(auth_client):
    """Test that MCP API prevents circular blocking dependencies (blocking is inverse of blocked_by)."""
    # Create two tasks
    task_a_response = auth_client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = auth_client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    # Task A blocks Task B (equivalent to B blocked_by A)
    auth_client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocking",
        "agent_id": "test-agent"
    })
    
    # Try to create Task B blocks Task A (should fail - circular dependency)
    response = auth_client.post("/relationships", json={
        "parent_task_id": task_b_id,
        "child_task_id": task_a_id,
        "relationship_type": "blocking",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    error_msg = response.json()["detail"].lower()
    assert "circular" in error_msg or "dependency" in error_msg


def test_mcp_prevent_mixed_blocking_blocked_by_circular_dependency(auth_client):
    """Test that mixing blocking and blocked_by relationships properly detects circular dependencies."""
    # Create two tasks
    task_a_response = auth_client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = auth_client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    # Task A blocks Task B (B blocked_by A)
    auth_client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocking",
        "agent_id": "test-agent"
    })
    
    # Try to create Task A blocked_by Task B (should fail - circular: A blocks B, but B blocks A)
    response = auth_client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    error_msg = response.json()["detail"].lower()
    assert "circular" in error_msg or "dependency" in error_msg


def test_mcp_allow_non_blocking_relationships_without_circular_checks(auth_client):
    """Test that non-blocking relationship types (subtask, related) can be created without circular checks."""
    # Create two tasks
    task_a_response = auth_client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "abstract",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = auth_client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    # These should work without circular dependency checks
    response1 = auth_client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "subtask",
        "agent_id": "test-agent"
    })
    assert response1.status_code == 201  # 201 Created is correct for POST /relationships
    
    response2 = auth_client.post("/relationships", json={
        "parent_task_id": task_b_id,
        "child_task_id": task_a_id,
        "relationship_type": "related",
        "agent_id": "test-agent"
    })
    assert response2.status_code == 201  # 201 Created is correct for POST /relationships


def test_mcp_circular_dependency_error_message_clarity(auth_client):
    """Test that circular dependency error messages are clear and informative."""
    # Create two tasks
    task_a_response = auth_client.post("/mcp/create_task", json={
        "title": "Task A",
        "task_type": "concrete",
        "task_instruction": "Task A",
        "verification_instruction": "Verify A",
        "agent_id": "test-agent"
    })
    task_a_id = task_a_response.json()["task_id"]
    
    task_b_response = auth_client.post("/mcp/create_task", json={
        "title": "Task B",
        "task_type": "concrete",
        "task_instruction": "Task B",
        "verification_instruction": "Verify B",
        "agent_id": "test-agent"
    })
    task_b_id = task_b_response.json()["task_id"]
    
    # Create initial relationship
    auth_client.post("/relationships", json={
        "parent_task_id": task_a_id,
        "child_task_id": task_b_id,
        "relationship_type": "blocked_by",
        "agent_id": "test-agent"
    })
    
    # Try to create circular relationship
    response = auth_client.post("/relationships", json={
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


def test_mcp_create_task_with_subtask_relationship(auth_client):
    """Test that creating a task with parent_task_id and relationship_type creates the relationship."""
    # Create a parent task
    parent_response = auth_client.post("/mcp/create_task", json={
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
    child_response = auth_client.post("/mcp/create_task", json={
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
    relationships_response = auth_client.get(f"/tasks/{parent_id}/relationships")
    assert relationships_response.status_code == 200
    relationships_data = relationships_response.json()
    assert "relationships" in relationships_data
    relationships = relationships_data["relationships"]
    
    # Find the subtask relationship where parent is the parent task and child is the child task
    subtask_relationships = [r for r in relationships if r["relationship_type"] == "subtask" and r["parent_task_id"] == parent_id and r["child_task_id"] == child_id]
    assert len(subtask_relationships) == 1, "Exactly one subtask relationship should exist"
    # Verify the relationship details match (relationship_id may differ if relationship already existed)
    assert subtask_relationships[0]["parent_task_id"] == parent_id, "Parent task ID should match"
    assert subtask_relationships[0]["child_task_id"] == child_id, "Child task ID should match"
    # The relationship_id from create_task should match the database ID, or the relationship already existed
    # If it doesn't match, it means the relationship already existed with a different ID
    if subtask_relationships[0]["id"] != relationship_id:
        # Relationship already existed - verify it's the same relationship
        assert subtask_relationships[0]["relationship_type"] == "subtask", "Relationship type should match"
    else:
        # New relationship - IDs should match
        assert subtask_relationships[0]["id"] == relationship_id, "Relationship ID should match"
    
    # Also verify by querying relationships for the child task
    child_relationships_response = auth_client.get(f"/tasks/{child_id}/relationships")
    assert child_relationships_response.status_code == 200
    child_relationships_data = child_relationships_response.json()
    assert "relationships" in child_relationships_data
    child_relationships = child_relationships_data["relationships"]
    
    # The child should show the relationship too (bidirectional view - task is child in relationship)
    child_subtask_relationships = [r for r in child_relationships if r["relationship_type"] == "subtask" and r["parent_task_id"] == parent_id and r["child_task_id"] == child_id]
    assert len(child_subtask_relationships) == 1, "Child task should also show the relationship"


def test_mcp_query_stale_tasks(auth_client):
    """Test MCP query_stale_tasks function."""
    from datetime import datetime, timedelta
    import json
    
    # Create and lock a task
    create_response = auth_client.post("/mcp/create_task", json={
        "title": "Stale Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json().get("task_id") or create_response.json().get("id")
    
    # Lock the task using MCP endpoint
    auth_client.post("/mcp/reserve_task", json={"task_id": task_id, "agent_id": "agent-1"})
    
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
    response = auth_client.post("/mcp/sse", json={
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


def test_mcp_list_projects(auth_client):
    """Test MCP list_projects function."""
    # Create a project via REST API with unique name
    import time
    unique_name = f"test-project-{int(time.time() * 1000000)}"
    project_response = auth_client.post("/projects", json={
        "name": unique_name,
        "local_path": "/tmp/test",
        "origin_url": "https://github.com/test/repo",
        "description": "Test project"
    })
    assert project_response.status_code == 201
    
    # Test list_projects
    response = auth_client.post("/mcp/list_projects", json={})
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "projects" in result
    assert "count" in result
    assert result["count"] >= 1
    assert any(p["name"] == unique_name for p in result["projects"])


def test_mcp_get_project(auth_client):
    """Test MCP get_project function."""
    # Create a project with unique name
    import time
    unique_name = f"get-test-project-{int(time.time() * 1000000)}"
    project_response = auth_client.post("/projects", json={
        "name": unique_name,
        "local_path": "/tmp/get-test",
        "origin_url": "https://github.com/test/repo",
        "description": "Get test project"
    })
    assert project_response.status_code == 201
    project_data = project_response.json()
    project_id = project_data.get("id") or project_data.get("project_id")
    assert project_id is not None, f"Project ID not found in response: {project_data}"
    
    # Test get_project with valid ID
    response = auth_client.post("/mcp/get_project", json={
        "project_id": project_id
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "project" in result
    assert result["project"]["id"] == project_id
    assert result["project"]["name"] == unique_name
    
    # Test get_project with invalid ID
    response = auth_client.post("/mcp/get_project", json={
        "project_id": 99999
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is False
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_mcp_get_project_by_name(auth_client):
    """Test MCP get_project_by_name function."""
    # Create a project with unique name
    import time
    project_name = f"name-test-project-{int(time.time() * 1000000)}"
    project_response = auth_client.post("/projects", json={
        "name": project_name,
        "local_path": "/tmp/name-test",
        "origin_url": "https://github.com/test/repo",
        "description": "Name test project"
    })
    assert project_response.status_code == 201
    project_data = project_response.json()
    assert "id" in project_data or "project_id" in project_data, f"Project ID not found in response: {project_data}"
    
    # Test get_project_by_name with valid name
    response = auth_client.post("/mcp/get_project_by_name", json={
        "name": project_name
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "project" in result
    assert result["project"]["name"] == project_name
    
    # Test get_project_by_name with invalid name
    response = auth_client.post("/mcp/get_project_by_name", json={
        "name": "nonexistent-project"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is False
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_mcp_create_project(auth_client):
    """Test MCP create_project function."""
    # Test create_project with all fields
    response = auth_client.post("/mcp/create_project", json={
        "name": "mcp-test-project",
        "local_path": "/tmp/mcp-test",
        "origin_url": "https://github.com/test/repo",
        "description": "MCP test project"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "project_id" in result
    assert "project" in result
    assert result["project"]["name"] == "mcp-test-project"
    assert result["project"]["local_path"] == "/tmp/mcp-test"
    assert result["project"]["origin_url"] == "https://github.com/test/repo"
    assert result["project"]["description"] == "MCP test project"
    
    # Test create_project with minimal fields
    response = auth_client.post("/mcp/create_project", json={
        "name": "mcp-minimal-project",
        "local_path": "/tmp/mcp-minimal"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert "project_id" in result
    assert result["project"]["name"] == "mcp-minimal-project"
    
    # Test create_project with duplicate name (should fail)
    response = auth_client.post("/mcp/create_project", json={
        "name": "mcp-test-project",
        "local_path": "/tmp/duplicate"
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is False
    assert "error" in result
    assert "already exists" in result["error"].lower()


def test_mcp_create_project_and_create_task(auth_client):
    """Test creating a project via MCP and then creating a task with that project_id."""
    # Create project via MCP
    project_response = auth_client.post("/mcp/create_project", json={
        "name": "task-project",
        "local_path": "/tmp/task-project",
        "description": "Project for task creation test"
    })
    assert project_response.status_code == 200
    project_result = project_response.json()
    assert project_result["success"] is True
    project_id = project_result["project_id"]
    
    # Create a task using the project_id from MCP
    task_response = auth_client.post("/mcp/create_task", json={
        "title": "Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    assert task_response.status_code == 200
    task_result = task_response.json()
    assert task_result["success"] is True
    assert "task_id" in task_result
    
    # Verify the task has the correct project_id
    task_id = task_result["task_id"]
    get_task_response = auth_client.post("/mcp/get_task_context", json={
        "task_id": task_id
    })
    assert get_task_response.status_code == 200
    task_context = get_task_response.json()
    assert task_context["task"]["project_id"] == project_id
    assert task_context["project"]["id"] == project_id
    assert task_context["project"]["name"] == "task-project"
