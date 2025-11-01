"""
Tests for MCP API functionality.
"""
import pytest
import os
import tempfile
import shutil
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

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

