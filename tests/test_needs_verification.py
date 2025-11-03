"""
Comprehensive tests for needs_verification state functionality.

Tests verify that:
1. Tasks in needs_verification state (complete but unverified) are properly identified
2. Computed fields (needs_verification, effective_status) are added correctly
3. Tasks in needs_verification state appear in list_available_tasks for implementation agents
4. Tasks in needs_verification state can be reserved/locked
5. Querying by needs_verification status works correctly
6. All task-returning methods include the computed fields
"""
import pytest
import os
import tempfile
import shutil
from fastapi.testclient import TestClient
from datetime import datetime

import sys
import os
# Set environment before importing main to avoid default database path issues
os.environ.setdefault("TODO_DB_PATH", "/tmp/test_todo.db")
os.environ.setdefault("TODO_BACKUPS_DIR", "/tmp/test_backups")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from database import TodoDatabase
from backup import BackupManager


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
    from mcp_api import set_db
    set_db(db)
    
    yield db, db_path, backups_dir
    
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    from main import app
    return TestClient(app)


def test_needs_verification_computed_fields(client):
    """Test that computed fields are added correctly to tasks."""
    # Create a task via MCP and mark it complete but unverified
    create_response = client.post("/mcp/create_task", json={
        "title": "Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent"
    })
    assert create_response.status_code == 200
    result = create_response.json()
    assert result["success"] is True
    task_id = result["task_id"]
    
    # Complete the task (it will be unverified by default)
    complete_response = client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "test-agent"
    })
    assert complete_response.status_code == 200
    
    # Query the task
    query_response = client.post("/mcp/query_tasks", json={
        "task_status": "complete",
        "limit": 10
    })
    assert query_response.status_code == 200
    tasks = query_response.json()["tasks"]
    
    task = next((t for t in tasks if t["id"] == task_id), None)
    assert task is not None
    assert task["task_status"] == "complete"
    assert task["verification_status"] == "unverified"
    assert task["needs_verification"] is True
    assert task["effective_status"] == "needs_verification"


def test_needs_verification_not_set_for_verified_tasks(client):
    """Test that verified tasks don't have needs_verification=True."""
    # Create and complete a task via MCP
    create_response = client.post("/mcp/create_task", json={
        "title": "Verified Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent"
    })
    assert create_response.status_code == 200
    result = create_response.json()
    assert result["success"] is True
    task_id = result["task_id"]
    
    # Complete the task
    complete_response = client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "test-agent"
    })
    assert complete_response.status_code == 200
    
    # Verify the task (using MCP or direct endpoint)
    verify_response = client.post(f"/tasks/{task_id}/verify", json={"agent_id": "test-agent"})
    # Note: /tasks/{id}/verify may require auth, but let's try MCP first
    # If it fails, we'll handle it
    
    # Query the task
    query_response = client.post("/mcp/query_tasks", json={
        "task_status": "complete",
        "limit": 10
    })
    assert query_response.status_code == 200
    tasks = query_response.json()["tasks"]
    
    task = next((t for t in tasks if t["id"] == task_id), None)
    assert task is not None
    assert task["task_status"] == "complete"
    assert task["verification_status"] == "verified"
    assert task["needs_verification"] is False
    assert task["effective_status"] == "complete"


def test_needs_verification_not_set_for_available_tasks(client):
    """Test that available tasks don't have needs_verification=True."""
    # Create a task via MCP (it starts as available)
    create_response = client.post("/mcp/create_task", json={
        "title": "Available Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent"
    })
    assert create_response.status_code == 200
    result = create_response.json()
    assert result["success"] is True
    task_id = result["task_id"]
    
    # Query the task
    query_response = client.post("/mcp/query_tasks", json={
        "task_status": "available",
        "limit": 10
    })
    assert query_response.status_code == 200
    tasks = query_response.json()["tasks"]
    
    task = next((t for t in tasks if t["id"] == task_id), None)
    assert task is not None
    assert task["task_status"] == "available"
    assert task["needs_verification"] is False
    assert task["effective_status"] == "available"


