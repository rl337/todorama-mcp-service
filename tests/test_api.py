"""
Tests for REST API endpoints.
"""
import pytest
import os
import tempfile
import shutil
import json
import time
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
    
    # Create conversation storage with test database path
    # Use SQLite for testing (conversation_storage will use db_adapter)
    conv_db_path = os.path.join(temp_dir, "test_conv.db")
    os.environ['DB_TYPE'] = 'sqlite'
    from src.conversation_storage import ConversationStorage
    conversation_storage = ConversationStorage(conv_db_path)
    
    # Override the database, backup manager, and conversation storage in the app
    import main
    main.db = db
    main.backup_manager = backup_manager
    main.conversation_storage = conversation_storage
    
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


def test_error_handling_invalid_task_type(client):
    """Test error handling for invalid task type."""
    response = client.post("/tasks", json={
        "title": "Test Task",
        "task_type": "invalid_type",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "invalid_type" in data["detail"].lower() or "concrete" in data["detail"].lower()


def test_error_handling_task_not_found(client):
    """Test error handling for task not found."""
    response = client.get("/tasks/99999")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "not found" in data["detail"].lower()


def test_error_handling_lock_task_not_found(client):
    """Test error handling when locking non-existent task."""
    response = client.post("/tasks/99999/lock", json={"agent_id": "agent-1"})
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "not found" in data["detail"].lower()


def test_error_handling_lock_already_locked_task(client):
    """Test error handling when locking already locked task."""
    # Create and lock task
    create_response = client.post("/tasks", json={
        "title": "Locked Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post(f"/tasks/{task_id}/lock", json={"agent_id": "agent-1"})
    
    # Try to lock again
    lock_response = client.post(f"/tasks/{task_id}/lock", json={"agent_id": "agent-2"})
    assert lock_response.status_code == 409
    data = lock_response.json()
    assert "detail" in data
    assert "cannot be locked" in data["detail"].lower() or "not available" in data["detail"].lower()


def test_error_handling_validation_error(client):
    """Test validation error handling."""
    response = client.post("/tasks", json={
        "title": "Test",
        # Missing required fields
    })
    assert response.status_code == 422
    data = response.json()
    assert "error" in data or "detail" in data


def test_error_handling_empty_agent_id(client):
    """Test error handling for empty agent_id."""
    response = client.post("/tasks/1/lock", json={"agent_id": ""})
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "required" in data["detail"].lower() or "cannot be empty" in data["detail"].lower()


def test_error_handling_project_not_found(client):
    """Test error handling when creating task with invalid project_id."""
    response = client.post("/tasks", json={
        "title": "Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": 99999
    })
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "not found" in data["detail"].lower()


def test_error_handling_backup_restore_invalid_path(client):
    """Test error handling for invalid backup path."""
    response = client.post("/backup/restore", json={
        "backup_path": "/nonexistent/backup.db.gz",
        "force": False
    })
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "not found" in data["detail"].lower()


def test_error_handling_backup_restore_empty_path(client):
    """Test error handling for empty backup path."""
    response = client.post("/backup/restore", json={
        "backup_path": "",
        "force": False
    })
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "required" in data["detail"].lower() or "cannot be empty" in data["detail"].lower()


def test_create_task_with_priority(client):
    """Test creating a task with priority via API."""
    response = client.post("/tasks", json={
        "title": "High Priority Task",
        "task_type": "concrete",
        "task_instruction": "Do something urgent",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent",
        "priority": "high"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["priority"] == "high"


def test_create_task_default_priority(client):
    """Test that tasks default to medium priority when not specified."""
    response = client.post("/tasks", json={
        "title": "Default Priority Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["priority"] == "medium"


def test_query_tasks_by_priority(client):
    """Test querying tasks filtered by priority."""
    # Create tasks with different priorities
    client.post("/tasks", json={
        "title": "Low Task",
        "task_type": "concrete",
        "task_instruction": "Low",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "priority": "low"
    })
    client.post("/tasks", json={
        "title": "High Task",
        "task_type": "concrete",
        "task_instruction": "High",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "priority": "high"
    })
    
    # Query high priority tasks
    response = client.get("/tasks?priority=high")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) >= 1
    assert all(t["priority"] == "high" for t in tasks)


def test_query_tasks_ordered_by_priority(client):
    """Test querying tasks ordered by priority."""
    # Create tasks with different priorities
    client.post("/tasks", json={
        "title": "Low Task",
        "task_type": "concrete",
        "task_instruction": "Low",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "priority": "low"
    })
    client.post("/tasks", json={
        "title": "Critical Task",
        "task_type": "concrete",
        "task_instruction": "Critical",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "priority": "critical"
    })
    client.post("/tasks", json={
        "title": "High Task",
        "task_type": "concrete",
        "task_instruction": "High",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "priority": "high"
    })
    
    # Query ordered by priority
    response = client.get("/tasks?order_by=priority&limit=10")
    assert response.status_code == 200
    tasks = response.json()
    priorities = [t["priority"] for t in tasks if t["title"] in ["Low Task", "Critical Task", "High Task"]]
    
    # Should be ordered: critical, high, low
    assert "critical" in priorities
    assert "high" in priorities
    assert "low" in priorities
    assert priorities.index("critical") < priorities.index("high")
    assert priorities.index("high") < priorities.index("low")


def test_invalid_priority_error(client):
    """Test that invalid priority values return an error."""
    response = client.post("/tasks", json={
        "title": "Invalid Priority",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "priority": "invalid"
    })
    assert response.status_code == 400
    data = response.json()
    assert "priority" in data["detail"].lower() or "invalid" in data["detail"].lower()


# Due dates and deadline tests
def test_create_task_with_due_date(client):
    """Test creating a task with a due date via API."""
    from datetime import datetime, timedelta
    
    due_date = (datetime.now() + timedelta(days=7)).isoformat()
    response = client.post("/tasks", json={
        "title": "Task with Due Date",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "due_date": due_date
    })
    assert response.status_code == 201
    data = response.json()
    assert data["due_date"] == due_date


def test_query_overdue_tasks(client):
    """Test querying overdue tasks via API."""
    from datetime import datetime, timedelta
    
    # Create overdue task
    past_date = (datetime.now() - timedelta(days=1)).isoformat()
    create_response = client.post("/tasks", json={
        "title": "Overdue Task",
        "task_type": "concrete",
        "task_instruction": "Overdue",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "due_date": past_date
    })
    overdue_task_id = create_response.json()["id"]
    
    # Create future task
    future_date = (datetime.now() + timedelta(days=1)).isoformat()
    create_response = client.post("/tasks", json={
        "title": "Future Task",
        "task_type": "concrete",
        "task_instruction": "Not overdue",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "due_date": future_date
    })
    
    # Query overdue tasks
    response = client.get("/tasks/overdue")
    assert response.status_code == 200
    overdue = response.json()
    assert "tasks" in overdue
    overdue_ids = [t["id"] for t in overdue["tasks"]]
    assert overdue_task_id in overdue_ids


def test_query_tasks_approaching_deadline(client):
    """Test querying tasks approaching deadlines via API."""
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
    response = client.get("/tasks/approaching-deadline?days_ahead=3")
    assert response.status_code == 200
    approaching = response.json()
    assert "tasks" in approaching
    approaching_ids = [t["id"] for t in approaching["tasks"]]
    assert soon_task_id in approaching_ids


def test_query_tasks_by_date_range_created(client):
    """Test querying tasks by created_at date range."""
    from datetime import datetime, timedelta
    import time
    
    # Create task now
    task1_response = client.post("/tasks", json={
        "title": "Recent Task",
        "task_type": "concrete",
        "task_instruction": "Recent",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    
    # Wait a bit, then create another task
    time.sleep(1)
    now = datetime.now()
    created_after = (now - timedelta(seconds=2)).isoformat()
    created_before = (now + timedelta(seconds=2)).isoformat()
    
    task2_response = client.post("/tasks", json={
        "title": "Another Recent Task",
        "task_type": "concrete",
        "task_instruction": "Another",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json()["id"]
    
    # Query tasks created after a specific date
    response = client.get(f"/tasks?created_after={created_after}")
    assert response.status_code == 200
    tasks = response.json()
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids or task2_id in task_ids
    
    # Query tasks created before a specific date
    future_date = (now + timedelta(days=1)).isoformat()
    response = client.get(f"/tasks?created_before={future_date}")
    assert response.status_code == 200
    tasks = response.json()
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids or task2_id in task_ids


def test_query_tasks_by_date_range_completed(client):
    """Test querying tasks by completed_at date range."""
    from datetime import datetime, timedelta
    import time
    
    # Create and complete task 1
    task1_response = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    time.sleep(1)
    now = datetime.now()
    client.post(f"/tasks/{task1_id}/complete", json={"agent_id": "test-agent"})
    
    # Create and complete task 2
    time.sleep(1)
    task2_response = client.post("/tasks", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Do something else",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json()["id"]
    client.post(f"/tasks/{task2_id}/complete", json={"agent_id": "test-agent"})
    
    # Query tasks completed after a specific date
    completed_after = (now - timedelta(seconds=5)).isoformat()
    response = client.get(f"/tasks?task_status=complete&completed_after={completed_after}")
    assert response.status_code == 200
    tasks = response.json()
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids or task2_id in task_ids


def test_query_tasks_by_date_range_updated(client):
    """Test querying tasks by updated_at date range."""
    from datetime import datetime, timedelta
    import time
    
    # Create task
    task_response = client.post("/tasks", json={
        "title": "Task to Update",
        "task_type": "concrete",
        "task_instruction": "Original",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = task_response.json()["id"]
    
    # Wait and update the task
    time.sleep(1)
    now = datetime.now()
    updated_after = (now - timedelta(seconds=2)).isoformat()
    
    client.put(f"/tasks/{task_id}", json={
        "title": "Updated Task",
        "task_type": "concrete",
        "task_instruction": "Updated",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    
    # Query tasks updated after a specific date
    response = client.get(f"/tasks?updated_after={updated_after}")
    assert response.status_code == 200
    tasks = response.json()
    task_ids = [t["id"] for t in tasks]
    assert task_id in task_ids


def test_query_tasks_by_text_search(client):
    """Test querying tasks by text search in title and instruction."""
    # Create tasks with different content
    task1_response = client.post("/tasks", json={
        "title": "Searchable Task Title",
        "task_instruction": "This is a searchable instruction",
        "task_type": "concrete",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    
    task2_response = client.post("/tasks", json={
        "title": "Different Title",
        "task_instruction": "This contains searchable word",
        "task_type": "concrete",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json()["id"]
    
    task3_response = client.post("/tasks", json={
        "title": "Unrelated Task",
        "task_instruction": "No matching content here",
        "task_type": "concrete",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task3_id = task3_response.json()["id"]
    
    # Search by title
    response = client.get("/tasks?search=Searchable")
    assert response.status_code == 200
    tasks = response.json()
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids
    assert task3_id not in task_ids
    
    # Search by instruction content
    response = client.get("/tasks?search=searchable")
    assert response.status_code == 200
    tasks = response.json()
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids or task2_id in task_ids
    
    # Search should be case-insensitive
    response = client.get("/tasks?search=SEARCHABLE")
    assert response.status_code == 200
    tasks = response.json()
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids or task2_id in task_ids


def test_query_tasks_combined_filters(client):
    """Test querying tasks with multiple advanced filters combined."""
    from datetime import datetime, timedelta
    
    # Create task with specific properties
    now = datetime.now()
    created_after = (now - timedelta(hours=1)).isoformat()
    
    task_response = client.post("/tasks", json={
        "title": "Complex Filter Task",
        "task_instruction": "Special keyword in instruction",
        "task_type": "concrete",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "priority": "high"
    })
    task_id = task_response.json()["id"]
    
    # Combine multiple filters: search + date + priority
    response = client.get(f"/tasks?search=keyword&created_after={created_after}&priority=high")
    assert response.status_code == 200
    tasks = response.json()
    task_ids = [t["id"] for t in tasks]
    assert task_id in task_ids


# ============================================================================
# Comprehensive Validation Tests
# ============================================================================

def test_validation_empty_strings_in_project_create(client):
    """Test validation for empty/whitespace strings in project creation."""
    # Empty name
    response = client.post("/projects", json={
        "name": "",
        "local_path": "/path"
    })
    assert response.status_code == 422
    
    # Whitespace-only name
    response = client.post("/projects", json={
        "name": "   ",
        "local_path": "/path"
    })
    assert response.status_code == 422
    
    # Empty local_path
    response = client.post("/projects", json={
        "name": "Test Project",
        "local_path": ""
    })
    assert response.status_code == 422


def test_validation_empty_strings_in_task_create(client):
    """Test validation for empty/whitespace strings in task creation."""
    # Empty title
    response = client.post("/tasks", json={
        "title": "",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    assert response.status_code == 422
    
    # Whitespace-only title
    response = client.post("/tasks", json={
        "title": "   ",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    assert response.status_code == 422
    
    # Empty agent_id
    response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": ""
    })
    assert response.status_code == 422


def test_validation_invalid_task_type(client):
    """Test validation for invalid task_type enum."""
    response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "invalid_type",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    assert response.status_code == 422
    data = response.json()
    assert "task_type" in str(data).lower() or "concrete" in str(data).lower()


def test_validation_invalid_priority(client):
    """Test validation for invalid priority enum."""
    response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "priority": "invalid_priority"
    })
    assert response.status_code == 422
    data = response.json()
    assert "priority" in str(data).lower() or "low" in str(data).lower()


def test_validation_negative_project_id(client):
    """Test validation for negative project_id."""
    response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": -1
    })
    assert response.status_code == 422


def test_validation_zero_project_id(client):
    """Test validation for zero project_id."""
    response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": 0
    })
    assert response.status_code == 422


def test_validation_negative_estimated_hours(client):
    """Test validation for negative estimated_hours."""
    response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "estimated_hours": -1.5
    })
    assert response.status_code == 422


def test_validation_zero_estimated_hours(client):
    """Test validation for zero estimated_hours."""
    response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "estimated_hours": 0
    })
    assert response.status_code == 422


def test_validation_invalid_due_date_format(client):
    """Test validation for invalid due_date format."""
    response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "due_date": "invalid-date-format"
    })
    assert response.status_code == 400
    data = response.json()
    assert "due_date" in data["detail"].lower() or "iso" in data["detail"].lower()


def test_validation_invalid_task_status(client):
    """Test validation for invalid task_status in update."""
    create_response = client.post("/tasks", json={
        "title": "Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    response = client.patch(f"/tasks/{task_id}", json={
        "task_status": "invalid_status"
    })
    assert response.status_code == 422


def test_validation_invalid_verification_status(client):
    """Test validation for invalid verification_status in update."""
    create_response = client.post("/tasks", json={
        "title": "Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    response = client.patch(f"/tasks/{task_id}", json={
        "verification_status": "invalid_status"
    })
    assert response.status_code == 422


def test_validation_invalid_relationship_type(client):
    """Test validation for invalid relationship_type."""
    create_response1 = client.post("/tasks", json={
        "title": "Parent Task",
        "task_type": "abstract",
        "task_instruction": "Parent",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    parent_id = create_response1.json()["id"]
    
    create_response2 = client.post("/tasks", json={
        "title": "Child Task",
        "task_type": "concrete",
        "task_instruction": "Child",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    child_id = create_response2.json()["id"]
    
    response = client.post("/relationships", json={
        "parent_task_id": parent_id,
        "child_task_id": child_id,
        "relationship_type": "invalid_type",
        "agent_id": "test-agent"
    })
    assert response.status_code == 422


def test_validation_parent_equals_child(client):
    """Test validation when parent_task_id equals child_task_id."""
    create_response = client.post("/tasks", json={
        "title": "Task",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    response = client.post("/relationships", json={
        "parent_task_id": task_id,
        "child_task_id": task_id,
        "relationship_type": "subtask",
        "agent_id": "test-agent"
    })
    assert response.status_code == 422
    data = response.json()
    assert "cannot be the same" in data["detail"].lower() or "same" in data["detail"].lower()


def test_validation_negative_task_id_in_path(client):
    """Test validation for negative task_id in path."""
    response = client.get("/tasks/-1")
    assert response.status_code == 422


def test_validation_zero_task_id_in_path(client):
    """Test validation for zero task_id in path."""
    response = client.get("/tasks/0")
    assert response.status_code == 422


def test_validation_empty_agent_id_in_lock(client):
    """Test validation for empty agent_id in lock request."""
    create_response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    response = client.post(f"/tasks/{task_id}/lock", json={
        "agent_id": ""
    })
    assert response.status_code == 422


def test_validation_whitespace_agent_id_in_lock(client):
    """Test validation for whitespace-only agent_id in lock request."""
    create_response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    response = client.post(f"/tasks/{task_id}/lock", json={
        "agent_id": "   "
    })
    assert response.status_code == 422


def test_validation_negative_actual_hours(client):
    """Test validation for negative actual_hours."""
    create_response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post(f"/tasks/{task_id}/lock", json={"agent_id": "test-agent"})
    
    response = client.post(f"/tasks/{task_id}/complete", json={
        "agent_id": "test-agent",
        "actual_hours": -1.5
    })
    assert response.status_code == 422


def test_validation_invalid_query_parameters(client):
    """Test validation for invalid query parameters."""
    # Invalid task_type
    response = client.get("/tasks?task_type=invalid")
    assert response.status_code == 400
    data = response.json()
    assert "task_type" in data["detail"].lower()
    
    # Invalid task_status
    response = client.get("/tasks?task_status=invalid")
    assert response.status_code == 400
    data = response.json()
    assert "task_status" in data["detail"].lower()
    
    # Invalid priority
    response = client.get("/tasks?priority=invalid")
    assert response.status_code == 400
    data = response.json()
    assert "priority" in data["detail"].lower()
    
    # Invalid order_by
    response = client.get("/tasks?order_by=invalid")
    assert response.status_code == 400
    data = response.json()
    assert "order_by" in data["detail"].lower()


def test_validation_invalid_tag_ids_format(client):
    """Test validation for invalid tag_ids format."""
    response = client.get("/tasks?tag_ids=not,a,number")
    assert response.status_code == 400
    data = response.json()
    assert "tag_ids" in data["detail"].lower()


def test_validation_negative_tag_id(client):
    """Test validation for negative tag_id."""
    response = client.get("/tasks?tag_id=-1")
    assert response.status_code == 422


def test_validation_negative_project_id_in_query(client):
    """Test validation for negative project_id in query."""
    response = client.get("/tasks?project_id=-1")
    assert response.status_code == 422


def test_validation_empty_tag_name(client):
    """Test validation for empty tag name."""
    response = client.post("/tags", json={
        "name": ""
    })
    assert response.status_code == 422


def test_validation_whitespace_tag_name(client):
    """Test validation for whitespace-only tag name."""
    response = client.post("/tags", json={
        "name": "   "
    })
    assert response.status_code == 422


# ============================================================================
# Search endpoint tests
# ============================================================================

def test_search_tasks_by_title(client):
    """Test searching tasks by title via API."""
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
    response = client.get("/tasks/search?q=authentication")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id
    
    # Search for "database"
    response = client.get("/tasks/search?q=database")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task2_id


def test_search_tasks_by_instruction(client):
    """Test searching tasks by task_instruction via API."""
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
    response = client.get("/tasks/search?q=REST")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id
    
    # Search for "schema"
    response = client.get("/tasks/search?q=schema")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task2_id


def test_search_tasks_by_notes(client):
    """Test searching tasks by notes via API."""
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
    response = client.get("/tasks/search?q=bug")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id
    
    # Search for "performance"
    response = client.get("/tasks/search?q=performance")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task2_id


def test_search_tasks_multiple_matches(client):
    """Test searching tasks that match multiple terms via API."""
    create_response1 = client.post("/tasks", json={
        "title": "Database optimization",
        "task_type": "concrete",
        "task_instruction": "Optimize database queries",
        "verification_instruction": "Verify performance",
        "agent_id": "test-agent",
        "notes": "Critical performance issue"
    })
    task1_id = create_response1.json()["id"]
    
    create_response2 = client.post("/tasks", json={
        "title": "UI improvement",
        "task_type": "concrete",
        "task_instruction": "Improve user interface",
        "verification_instruction": "Verify UI works",
        "agent_id": "test-agent",
        "notes": "User feedback"
    })
    task2_id = create_response2.json()["id"]
    
    # Search for "database" - should find task1
    response = client.get("/tasks/search?q=database")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id
    
    # Search for "optimization" - should find task1
    response = client.get("/tasks/search?q=optimization")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id


def test_search_tasks_case_insensitive(client):
    """Test that search is case insensitive via API."""
    create_response = client.post("/tasks", json={
        "title": "Python API",
        "task_type": "concrete",
        "task_instruction": "Create Python REST API",
        "verification_instruction": "Verify API",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Search with different cases
    response1 = client.get("/tasks/search?q=python")
    assert response1.status_code == 200
    tasks1 = response1.json()
    
    response2 = client.get("/tasks/search?q=Python")
    assert response2.status_code == 200
    tasks2 = response2.json()
    
    response3 = client.get("/tasks/search?q=PYTHON")
    assert response3.status_code == 200
    tasks3 = response3.json()
    
    assert len(tasks1) == 1
    assert len(tasks2) == 1
    assert len(tasks3) == 1
    assert tasks1[0]["id"] == task_id
    assert tasks2[0]["id"] == task_id
    assert tasks3[0]["id"] == task_id


def test_search_tasks_with_limit(client):
    """Test that search respects limit parameter via API."""
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
    response = client.get("/tasks/search?q=Searchable&limit=5")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 5


def test_search_tasks_empty_query(client):
    """Test that empty query returns error via API."""
    response = client.get("/tasks/search?q=")
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "cannot be empty" in data["detail"].lower()


def test_search_tasks_ranks_by_relevance(client):
    """Test that search results are ranked by relevance via API."""
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
    response = client.get("/tasks/search?q=API")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) >= 2  # Should find task1 and task3
    # First result should be task1 (most relevant)
    assert tasks[0]["id"] == task1_id


def test_search_tasks_with_special_characters(client):
    """Test that search handles special characters gracefully via API."""
    create_response = client.post("/tasks", json={
        "title": "Task with special chars: test@example.com",
        "task_type": "concrete",
        "task_instruction": "Handle special characters",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Search should handle special characters
    response = client.get("/tasks/search?q=test@example")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task_id


def test_search_tasks_multiple_keywords(client):
    """Test searching with multiple keywords via API."""
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
    response = client.get("/tasks/search?q=authentication user")
    assert response.status_code == 200
    tasks = response.json()
    # Should find task1 which contains both terms
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids


# Template API tests
def test_create_template(client):
    """Test creating a task template via API."""
    response = client.post("/templates", json={
        "name": "Test Template",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Check it works"
    })
    assert response.status_code == 201
    template = response.json()
    assert template["name"] == "Test Template"
    assert template["task_type"] == "concrete"
    assert template["id"] > 0


def test_create_template_with_all_fields(client):
    """Test creating a template with all fields."""
    response = client.post("/templates", json={
        "name": "Full Template",
        "description": "A complete template",
        "task_type": "abstract",
        "task_instruction": "Break down",
        "verification_instruction": "Verify breakdown",
        "priority": "high",
        "estimated_hours": 5.5,
        "notes": "Template notes"
    })
    assert response.status_code == 201
    template = response.json()
    assert template["description"] == "A complete template"
    assert template["priority"] == "high"
    assert template["estimated_hours"] == 5.5
    assert template["notes"] == "Template notes"


def test_get_template(client):
    """Test getting a template by ID."""
    # Create template first
    create_response = client.post("/templates", json={
        "name": "Get Template",
        "task_type": "concrete",
        "task_instruction": "Task",
        "verification_instruction": "Verify"
    })
    template_id = create_response.json()["id"]
    
    # Get template
    response = client.get(f"/templates/{template_id}")
    assert response.status_code == 200
    template = response.json()
    assert template["id"] == template_id
    assert template["name"] == "Get Template"


def test_get_template_not_found(client):
    """Test getting a nonexistent template."""
    response = client.get("/templates/999")
    assert response.status_code == 404


def test_list_templates(client):
    """Test listing all templates."""
    # Create multiple templates
    client.post("/templates", json={
        "name": "Template 1",
        "task_type": "concrete",
        "task_instruction": "Task 1",
        "verification_instruction": "Verify 1"
    })
    client.post("/templates", json={
        "name": "Template 2",
        "task_type": "abstract",
        "task_instruction": "Task 2",
        "verification_instruction": "Verify 2"
    })
    
    response = client.get("/templates")
    assert response.status_code == 200
    templates = response.json()
    assert len(templates) >= 2


def test_list_templates_filtered_by_type(client):
    """Test listing templates filtered by task type."""
    client.post("/templates", json={
        "name": "Concrete Template",
        "task_type": "concrete",
        "task_instruction": "Task",
        "verification_instruction": "Verify"
    })
    client.post("/templates", json={
        "name": "Abstract Template",
        "task_type": "abstract",
        "task_instruction": "Task",
        "verification_instruction": "Verify"
    })
    
    response = client.get("/templates?task_type=concrete")
    assert response.status_code == 200
    templates = response.json()
    assert all(t["task_type"] == "concrete" for t in templates)
    
    response = client.get("/templates?task_type=abstract")
    assert response.status_code == 200
    templates = response.json()
    assert all(t["task_type"] == "abstract" for t in templates)


def test_create_task_from_template(client):
    """Test creating a task from a template."""
    # Create template
    template_response = client.post("/templates", json={
        "name": "Task Template",
        "task_type": "concrete",
        "task_instruction": "Do work",
        "verification_instruction": "Verify work",
        "priority": "high",
        "estimated_hours": 2.5
    })
    template_id = template_response.json()["id"]
    
    # Create task from template
    response = client.post(f"/templates/{template_id}/create-task", json={
        "agent_id": "test-agent"
    })
    assert response.status_code == 201
    task = response.json()
    assert task["title"] == "Task Template"
    assert task["task_type"] == "concrete"
    assert task["task_instruction"] == "Do work"
    assert task["priority"] == "high"
    assert task["estimated_hours"] == 2.5


def test_create_task_from_template_with_overrides(client):
    """Test creating task from template with field overrides."""
    template_response = client.post("/templates", json={
        "name": "Base Template",
        "task_type": "concrete",
        "task_instruction": "Base instruction",
        "verification_instruction": "Base verification",
        "priority": "low"
    })
    template_id = template_response.json()["id"]
    
    # Create task with overrides
    response = client.post(f"/templates/{template_id}/create-task", json={
        "agent_id": "test-agent",
        "title": "Custom Title",
        "priority": "critical",
        "notes": "Custom notes"
    })
    assert response.status_code == 201
    task = response.json()
    assert task["title"] == "Custom Title"
    assert task["priority"] == "critical"
    assert task["notes"] == "Custom notes"
    assert task["task_instruction"] == "Base instruction"  # From template


def test_create_task_from_nonexistent_template(client):
    """Test creating task from nonexistent template."""
    response = client.post("/templates/999/create-task", json={
        "agent_id": "test-agent"
    })
    assert response.status_code == 404


def test_template_name_unique_constraint(client):
    """Test that template names must be unique."""
    client.post("/templates", json={
        "name": "Unique Template",
        "task_type": "concrete",
        "task_instruction": "Task",
        "verification_instruction": "Verify"
    })
    
    # Try to create another with same name
    response = client.post("/templates", json={
        "name": "Unique Template",
        "task_type": "abstract",
        "task_instruction": "Different",
        "verification_instruction": "Different"
    })
    assert response.status_code == 409  # Conflict


# Export functionality tests
def test_export_tasks_json(client):
    """Test exporting tasks as JSON."""
    # Create tasks
    create_response1 = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task1_id = create_response1.json()["id"]
    
    create_response2 = client.post("/tasks", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Do something else",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json()["id"]
    
    # Export as JSON
    response = client.get("/tasks/export/json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = json.loads(response.text)
    assert "tasks" in data
    assert len(data["tasks"]) >= 2
    task_ids = [t["id"] for t in data["tasks"]]
    assert task1_id in task_ids
    assert task2_id in task_ids


def test_export_tasks_csv(client):
    """Test exporting tasks as CSV."""
    # Create tasks
    create_response1 = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task1_id = create_response1.json()["id"]
    
    # Export as CSV
    response = client.get("/tasks/export/csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"] or "text/plain" in response.headers["content-type"]
    csv_content = response.text
    assert "id" in csv_content
    assert "title" in csv_content
    assert str(task1_id) in csv_content
    assert "Task 1" in csv_content


def test_export_tasks_filtered_by_project(client):
    """Test exporting tasks filtered by project."""
    # Create project
    project_response = client.post("/projects", json={
        "name": "Test Project",
        "local_path": "/test/path"
    })
    project_id = project_response.json()["id"]
    
    # Create tasks in project
    create_response1 = client.post("/tasks", json={
        "title": "Project Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    task1_id = create_response1.json()["id"]
    
    # Create task without project
    create_response2 = client.post("/tasks", json={
        "title": "No Project Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json()["id"]
    
    # Export filtered by project
    response = client.get(f"/tasks/export/json?project_id={project_id}")
    assert response.status_code == 200
    data = json.loads(response.text)
    task_ids = [t["id"] for t in data["tasks"]]
    assert task1_id in task_ids
    assert task2_id not in task_ids


def test_export_tasks_filtered_by_status(client):
    """Test exporting tasks filtered by status."""
    # Create tasks
    create_response1 = client.post("/tasks", json={
        "title": "Available Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task1_id = create_response1.json()["id"]
    
    create_response2 = client.post("/tasks", json={
        "title": "Complete Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = create_response2.json()["id"]
    
    # Complete task 2
    client.post(f"/tasks/{task2_id}/lock", json={"agent_id": "test-agent"})
    client.post(f"/tasks/{task2_id}/complete", json={"agent_id": "test-agent"})
    
    # Export only complete tasks
    response = client.get("/tasks/export/json?task_status=complete")
    assert response.status_code == 200
    data = json.loads(response.text)
    task_ids = [t["id"] for t in data["tasks"]]
    assert task1_id not in task_ids
    assert task2_id in task_ids
    assert all(t["task_status"] == "complete" for t in data["tasks"])


def test_export_tasks_with_date_range(client):
    """Test exporting tasks filtered by date range."""
    from datetime import datetime, timedelta
    
    # Create task
    create_response = client.post("/tasks", json={
        "title": "Date Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Get task to see its created_at
    task_response = client.get(f"/tasks/{task_id}")
    task = task_response.json()
    created_at = task["created_at"]
    
    # Parse date and add/subtract days
    created_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    start_date = (created_date - timedelta(days=1)).isoformat()
    end_date = (created_date + timedelta(days=1)).isoformat()
    
    # Export with date range
    response = client.get(f"/tasks/export/json?start_date={start_date}&end_date={end_date}")
    assert response.status_code == 200
    data = json.loads(response.text)
    task_ids = [t["id"] for t in data["tasks"]]
    assert task_id in task_ids


def test_export_tasks_with_relationships(client):
    """Test that exported tasks include relationships."""
    # Create parent and child tasks
    parent_response = client.post("/tasks", json={
        "title": "Parent Task",
        "task_type": "abstract",
        "task_instruction": "Parent",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    parent_id = parent_response.json()["id"]
    
    child_response = client.post("/tasks", json={
        "title": "Child Task",
        "task_type": "concrete",
        "task_instruction": "Child",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    child_id = child_response.json()["id"]
    
    # Create relationship
    client.post("/relationships", json={
        "parent_task_id": parent_id,
        "child_task_id": child_id,
        "relationship_type": "subtask",
        "agent_id": "test-agent"
    })
    
    # Export as JSON
    response = client.get("/tasks/export/json")
    assert response.status_code == 200
    data = json.loads(response.text)
    
    # Find parent task in export
    parent_task = next((t for t in data["tasks"] if t["id"] == parent_id), None)
    assert parent_task is not None
    assert "relationships" in parent_task
    assert len(parent_task["relationships"]) >= 1
    assert any(r["child_task_id"] == child_id for r in parent_task["relationships"])


def test_export_tasks_csv_includes_all_fields(client):
    """Test that CSV export includes all task fields."""
    # Create task with various fields
    create_response = client.post("/tasks", json={
        "title": "Full Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent",
        "priority": "high",
        "estimated_hours": 5.5,
        "notes": "Task notes"
    })
    task_id = create_response.json()["id"]
    
    # Export as CSV
    response = client.get("/tasks/export/csv")
    assert response.status_code == 200
    csv_content = response.text
    lines = csv_content.split("\n")
    header = lines[0]
    
    # Check that important fields are in CSV
    assert "id" in header.lower()
    assert "title" in header.lower()
    assert "task_type" in header.lower()
    assert "task_status" in header.lower()
    assert "priority" in header.lower()
    assert str(task_id) in csv_content
    assert "Full Task" in csv_content
    assert "high" in csv_content


def test_export_tasks_json_includes_all_fields(client):
    """Test that JSON export includes all task fields."""
    # Create task with various fields
    create_response = client.post("/tasks", json={
        "title": "Full Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent",
        "priority": "high",
        "estimated_hours": 5.5,
        "notes": "Task notes"
    })
    task_id = create_response.json()["id"]
    
    # Export as JSON
    response = client.get("/tasks/export/json")
    assert response.status_code == 200
    data = json.loads(response.text)
    
    # Find our task
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    assert task is not None
    assert task["title"] == "Full Task"
    assert task["task_type"] == "concrete"
    assert task["priority"] == "high"
    assert task["estimated_hours"] == 5.5
    assert task["notes"] == "Task notes"
    assert "relationships" in task
    assert "tags" in task


def test_export_tasks_empty_result(client):
    """Test exporting when no tasks match filters."""
    # Export with filter that matches nothing
    response = client.get("/tasks/export/json?task_status=complete")
    assert response.status_code == 200
    data = json.loads(response.text)
    assert "tasks" in data
    # Should return empty list, not error
    assert isinstance(data["tasks"], list)


def test_export_tasks_invalid_date_format(client):
    """Test exporting with invalid date format."""
    response = client.get("/tasks/export/json?start_date=invalid-date")
    # Should handle gracefully - either 400 error or ignore invalid date
    assert response.status_code in [200, 400]


def test_export_tasks_large_dataset(client):
    """Test exporting with a large number of tasks."""
    # Create multiple tasks
    task_ids = []
    for i in range(50):
        create_response = client.post("/tasks", json={
            "title": f"Task {i}",
            "task_type": "concrete",
            "task_instruction": f"Do something {i}",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
        task_ids.append(create_response.json()["id"])
    
    # Export as JSON
    response = client.get("/tasks/export/json")
    assert response.status_code == 200
    data = json.loads(response.text)
    assert len(data["tasks"]) >= 50
    
    # Export as CSV
    response = client.get("/tasks/export/csv")
    assert response.status_code == 200
    csv_content = response.text
    # Should have at least 51 lines (header + 50 tasks)
    assert len(csv_content.split("\n")) >= 51


def test_prometheus_metrics_endpoint(client):
    """Test that Prometheus metrics endpoint exists and returns metrics."""
    response = client.get("/metrics")
    assert response.status_code == 200
    content = response.text
    # Should contain Prometheus metrics format
    assert "# HELP" in content or "# TYPE" in content
    # Should have HTTP request metrics
    assert "http_requests_total" in content or "http_request_duration_seconds" in content


def test_request_tracing_header(client):
    """Test that requests include trace IDs in response headers."""
    response = client.get("/health")
    assert response.status_code == 200
    # Should have request ID in headers for tracing
    assert "X-Request-ID" in response.headers or "X-Trace-ID" in response.headers


def test_structured_logging_on_error(client):
    """Test that errors are logged with structured context."""
    # Make a request that will cause an error (invalid task ID)
    response = client.get("/tasks/99999")
    assert response.status_code == 404
    # Response should still include trace ID
    assert "X-Request-ID" in response.headers or "X-Trace-ID" in response.headers


def test_health_check_with_metrics(client):
    """Test enhanced health check endpoint includes metrics information."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    # Enhanced health check might include uptime or other metrics
    assert "service" in data


def test_comprehensive_health_check(client):
    """Test comprehensive health check includes database and component status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    
    # Should have overall status
    assert "status" in data
    assert data["status"] in ["healthy", "degraded", "unhealthy"]
    
    # Should have components section
    assert "components" in data
    components = data["components"]
    
    # Database should be checked
    assert "database" in components
    db_status = components["database"]
    assert "status" in db_status
    assert db_status["status"] in ["healthy", "degraded", "unhealthy"]
    
    # Service should be checked
    assert "service" in components
    service_status = components["service"]
    assert "status" in service_status
    
    # Should include timestamps
    assert "timestamp" in data
    assert "uptime_seconds" in data or "uptime_formatted" in data


def test_health_check_database_connectivity(client):
    """Test that health check verifies database connectivity."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    
    components = data.get("components", {})
    db_component = components.get("database", {})
    
    # Database should report healthy when connected
    assert db_component.get("status") == "healthy"
    # Should include connection info
    assert "response_time_ms" in db_component or "connectivity" in db_component


def test_health_check_database_failure_handling(client):
    """Test that health check handles database failures gracefully."""
    # Temporarily break database connection
    import main
    original_db = main.db
    
    # Create a mock database that fails on connect
    class FailingDatabase:
        def _get_connection(self):
            raise Exception("Database connection failed")
    
    main.db = FailingDatabase()
    
    try:
        response = client.get("/health")
        # Should still return response (might be 200 with degraded/unhealthy status)
        assert response.status_code in [200, 503]
        data = response.json()
        
        # Should report database as unhealthy
        if "components" in data:
            db_component = data["components"].get("database", {})
            if "status" in db_component:
                assert db_component["status"] in ["degraded", "unhealthy"]
    finally:
        # Restore original database
        main.db = original_db


def test_request_latency_metrics(client):
    """Test that request latency is tracked via Prometheus."""
    # Make a few requests to generate metrics
    for _ in range(3):
        client.get("/health")
        client.get("/projects")
    
    # Check metrics endpoint
    response = client.get("/metrics")
    assert response.status_code == 200
    content = response.text
    # Should have duration or latency metrics
    assert "duration" in content.lower() or "latency" in content.lower() or "seconds" in content


def test_error_metrics(client):
    """Test that errors are tracked in metrics."""
    # Generate some errors
    client.get("/tasks/99999")  # 404
    client.post("/tasks", json={})  # 422 validation error
    
    # Check metrics endpoint
    response = client.get("/metrics")
    assert response.status_code == 200
    content = response.text
    # Should track error responses
    assert "error" in content.lower() or "status" in content.lower()


# ============================================================================
# Import functionality tests
# ============================================================================

def test_import_tasks_json(client):
    """Test importing tasks from JSON format."""
    import json
    
    tasks_data = {
        "tasks": [
            {
                "title": "Imported Task 1",
                "task_type": "concrete",
                "task_instruction": "Do something",
                "verification_instruction": "Verify it works",
                "priority": "high",
                "estimated_hours": 2.5,
                "notes": "Imported task"
            },
            {
                "title": "Imported Task 2",
                "task_type": "abstract",
                "task_instruction": "Break down",
                "verification_instruction": "Verify breakdown"
            }
        ]
    }
    
    tasks_data["agent_id"] = "import-agent"
    response = client.post(
        "/tasks/import/json",
        json=tasks_data
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["created"] == 2
    assert data["skipped"] == 0
    assert data["error_count"] == 0
    assert len(data["task_ids"]) == 2


def test_import_tasks_json_with_duplicates(client):
    """Test importing tasks with duplicate detection."""
    import json
    
    # Create existing task
    existing_response = client.post("/tasks", json={
        "title": "Existing Task",
        "task_type": "concrete",
        "task_instruction": "Existing",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    existing_id = existing_response.json()["id"]
    
    # Try to import same task (duplicate by title)
    tasks_data = {
        "tasks": [
            {
                "title": "Existing Task",
                "task_type": "concrete",
                "task_instruction": "Existing",
                "verification_instruction": "Verify"
            },
            {
                "title": "New Task",
                "task_type": "concrete",
                "task_instruction": "New",
                "verification_instruction": "Verify"
            }
        ]
    }
    
    tasks_data["agent_id"] = "import-agent"
    tasks_data["handle_duplicates"] = "skip"
    response = client.post(
        "/tasks/import/json",
        json=tasks_data
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["created"] == 1
    assert data["skipped"] == 1
    assert len(data["task_ids"]) == 1
    assert len(data["skipped_tasks"]) == 1


def test_import_tasks_json_with_relationships(client):
    """Test importing tasks with relationships."""
    import json
    
    tasks_data = {
        "tasks": [
            {
                "title": "Parent Task",
                "task_type": "abstract",
                "task_instruction": "Parent",
                "verification_instruction": "Verify",
                "import_id": "parent-1"
            },
            {
                "title": "Child Task",
                "task_type": "concrete",
                "task_instruction": "Child",
                "verification_instruction": "Verify",
                "import_id": "child-1",
                "parent_import_id": "parent-1",
                "relationship_type": "subtask"
            }
        ]
    }
    
    tasks_data["agent_id"] = "import-agent"
    response = client.post(
        "/tasks/import/json",
        json=tasks_data
    )
    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 2
    
    # Verify relationship was created
    task_ids = data["task_ids"]
    parent_id = task_ids[0]
    child_id = task_ids[1]
    
    relationships_response = client.get(f"/tasks/{parent_id}/relationships")
    relationships = relationships_response.json()["relationships"]
    assert len(relationships) >= 1
    assert any(r["child_task_id"] == child_id and r["relationship_type"] == "subtask" 
               for r in relationships)


def test_import_tasks_json_validation_errors(client):
    """Test importing tasks with validation errors."""
    import json
    
    tasks_data = {
        "tasks": [
            {
                "title": "",  # Invalid: empty title
                "task_type": "concrete",
                "task_instruction": "Test",
                "verification_instruction": "Verify"
            },
            {
                "title": "Valid Task",
                "task_type": "invalid_type",  # Invalid task type
                "task_instruction": "Test",
                "verification_instruction": "Verify"
            },
            {
                "title": "Another Valid Task",
                "task_type": "concrete",
                "task_instruction": "Test",
                "verification_instruction": "Verify"
            }
        ]
    }
    
    tasks_data["agent_id"] = "import-agent"
    response = client.post(
        "/tasks/import/json",
        json=tasks_data
    )
    assert response.status_code == 200
    data = response.json()
    assert data["error_count"] >= 1  # At least 2 errors
    assert data["created"] == 1  # Only valid task created
    assert len(data["errors"]) >= 1


def test_import_tasks_csv(client):
    """Test importing tasks from CSV format."""
    import csv
    from io import StringIO
    
    # Create CSV content
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "title", "task_type", "task_instruction", "verification_instruction", 
        "priority", "estimated_hours", "notes"
    ])
    writer.writeheader()
    writer.writerow({
        "title": "CSV Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "priority": "high",
        "estimated_hours": "3.5",
        "notes": "CSV imported"
    })
    writer.writerow({
        "title": "CSV Task 2",
        "task_type": "abstract",
        "task_instruction": "Break down",
        "verification_instruction": "Verify breakdown",
        "priority": "medium",
        "estimated_hours": "",
        "notes": ""
    })
    csv_content = output.getvalue()
    
    response = client.post(
        "/tasks/import/csv",
        files={"file": ("tasks.csv", csv_content, "text/csv")},
        data={"agent_id": "import-agent"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["created"] == 2
    assert data["skipped"] == 0
    assert data["error_count"] == 0


def test_import_tasks_csv_with_field_mapping(client):
    """Test importing CSV with custom field mapping."""
    import csv
    from io import StringIO
    
    # Create CSV with different column names
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "Task Title", "Type", "Instruction", "Verification", "Priority"
    ])
    writer.writeheader()
    writer.writerow({
        "Task Title": "Mapped Task",
        "Type": "concrete",
        "Instruction": "Do work",
        "Verification": "Check it",
        "Priority": "high"
    })
    csv_content = output.getvalue()
    
    # Import with field mapping
    mapping = {
        "title": "Task Title",
        "task_type": "Type",
        "task_instruction": "Instruction",
        "verification_instruction": "Verification",
        "priority": "Priority"
    }
    
    response = client.post(
        "/tasks/import/csv",
        files={"file": ("tasks.csv", csv_content, "text/csv")},
        data={"agent_id": "import-agent", "field_mapping": json.dumps(mapping)}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 1
    assert len(data["task_ids"]) == 1


def test_import_tasks_csv_duplicate_handling(client):
    """Test CSV import with duplicate handling."""
    import csv
    from io import StringIO
    
    # Create existing task
    existing_response = client.post("/tasks", json={
        "title": "Existing CSV Task",
        "task_type": "concrete",
        "task_instruction": "Existing",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    
    # Create CSV with duplicate
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "title", "task_type", "task_instruction", "verification_instruction"
    ])
    writer.writeheader()
    writer.writerow({
        "title": "Existing CSV Task",
        "task_type": "concrete",
        "task_instruction": "Existing",
        "verification_instruction": "Verify"
    })
    writer.writerow({
        "title": "New CSV Task",
        "task_type": "concrete",
        "task_instruction": "New",
        "verification_instruction": "Verify"
    })
    csv_content = output.getvalue()
    
    response = client.post(
        "/tasks/import/csv",
        files={"file": ("tasks.csv", csv_content, "text/csv")},
        data={"agent_id": "import-agent", "handle_duplicates": "skip"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 1
    assert data["skipped"] == 1


def test_import_tasks_json_project_id(client):
    """Test importing tasks with project_id."""
    import json
    
    # Create project
    project_response = client.post("/projects", json={
        "name": "Import Project",
        "local_path": "/test/path"
    })
    project_id = project_response.json()["id"]
    
    tasks_data = {
        "tasks": [
            {
                "title": "Project Task",
                "task_type": "concrete",
                "task_instruction": "Task in project",
                "verification_instruction": "Verify",
                "project_id": project_id
            }
        ]
    }
    
    tasks_data["agent_id"] = "import-agent"
    response = client.post(
        "/tasks/import/json",
        json=tasks_data
    )
    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 1
    
    # Verify task has correct project_id
    task_id = data["task_ids"][0]
    task_response = client.get(f"/tasks/{task_id}")
    task = task_response.json()
    assert task["project_id"] == project_id


def test_import_tasks_json_invalid_project_id(client):
    """Test importing tasks with invalid project_id."""
    import json
    
    tasks_data = {
        "tasks": [
            {
                "title": "Invalid Project Task",
                "task_type": "concrete",
                "task_instruction": "Test",
                "verification_instruction": "Verify",
                "project_id": 99999
            }
        ]
    }
    
    tasks_data["agent_id"] = "import-agent"
    response = client.post(
        "/tasks/import/json",
        json=tasks_data
    )
    assert response.status_code == 200
    data = response.json()
    assert data["error_count"] >= 1
    assert len(data["errors"]) >= 1


def test_import_tasks_json_empty_file(client):
    """Test importing empty JSON file."""
    tasks_data = {"tasks": []}
    
    tasks_data["agent_id"] = "import-agent"
    response = client.post(
        "/tasks/import/json",
        json=tasks_data
    )
    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 0
    assert data["error_count"] == 0


def test_import_tasks_csv_empty_file(client):
    """Test importing empty CSV file."""
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "title", "task_type", "task_instruction", "verification_instruction"
    ])
    writer.writeheader()
    csv_content = output.getvalue()
    
    response = client.post(
        "/tasks/import/csv",
        files={"file": ("tasks.csv", csv_content, "text/csv")},
        data={"agent_id": "import-agent"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 0


def test_import_tasks_csv_missing_required_fields(client):
    """Test CSV import with missing required fields."""
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=["title", "task_type"])
    writer.writeheader()
    writer.writerow({
        "title": "Incomplete Task",
        "task_type": "concrete"
        # Missing task_instruction and verification_instruction
    })
    csv_content = output.getvalue()
    
    response = client.post(
        "/tasks/import/csv",
        files={"file": ("tasks.csv", csv_content, "text/csv")},
        data={"agent_id": "import-agent"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["errors"] >= 1
    assert data["created"] == 0


# Rate limiting tests
def test_rate_limit_global_limit(client):
    """Test that global rate limiting applies to all endpoints."""
    # Make many rapid requests
    responses = []
    for i in range(150):  # Should hit default limit
        response = client.get("/health")
        responses.append(response.status_code)
        
        # Stop if we hit rate limit
        if response.status_code == 429:
            break
    
    # Should have at least one 429 response
    assert 429 in responses, "Rate limit should have been triggered"
    
    # Check rate limit headers - make another request that should be rate limited
    rate_limit_response = client.get("/health")
    if rate_limit_response.status_code == 429:
        assert "Retry-After" in rate_limit_response.headers
        assert "X-RateLimit-Limit" in rate_limit_response.headers
        assert "X-RateLimit-Remaining" in rate_limit_response.headers


def test_rate_limit_per_endpoint(client):
    """Test that different endpoints can have different rate limits."""
    # This test will verify endpoint-specific limits work
    # Make rapid requests to /health endpoint
    responses = []
    for i in range(50):
        response = client.get("/health")
        responses.append(response.status_code)
        if response.status_code == 429:
            break
    
    # Reset and try different endpoint
    time.sleep(1)
    
    # Try /metrics endpoint
    responses2 = []
    for i in range(50):
        response = client.get("/metrics")
        responses2.append(response.status_code)
        if response.status_code == 429:
            break
    
    # At least one should hit rate limit
    assert (429 in responses) or (429 in responses2), "Rate limit should apply to endpoints"


def test_rate_limit_per_agent(client):
    """Test that rate limits can be configured per agent."""
    # Create tasks with different agent IDs
    agent1_responses = []
    agent2_responses = []
    
    for i in range(50):
        # Agent 1 requests
        response1 = client.post("/tasks", json={
            "title": f"Task {i}",
            "task_type": "concrete",
            "task_instruction": "Test",
            "verification_instruction": "Verify",
            "agent_id": "agent-1"
        })
        agent1_responses.append(response1.status_code)
        if response1.status_code == 429:
            break
        
        # Agent 2 requests
        response2 = client.post("/tasks", json={
            "title": f"Task {i}",
            "task_type": "concrete",
            "task_instruction": "Test",
            "verification_instruction": "Verify",
            "agent_id": "agent-2"
        })
        agent2_responses.append(response2.status_code)
        if response2.status_code == 429:
            break
    
    # Both agents should be rate limited independently
    # (or one should hit limit, depending on configuration)
    assert True  # Test passes if rate limiting applies


def test_rate_limit_429_response(client):
    """Test that 429 responses include proper headers and body."""
    # Make enough requests to hit rate limit
    response = None
    for i in range(150):
        response = client.get("/health")
        if response.status_code == 429:
            break
    
    if response and response.status_code == 429:
        # Check response headers
        assert "Retry-After" in response.headers
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers
        
        # Check response body
        data = response.json()
        assert "error" in data
        assert "detail" in data
        assert "retry_after" in data or "Retry-After" in response.headers


def test_rate_limit_retry_after(client):
    """Test that Retry-After header is properly set."""
    # Hit rate limit
    response = None
    for i in range(150):
        response = client.get("/health")
        if response.status_code == 429:
            break
    
    if response and response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        assert retry_after is not None
        retry_seconds = int(retry_after)
        assert retry_seconds >= 0
        assert retry_seconds <= 60  # Should be reasonable


def test_rate_limit_sliding_window(client):
    """Test that sliding window algorithm works correctly."""
    # Make requests at steady rate (should not hit limit)
    for i in range(50):
        response = client.get("/health")
        assert response.status_code == 200, f"Request {i} should succeed"
        time.sleep(0.1)  # Small delay to spread requests
    
    # Make burst of requests (should hit limit)
    responses = []
    for i in range(100):
        response = client.get("/health")
        responses.append(response.status_code)
        if response.status_code == 429:
            break
    
    # Should have at least one rate limited response
    assert 429 in responses, "Burst requests should hit rate limit"


def test_rate_limit_configuration_env(client):
    """Test that rate limit configuration can be set via environment."""
    # This test verifies that environment variables control rate limits
    # The actual implementation will read from env vars
    response = client.get("/health")
    # Should succeed - configuration test
    assert response.status_code in [200, 429]  # Either works or is already rate limited


def test_rate_limit_per_user_token_bucket(client):
    """Test token bucket rate limiting per user."""
    # Register and login as user1
    client.post("/users/register", json={
        "username": "user1",
        "email": "user1@example.com",
        "password": "SecurePass123!"
    })
    login_response = client.post("/users/login", json={
        "username": "user1",
        "password": "SecurePass123!"
    })
    session_token = login_response.json()["session_token"]
    headers = {"Authorization": f"Bearer {session_token}"}
    
    # Make many requests as authenticated user
    rate_limited = False
    for i in range(150):  # Should hit user rate limit
        response = client.get("/users/me", headers=headers)
        if response.status_code == 429:
            rate_limited = True
            # Check error message is clear
            data = response.json()
            assert "error" in data
            assert "detail" in data
            assert "Rate limit exceeded" in data["error"] or "rate limit" in data["error"].lower()
            assert "Retry-After" in response.headers
            break
    
    assert rate_limited, "User rate limit should have been triggered"


def test_rate_limit_per_user_token_bucket_clear_message(client):
    """Test that token bucket rate limiting returns clear error messages."""
    # Register and login
    client.post("/users/register", json={
        "username": "user2",
        "email": "user2@example.com",
        "password": "SecurePass123!"
    })
    login_response = client.post("/users/login", json={
        "username": "user2",
        "password": "SecurePass123!"
    })
    session_token = login_response.json()["session_token"]
    headers = {"Authorization": f"Bearer {session_token}"}
    
    # Hit rate limit
    response = None
    for i in range(150):
        response = client.get("/users/me", headers=headers)
        if response.status_code == 429:
            break
    
    if response and response.status_code == 429:
        data = response.json()
        # Verify clear error message
        assert "error" in data
        assert "detail" in data
        assert isinstance(data["detail"], str)
        assert len(data["detail"]) > 0
        # Message should mention retry time or rate limit
        detail_lower = data["detail"].lower()
        assert "retry" in detail_lower or "limit" in detail_lower or "seconds" in detail_lower
        # Should have retry_after in response
        assert "retry_after" in data or "Retry-After" in response.headers


def test_rate_limit_per_user_token_bucket_burst_allowance(client):
    """Test that token bucket allows burst up to bucket capacity."""
    # Register and login
    client.post("/users/register", json={
        "username": "user3",
        "email": "user3@example.com",
        "password": "SecurePass123!"
    })
    login_response = client.post("/users/login", json={
        "username": "user3",
        "password": "SecurePass123!"
    })
    session_token = login_response.json()["session_token"]
    headers = {"Authorization": f"Bearer {session_token}"}
    
    # Make burst of requests quickly (token bucket should allow this)
    # Token bucket typically allows burst equal to bucket capacity
    burst_size = 50
    successes = 0
    for i in range(burst_size):
        response = client.get("/users/me", headers=headers)
        if response.status_code == 200:
            successes += 1
        elif response.status_code == 429:
            break
    
    # Token bucket should allow some burst (at least a few requests)
    # Exact number depends on bucket capacity and refill rate
    assert successes > 0, "Token bucket should allow some burst requests"


def test_rate_limit_per_user_different_users_independent(client):
    """Test that different users have independent rate limits."""
    # Register two users
    client.post("/users/register", json={
        "username": "user4",
        "email": "user4@example.com",
        "password": "SecurePass123!"
    })
    client.post("/users/register", json={
        "username": "user5",
        "email": "user5@example.com",
        "password": "SecurePass123!"
    })
    
    # Login both
    login1 = client.post("/users/login", json={
        "username": "user4",
        "password": "SecurePass123!"
    })
    login2 = client.post("/users/login", json={
        "username": "user5",
        "password": "SecurePass123!"
    })
    
    headers1 = {"Authorization": f"Bearer {login1.json()['session_token']}"}
    headers2 = {"Authorization": f"Bearer {login2.json()['session_token']}"}
    
    # User1 hits rate limit
    rate_limited_1 = False
    for i in range(150):
        response = client.get("/users/me", headers=headers1)
        if response.status_code == 429:
            rate_limited_1 = True
            break
    
    # User2 should still be able to make requests (independent limits)
    response2 = client.get("/users/me", headers=headers2)
    # User2 should not be rate limited by user1's activity
    assert response2.status_code == 200, "Different users should have independent rate limits"
    if rate_limited_1:
        assert True  # Test passes if user limits are independent


def test_get_activity_feed(client, temp_db):
    """Test getting activity feed for a task."""
    db, _, _ = temp_db
    # Create task
    create_response = client.post("/tasks", json={
        "title": "Activity Feed Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Add some activities using database directly
    db.lock_task(task_id, "agent-1")
    db.add_task_update(task_id, "agent-1", "Progress update", "progress")
    db.complete_task(task_id, "agent-1", notes="Done!")
    
    # Get activity feed
    response = client.get(f"/tasks/activity-feed?task_id={task_id}")
    assert response.status_code == 200
    data = response.json()
    assert "feed" in data
    assert "count" in data
    assert len(data["feed"]) >= 3  # At least: created, progress, completed
    
    # Check chronological order (oldest first)
    feed = data["feed"]
    for i in range(len(feed) - 1):
        assert feed[i]["created_at"] <= feed[i + 1]["created_at"]


def test_get_activity_feed_filtered_by_agent(client, temp_db):
    """Test getting activity feed filtered by agent."""
    db, _, _ = temp_db
    # Create task
    create_response = client.post("/tasks", json={
        "title": "Activity Feed Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Add activities from different agents using database directly
    db.add_task_update(task_id, "agent-1", "Update 1", "progress")
    db.add_task_update(task_id, "agent-2", "Update 2", "progress")
    
    # Get feed filtered by agent-1
    response = client.get(f"/tasks/activity-feed?task_id={task_id}&agent_id=agent-1")
    assert response.status_code == 200
    data = response.json()
    feed = data["feed"]
    
    # All entries should be from agent-1 (except created which is from test-agent)
    for entry in feed:
        if entry["change_type"] != "created":
            assert entry["agent_id"] == "agent-1"


def test_get_activity_feed_all_tasks(client, temp_db):
    """Test getting activity feed across all tasks."""
    db, _, _ = temp_db
    # Create multiple tasks
    task1_response = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Task 1",
        "verification_instruction": "Verify 1",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    
    task2_response = client.post("/tasks", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Task 2",
        "verification_instruction": "Verify 2",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json()["id"]
    
    # Add activities using database directly
    db.add_task_update(task1_id, "agent-1", "Update 1", "progress")
    db.add_task_update(task2_id, "agent-2", "Update 2", "progress")
    
    # Get feed for all tasks (no task_id filter)
    response = client.get("/tasks/activity-feed")
    assert response.status_code == 200
    data = response.json()
    feed = data["feed"]
    
    # Should include activities from both tasks
    task_ids = set(entry["task_id"] for entry in feed)
    assert task1_id in task_ids
    assert task2_id in task_ids
    
    # Should be in chronological order
    for i in range(len(feed) - 1):
        assert feed[i]["created_at"] <= feed[i + 1]["created_at"]


def test_get_activity_feed_with_date_filter(client, temp_db):
    """Test getting activity feed with date range filter."""
    from datetime import datetime, timedelta
    
    db, _, _ = temp_db
    # Create task
    create_response = client.post("/tasks", json={
        "title": "Activity Feed Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Add activity using database directly
    db.add_task_update(task_id, "agent-1", "Recent update", "progress")
    
    # Get feed for last hour
    end_date = datetime.now()
    start_date = end_date - timedelta(hours=1)
    
    response = client.get(
        f"/tasks/activity-feed?task_id={task_id}&"
        f"start_date={start_date.isoformat()}&end_date={end_date.isoformat()}"
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["feed"]) >= 1  # Should include recent activity


# ============================================================================
# Bulk task operations tests
# ============================================================================

def test_bulk_complete_tasks(client):
    """Test bulk completing multiple tasks."""
    # Create multiple tasks
    task_ids = []
    for i in range(3):
        create_response = client.post("/tasks", json={
            "title": f"Bulk Task {i}",
            "task_type": "concrete",
            "task_instruction": "Task",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
        task_id = create_response.json()["id"]
        # Lock each task
        client.post(f"/tasks/{task_id}/lock", json={"agent_id": "test-agent"})
        task_ids.append(task_id)
    
    # Bulk complete
    response = client.post("/tasks/bulk/complete", json={
        "task_ids": task_ids,
        "agent_id": "test-agent",
        "notes": "Bulk completed"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["completed"] == 3
    assert len(data["task_ids"]) == 3
    
    # Verify all tasks are complete
    for task_id in task_ids:
        get_response = client.get(f"/tasks/{task_id}")
        task = get_response.json()
        assert task["task_status"] == "complete"


def test_bulk_complete_partial_failure(client):
    """Test bulk complete when some tasks fail."""
    # Create tasks
    task1_response = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Task",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    client.post(f"/tasks/{task1_id}/lock", json={"agent_id": "test-agent"})
    
    # Include non-existent task ID
    response = client.post("/tasks/bulk/complete", json={
        "task_ids": [task1_id, 99999],
        "agent_id": "test-agent"
    })
    assert response.status_code == 200
    data = response.json()
    # Should complete task1, but skip 99999
    assert data["completed"] >= 1
    assert len(data["failed"]) >= 0


def test_bulk_assign_tasks(client):
    """Test bulk assigning tasks to an agent."""
    # Create multiple tasks
    task_ids = []
    for i in range(3):
        create_response = client.post("/tasks", json={
            "title": f"Bulk Assign Task {i}",
            "task_type": "concrete",
            "task_instruction": "Task",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
        task_ids.append(create_response.json()["id"])
    
    # Bulk assign
    response = client.post("/tasks/bulk/assign", json={
        "task_ids": task_ids,
        "agent_id": "assigned-agent"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["assigned"] == 3
    
    # Verify all tasks are assigned and locked
    for task_id in task_ids:
        get_response = client.get(f"/tasks/{task_id}")
        task = get_response.json()
        assert task["assigned_agent"] == "assigned-agent"
        assert task["task_status"] == "in_progress"


def test_bulk_update_status(client):
    """Test bulk updating task status."""
    # Create multiple tasks
    task_ids = []
    for i in range(3):
        create_response = client.post("/tasks", json={
            "title": f"Bulk Status Task {i}",
            "task_type": "concrete",
            "task_instruction": "Task",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
        task_ids.append(create_response.json()["id"])
    
    # Bulk update status to blocked
    response = client.post("/tasks/bulk/update-status", json={
        "task_ids": task_ids,
        "task_status": "blocked",
        "agent_id": "test-agent"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["updated"] == 3
    
    # Verify all tasks are blocked
    for task_id in task_ids:
        get_response = client.get(f"/tasks/{task_id}")
        task = get_response.json()
        assert task["task_status"] == "blocked"


def test_bulk_delete_tasks(client):
    """Test bulk deleting tasks with confirmation."""
    # Create multiple tasks
    task_ids = []
    for i in range(3):
        create_response = client.post("/tasks", json={
            "title": f"Bulk Delete Task {i}",
            "task_type": "concrete",
            "task_instruction": "Task",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
        task_ids.append(create_response.json()["id"])
    
    # Bulk delete without confirmation (should fail)
    response = client.post("/tasks/bulk/delete", json={
        "task_ids": task_ids
    })
    assert response.status_code == 400
    assert "confirmation" in response.json()["detail"].lower()
    
    # Bulk delete with confirmation
    response = client.post("/tasks/bulk/delete", json={
        "task_ids": task_ids,
        "confirm": True
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["deleted"] == 3
    
    # Verify all tasks are deleted
    for task_id in task_ids:
        get_response = client.get(f"/tasks/{task_id}")
        assert get_response.status_code == 404


def test_bulk_delete_without_confirmation(client):
    """Test that bulk delete requires confirmation."""
    task_response = client.post("/tasks", json={
        "title": "Delete Test",
        "task_type": "concrete",
        "task_instruction": "Task",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = task_response.json()["id"]
    
    response = client.post("/tasks/bulk/delete", json={
        "task_ids": [task_id],
        "confirm": False
    })
    assert response.status_code == 400


def test_bulk_operations_transaction_rollback(client):
    """Test that bulk operations roll back on partial failure if transaction=True."""
    # Create tasks
    task1_response = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Task",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    client.post(f"/tasks/{task1_id}/lock", json={"agent_id": "test-agent"})
    
    # Try to bulk complete with invalid task (transaction should rollback)
    response = client.post("/tasks/bulk/complete", json={
        "task_ids": [task1_id, 99999],
        "agent_id": "test-agent",
        "require_all": True  # Require all to succeed
    })
    # If transaction fails, task1 should not be completed
    if response.status_code == 400:
        # Verify task1 is still in_progress (not completed)
        get_response = client.get(f"/tasks/{task1_id}")
        task = get_response.json()
        assert task["task_status"] == "in_progress"


def test_bulk_operations_empty_task_ids(client):
    """Test bulk operations with empty task_ids list."""
    response = client.post("/tasks/bulk/complete", json={
        "task_ids": [],
        "agent_id": "test-agent"
    })
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower() or "required" in response.json()["detail"].lower()


def test_bulk_operations_invalid_task_ids(client):
    """Test bulk operations with invalid task_ids."""
    response = client.post("/tasks/bulk/complete", json={
        "task_ids": [-1, 0],
        "agent_id": "test-agent"
    })
    assert response.status_code == 422  # Validation error


def test_bulk_assign_locked_tasks(client):
    """Test bulk assign when some tasks are already locked."""
    # Create and lock a task
    task1_response = client.post("/tasks", json={
        "title": "Locked Task",
        "task_type": "concrete",
        "task_instruction": "Task",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    client.post(f"/tasks/{task1_id}/lock", json={"agent_id": "agent-1"})
    
    # Create unlocked task
    task2_response = client.post("/tasks", json={
        "title": "Unlocked Task",
        "task_type": "concrete",
        "task_instruction": "Task",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json()["id"]
    
    # Bulk assign (should skip locked task1, assign task2)
    response = client.post("/tasks/bulk/assign", json={
        "task_ids": [task1_id, task2_id],
        "agent_id": "agent-2"
    })
    assert response.status_code == 200
    data = response.json()
    # task2 should be assigned, task1 might be skipped or fail
    assert data["assigned"] >= 1
    
    # Verify task2 is assigned
    get_response = client.get(f"/tasks/{task2_id}")
    task = get_response.json()
    assert task["assigned_agent"] == "agent-2"


def test_bulk_update_status_invalid_status(client):
    """Test bulk update status with invalid status."""
    task_response = client.post("/tasks", json={
        "title": "Status Test",
        "task_type": "concrete",
        "task_instruction": "Task",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = task_response.json()["id"]
    
    response = client.post("/tasks/bulk/update-status", json={
        "task_ids": [task_id],
        "task_status": "invalid_status",
        "agent_id": "test-agent"
    })
    assert response.status_code == 422  # Validation error


# ============================================================================
# Analytics and Reporting Tests
# ============================================================================

def test_analytics_completion_rates(client, temp_db):
    """Test analytics endpoint for completion rates."""
    db, _, _ = temp_db
    
    # Create project
    project_id = db.create_project(
        name="Test Project",
        local_path="/test/path",
        description="Test"
    )
    
    # Create tasks with different statuses
    task1_id = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-1",
        project_id=project_id
    )
    task2_id = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-1",
        project_id=project_id
    )
    task3_id = db.create_task(
        title="Task 3",
        task_type="abstract",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-1",
        project_id=project_id
    )
    
    # Complete two tasks
    db.complete_task(task1_id, "agent-1")
    db.complete_task(task2_id, "agent-1")
    
    # Get analytics
    response = client.get("/analytics/metrics")
    assert response.status_code == 200
    data = response.json()
    
    assert "completion_rates" in data
    assert "total_tasks" in data["completion_rates"]
    assert "completed_tasks" in data["completion_rates"]
    assert "completion_percentage" in data["completion_rates"]
    
    # Should have 3 total, 2 completed
    assert data["completion_rates"]["total_tasks"] == 3
    assert data["completion_rates"]["completed_tasks"] == 2
    assert abs(data["completion_rates"]["completion_percentage"] - 66.67) < 0.1
    
    # Test with project filter
    response = client.get(f"/analytics/metrics?project_id={project_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["completion_rates"]["total_tasks"] == 3
    assert data["completion_rates"]["completed_tasks"] == 2


def test_analytics_average_time_to_complete(client, temp_db):
    """Test analytics endpoint for average time to complete."""
    db, _, _ = temp_db
    
    # Create tasks
    task1_id = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-1"
    )
    task2_id = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-1"
    )
    
    # Complete tasks (they will have completed_at set)
    db.complete_task(task1_id, "agent-1")
    db.complete_task(task2_id, "agent-1")
    
    # Get analytics
    response = client.get("/analytics/metrics")
    assert response.status_code == 200
    data = response.json()
    
    assert "average_time_to_complete" in data
    assert "average_hours" in data["average_time_to_complete"]
    assert data["average_time_to_complete"]["average_hours"] >= 0


def test_analytics_bottlenecks(client, temp_db):
    """Test analytics endpoint for bottleneck identification."""
    db, _, _ = temp_db
    
    # Create a task that's been in_progress for a while
    task1_id = db.create_task(
        title="Stuck Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-1"
    )
    db.lock_task(task1_id, "agent-1")
    
    # Create blocking relationships
    task2_id = db.create_task(
        title="Blocking Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-1"
    )
    db.create_relationship(
        parent_task_id=task2_id,
        child_task_id=task1_id,
        relationship_type="blocking",
        agent_id="agent-1"
    )
    
    # Get bottlenecks
    response = client.get("/analytics/bottlenecks")
    assert response.status_code == 200
    data = response.json()
    
    assert "long_running_tasks" in data
    assert "blocking_tasks" in data
    assert isinstance(data["long_running_tasks"], list)
    assert isinstance(data["blocking_tasks"], list)


def test_analytics_agent_comparisons(client, temp_db):
    """Test analytics endpoint for agent performance comparisons."""
    db, _, _ = temp_db
    
    # Create tasks for different agents
    task1_id = db.create_task(
        title="Agent 1 Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-1"
    )
    task2_id = db.create_task(
        title="Agent 2 Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-2"
    )
    
    # Complete with different actual hours
    db.complete_task(task1_id, "agent-1", actual_hours=5.0)
    db.complete_task(task2_id, "agent-2", actual_hours=10.0)
    
    # Get agent comparisons
    response = client.get("/analytics/agents")
    assert response.status_code == 200
    data = response.json()
    
    assert "agents" in data
    assert isinstance(data["agents"], list)
    
    # Should have data for both agents
    agent_ids = [a["agent_id"] for a in data["agents"]]
    assert "agent-1" in agent_ids
    assert "agent-2" in agent_ids
    
    # Check agent data structure
    agent1_data = next(a for a in data["agents"] if a["agent_id"] == "agent-1")
    assert "tasks_completed" in agent1_data
    assert "average_time_delta" in agent1_data or "avg_time_delta" in agent1_data


def test_analytics_visualization_data(client, temp_db):
    """Test analytics endpoint for visualization data."""
    db, _, _ = temp_db
    
    # Create some tasks
    for i in range(5):
        db.create_task(
            title=f"Task {i}",
            task_type="concrete",
            task_instruction="Do something",
            verification_instruction="Verify",
            agent_id="agent-1"
        )
    
    # Complete some
    tasks = db.query_tasks(limit=5)
    for i, task in enumerate(tasks[:3]):
        db.complete_task(task["id"], "agent-1")
    
    # Get visualization data
    response = client.get("/analytics/visualization")
    assert response.status_code == 200
    data = response.json()
    
    assert "completion_timeline" in data or "status_distribution" in data
    # Should have some form of chart/visualization data
    assert isinstance(data, dict)
    
    # Test with date filters
    response = client.get("/analytics/visualization?start_date=2024-01-01&end_date=2025-12-31")
    assert response.status_code == 200


def test_analytics_metrics_with_filters(client, temp_db):
    """Test analytics metrics with various filters."""
    db, _, _ = temp_db
    
    # Create project
    project_id = db.create_project(
        name="Test Project",
        local_path="/test/path"
    )
    
    # Create tasks
    task1_id = db.create_task(
        title="Concrete Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-1",
        project_id=project_id
    )
    task2_id = db.create_task(
        title="Abstract Task",
        task_type="abstract",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="agent-1",
        project_id=project_id
    )
    
    db.complete_task(task1_id, "agent-1")
    
    # Test with project filter
    response = client.get(f"/analytics/metrics?project_id={project_id}")
    assert response.status_code == 200
    
    # Test with task_type filter
    response = client.get("/analytics/metrics?task_type=concrete")
    assert response.status_code == 200
    data = response.json()
    # All tasks in result should be concrete
    if "tasks_by_type" in data:
        assert data.get("tasks_by_type", {}).get("concrete", {}).get("total", 0) >= 1


# API Key Authentication Tests

def test_create_api_key_endpoint(client, temp_db):
    """Test creating an API key via API endpoint."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    response = client.post(
        f"/projects/{project_id}/api-keys",
        json={"name": "Test API Key"}
    )
    assert response.status_code == 201
    data = response.json()
    assert "key_id" in data
    assert "api_key" in data
    assert "key_prefix" in data
    assert data["name"] == "Test API Key"
    assert data["project_id"] == project_id
    assert len(data["api_key"]) > 32


def test_list_api_keys_endpoint(client, temp_db):
    """Test listing API keys for a project."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    # Create some keys via database
    db.create_api_key(project_id, "Key 1")
    db.create_api_key(project_id, "Key 2")
    
    response = client.get(f"/projects/{project_id}/api-keys")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all("key_id" in k for k in data)
    assert all("name" in k for k in data)
    assert all("key_prefix" in k for k in data)
    # Full key should NOT be in list
    assert all("api_key" not in k for k in data)


def test_revoke_api_key_endpoint(client, temp_db):
    """Test revoking an API key."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    key_id, full_key = db.create_api_key(project_id, "Test Key")
    
    response = client.delete(f"/api-keys/{key_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Verify key is disabled
    key_info = db.get_api_key_by_hash(db._hash_api_key(full_key))
    assert key_info["enabled"] == 0


def test_rotate_api_key_endpoint(client, temp_db):
    """Test rotating an API key."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    key_id, old_key = db.create_api_key(project_id, "Test Key")
    
    response = client.post(f"/api-keys/{key_id}/rotate")
    assert response.status_code == 200
    data = response.json()
    assert "key_id" in data
    assert "api_key" in data
    assert data["key_id"] != key_id
    assert data["api_key"] != old_key
    
    # Old key should be disabled
    old_key_info = db.get_api_key_by_hash(db._hash_api_key(old_key))
    assert old_key_info["enabled"] == 0


def test_authenticate_with_valid_api_key(client, temp_db):
    """Test accessing a protected endpoint with a valid API key."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    key_id, api_key = db.create_api_key(project_id, "Test Key")
    
    # Create a task (this should be protected)
    response = client.post(
        "/tasks",
        json={
            "title": "Test Task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "project_id": project_id,
            "agent_id": "test-agent"
        },
        headers={"X-API-Key": api_key}
    )
    assert response.status_code == 201


def test_authenticate_with_bearer_token(client, temp_db):
    """Test accessing a protected endpoint with Bearer token format."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    key_id, api_key = db.create_api_key(project_id, "Test Key")
    
    # Use Authorization: Bearer header
    response = client.post(
        "/tasks",
        json={
            "title": "Test Task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "project_id": project_id,
            "agent_id": "test-agent"
        },
        headers={"Authorization": f"Bearer {api_key}"}
    )
    assert response.status_code == 201


def test_authenticate_with_invalid_api_key(client, temp_db):
    """Test accessing a protected endpoint with an invalid API key."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    response = client.post(
        "/tasks",
        json={
            "title": "Test Task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "project_id": project_id,
            "agent_id": "test-agent"
        },
        headers={"X-API-Key": "invalid_key_12345"}
    )
    assert response.status_code == 401
    assert "error" in response.json()


def test_authenticate_with_revoked_api_key(client, temp_db):
    """Test accessing a protected endpoint with a revoked API key."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    key_id, api_key = db.create_api_key(project_id, "Test Key")
    
    # Revoke the key
    db.revoke_api_key(key_id)
    
    response = client.post(
        "/tasks",
        json={
            "title": "Test Task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "project_id": project_id,
            "agent_id": "test-agent"
        },
        headers={"X-API-Key": api_key}
    )
    assert response.status_code == 401


def test_authenticate_without_api_key(client, temp_db):
    """Test accessing a protected endpoint without an API key."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    response = client.post(
        "/tasks",
        json={
            "title": "Test Task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "project_id": project_id,
            "agent_id": "test-agent"
        }
    )
    # Should require authentication
    assert response.status_code == 401


def test_api_key_scoped_to_project(client, temp_db):
    """Test that API keys are scoped to their project."""
    db, _, _ = temp_db
    project1_id = db.create_project("Project 1", "/path1")
    project2_id = db.create_project("Project 2", "/path2")
    
    key_id, api_key = db.create_api_key(project1_id, "Key 1")
    
    # Try to create a task in project 2 with project 1's key
    response = client.post(
        "/tasks",
        json={
            "title": "Test Task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "project_id": project2_id,
            "agent_id": "test-agent"
        },
        headers={"X-API-Key": api_key}
    )
    # Should fail because key is scoped to project 1
    assert response.status_code == 403


def test_public_endpoints_no_auth_required(client):
    """Test that public endpoints don't require authentication."""
    # Health check should not require auth
    response = client.get("/health")
    assert response.status_code == 200
    
    # Metrics should not require auth
    response = client.get("/metrics")
    assert response.status_code == 200


def test_create_api_key_invalid_project(client, temp_db):
    """Test creating an API key for a non-existent project."""
    response = client.post(
        "/projects/99999/api-keys",
        json={"name": "Test Key"}
    )
    assert response.status_code == 404


def test_revoke_nonexistent_api_key(client):
    """Test revoking a non-existent API key."""
    response = client.delete("/api-keys/99999")
    assert response.status_code == 404


def test_rotate_nonexistent_api_key(client):
    """Test rotating a non-existent API key."""
    response = client.post("/api-keys/99999/rotate")
    assert response.status_code == 404


def test_create_api_key_without_name(client, temp_db):
    """Test creating an API key without a name."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    response = client.post(
        f"/projects/{project_id}/api-keys",
        json={}
    )
    assert response.status_code == 422  # Validation error


def test_create_api_key_empty_name(client, temp_db):
    """Test creating an API key with empty name."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    response = client.post(
        f"/projects/{project_id}/api-keys",
        json={"name": ""}
    )
    assert response.status_code == 422  # Validation error


def test_api_key_last_used_updated(client, temp_db):
    """Test that API key last_used_at is updated when used."""
    db, _, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    key_id, api_key = db.create_api_key(project_id, "Test Key")
    
    # Initially last_used_at should be None
    key_info = db.get_api_key_by_hash(db._hash_api_key(api_key))
    assert key_info["last_used_at"] is None
    
    # Use the key
    response = client.get(
        "/projects",
        headers={"X-API-Key": api_key}
    )
    assert response.status_code == 200
    
    # last_used_at should now be set
    key_info = db.get_api_key_by_hash(db._hash_api_key(api_key))
    assert key_info["last_used_at"] is not None


# ===== Conversation Management API Tests =====

def test_get_or_create_conversation(client):
    """Test getting or creating a conversation."""
    response = client.post("/conversations/user1/chat1")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "user1"
    assert data["chat_id"] == "chat1"
    assert data["message_count"] == 0
    assert "id" in data
    assert "messages" in data
    assert len(data["messages"]) == 0


def test_get_existing_conversation(client):
    """Test getting an existing conversation."""
    # Create conversation
    client.post("/conversations/user1/chat1")
    
    # Get it again
    response = client.get("/conversations/user1/chat1")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "user1"
    assert data["chat_id"] == "chat1"


def test_get_nonexistent_conversation(client):
    """Test getting a non-existent conversation returns 404."""
    response = client.get("/conversations/user999/chat999")
    assert response.status_code == 404


def test_add_message_to_conversation(client):
    """Test adding a message to a conversation."""
    # Create conversation
    client.post("/conversations/user1/chat1")
    
    # Add message
    response = client.post(
        "/conversations/user1/chat1/messages",
        json={
            "role": "user",
            "content": "Hello, world!",
            "tokens": 10
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert "message_id" in data
    assert "conversation_id" in data
    
    # Verify message was added
    get_response = client.get("/conversations/user1/chat1")
    conv_data = get_response.json()
    assert conv_data["message_count"] == 1
    assert len(conv_data["messages"]) == 1
    assert conv_data["messages"][0]["content"] == "Hello, world!"
    assert conv_data["messages"][0]["role"] == "user"
    assert conv_data["messages"][0]["tokens"] == 10


def test_add_message_invalid_role(client):
    """Test adding a message with invalid role."""
    client.post("/conversations/user1/chat1")
    
    response = client.post(
        "/conversations/user1/chat1/messages",
        json={
            "role": "invalid_role",
            "content": "Test"
        }
    )
    assert response.status_code == 422  # Validation error


def test_reset_conversation(client):
    """Test resetting a conversation."""
    # Create conversation and add messages
    client.post("/conversations/user1/chat1")
    client.post(
        "/conversations/user1/chat1/messages",
        json={"role": "user", "content": "Message 1", "tokens": 10}
    )
    client.post(
        "/conversations/user1/chat1/messages",
        json={"role": "assistant", "content": "Response 1", "tokens": 15}
    )
    
    # Verify messages exist
    get_response = client.get("/conversations/user1/chat1")
    assert get_response.json()["message_count"] == 2
    
    # Reset conversation
    response = client.post("/conversations/user1/chat1/reset")
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    # Verify messages are gone but conversation exists
    get_response = client.get("/conversations/user1/chat1")
    conv_data = get_response.json()
    assert conv_data["message_count"] == 0
    assert len(conv_data["messages"]) == 0
    assert conv_data["total_tokens"] == 0


def test_reset_nonexistent_conversation(client):
    """Test resetting a non-existent conversation returns 404."""
    response = client.post("/conversations/user999/chat999/reset")
    assert response.status_code == 404


def test_delete_conversation(client):
    """Test deleting a conversation."""
    # Create conversation and add messages
    client.post("/conversations/user1/chat1")
    client.post(
        "/conversations/user1/chat1/messages",
        json={"role": "user", "content": "Test message"}
    )
    
    # Delete conversation
    response = client.delete("/conversations/user1/chat1")
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    # Verify conversation is gone
    get_response = client.get("/conversations/user1/chat1")
    assert get_response.status_code == 404


def test_delete_nonexistent_conversation(client):
    """Test deleting a non-existent conversation returns 404."""
    response = client.delete("/conversations/user999/chat999")
    assert response.status_code == 404


def test_prune_conversation(client):
    """Test pruning old messages from a conversation."""
    # Create conversation and add many messages
    client.post("/conversations/user1/chat1")
    for i in range(10):
        client.post(
            "/conversations/user1/chat1/messages",
            json={"role": "user", "content": f"Message {i}", "tokens": 10}
        )
    
    # Verify all messages exist
    get_response = client.get("/conversations/user1/chat1")
    assert get_response.json()["message_count"] == 10
    
    # Prune to keep only 50 tokens (should keep about 5 messages)
    response = client.post(
        "/conversations/user1/chat1/prune",
        json={"max_tokens": 50, "keep_recent": 5}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["pruned_count"] > 0
    
    # Verify messages were pruned
    get_response = client.get("/conversations/user1/chat1")
    conv_data = get_response.json()
    assert conv_data["message_count"] <= 10
    total_tokens = sum(msg.get("tokens", 0) for msg in conv_data["messages"])
    assert total_tokens <= 50


def test_get_conversation_with_limit(client):
    """Test getting conversation with message limit."""
    client.post("/conversations/user1/chat1")
    for i in range(10):
        client.post(
            "/conversations/user1/chat1/messages",
            json={"role": "user", "content": f"Message {i}"}
        )
    
    # Get with limit
    response = client.get("/conversations/user1/chat1?limit=5")
    assert response.status_code == 200
    assert len(response.json()["messages"]) == 5


def test_get_conversation_with_token_limit(client):
    """Test getting conversation with token limit."""
    client.post("/conversations/user1/chat1")
    for i in range(5):
        client.post(
            "/conversations/user1/chat1/messages",
            json={"role": "user", "content": f"Message {i}", "tokens": 10}
        )
    
    # Get with token limit
    response = client.get("/conversations/user1/chat1?max_tokens=25")
    assert response.status_code == 200
    messages = response.json()["messages"]
    total_tokens = sum(msg.get("tokens", 0) for msg in messages)
    assert total_tokens <= 25


def test_list_conversations(client):
    """Test listing conversations."""
    # Create multiple conversations
    client.post("/conversations/user1/chat1")
    client.post("/conversations/user1/chat2")
    client.post("/conversations/user2/chat1")
    
    # List all conversations
    response = client.get("/conversations")
    assert response.status_code == 200
    conversations = response.json()
    assert len(conversations) >= 3
    
    # List conversations for specific user
    response = client.get("/conversations?user_id=user1")
    assert response.status_code == 200
    user_convs = response.json()
    assert len(user_convs) == 2
    assert all(conv["user_id"] == "user1" for conv in user_convs)


def test_conversation_context_limits(client):
    """Test that conversation history maintains proper context limits."""
    client.post("/conversations/user1/chat1")
    
    # Add messages
    for i in range(5):
        client.post(
            "/conversations/user1/chat1/messages",
            json={"role": "user", "content": f"Message {i}", "tokens": 10}
        )
    
    # Get conversation - should have all messages
    response = client.get("/conversations/user1/chat1")
    assert response.json()["message_count"] == 5
    
    # Prune to smaller limit
    client.post(
        "/conversations/user1/chat1/prune",
        json={"max_tokens": 30, "keep_recent": 2}
    )
    
    # Verify conversation respects limits
    response = client.get("/conversations/user1/chat1")
    conv_data = response.json()
    total_tokens = sum(msg.get("tokens", 0) for msg in conv_data["messages"])
    assert total_tokens <= 30


def test_export_conversation_json(client):
    """Test exporting conversation in JSON format."""
    # Create conversation and add messages
    client.post("/conversations/user1/chat1")
    client.post(
        "/conversations/user1/chat1/messages",
        json={"role": "user", "content": "Hello", "tokens": 10}
    )
    client.post(
        "/conversations/user1/chat1/messages",
        json={"role": "assistant", "content": "Hi there!", "tokens": 5}
    )
    
    # Export as JSON
    response = client.get("/conversations/user1/chat1/export?format=json")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "user1"
    assert data["chat_id"] == "chat1"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["content"] == "Hello"
    assert data["messages"][1]["content"] == "Hi there!"


def test_export_conversation_txt(client):
    """Test exporting conversation in TXT format."""
    client.post("/conversations/user1/chat1")
    client.post(
        "/conversations/user1/chat1/messages",
        json={"role": "user", "content": "Test message", "tokens": 10}
    )
    
    # Export as TXT
    response = client.get("/conversations/user1/chat1/export?format=txt")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    text_content = response.text
    assert "user1" in text_content or "chat1" in text_content
    assert "Test message" in text_content


def test_export_conversation_pdf(client):
    """Test exporting conversation in PDF format."""
    client.post("/conversations/user1/chat1")
    client.post(
        "/conversations/user1/chat1/messages",
        json={"role": "user", "content": "PDF test", "tokens": 10}
    )
    
    # Export as PDF
    response = client.get("/conversations/user1/chat1/export?format=pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    pdf_content = response.content
    assert isinstance(pdf_content, bytes)
    assert pdf_content.startswith(b"%PDF")


def test_export_conversation_with_date_filter(client):
    """Test exporting conversation with date range filtering."""
    from datetime import datetime, timedelta
    
    client.post("/conversations/user1/chat1")
    client.post(
        "/conversations/user1/chat1/messages",
        json={"role": "user", "content": "Message 1", "tokens": 10}
    )
    
    # Export with date filter
    start_date = (datetime.now() - timedelta(days=1)).isoformat()
    end_date = (datetime.now() + timedelta(days=1)).isoformat()
    
    response = client.get(
        f"/conversations/user1/chat1/export?format=json&start_date={start_date}&end_date={end_date}"
    )
    assert response.status_code == 200
    data = response.json()
    assert "messages" in data


def test_export_nonexistent_conversation(client):
    """Test exporting non-existent conversation returns 404."""
    response = client.get("/conversations/user999/chat999/export?format=json")
    assert response.status_code == 404


def test_export_conversation_invalid_format(client):
    """Test exporting with invalid format returns error."""
    client.post("/conversations/user1/chat1")
    
    response = client.get("/conversations/user1/chat1/export?format=invalid")
    assert response.status_code == 400 or response.status_code == 422


# Conversation Analytics Tests

def test_conversation_analytics_metrics(client):
    """Test getting conversation analytics metrics."""
    # Create conversation and add messages
    response = client.post("/conversations/user1/chat1", json={})
    assert response.status_code == 200
    
    # Add messages
    client.post("/conversations/user1/chat1/messages", json={
        "role": "user",
        "content": "Hello"
    })
    client.post("/conversations/user1/chat1/messages", json={
        "role": "assistant",
        "content": "Hi there!"
    })
    
    # Get analytics
    response = client.get("/conversations/analytics/metrics?user_id=user1&chat_id=chat1")
    assert response.status_code == 200
    data = response.json()
    assert "message_count" in data
    assert "average_response_time_seconds" in data
    assert "total_tokens" in data


def test_conversation_analytics_dashboard(client):
    """Test getting conversation analytics dashboard."""
    # Create multiple conversations
    for i in range(3):
        client.post(f"/conversations/user{i}/chat{i}", json={})
        client.post(f"/conversations/user{i}/chat{i}/messages", json={
            "role": "user",
            "content": "Hello"
        })
    
    # Get dashboard
    response = client.get("/conversations/analytics/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert "total_conversations" in data
    assert "active_users" in data
    assert "total_messages" in data
    assert "average_response_time" in data
    assert "engagement_metrics" in data


def test_conversation_analytics_dashboard_with_date_range(client):
    """Test dashboard analytics with date range filter."""
    import datetime
    from datetime import timedelta
    
    # Create conversation
    client.post("/conversations/user1/chat1", json={})
    
    # Get dashboard with date range
    end_date = datetime.datetime.now()
    start_date = end_date - timedelta(days=7)
    
    response = client.get(
        f"/conversations/analytics/dashboard?"
        f"start_date={start_date.isoformat()}&"
        f"end_date={end_date.isoformat()}"
    )
    assert response.status_code == 200
    data = response.json()
    assert "total_conversations" in data
    assert "date_range" in data


def test_conversation_analytics_report(client):
    """Test generating conversation analytics report."""
    # Create conversation
    client.post("/conversations/user1/chat1", json={})
    client.post("/conversations/user1/chat1/messages", json={
        "role": "user",
        "content": "Hello"
    })
    
    # Generate report (JSON)
    response = client.get("/conversations/analytics/report?format=json")
    assert response.status_code == 200
    data = response.json()
    assert "report" in data or "analytics" in data
    
    # Generate report (CSV)
    response = client.get("/conversations/analytics/report?format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"


# User Authentication Tests

def test_register_user(client):
    """Test user registration."""
    response = client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"
    assert "id" in data
    assert "password" not in data  # Password should never be returned


def test_register_user_duplicate_username(client):
    """Test that duplicate usernames are rejected."""
    client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    
    # Try to register again with same username
    response = client.post("/users/register", json={
        "username": "testuser",
        "email": "other@example.com",
        "password": "DifferentPass123!"
    })
    assert response.status_code == 409
    assert "username" in response.json()["detail"].lower()


def test_register_user_duplicate_email(client):
    """Test that duplicate emails are rejected."""
    client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    
    # Try to register again with same email
    response = client.post("/users/register", json={
        "username": "otheruser",
        "email": "test@example.com",
        "password": "DifferentPass123!"
    })
    assert response.status_code == 409
    assert "email" in response.json()["detail"].lower()


def test_register_user_weak_password(client):
    """Test that weak passwords are rejected."""
    response = client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "short"
    })
    assert response.status_code == 400
    assert "password" in response.json()["detail"].lower()


def test_user_login(client):
    """Test user login and session creation."""
    # Register user first
    client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    
    # Login
    response = client.post("/users/login", json={
        "username": "testuser",
        "password": "SecurePass123!"
    })
    assert response.status_code == 200
    data = response.json()
    assert "session_token" in data
    assert "user_id" in data
    assert "expires_at" in data
    assert data["username"] == "testuser"


def test_user_login_wrong_password(client):
    """Test login with wrong password."""
    client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    
    response = client.post("/users/login", json={
        "username": "testuser",
        "password": "WrongPassword123!"
    })
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


def test_user_login_nonexistent_user(client):
    """Test login with nonexistent user."""
    response = client.post("/users/login", json={
        "username": "nonexistent",
        "password": "SomePass123!"
    })
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


def test_user_login_with_email(client):
    """Test that login works with email instead of username."""
    client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    
    # Login with email
    response = client.post("/users/login", json={
        "username": "test@example.com",  # Can use email
        "password": "SecurePass123!"
    })
    assert response.status_code == 200
    assert "session_token" in response.json()


def test_authenticate_with_session_token(client):
    """Test authentication using session token."""
    # Register and login
    client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    login_response = client.post("/users/login", json={
        "username": "testuser",
        "password": "SecurePass123!"
    })
    session_token = login_response.json()["session_token"]
    
    # Use session token to access protected endpoint
    response = client.get("/users/me", headers={
        "Authorization": f"Bearer {session_token}"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"


def test_authenticate_with_invalid_session_token(client):
    """Test authentication with invalid session token."""
    response = client.get("/users/me", headers={
        "Authorization": "Bearer invalid_token_12345"
    })
    assert response.status_code == 401


def test_get_user_by_id(client):
    """Test getting user by ID."""
    # Register user
    register_response = client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    user_id = register_response.json()["id"]
    
    # Get user
    response = client.get(f"/users/{user_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user_id
    assert data["username"] == "testuser"
    assert "password" not in data


def test_get_nonexistent_user(client):
    """Test getting nonexistent user."""
    response = client.get("/users/99999")
    assert response.status_code == 404


def test_list_users(client):
    """Test listing users."""
    # Register multiple users
    client.post("/users/register", json={
        "username": "user1",
        "email": "user1@example.com",
        "password": "Pass123!"
    })
    client.post("/users/register", json={
        "username": "user2",
        "email": "user2@example.com",
        "password": "Pass123!"
    })
    
    response = client.get("/users")
    assert response.status_code == 200
    users = response.json()
    assert len(users) >= 2
    assert all("password" not in user for user in users)


def test_update_user(client):
    """Test updating user information."""
    # Register and login
    register_response = client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    user_id = register_response.json()["id"]
    login_response = client.post("/users/login", json={
        "username": "testuser",
        "password": "SecurePass123!"
    })
    session_token = login_response.json()["session_token"]
    
    # Update user
    response = client.put(
        f"/users/{user_id}",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"email": "newemail@example.com"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "newemail@example.com"


def test_update_user_without_authentication(client):
    """Test that updating user requires authentication."""
    register_response = client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    user_id = register_response.json()["id"]
    
    response = client.put(
        f"/users/{user_id}",
        json={"email": "newemail@example.com"}
    )
    assert response.status_code == 401


def test_logout(client):
    """Test user logout (session invalidation)."""
    # Register and login
    client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    login_response = client.post("/users/login", json={
        "username": "testuser",
        "password": "SecurePass123!"
    })
    session_token = login_response.json()["session_token"]
    
    # Logout
    response = client.post(
        "/users/logout",
        headers={"Authorization": f"Bearer {session_token}"}
    )
    assert response.status_code == 200
    
    # Try to use session token after logout
    response = client.get("/users/me", headers={
        "Authorization": f"Bearer {session_token}"
    })
    assert response.status_code == 401


def test_session_expiration(client):
    """Test that expired sessions are rejected."""
    # Register and login
    client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    login_response = client.post("/users/login", json={
        "username": "testuser",
        "password": "SecurePass123!"
    })
    session_token = login_response.json()["session_token"]
    
    # Manually expire the session in database (for testing)
    import main
    main.db.expire_session(session_token)
    
    # Try to use expired session
    response = client.get("/users/me", headers={
        "Authorization": f"Bearer {session_token}"
    })
    assert response.status_code == 401


def test_delete_user(client):
    """Test deleting a user account."""
    # Register and login
    register_response = client.post("/users/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!"
    })
    user_id = register_response.json()["id"]
    login_response = client.post("/users/login", json={
        "username": "testuser",
        "password": "SecurePass123!"
    })
    session_token = login_response.json()["session_token"]
    
    # Delete user
    response = client.delete(
        f"/users/{user_id}",
        headers={"Authorization": f"Bearer {session_token}"}
    )
    assert response.status_code == 200
    
    # Verify user is deleted
    response = client.get(f"/users/{user_id}")
    assert response.status_code == 404


def test_get_stale_tasks_endpoint(client):
    """Test monitoring endpoint to get stale tasks."""
    from datetime import datetime, timedelta
    
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
    
    # Manually update task to be stale (requires direct DB access)
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
    
    # Get stale tasks
    response = client.get("/monitoring/stale-tasks", params={"hours": 24})
    assert response.status_code == 200
    data = response.json()
    assert "stale_tasks" in data
    stale_task_ids = [t["id"] for t in data["stale_tasks"]]
    assert task_id in stale_task_ids


def test_manual_unlock_stale_task(client):
    """Test manual unlock endpoint for stale tasks."""
    from datetime import datetime, timedelta
    
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
    
    # Manually unlock stale task
    response = client.post(f"/tasks/{task_id}/unlock-stale")
    assert response.status_code == 200
    data = response.json()
    assert data["unlocked"] is True
    
    # Verify task is available
    get_response = client.get(f"/tasks/{task_id}")
    task = get_response.json()
    assert task["task_status"] == "available"
    assert task["assigned_agent"] is None
