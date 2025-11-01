"""
Tests for database operations.
"""
import pytest
import sqlite3
import os
import tempfile
import shutil
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import TodoDatabase


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    db = TodoDatabase(db_path)
    yield db, db_path
    shutil.rmtree(temp_dir)


def test_create_task(temp_db):
    """Test creating a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    assert task_id > 0
    
    task = db.get_task(task_id)
    assert task is not None
    assert task["title"] == "Test Task"
    assert task["task_type"] == "concrete"
    assert task["task_status"] == "available"


def test_lock_task(temp_db):
    """Test locking a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    # Lock task
    success = db.lock_task(task_id, "agent-1")
    assert success is True
    
    task = db.get_task(task_id)
    assert task["task_status"] == "in_progress"
    assert task["assigned_agent"] == "agent-1"
    
    # Try to lock again (should fail)
    success = db.lock_task(task_id, "agent-2")
    assert success is False


def test_complete_task(temp_db):
    """Test completing a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    db.complete_task(task_id, "agent-1", notes="Done!")
    
    task = db.get_task(task_id)
    assert task["task_status"] == "complete"
    assert task["completed_at"] is not None


def test_verify_task(temp_db):
    """Test verifying a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    db.complete_task(task_id, "agent-1")
    db.verify_task(task_id, "agent-1")
    
    task = db.get_task(task_id)
    assert task["verification_status"] == "verified"


def test_create_relationship(temp_db):
    """Test creating task relationships."""
    db, _ = temp_db
    parent_id = db.create_task(
        title="Parent Task",
        task_type="epic",
        task_instruction="Big task",
        verification_instruction="Verify epic",
        agent_id="test-agent"
    )
    child_id = db.create_task(
        title="Child Task",
        task_type="concrete",
        task_instruction="Small task",
        verification_instruction="Verify child",
        agent_id="test-agent"
    )
    
    rel_id = db.create_relationship(parent_id, child_id, "subtask", "test-agent")
    assert rel_id > 0
    
    # Test blocking relationship
    blocking_id = db.create_task(
        title="Blocking Task",
        task_type="concrete",
        task_instruction="Block task",
        verification_instruction="Verify block",
        agent_id="test-agent"
    )
    
    db.create_relationship(blocking_id, parent_id, "blocked_by", "test-agent")
    
    parent_task = db.get_task(parent_id)
    assert parent_task["task_status"] == "blocked"


def test_change_history(temp_db):
    """Test change history tracking."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    # Check creation history
    history = db.get_change_history(task_id=task_id)
    assert len(history) >= 1
    assert history[0]["change_type"] == "created"
    assert history[0]["agent_id"] == "test-agent"
    
    # Lock and check history
    db.lock_task(task_id, "agent-1")
    history = db.get_change_history(task_id=task_id)
    assert len(history) >= 2
    assert any(h["change_type"] == "locked" for h in history)
    
    # Complete and check history
    db.complete_task(task_id, "agent-1")
    history = db.get_change_history(task_id=task_id)
    assert any(h["change_type"] == "completed" for h in history)


def test_get_available_tasks(temp_db):
    """Test getting available tasks for agents."""
    db, _ = temp_db
    
    # Create abstract task
    abstract_id = db.create_task(
        title="Abstract Task",
        task_type="abstract",
        task_instruction="Break this down",
        verification_instruction="Verify breakdown",
        agent_id="test-agent"
    )
    
    # Create concrete task
    concrete_id = db.create_task(
        title="Concrete Task",
        task_type="concrete",
        task_instruction="Do this",
        verification_instruction="Verify done",
        agent_id="test-agent"
    )
    
    # Get breakdown tasks
    breakdown_tasks = db.get_available_tasks_for_agent("breakdown", limit=10)
    assert len(breakdown_tasks) >= 1
    assert any(t["id"] == abstract_id for t in breakdown_tasks)
    
    # Get implementation tasks
    impl_tasks = db.get_available_tasks_for_agent("implementation", limit=10)
    assert len(impl_tasks) >= 1
    assert any(t["id"] == concrete_id for t in impl_tasks)


def test_agent_stats(temp_db):
    """Test agent statistics."""
    db, _ = temp_db
    
    # Create and complete tasks
    task1 = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do 1",
        verification_instruction="Verify 1",
        agent_id="test-agent"
    )
    task2 = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do 2",
        verification_instruction="Verify 2",
        agent_id="test-agent"
    )
    
    db.complete_task(task1, "test-agent")
    db.verify_task(task1, "test-agent")
    db.complete_task(task2, "test-agent")
    
    stats = db.get_agent_stats("test-agent")
    assert stats["tasks_completed"] == 2
    assert stats["tasks_verified"] >= 1