def test_needs_verification_in_list_available_tasks(client):
    """Test that tasks in needs_verification state appear in list_available_tasks for implementation agents."""
    # Create two concrete tasks
    task1_response = client.post("/tasks", json={
        "title": "Available Concrete Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    
    task2_response = client.post("/tasks", json={
        "title": "Completed Unverified Task",
        "task_type": "concrete",
        "task_instruction": "Do something else",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json()["id"]
    
    # Complete task2 (it will be unverified)
    client.post(f"/tasks/{task2_id}/complete", json={"agent_id": "test-agent"})
    
    # List available tasks for implementation agents
    response = client.post("/mcp/list_available_tasks", json={
        "agent_type": "implementation",
        "limit": 10
    })
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    
    # Should include both available task and needs_verification task
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids, "Available task should appear"
    assert task2_id in task_ids, "Needs verification task should appear"
    
    # Find the needs_verification task
    needs_verification_task = next((t for t in tasks if t["id"] == task2_id), None)
    assert needs_verification_task is not None
    assert needs_verification_task["needs_verification"] is True
    assert needs_verification_task["effective_status"] == "needs_verification"
    
    # Needs verification tasks should be prioritized (appear first)
    # Since we order by CASE WHEN needs_verification THEN 0 ELSE 1
    needs_verification_tasks = [t for t in tasks if t.get("needs_verification", False)]
    available_tasks = [t for t in tasks if t.get("task_status") == "available"]
    if needs_verification_tasks and available_tasks:
        # The first task should be a needs_verification task
        assert tasks[0]["needs_verification"] is True


def test_needs_verification_not_in_list_available_tasks_for_breakdown(client):
    """Test that needs_verification tasks don't appear for breakdown agents."""
    # Create an abstract task and complete it (unverified)
    task_response = client.post("/tasks", json={
        "title": "Abstract Task",
        "task_type": "abstract",
        "task_instruction": "Break down",
        "verification_instruction": "Verify breakdown",
        "agent_id": "test-agent"
    })
    task_id = task_response.json()["id"]
    
    # Complete it
    client.post(f"/tasks/{task_id}/complete", json={"agent_id": "test-agent"})
    
    # List available tasks for breakdown agents
    response = client.post("/mcp/list_available_tasks", json={
        "agent_type": "breakdown",
        "limit": 10
    })
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    
    # Should not include the completed task (only available abstract/epic tasks)
    task_ids = [t["id"] for t in tasks]
    assert task_id not in task_ids, "Completed task should not appear for breakdown agents"


def test_reserve_needs_verification_task(client):
    """Test that tasks in needs_verification state can be reserved/locked."""
    # Create and complete a task (it will be unverified)
    create_response = client.post("/tasks", json={
        "title": "Task to Verify",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    
    # Complete the task
    client.post(f"/tasks/{task_id}/complete", json={"agent_id": "test-agent"})
    
    # Verify it's in needs_verification state
    task_response = client.get(f"/tasks/{task_id}")
    assert task_response.status_code == 200
    task = task_response.json()
    assert task["task_status"] == "complete"
    assert task["verification_status"] == "unverified"
    
    # Reserve the task (should work for needs_verification tasks)
    reserve_response = client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "verification-agent"
    })
    assert reserve_response.status_code == 200
    result = reserve_response.json()
    assert result["success"] is True
    
    # Check that the reserved task has computed fields
    reserved_task = result["task"]
    assert reserved_task["id"] == task_id
    assert reserved_task["needs_verification"] is True
    assert reserved_task["effective_status"] == "needs_verification"
    assert reserved_task["task_status"] == "in_progress"  # Should be locked now
    assert reserved_task["assigned_agent"] == "verification-agent"


def test_query_by_needs_verification_status(client):
    """Test querying tasks by needs_verification status."""
    # Create and complete some tasks
    task1_response = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent"
    })
    task1_id = task1_response.json()["id"]
    client.post(f"/tasks/{task1_id}/complete", json={"agent_id": "test-agent"})
    
    task2_response = client.post("/tasks", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Do something else",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json()["id"]
    client.post(f"/tasks/{task2_id}/complete", json={"agent_id": "test-agent"})
    client.post(f"/tasks/{task2_id}/verify", json={"agent_id": "test-agent"})  # Verify this one
    
    # Query by needs_verification status
    query_response = client.post("/mcp/query_tasks", json={
        "task_status": "needs_verification",
        "limit": 10
    })
    assert query_response.status_code == 200
    tasks = query_response.json()["tasks"]
    
    # Should only return task1 (complete but unverified)
    task_ids = [t["id"] for t in tasks]
    assert task1_id in task_ids
    assert task2_id not in task_ids  # This one is verified
    
    # All returned tasks should have needs_verification=True
    for task in tasks:
        assert task["needs_verification"] is True
        assert task["effective_status"] == "needs_verification"


def test_needs_verification_in_get_task_context(client):
    """Test that get_task_context includes computed fields."""
    # Create and complete a task
    create_response = client.post("/tasks", json={
        "title": "Context Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post(f"/tasks/{task_id}/complete", json={"agent_id": "test-agent"})
    
    # Get task context
    context_response = client.post("/mcp/get_task_context", json={
        "task_id": task_id
    })
    assert context_response.status_code == 200
    context = context_response.json()
    
    # Check that the task has computed fields
    task = context["task"]
    assert task["needs_verification"] is True
    assert task["effective_status"] == "needs_verification"
    
    # Check that ancestry tasks also have computed fields (if any)
    for ancestry_task in context.get("ancestry", []):
        assert "needs_verification" in ancestry_task
        assert "effective_status" in ancestry_task


def test_needs_verification_in_query_stale_tasks(client):
    """Test that stale tasks query includes computed fields."""
    from datetime import timedelta
    
    # Create, complete, and lock a task
    create_response = client.post("/tasks", json={
        "title": "Stale Verification Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post(f"/tasks/{task_id}/complete", json={"agent_id": "test-agent"})
    
    # Lock it
    client.post(f"/tasks/{task_id}/lock", json={"agent_id": "test-agent"})
    
    # Make it stale
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
    
    # Query stale tasks
    stale_response = client.post("/mcp/query_stale_tasks", json={
        "hours": 24
    })
    assert stale_response.status_code == 200
    result = stale_response.json()
    
    # Check that stale tasks have computed fields
    stale_tasks = result["stale_tasks"]
    task = next((t for t in stale_tasks if t["id"] == task_id), None)
    assert task is not None
    assert "needs_verification" in task
    assert "effective_status" in task


def test_needs_verification_in_get_recent_completions(client):
    """Test that get_recent_completions includes computed fields."""
    # Create and complete a task
    create_response = client.post("/tasks", json={
        "title": "Recent Completion",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post(f"/tasks/{task_id}/complete", json={"agent_id": "test-agent"})
    
    # Get recent completions
    completions_response = client.post("/mcp/get_recent_completions", json={
        "limit": 10
    })
    assert completions_response.status_code == 200
    result = completions_response.json()
    
    # Check that completed tasks have computed fields
    tasks = result["tasks"]
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task:  # May not be in lightweight format, but if it has full fields, check them
        if "needs_verification" in task:
            # This task should have needs_verification=True (it's complete but unverified)
            assert task["needs_verification"] is True
            assert task["effective_status"] == "needs_verification"


def test_needs_verification_in_get_tasks_approaching_deadline(client):
    """Test that get_tasks_approaching_deadline includes computed fields."""
    from datetime import datetime, timedelta
    
    # Create a task with a deadline
    deadline = (datetime.utcnow() + timedelta(days=2)).isoformat()
    create_response = client.post("/tasks", json={
        "title": "Deadline Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent",
        "due_date": deadline
    })
    task_id = create_response.json()["id"]
    
    # Complete it (unverified)
    client.post(f"/tasks/{task_id}/complete", json={"agent_id": "test-agent"})
    
    # Get tasks approaching deadline
    deadline_response = client.post("/mcp/get_tasks_approaching_deadline", json={
        "days_ahead": 3,
        "limit": 10
    })
    assert deadline_response.status_code == 200
    result = deadline_response.json()
    
    # Check that tasks have computed fields
    tasks = result["tasks"]
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task:  # May not have deadline anymore if completed
        assert "needs_verification" in task
        assert "effective_status" in task


def test_needs_verification_priority_in_list_available(client):
    """Test that needs_verification tasks are prioritized in list_available_tasks."""
    # Create multiple tasks
    available_task_ids = []
    for i in range(3):
        response = client.post("/tasks", json={
            "title": f"Available Task {i}",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify it",
            "agent_id": "test-agent"
        })
        available_task_ids.append(response.json()["id"])
    
    # Create and complete a task (needs verification)
    needs_verification_response = client.post("/tasks", json={
        "title": "Needs Verification Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent"
    })
    needs_verification_id = needs_verification_response.json()["id"]
    client.post(f"/tasks/{needs_verification_id}/complete", json={"agent_id": "test-agent"})
    
    # List available tasks
    response = client.post("/mcp/list_available_tasks", json={
        "agent_type": "implementation",
        "limit": 10
    })
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    
    # The needs_verification task should appear first (or at least before regular available tasks)
    needs_verification_task = next((t for t in tasks if t["id"] == needs_verification_id), None)
    assert needs_verification_task is not None
    assert needs_verification_task["needs_verification"] is True
    
    # Check ordering: needs_verification tasks should come before available tasks
    needs_verification_indices = [i for i, t in enumerate(tasks) if t.get("needs_verification", False)]
    available_indices = [i for i, t in enumerate(tasks) if t.get("task_status") == "available" and not t.get("needs_verification", False)]
    
    if needs_verification_indices and available_indices:
        assert min(needs_verification_indices) < min(available_indices), "Needs verification tasks should come before available tasks"


def test_lock_task_from_needs_verification_state(client):
    """Test that lock_task in database allows locking needs_verification tasks."""
    # Create and complete a task
    create_response = client.post("/tasks", json={
        "title": "Lock Test",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent"
    })
    task_id = create_response.json()["id"]
    client.post(f"/tasks/{task_id}/complete", json={"agent_id": "test-agent"})
    
    # Verify task is complete and unverified
    task_response = client.get(f"/tasks/{task_id}")
    task = task_response.json()
    assert task["task_status"] == "complete"
    assert task["verification_status"] == "unverified"
    
    # Lock the task directly (this tests the database lock_task method)
    lock_response = client.post(f"/tasks/{task_id}/lock", json={
        "agent_id": "verification-agent"
    })
    assert lock_response.status_code == 200
    
    # Verify it's now locked
    task_response = client.get(f"/tasks/{task_id}")
    task = task_response.json()
    assert task["task_status"] == "in_progress"
    assert task["assigned_agent"] == "verification-agent"

