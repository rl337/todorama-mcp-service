"""
Tests for REST API endpoints.
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


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    backups_dir = os.path.join(temp_dir, "backups")
    
    # Create database
    db = TodoDatabase(db_path)
    backup_manager = BackupManager(db_path, backups_dir)
    
    # Override the database and backup manager in the app
    import main
    main.db = db
    main.backup_manager = backup_manager
    
    yield db, db_path, backups_dir
    
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    return TestClient(app)


def test_health_check(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_task(client):
    """Test creating a task via API."""
    response = client.post("/tasks", json={
        "title": "API Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "API Test Task"
    assert data["task_type"] == "concrete"
    assert "id" in data


def test_lock_task(client):
    """Test locking a task."""
    # Create task
    create_response = client.post("/tasks", json={
        "title": "Lock Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Lock task
    lock_response = client.post(f"/tasks/{task_id}/lock", json={"agent_id": "agent-1"})
    assert lock_response.status_code == 200
    
    # Verify locked
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["task_status"] == "in_progress"
    assert task["assigned_agent"] == "agent-1"


def test_complete_task(client):
    """Test completing a task."""
    # Create and lock task
    create_response = client.post("/tasks", json={
        "title": "Complete Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post(f"/tasks/{task_id}/lock", json={"agent_id": "agent-1"})
    
    # Complete task
    complete_response = client.post(
        f"/tasks/{task_id}/complete",
        json={"agent_id": "agent-1", "notes": "Done!"}
    )
    assert complete_response.status_code == 200
    
    # Verify completed
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["task_status"] == "complete"
    
    # Verify task
    verify_response = client.post(f"/tasks/{task_id}/verify", json={"agent_id": "agent-1"})
    assert verify_response.status_code == 200
    
    # Verify verification status
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["verification_status"] == "verified"


def test_mcp_list_available_tasks(client):
    """Test MCP list available tasks."""
    # Create tasks
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
    
    # Get breakdown tasks
    response = client.post("/mcp/list_available_tasks", json={
        "agent_type": "breakdown",
        "limit": 10
    })
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert len(tasks) >= 1
    assert any(t["task_type"] == "abstract" for t in tasks)


def test_backup_create(client):
    """Test creating backup."""
    response = client.post("/backup/create")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "backup_path" in data


def test_backup_list(client):
    """Test listing backups."""
    # Create a backup first
    client.post("/backup/create")
    
    # List backups
    response = client.get("/backup/list")
    assert response.status_code == 200
    data = response.json()
    assert "backups" in data
    assert "count" in data
    assert data["count"] >= 1


def test_backup_restore(client):
    """Test backup and restore functionality."""
    # Create a task
    create_response = client.post("/tasks", json={
        "title": "Restore Test",
        "task_type": "concrete",
        "task_instruction": "Test restore",
        "verification_instruction": "Verify restore",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Create backup
    backup_response = client.post("/backup/create")
    assert backup_response.status_code == 200
    backup_path = backup_response.json()["backup_path"]
    
    # Add another task
    client.post("/tasks", json={
        "title": "Task to be lost",
        "task_type": "concrete",
        "task_instruction": "This will be lost",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    
    # Restore from backup (should have only 1 task)
    restore_response = client.post("/backup/restore", json={
        "backup_path": backup_path,
        "force": True
    })
    assert restore_response.status_code == 200
    assert restore_response.json()["success"] is True
    
    # Verify only original task exists
    tasks_response = client.get("/tasks")
    tasks = tasks_response.json()
    assert len([t for t in tasks if t["title"] == "Restore Test"]) == 1
    assert len([t for t in tasks if t["title"] == "Task to be lost"]) == 0

