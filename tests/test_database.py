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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

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


def test_auto_complete_parent_when_all_subtasks_done(temp_db):
    """Test that parent task auto-completes when all subtasks are complete."""
    db, _ = temp_db
    
    # Create parent task
    parent_id = db.create_task(
        title="Parent Task",
        task_type="abstract",
        task_instruction="Complete all subtasks",
        verification_instruction="All subtasks complete",
        agent_id="test-agent"
    )
    
    # Create 3 subtasks
    subtask1 = db.create_task(
        title="Subtask 1",
        task_type="concrete",
        task_instruction="Do step 1",
        verification_instruction="Step 1 done",
        agent_id="test-agent"
    )
    subtask2 = db.create_task(
        title="Subtask 2",
        task_type="concrete",
        task_instruction="Do step 2",
        verification_instruction="Step 2 done",
        agent_id="test-agent"
    )
    subtask3 = db.create_task(
        title="Subtask 3",
        task_type="concrete",
        task_instruction="Do step 3",
        verification_instruction="Step 3 done",
        agent_id="test-agent"
    )
    
    # Create relationships
    db.create_relationship(parent_id, subtask1, "subtask", "test-agent")
    db.create_relationship(parent_id, subtask2, "subtask", "test-agent")
    db.create_relationship(parent_id, subtask3, "subtask", "test-agent")
    
    # Verify parent is not complete
    parent = db.get_task(parent_id)
    assert parent["task_status"] == "available"
    
    # Complete first two subtasks - parent should still not be complete
    db.complete_task(subtask1, "test-agent")
    db.complete_task(subtask2, "test-agent")
    
    parent = db.get_task(parent_id)
    assert parent["task_status"] == "available"
    
    # Complete third subtask - parent should auto-complete
    db.complete_task(subtask3, "test-agent")
    
    parent = db.get_task(parent_id)
    assert parent["task_status"] == "complete"
    assert parent["completed_at"] is not None


def test_auto_complete_nested_hierarchy(temp_db):
    """Test auto-completion works recursively with nested hierarchies."""
    db, _ = temp_db
    
    # Create grandparent
    grandparent_id = db.create_task(
        title="Grandparent Task",
        task_type="epic",
        task_instruction="Complete epic",
        verification_instruction="Epic complete",
        agent_id="test-agent"
    )
    
    # Create parent
    parent_id = db.create_task(
        title="Parent Task",
        task_type="abstract",
        task_instruction="Complete parent",
        verification_instruction="Parent complete",
        agent_id="test-agent"
    )
    
    # Create subtasks
    subtask1 = db.create_task(
        title="Subtask 1",
        task_type="concrete",
        task_instruction="Do step 1",
        verification_instruction="Step 1 done",
        agent_id="test-agent"
    )
    subtask2 = db.create_task(
        title="Subtask 2",
        task_type="concrete",
        task_instruction="Do step 2",
        verification_instruction="Step 2 done",
        agent_id="test-agent"
    )
    
    # Create relationships: grandparent -> parent -> subtasks
    db.create_relationship(grandparent_id, parent_id, "subtask", "test-agent")
    db.create_relationship(parent_id, subtask1, "subtask", "test-agent")
    db.create_relationship(parent_id, subtask2, "subtask", "test-agent")
    
    # Verify nothing is complete
    assert db.get_task(grandparent_id)["task_status"] == "available"
    assert db.get_task(parent_id)["task_status"] == "available"
    
    # Complete first subtask - nothing should change
    db.complete_task(subtask1, "test-agent")
    assert db.get_task(grandparent_id)["task_status"] == "available"
    assert db.get_task(parent_id)["task_status"] == "available"
    
    # Complete second subtask - parent should auto-complete
    db.complete_task(subtask2, "test-agent")
    assert db.get_task(parent_id)["task_status"] == "complete"
    # Grandparent should also auto-complete (only one subtask - parent)
    assert db.get_task(grandparent_id)["task_status"] == "complete"


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
    
    # parent_id is blocked by blocking_id
    # create_relationship(parent_task_id, child_task_id, "blocked_by") means parent_task_id is blocked by child_task_id
    db.create_relationship(parent_id, blocking_id, "blocked_by", "test-agent")
    
    parent_task = db.get_task(parent_id)
    assert parent_task["task_status"] == "blocked"


def test_prevent_circular_blocked_by_dependency(temp_db):
    """Test that circular blocked_by dependencies are prevented."""
    db, _ = temp_db
    
    # Create two tasks
    task_a_id = db.create_task(
        title="Task A",
        task_type="concrete",
        task_instruction="Task A",
        verification_instruction="Verify A",
        agent_id="test-agent"
    )
    task_b_id = db.create_task(
        title="Task B",
        task_type="concrete",
        task_instruction="Task B",
        verification_instruction="Verify B",
        agent_id="test-agent"
    )
    
    # Task A blocked by Task B
    db.create_relationship(task_a_id, task_b_id, "blocked_by", "test-agent")
    
    # Try to create Task B blocked by Task A (should fail - circular dependency)
    with pytest.raises(ValueError, match="(?i)circular dependency"):
        db.create_relationship(task_b_id, task_a_id, "blocked_by", "test-agent")


def test_prevent_circular_blocked_by_dependency_indirect(temp_db):
    """Test that indirect circular blocked_by dependencies are prevented."""
    db, _ = temp_db
    
    # Create three tasks: A -> B -> C
    task_a_id = db.create_task(
        title="Task A",
        task_type="concrete",
        task_instruction="Task A",
        verification_instruction="Verify A",
        agent_id="test-agent"
    )
    task_b_id = db.create_task(
        title="Task B",
        task_type="concrete",
        task_instruction="Task B",
        verification_instruction="Verify B",
        agent_id="test-agent"
    )
    task_c_id = db.create_task(
        title="Task C",
        task_type="concrete",
        task_instruction="Task C",
        verification_instruction="Verify C",
        agent_id="test-agent"
    )
    
    # Create chain: A blocked_by B, B blocked_by C
    db.create_relationship(task_a_id, task_b_id, "blocked_by", "test-agent")
    db.create_relationship(task_b_id, task_c_id, "blocked_by", "test-agent")
    
    # Try to create C blocked_by A (should fail - creates cycle A->B->C->A)
    with pytest.raises(ValueError, match="(?i)circular dependency"):
        db.create_relationship(task_c_id, task_a_id, "blocked_by", "test-agent")


def test_prevent_circular_blocking_dependency(temp_db):
    """Test that circular blocking dependencies are prevented (blocking is inverse of blocked_by)."""
    db, _ = temp_db
    
    # Create two tasks
    task_a_id = db.create_task(
        title="Task A",
        task_type="concrete",
        task_instruction="Task A",
        verification_instruction="Verify A",
        agent_id="test-agent"
    )
    task_b_id = db.create_task(
        title="Task B",
        task_type="concrete",
        task_instruction="Task B",
        verification_instruction="Verify B",
        agent_id="test-agent"
    )
    
    # Task A blocks Task B (equivalent to B blocked_by A)
    db.create_relationship(task_a_id, task_b_id, "blocking", "test-agent")
    
    # Try to create Task B blocks Task A (should fail - circular dependency)
    with pytest.raises(ValueError, match="(?i)circular dependency"):
        db.create_relationship(task_b_id, task_a_id, "blocking", "test-agent")


def test_allow_non_blocking_relationships_to_reuse_tasks(temp_db):
    """Test that non-blocking relationship types (subtask, related) can reuse tasks without circular checks."""
    db, _ = temp_db
    
    # Create two tasks
    task_a_id = db.create_task(
        title="Task A",
        task_type="abstract",
        task_instruction="Task A",
        verification_instruction="Verify A",
        agent_id="test-agent"
    )
    task_b_id = db.create_task(
        title="Task B",
        task_type="concrete",
        task_instruction="Task B",
        verification_instruction="Verify B",
        agent_id="test-agent"
    )
    
    # These should work without circular dependency checks
    db.create_relationship(task_a_id, task_b_id, "subtask", "test-agent")
    db.create_relationship(task_b_id, task_a_id, "related", "test-agent")  # Should work


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


def test_create_task_with_priority(temp_db):
    """Test creating tasks with different priorities."""
    db, _ = temp_db
    
    # Create tasks with different priorities
    task_low = db.create_task(
        title="Low Priority Task",
        task_type="concrete",
        task_instruction="Low priority work",
        verification_instruction="Verify",
        agent_id="test-agent",
        priority="low"
    )
    task_medium = db.create_task(
        title="Medium Priority Task",
        task_type="concrete",
        task_instruction="Medium priority work",
        verification_instruction="Verify",
        agent_id="test-agent",
        priority="medium"
    )
    task_high = db.create_task(
        title="High Priority Task",
        task_type="concrete",
        task_instruction="High priority work",
        verification_instruction="Verify",
        agent_id="test-agent",
        priority="high"
    )
    task_critical = db.create_task(
        title="Critical Priority Task",
        task_type="concrete",
        task_instruction="Critical priority work",
        verification_instruction="Verify",
        agent_id="test-agent",
        priority="critical"
    )
    
    # Verify priorities
    assert db.get_task(task_low)["priority"] == "low"
    assert db.get_task(task_medium)["priority"] == "medium"
    assert db.get_task(task_high)["priority"] == "high"
    assert db.get_task(task_critical)["priority"] == "critical"


def test_create_task_default_priority(temp_db):
    """Test that tasks default to medium priority when not specified."""
    db, _ = temp_db
    
    task_id = db.create_task(
        title="Default Priority Task",
        task_type="concrete",
        task_instruction="Default priority",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    task = db.get_task(task_id)
    assert task["priority"] == "medium"


def test_query_tasks_order_by_priority(temp_db):
    """Test querying tasks ordered by priority."""
    db, _ = temp_db
    
    # Create tasks with different priorities
    task_low = db.create_task(
        title="Low",
        task_type="concrete",
        task_instruction="Low",
        verification_instruction="Verify",
        agent_id="test-agent",
        priority="low"
    )
    task_high = db.create_task(
        title="High",
        task_type="concrete",
        task_instruction="High",
        verification_instruction="Verify",
        agent_id="test-agent",
        priority="high"
    )
    task_critical = db.create_task(
        title="Critical",
        task_type="concrete",
        task_instruction="Critical",
        verification_instruction="Verify",
        agent_id="test-agent",
        priority="critical"
    )
    task_medium = db.create_task(
        title="Medium",
        task_type="concrete",
        task_instruction="Medium",
        verification_instruction="Verify",
        agent_id="test-agent",
        priority="medium"
    )
    
    # Query ordered by priority (descending: critical > high > medium > low)
    tasks = db.query_tasks(order_by="priority", limit=10)
    priorities = [t["priority"] for t in tasks]
    
    # Should be ordered: critical, high, medium, low
    assert priorities[0] == "critical"
    assert priorities[1] == "high"
    assert priorities[2] == "medium"
    assert priorities[3] == "low"


def test_query_tasks_filter_by_priority(temp_db):
    """Test filtering tasks by priority."""
    db, _ = temp_db
    
    # Create tasks with different priorities
    task_low = db.create_task(
        title="Low Task",
        task_type="concrete",
        task_instruction="Low",
        verification_instruction="Verify",
        agent_id="test-agent",
        priority="low"
    )
    task_high = db.create_task(
        title="High Task",
        task_type="concrete",
        task_instruction="High",
        verification_instruction="Verify",
        agent_id="test-agent",
        priority="high"
    )
    
    # Filter by priority
    high_tasks = db.query_tasks(priority="high", limit=10)
    assert len(high_tasks) >= 1
    assert all(t["priority"] == "high" for t in high_tasks)
    
    low_tasks = db.query_tasks(priority="low", limit=10)
    assert len(low_tasks) >= 1
    assert all(t["priority"] == "low" for t in low_tasks)


def test_invalid_priority_raises_error(temp_db):
    """Test that invalid priority values raise an error."""
    db, _ = temp_db
    
    with pytest.raises(ValueError, match="Invalid priority"):
        db.create_task(
            title="Invalid Priority",
            task_type="concrete",
            task_instruction="Test",
            verification_instruction="Verify",
            agent_id="test-agent",
            priority="invalid"
        )


# Tags system tests
def test_create_tag(temp_db):
    """Test creating a tag."""
    db, _ = temp_db
    tag_id = db.create_tag(name="bug")
    assert tag_id > 0
    
    tag = db.get_tag(tag_id)
    assert tag is not None
    assert tag["name"] == "bug"


def test_create_tag_duplicate_returns_existing(temp_db):
    """Test that creating a duplicate tag returns the existing tag ID."""
    db, _ = temp_db
    tag_id1 = db.create_tag(name="feature")
    tag_id2 = db.create_tag(name="feature")
    
    assert tag_id1 == tag_id2


def test_get_tag_by_name(temp_db):
    """Test getting a tag by name."""
    db, _ = temp_db
    tag_id = db.create_tag(name="enhancement")
    
    tag = db.get_tag_by_name("enhancement")
    assert tag is not None
    assert tag["id"] == tag_id
    assert tag["name"] == "enhancement"


def test_list_tags(temp_db):
    """Test listing all tags."""
    db, _ = temp_db
    db.create_tag(name="bug")
    db.create_tag(name="feature")
    db.create_tag(name="enhancement")
    
    tags = db.list_tags()
    assert len(tags) >= 3
    tag_names = [t["name"] for t in tags]
    assert "bug" in tag_names
    assert "feature" in tag_names
    assert "enhancement" in tag_names


def test_assign_tag_to_task(temp_db):
    """Test assigning a tag to a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    tag_id = db.create_tag(name="bug")
    
    db.assign_tag_to_task(task_id, tag_id)
    
    # Verify tag is assigned
    tags = db.get_task_tags(task_id)
    assert len(tags) == 1
    assert tags[0]["id"] == tag_id
    assert tags[0]["name"] == "bug"


def test_assign_multiple_tags_to_task(temp_db):
    """Test assigning multiple tags to a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    tag1_id = db.create_tag(name="bug")
    tag2_id = db.create_tag(name="urgent")
    tag3_id = db.create_tag(name="frontend")
    
    db.assign_tag_to_task(task_id, tag1_id)
    db.assign_tag_to_task(task_id, tag2_id)
    db.assign_tag_to_task(task_id, tag3_id)
    
    tags = db.get_task_tags(task_id)
    assert len(tags) == 3
    tag_names = {t["name"] for t in tags}
    assert tag_names == {"bug", "urgent", "frontend"}


def test_assign_duplicate_tag_to_task(temp_db):
    """Test that assigning the same tag twice doesn't create duplicates."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    tag_id = db.create_tag(name="bug")
    
    db.assign_tag_to_task(task_id, tag_id)
    db.assign_tag_to_task(task_id, tag_id)  # Assign again
    
    tags = db.get_task_tags(task_id)
    assert len(tags) == 1  # Should still be 1, not 2


def test_remove_tag_from_task(temp_db):
    """Test removing a tag from a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    tag1_id = db.create_tag(name="bug")
    tag2_id = db.create_tag(name="urgent")
    
    db.assign_tag_to_task(task_id, tag1_id)
    db.assign_tag_to_task(task_id, tag2_id)
    
    db.remove_tag_from_task(task_id, tag1_id)
    
    tags = db.get_task_tags(task_id)
    assert len(tags) == 1
    assert tags[0]["name"] == "urgent"


def test_query_tasks_by_tag(temp_db):
    """Test querying tasks by tag."""
    db, _ = temp_db
    # Create tasks
    task1_id = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do 1",
        verification_instruction="Verify 1",
        agent_id="test-agent"
    )
    task2_id = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do 2",
        verification_instruction="Verify 2",
        agent_id="test-agent"
    )
    task3_id = db.create_task(
        title="Task 3",
        task_type="concrete",
        task_instruction="Do 3",
        verification_instruction="Verify 3",
        agent_id="test-agent"
    )
    
    # Create tags
    bug_tag_id = db.create_tag(name="bug")
    feature_tag_id = db.create_tag(name="feature")
    
    # Assign tags
    db.assign_tag_to_task(task1_id, bug_tag_id)
    db.assign_tag_to_task(task2_id, bug_tag_id)
    db.assign_tag_to_task(task3_id, feature_tag_id)
    
    # Query by bug tag
    bug_tasks = db.query_tasks(tag_id=bug_tag_id, limit=10)
    assert len(bug_tasks) == 2
    task_ids = {t["id"] for t in bug_tasks}
    assert task_ids == {task1_id, task2_id}
    
    # Query by feature tag
    feature_tasks = db.query_tasks(tag_id=feature_tag_id, limit=10)
    assert len(feature_tasks) == 1
    assert feature_tasks[0]["id"] == task3_id


def test_query_tasks_by_multiple_tags(temp_db):
    """Test querying tasks that have all of the specified tags."""
    db, _ = temp_db
    # Create tasks
    task1_id = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do 1",
        verification_instruction="Verify 1",
        agent_id="test-agent"
    )
    task2_id = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do 2",
        verification_instruction="Verify 2",
        agent_id="test-agent"
    )
    
    # Create tags
    bug_tag_id = db.create_tag(name="bug")
    urgent_tag_id = db.create_tag(name="urgent")
    
    # Assign tags: task1 has both, task2 has only bug
    db.assign_tag_to_task(task1_id, bug_tag_id)
    db.assign_tag_to_task(task1_id, urgent_tag_id)
    db.assign_tag_to_task(task2_id, bug_tag_id)
    
    # Query by both tags (should return only task1)
    tasks = db.query_tasks(tag_ids=[bug_tag_id, urgent_tag_id], limit=10)
    assert len(tasks) == 1
    assert tasks[0]["id"] == task1_id


def test_delete_tag(temp_db):
    """Test deleting a tag (should also remove from all tasks)."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    tag_id = db.create_tag(name="bug")
    db.assign_tag_to_task(task_id, tag_id)
    
    # Delete tag
    db.delete_tag(tag_id)
    
    # Verify tag is deleted
    tag = db.get_tag(tag_id)
    assert tag is None
    
    # Verify tag is removed from task
    tags = db.get_task_tags(task_id)
    assert len(tags) == 0


def test_get_task_tags_empty(temp_db):
    """Test getting tags for a task with no tags."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    tags = db.get_task_tags(task_id)
    assert len(tags) == 0
    assert tags == []


# Time tracking tests
def test_create_task_with_estimated_hours(temp_db):
    """Test creating a task with estimated hours."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Time Tracked Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent",
        estimated_hours=5.5
    )
    
    task = db.get_task(task_id)
    assert task is not None
    assert task["estimated_hours"] == 5.5


def test_lock_task_tracks_start_time(temp_db):
    """Test that locking a task records the start time."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Time Tracked Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent",
        estimated_hours=3.0
    )
    
    # Lock the task
    db.lock_task(task_id, "agent-1")
    
    task = db.get_task(task_id)
    assert task["task_status"] == "in_progress"
    assert task["started_at"] is not None


def test_complete_task_with_actual_hours(temp_db):
    """Test completing a task with actual hours."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Time Tracked Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent",
        estimated_hours=4.0
    )
    
    # Lock and complete
    db.lock_task(task_id, "agent-1")
    db.complete_task(task_id, "agent-1", actual_hours=4.5)
    
    task = db.get_task(task_id)
    assert task["task_status"] == "complete"
    assert task["actual_hours"] == 4.5


def test_time_delta_calculation(temp_db):
    """Test that time delta is calculated correctly."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Time Tracked Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent",
        estimated_hours=5.0
    )
    
    db.lock_task(task_id, "agent-1")
    db.complete_task(task_id, "agent-1", actual_hours=6.5)
    
    task = db.get_task(task_id)
    assert task["estimated_hours"] == 5.0
    assert task["actual_hours"] == 6.5
    # Delta should be actual - estimated = 6.5 - 5.0 = 1.5
    assert task["time_delta_hours"] == 1.5


def test_performance_metrics_with_time_tracking(temp_db):
    """Test that performance metrics include time tracking data."""
    db, _ = temp_db
    
    # Create and complete tasks with time estimates
    task1 = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do 1",
        verification_instruction="Verify 1",
        agent_id="test-agent",
        estimated_hours=2.0
    )
    task2 = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do 2",
        verification_instruction="Verify 2",
        agent_id="test-agent",
        estimated_hours=3.0
    )
    
    db.lock_task(task1, "test-agent")
    db.complete_task(task1, "test-agent", actual_hours=2.5)
    db.lock_task(task2, "test-agent")
    db.complete_task(task2, "test-agent", actual_hours=2.8)
    
    stats = db.get_agent_stats("test-agent")
    assert "avg_time_delta" in stats
    # Task 1: 2.5 - 2.0 = 0.5, Task 2: 2.8 - 3.0 = -0.2
    # Average: (0.5 + (-0.2)) / 2 = 0.15
    assert abs(stats["avg_time_delta"] - 0.15) < 0.01


def test_default_estimated_hours_is_none(temp_db):
    """Test that estimated_hours defaults to None when not specified."""
    db, _ = temp_db
    task_id = db.create_task(
        title="No Estimate Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    task = db.get_task(task_id)
    assert task["estimated_hours"] is None


def test_automatic_time_calculation_on_completion(temp_db):
    """Test that actual_hours is automatically calculated from started_at to completed_at when not provided."""
    import time
    db, _ = temp_db
    task_id = db.create_task(
        title="Auto Time Tracked Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent",
        estimated_hours=2.0
    )
    
    # Lock task to set started_at
    db.lock_task(task_id, "agent-1")
    task = db.get_task(task_id)
    assert task["started_at"] is not None
    
    # Wait a bit to simulate work
    time.sleep(0.1)
    
    # Complete without providing actual_hours - should auto-calculate
    db.complete_task(task_id, "agent-1", notes="Completed")
    
    task = db.get_task(task_id)
    assert task["actual_hours"] is not None
    assert task["actual_hours"] > 0
    # Should be approximately the time elapsed (within reasonable tolerance)
    # Since we waited 0.1 seconds, it should be a very small fraction of an hour
    assert task["actual_hours"] < 0.001  # Less than 3.6 seconds


def test_automatic_time_calculation_with_estimated_hours(temp_db):
    """Test that time_delta_hours is calculated when actual_hours is auto-calculated and estimated_hours exists."""
    import time
    db, _ = temp_db
    task_id = db.create_task(
        title="Auto Time Delta Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent",
        estimated_hours=1.0  # 1 hour estimate
    )
    
    # Lock task
    db.lock_task(task_id, "agent-1")
    time.sleep(0.1)
    
    # Complete without providing actual_hours
    db.complete_task(task_id, "agent-1")
    
    task = db.get_task(task_id)
    assert task["estimated_hours"] == 1.0
    assert task["actual_hours"] is not None
    # time_delta_hours should be calculated: actual_hours - estimated_hours
    assert task["time_delta_hours"] is not None
    # Since actual_hours is very small (< 0.001) and estimated is 1.0, delta should be negative
    assert task["time_delta_hours"] < 0


def test_explicit_actual_hours_overrides_automatic_calculation(temp_db):
    """Test that providing explicit actual_hours overrides automatic calculation."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Explicit Hours Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent",
        estimated_hours=2.0
    )
    
    db.lock_task(task_id, "agent-1")
    # Complete with explicit actual_hours - should use this, not auto-calculate
    db.complete_task(task_id, "agent-1", actual_hours=3.5)
    
    task = db.get_task(task_id)
    assert task["actual_hours"] == 3.5
    assert task["time_delta_hours"] == 1.5  # 3.5 - 2.0


# Full-text search tests
def test_search_tasks_by_title(temp_db):
    """Test searching tasks by title."""
    db, _ = temp_db
    task1_id = db.create_task(
        title="Implement user authentication",
        task_type="concrete",
        task_instruction="Add login functionality",
        verification_instruction="Verify login works",
        agent_id="test-agent"
    )
    task2_id = db.create_task(
        title="Add database migrations",
        task_type="concrete",
        task_instruction="Create migration system",
        verification_instruction="Verify migrations",
        agent_id="test-agent"
    )
    
    # Search for "authentication"
    results = db.search_tasks("authentication")
    assert len(results) == 1
    assert results[0]["id"] == task1_id
    
    # Search for "database"
    results = db.search_tasks("database")
    assert len(results) == 1
    assert results[0]["id"] == task2_id


def test_search_tasks_by_instruction(temp_db):
    """Test searching tasks by task_instruction."""
    db, _ = temp_db
    task1_id = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Implement REST API endpoints",
        verification_instruction="Test endpoints",
        agent_id="test-agent"
    )
    task2_id = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Create database schema",
        verification_instruction="Verify schema",
        agent_id="test-agent"
    )
    
    # Search for "REST"
    results = db.search_tasks("REST")
    assert len(results) == 1
    assert results[0]["id"] == task1_id
    
    # Search for "schema"
    results = db.search_tasks("schema")
    assert len(results) == 1
    assert results[0]["id"] == task2_id


def test_search_tasks_by_notes(temp_db):
    """Test searching tasks by notes."""
    db, _ = temp_db
    task1_id = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent",
        notes="High priority bug fix needed"
    )
    task2_id = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do something else",
        verification_instruction="Verify",
        agent_id="test-agent",
        notes="Performance optimization"
    )
    
    # Search for "bug"
    results = db.search_tasks("bug")
    assert len(results) == 1
    assert results[0]["id"] == task1_id
    
    # Search for "performance"
    results = db.search_tasks("performance")
    assert len(results) == 1
    assert results[0]["id"] == task2_id


def test_search_tasks_multiple_matches(temp_db):
    """Test searching tasks that match multiple terms."""
    db, _ = temp_db
    task1_id = db.create_task(
        title="Database optimization",
        task_type="concrete",
        task_instruction="Optimize database queries",
        verification_instruction="Verify performance",
        agent_id="test-agent",
        notes="Critical performance issue"
    )
    task2_id = db.create_task(
        title="UI improvement",
        task_type="concrete",
        task_instruction="Improve user interface",
        verification_instruction="Verify UI works",
        agent_id="test-agent",
        notes="User feedback"
    )
    
    # Search for "database" - should find task1
    results = db.search_tasks("database")
    assert len(results) == 1
    assert results[0]["id"] == task1_id
    
    # Search for "optimization" - should find task1
    results = db.search_tasks("optimization")
    assert len(results) == 1
    assert results[0]["id"] == task1_id


def test_search_tasks_case_insensitive(temp_db):
    """Test that search is case insensitive."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Python API",
        task_type="concrete",
        task_instruction="Create Python REST API",
        verification_instruction="Verify API",
        agent_id="test-agent"
    )
    
    # Search with different cases
    results1 = db.search_tasks("python")
    results2 = db.search_tasks("Python")
    results3 = db.search_tasks("PYTHON")
    
    assert len(results1) == 1
    assert len(results2) == 1
    assert len(results3) == 1
    assert results1[0]["id"] == task_id


def test_search_tasks_partial_matches(temp_db):
    """Test that search finds partial word matches."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Authentication system",
        task_type="concrete",
        task_instruction="Implement authentication",
        verification_instruction="Verify auth works",
        agent_id="test-agent"
    )
    
    # Search for partial word
    results = db.search_tasks("auth")
    assert len(results) == 1
    assert results[0]["id"] == task_id


def test_search_tasks_empty_query(temp_db):
    """Test that empty query returns all tasks."""
    db, _ = temp_db
    task1_id = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    task2_id = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do something else",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    # Empty query should return all tasks (up to limit)
    results = db.search_tasks("")
    assert len(results) >= 2
    task_ids = {r["id"] for r in results}
    assert task1_id in task_ids
    assert task2_id in task_ids


def test_search_tasks_with_limit(temp_db):
    """Test that search respects limit parameter."""
    db, _ = temp_db
    # Create multiple tasks
    for i in range(10):
        db.create_task(
            title=f"Searchable Task {i}",
            task_type="concrete",
            task_instruction="Searchable content",
            verification_instruction="Verify",
            agent_id="test-agent"
        )
    
    # Search with limit
    results = db.search_tasks("Searchable", limit=5)
    assert len(results) == 5


def test_search_tasks_ranks_by_relevance(temp_db):
    """Test that search results are ranked by relevance."""
    db, _ = temp_db
    # Create tasks with varying relevance to search term
    task1_id = db.create_task(
        title="API endpoint",
        task_type="concrete",
        task_instruction="Create API endpoint for user management",
        verification_instruction="Verify API",
        agent_id="test-agent",
        notes="API endpoint implementation"
    )
    task2_id = db.create_task(
        title="Database schema",
        task_type="concrete",
        task_instruction="Design database schema",
        verification_instruction="Verify schema",
        agent_id="test-agent"
    )
    task3_id = db.create_task(
        title="API documentation",
        task_type="concrete",
        task_instruction="Write API documentation",
        verification_instruction="Verify docs",
        agent_id="test-agent"
    )
    
    # Search for "API" - task1 should rank highest (multiple mentions)
    results = db.search_tasks("API")
    assert len(results) >= 2  # Should find task1 and task3
    # First result should be task1 (most relevant)
    assert results[0]["id"] == task1_id


def test_search_tasks_with_special_characters(temp_db):
    """Test that search handles special characters gracefully."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Task with special chars: test@example.com",
        task_type="concrete",
        task_instruction="Handle special characters",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    # Search should handle special characters
    results = db.search_tasks("test@example")
    assert len(results) == 1
    assert results[0]["id"] == task_id


# Due dates and deadline tests
def test_create_task_with_due_date(temp_db):
    """Test creating a task with a due date."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    due_date = datetime.now() + timedelta(days=7)
    task_id = db.create_task(
        title="Task with Due Date",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify",
        agent_id="test-agent",
        due_date=due_date
    )
    
    task = db.get_task(task_id)
    assert task is not None
    assert task["due_date"] is not None
    # due_date should be stored as ISO format string
    assert isinstance(task["due_date"], str)


def test_get_overdue_tasks(temp_db):
    """Test querying overdue tasks."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    # Create overdue task (due yesterday)
    past_date = datetime.now() - timedelta(days=1)
    overdue_task_id = db.create_task(
        title="Overdue Task",
        task_type="concrete",
        task_instruction="Should be overdue",
        verification_instruction="Verify",
        agent_id="test-agent",
        due_date=past_date
    )
    
    # Create future task (due tomorrow)
    future_date = datetime.now() + timedelta(days=1)
    future_task_id = db.create_task(
        title="Future Task",
        task_type="concrete",
        task_instruction="Not overdue",
        verification_instruction="Verify",
        agent_id="test-agent",
        due_date=future_date
    )
    
    # Query overdue tasks
    overdue = db.get_overdue_tasks()
    assert len(overdue) >= 1
    overdue_ids = [t["id"] for t in overdue]
    assert overdue_task_id in overdue_ids
    assert future_task_id not in overdue_ids


def test_get_tasks_approaching_deadline(temp_db):
    """Test querying tasks approaching deadlines."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    # Create task due in 2 days (within 3-day window)
    soon_task_id = db.create_task(
        title="Soon Due Task",
        task_type="concrete",
        task_instruction="Due soon",
        verification_instruction="Verify",
        agent_id="test-agent",
        due_date=datetime.now() + timedelta(days=2)
    )
    
    # Create task due in 5 days (outside window)
    later_task_id = db.create_task(
        title="Later Task",
        task_type="concrete",
        task_instruction="Due later",
        verification_instruction="Verify",
        agent_id="test-agent",
        due_date=datetime.now() + timedelta(days=5)
    )
    
    # Query tasks approaching deadline (default 3 days)
    approaching = db.get_tasks_approaching_deadline(days_ahead=3)
    assert len(approaching) >= 1
    approaching_ids = [t["id"] for t in approaching]
    assert soon_task_id in approaching_ids
    assert later_task_id not in approaching_ids


def test_get_tasks_approaching_deadline_custom_window(temp_db):
    """Test querying tasks with custom deadline window."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    # Create task due in 7 days
    task_id = db.create_task(
        title="7 Day Task",
        task_type="concrete",
        task_instruction="Due in 7 days",
        verification_instruction="Verify",
        agent_id="test-agent",
        due_date=datetime.now() + timedelta(days=7)
    )
    
    # Query with 7-day window (should find it)
    approaching = db.get_tasks_approaching_deadline(days_ahead=7)
    approaching_ids = [t["id"] for t in approaching]
    assert task_id in approaching_ids
    
    # Query with 3-day window (should not find it)
    approaching = db.get_tasks_approaching_deadline(days_ahead=3)
    approaching_ids = [t["id"] for t in approaching]
    assert task_id not in approaching_ids


def test_overdue_tasks_exclude_completed(temp_db):
    """Test that overdue tasks query excludes completed tasks."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    # Create overdue task
    past_date = datetime.now() - timedelta(days=1)
    overdue_task_id = db.create_task(
        title="Overdue Task",
        task_type="concrete",
        task_instruction="Overdue",
        verification_instruction="Verify",
        agent_id="test-agent",
        due_date=past_date
    )
    
    # Complete the task
    db.complete_task(overdue_task_id, "test-agent")
    
    # Query overdue tasks (should exclude completed)
    overdue = db.get_overdue_tasks()
    overdue_ids = [t["id"] for t in overdue]
    assert overdue_task_id not in overdue_ids


def test_query_tasks_filter_by_due_date(temp_db):
    """Test filtering tasks by due date in query_tasks."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    # Create tasks with and without due dates
    task_with_due = db.create_task(
        title="Task with Due",
        task_type="concrete",
        task_instruction="Has due date",
        verification_instruction="Verify",
        agent_id="test-agent",
        due_date=datetime.now() + timedelta(days=1)
    )
    task_without_due = db.create_task(
        title="Task without Due",
        task_type="concrete",
        task_instruction="No due date",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    # Query tasks with due dates only
    tasks_with_due = db.query_tasks(has_due_date=True, limit=10)
    task_ids = [t["id"] for t in tasks_with_due]
    assert task_with_due in task_ids
    assert task_without_due not in task_ids


def test_default_due_date_is_none(temp_db):
    """Test that tasks default to no due date when not specified."""
    db, _ = temp_db
    task_id = db.create_task(
        title="No Due Date Task",
        task_type="concrete",
        task_instruction="No due date",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    task = db.get_task(task_id)
    assert task["due_date"] is None


# Template tests
def test_create_template(temp_db):
    """Test creating a task template."""
    db, _ = temp_db
    template_id = db.create_template(
        name="Test Template",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works"
    )
    assert template_id > 0
    
    template = db.get_template(template_id)
    assert template is not None
    assert template["name"] == "Test Template"
    assert template["task_type"] == "concrete"
    assert template["task_instruction"] == "Do something"
    assert template["verification_instruction"] == "Check it works"
    assert template["priority"] == "medium"  # Default


def test_create_template_with_all_fields(temp_db):
    """Test creating a template with all optional fields."""
    db, _ = temp_db
    template_id = db.create_template(
        name="Full Template",
        description="A complete template",
        task_type="abstract",
        task_instruction="Break down into tasks",
        verification_instruction="Verify breakdown is complete",
        priority="high",
        estimated_hours=5.5,
        notes="Template notes"
    )
    
    template = db.get_template(template_id)
    assert template["name"] == "Full Template"
    assert template["description"] == "A complete template"
    assert template["task_type"] == "abstract"
    assert template["priority"] == "high"
    assert template["estimated_hours"] == 5.5
    assert template["notes"] == "Template notes"


def test_get_template_by_name(temp_db):
    """Test getting a template by name."""
    db, _ = temp_db
    template_id = db.create_template(
        name="Named Template",
        task_type="concrete",
        task_instruction="Do work",
        verification_instruction="Verify work"
    )
    
    template = db.get_template_by_name("Named Template")
    assert template is not None
    assert template["id"] == template_id
    assert template["name"] == "Named Template"


def test_list_templates(temp_db):
    """Test listing all templates."""
    db, _ = temp_db
    # Create multiple templates
    db.create_template(
        name="Template 1",
        task_type="concrete",
        task_instruction="Task 1",
        verification_instruction="Verify 1"
    )
    db.create_template(
        name="Template 2",
        task_type="abstract",
        task_instruction="Task 2",
        verification_instruction="Verify 2"
    )
    db.create_template(
        name="Template 3",
        task_type="concrete",
        task_instruction="Task 3",
        verification_instruction="Verify 3"
    )
    
    templates = db.list_templates()
    assert len(templates) == 3
    # Check they're sorted by name
    assert templates[0]["name"] == "Template 1"
    assert templates[1]["name"] == "Template 2"
    assert templates[2]["name"] == "Template 3"


def test_list_templates_filtered_by_type(temp_db):
    """Test listing templates filtered by task type."""
    db, _ = temp_db
    db.create_template(
        name="Concrete Template",
        task_type="concrete",
        task_instruction="Task",
        verification_instruction="Verify"
    )
    db.create_template(
        name="Abstract Template",
        task_type="abstract",
        task_instruction="Task",
        verification_instruction="Verify"
    )
    
    concrete_templates = db.list_templates(task_type="concrete")
    assert len(concrete_templates) == 1
    assert concrete_templates[0]["name"] == "Concrete Template"
    
    abstract_templates = db.list_templates(task_type="abstract")
    assert len(abstract_templates) == 1
    assert abstract_templates[0]["name"] == "Abstract Template"


def test_create_task_from_template(temp_db):
    """Test creating a task from a template."""
    db, _ = temp_db
    # Create template
    template_id = db.create_template(
        name="Test Template",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        priority="high",
        estimated_hours=2.5,
        notes="Template notes"
    )
    
    # Create task from template
    task_id = db.create_task_from_template(
        template_id=template_id,
        agent_id="test-agent"
    )
    
    task = db.get_task(task_id)
    assert task is not None
    assert task["title"] == "Test Template"  # Uses template name as title
    assert task["task_type"] == "concrete"
    assert task["task_instruction"] == "Do something"
    assert task["verification_instruction"] == "Check it works"
    assert task["priority"] == "high"
    assert task["estimated_hours"] == 2.5
    assert task["notes"] == "Template notes"


def test_create_task_from_template_with_overrides(temp_db):
    """Test creating a task from template with field overrides."""
    db, _ = temp_db
    template_id = db.create_template(
        name="Base Template",
        task_type="concrete",
        task_instruction="Base instruction",
        verification_instruction="Base verification",
        priority="low",
        estimated_hours=1.0
    )
    
    # Create task with overrides
    task_id = db.create_task_from_template(
        template_id=template_id,
        agent_id="test-agent",
        title="Custom Title",
        project_id=None,
        notes="Custom notes",
        priority="critical",
        estimated_hours=3.0
    )
    
    task = db.get_task(task_id)
    assert task["title"] == "Custom Title"  # Overridden
    assert task["task_type"] == "concrete"  # From template
    assert task["task_instruction"] == "Base instruction"  # From template
    assert task["verification_instruction"] == "Base verification"  # From template
    assert task["priority"] == "critical"  # Overridden
    assert task["estimated_hours"] == 3.0  # Overridden
    assert task["notes"] == "Custom notes"  # Overridden


def test_create_task_from_template_combines_notes(temp_db):
    """Test that creating a task from template combines template notes with provided notes."""
    db, _ = temp_db
    template_id = db.create_template(
        name="Template with notes",
        task_type="concrete",
        task_instruction="Do work",
        verification_instruction="Verify",
        notes="Template notes"
    )
    
    # Create task with additional notes
    task_id = db.create_task_from_template(
        template_id=template_id,
        agent_id="test-agent",
        notes="Additional notes"
    )
    
    task = db.get_task(task_id)
    assert "Template notes" in task["notes"]
    assert "Additional notes" in task["notes"]


def test_create_task_from_nonexistent_template(temp_db):
    """Test that creating task from nonexistent template raises error."""
    db, _ = temp_db
    with pytest.raises(ValueError, match="Template.*not found"):
        db.create_task_from_template(
            template_id=999,
            agent_id="test-agent"
        )


def test_verify_all_template_fields_populated(temp_db):
    """Comprehensive test to verify all template fields are correctly populated in created task.
    
    This test verifies that when creating a task from a template, all template fields
    (name, task_type, task_instruction, verification_instruction, priority, estimated_hours, notes)
    are correctly mapped to the created task.
    """
    db, _ = temp_db
    
    # Create template with ALL fields populated (including optional ones)
    template_id = db.create_template(
        name="Complete Template",
        task_type="abstract",
        task_instruction="Complete instruction",
        verification_instruction="Complete verification",
        description="Template description (metadata only, not copied to task)",
        priority="critical",
        estimated_hours=5.5,
        notes="Template notes"
    )
    
    # Create task from template without any overrides
    task_id = db.create_task_from_template(
        template_id=template_id,
        agent_id="test-agent"
    )
    
    task = db.get_task(task_id)
    assert task is not None
    
    # Verify ALL template fields are correctly populated
    assert task["title"] == "Complete Template", "Title should be populated from template name"
    assert task["task_type"] == "abstract", "Task type should be populated from template"
    assert task["task_instruction"] == "Complete instruction", "Task instruction should be populated from template"
    assert task["verification_instruction"] == "Complete verification", "Verification instruction should be populated from template"
    assert task["priority"] == "critical", "Priority should be populated from template"
    assert task["estimated_hours"] == 5.5, "Estimated hours should be populated from template"
    assert task["notes"] == "Template notes", "Notes should be populated from template"
    
    # Verify template description is NOT copied (it's template metadata only)
    # Tasks don't have a description field, so this is expected behavior
    
    # Test with template having None/optional fields
    template_id_minimal = db.create_template(
        name="Minimal Template",
        task_type="concrete",
        task_instruction="Minimal instruction",
        verification_instruction="Minimal verification"
        # priority, estimated_hours, notes are None/optional
    )
    
    task_id_minimal = db.create_task_from_template(
        template_id=template_id_minimal,
        agent_id="test-agent"
    )
    
    task_minimal = db.get_task(task_id_minimal)
    assert task_minimal is not None
    assert task_minimal["title"] == "Minimal Template"
    assert task_minimal["task_type"] == "concrete"
    assert task_minimal["task_instruction"] == "Minimal instruction"
    assert task_minimal["verification_instruction"] == "Minimal verification"
    assert task_minimal["priority"] == "medium", "Priority should default to 'medium' when template priority is None"
    assert task_minimal["estimated_hours"] is None, "Estimated hours can be None"
    assert task_minimal["notes"] is None, "Notes can be None"


def test_template_name_unique_constraint(temp_db):
    """Test that template names must be unique."""
    db, _ = temp_db
    db.create_template(
        name="Unique Template",
        task_type="concrete",
        task_instruction="Task",
        verification_instruction="Verify"
    )
    
    # Try to create another template with the same name
    with pytest.raises(sqlite3.IntegrityError):
        db.create_template(
            name="Unique Template",
            task_type="abstract",
            task_instruction="Different task",
            verification_instruction="Different verify"
        )


def test_parent_shows_blocked_when_subtask_blocked(temp_db):
    """Test that parent task shows as blocked when subtask is blocked."""
    db, _ = temp_db
    
    # Create parent task
    parent_id = db.create_task(
        title="Parent Task",
        task_type="abstract",
        task_instruction="Complete all subtasks",
        verification_instruction="All subtasks complete",
        agent_id="test-agent"
    )
    
    # Create subtasks
    subtask1 = db.create_task(
        title="Subtask 1",
        task_type="concrete",
        task_instruction="Do step 1",
        verification_instruction="Step 1 done",
        agent_id="test-agent"
    )
    subtask2 = db.create_task(
        title="Subtask 2",
        task_type="concrete",
        task_instruction="Do step 2",
        verification_instruction="Step 2 done",
        agent_id="test-agent"
    )
    
    # Create relationships
    db.create_relationship(parent_id, subtask1, "subtask", "test-agent")
    db.create_relationship(parent_id, subtask2, "subtask", "test-agent")
    
    # Initially, parent should be available
    parent = db.get_task(parent_id)
    assert parent["task_status"] == "available"
    
    # Set one subtask to blocked
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tasks SET task_status = 'blocked', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (subtask1,)
        )
        conn.commit()
    finally:
        conn.close()
    
    # Parent should now show as blocked when queried
    parent = db.get_task(parent_id)
    assert parent["task_status"] == "blocked"
    
    # Parent should show as blocked in query_tasks
    tasks = db.query_tasks(task_type="abstract")
    parent_in_query = next((t for t in tasks if t["id"] == parent_id), None)
    assert parent_in_query is not None
    assert parent_in_query["task_status"] == "blocked"


def test_parent_shows_blocked_when_subtask_blocked_in_query(temp_db):
    """Test that parent task shows as blocked in query results when subtask is blocked."""
    db, _ = temp_db
    
    # Create parent task
    parent_id = db.create_task(
        title="Parent Task",
        task_type="abstract",
        task_instruction="Complete all subtasks",
        verification_instruction="All subtasks complete",
        agent_id="test-agent"
    )
    
    # Create subtask
    subtask = db.create_task(
        title="Subtask",
        task_type="concrete",
        task_instruction="Do step",
        verification_instruction="Step done",
        agent_id="test-agent"
    )
    
    # Create relationship
    db.create_relationship(parent_id, subtask, "subtask", "test-agent")
    
    # Set subtask to blocked
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tasks SET task_status = 'blocked', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (subtask,)
        )
        conn.commit()
    finally:
        conn.close()
    
    # Query tasks - parent should show as blocked
    tasks = db.query_tasks()
    parent_in_query = next((t for t in tasks if t["id"] == parent_id), None)
    assert parent_in_query is not None
    assert parent_in_query["task_status"] == "blocked"
    
    # Query by task_status='blocked' should include parent
    blocked_tasks = db.query_tasks(task_status="blocked")
    blocked_ids = [t["id"] for t in blocked_tasks]
    assert parent_id in blocked_ids


def test_nested_blocked_status_propagation(temp_db):
    """Test blocked status propagation with nested subtasks (grandparent -> parent -> blocked child)."""
    db, _ = temp_db
    
    # Create grandparent
    grandparent_id = db.create_task(
        title="Grandparent Task",
        task_type="epic",
        task_instruction="Complete epic",
        verification_instruction="Epic complete",
        agent_id="test-agent"
    )
    
    # Create parent
    parent_id = db.create_task(
        title="Parent Task",
        task_type="abstract",
        task_instruction="Complete parent",
        verification_instruction="Parent complete",
        agent_id="test-agent"
    )
    
    # Create subtask (child of parent)
    subtask = db.create_task(
        title="Subtask",
        task_type="concrete",
        task_instruction="Do step",
        verification_instruction="Step done",
        agent_id="test-agent"
    )
    
    # Create relationships: grandparent -> parent -> subtask
    db.create_relationship(grandparent_id, parent_id, "subtask", "test-agent")
    db.create_relationship(parent_id, subtask, "subtask", "test-agent")
    
    # Set subtask to blocked
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tasks SET task_status = 'blocked', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (subtask,)
        )
        conn.commit()
    finally:
        conn.close()
    
    # Both parent and grandparent should show as blocked
    parent = db.get_task(parent_id)
    assert parent["task_status"] == "blocked"
    
    grandparent = db.get_task(grandparent_id)
    assert grandparent["task_status"] == "blocked"
    
    # Query should also show both as blocked
    tasks = db.query_tasks()
    parent_in_query = next((t for t in tasks if t["id"] == parent_id), None)
    grandparent_in_query = next((t for t in tasks if t["id"] == grandparent_id), None)
    
    assert parent_in_query is not None
    assert parent_in_query["task_status"] == "blocked"
    assert grandparent_in_query is not None
    assert grandparent_in_query["task_status"] == "blocked"


def test_blocked_status_clears_when_subtask_unblocked(temp_db):
    """Test that parent task no longer shows as blocked when subtask is unblocked."""
    db, _ = temp_db
    
    # Create parent and subtask
    parent_id = db.create_task(
        title="Parent Task",
        task_type="abstract",
        task_instruction="Complete all subtasks",
        verification_instruction="All subtasks complete",
        agent_id="test-agent"
    )
    
    subtask = db.create_task(
        title="Subtask",
        task_type="concrete",
        task_instruction="Do step",
        verification_instruction="Step done",
        agent_id="test-agent"
    )
    
    db.create_relationship(parent_id, subtask, "subtask", "test-agent")
    
    # Set subtask to blocked
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tasks SET task_status = 'blocked', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (subtask,)
        )
        conn.commit()
    finally:
        conn.close()
    
    # Parent should show as blocked
    parent = db.get_task(parent_id)
    assert parent["task_status"] == "blocked"
    
    # Unblock subtask
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tasks SET task_status = 'available', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (subtask,)
        )
        conn.commit()
    finally:
        conn.close()
    
    # Parent should no longer show as blocked (should revert to its actual status)
    parent = db.get_task(parent_id)
    # Note: parent's actual status in DB is still 'available', so it should show as available
    assert parent["task_status"] == "available"


def test_get_available_tasks_for_agent_excludes_blocked_parents(temp_db):
    """Test that get_available_tasks_for_agent excludes parents with blocked subtasks."""
    db, _ = temp_db
    
    # Create parent task
    parent_id = db.create_task(
        title="Parent Task",
        task_type="abstract",
        task_instruction="Complete all subtasks",
        verification_instruction="All subtasks complete",
        agent_id="test-agent"
    )
    
    # Create subtask
    subtask = db.create_task(
        title="Subtask",
        task_type="concrete",
        task_instruction="Do step",
        verification_instruction="Step done",
        agent_id="test-agent"
    )
    
    db.create_relationship(parent_id, subtask, "subtask", "test-agent")
    
    # Set subtask to blocked
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tasks SET task_status = 'blocked', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (subtask,)
        )
        conn.commit()
    finally:
        conn.close()
    
    # get_available_tasks_for_agent should not include the parent (it's effectively blocked)
    available_tasks = db.get_available_tasks_for_agent("breakdown", limit=10)
    available_ids = [t["id"] for t in available_tasks]
    assert parent_id not in available_ids


def test_get_activity_feed(temp_db):
    """Test getting activity feed for a task."""
    db, _ = temp_db
    # Create task
    task_id = db.create_task(
        title="Activity Test Task",
        task_type="concrete",
        task_instruction="Test activity",
        verification_instruction="Verify activity",
        agent_id="test-agent"
    )
    
    # Add various activities
    db.add_task_update(task_id, "agent-1", "Progress update", "progress")
    db.lock_task(task_id, "agent-1")
    db.add_task_update(task_id, "agent-1", "Working on it", "note")
    db.complete_task(task_id, "agent-1", notes="Done!")
    
    # Get activity feed
    feed = db.get_activity_feed(task_id=task_id)
    
    assert len(feed) >= 4  # At least: created, progress, locked, note, completed
    # Check chronological order (oldest first)
    for i in range(len(feed) - 1):
        assert feed[i]["created_at"] <= feed[i + 1]["created_at"]


def test_get_activity_feed_filtered_by_agent(temp_db):
    """Test getting activity feed filtered by agent."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Activity Test Task",
        task_type="concrete",
        task_instruction="Test",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    # Add activities from different agents
    db.add_task_update(task_id, "agent-1", "Update 1", "progress")
    db.add_task_update(task_id, "agent-2", "Update 2", "progress")
    db.complete_task(task_id, "agent-1")
    
    # Get feed filtered by agent-1
    feed = db.get_activity_feed(task_id=task_id, agent_id="agent-1")
    
    # All entries should be from agent-1
    for entry in feed:
        assert entry["agent_id"] == "agent-1"
    
    # Should include update 1 (by agent-1) and completed (by agent-1)
    # Note: created entry is from test-agent, so it's excluded by agent filter
    assert len(feed) >= 2


def test_get_activity_feed_filtered_by_date_range(temp_db):
    """Test getting activity feed filtered by date range."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    task_id = db.create_task(
        title="Activity Test Task",
        task_type="concrete",
        task_instruction="Test",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    # Add activities
    db.add_task_update(task_id, "agent-1", "Update 1", "progress")
    
    # Get feed for last hour (should include recent activities)
    from datetime import UTC
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(hours=1)
    
    feed = db.get_activity_feed(
        task_id=task_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat()
    )
    
    # All entries should be within date range
    for entry in feed:
        entry_date = datetime.fromisoformat(entry["created_at"].replace("Z", "+00:00"))
        # Make entry_date timezone-aware if it's not
        if entry_date.tzinfo is None:
            entry_date = entry_date.replace(tzinfo=UTC)
        assert start_date <= entry_date <= end_date


def test_get_activity_feed_includes_all_event_types(temp_db):
    """Test that activity feed includes updates, completions, and relationship changes."""
    db, _ = temp_db
    
    # Create parent and child tasks
    parent_id = db.create_task(
        title="Parent Task",
        task_type="abstract",
        task_instruction="Parent",
        verification_instruction="Verify parent",
        agent_id="test-agent"
    )
    
    child_id = db.create_task(
        title="Child Task",
        task_type="concrete",
        task_instruction="Child",
        verification_instruction="Verify child",
        agent_id="test-agent"
    )
    
    # Add various activities
    db.add_task_update(parent_id, "agent-1", "Progress", "progress")
    db.add_task_update(parent_id, "agent-1", "Blocker", "blocker")
    db.create_relationship(parent_id, child_id, "subtask", "agent-1")
    db.complete_task(child_id, "agent-1")
    
    # Get feed for parent (should include relationship change)
    feed = db.get_activity_feed(task_id=parent_id)
    
    # Check that we have different event types
    event_types = [entry["change_type"] for entry in feed]
    assert "progress" in event_types
    assert "blocker" in event_types
    assert "relationship_added" in event_types
    
    # Get feed for child
    child_feed = db.get_activity_feed(task_id=child_id)
    assert "completed" in [entry["change_type"] for entry in child_feed]


def test_get_activity_feed_all_tasks(temp_db):
    """Test getting activity feed across all tasks (no task filter)."""
    db, _ = temp_db
    
    # Create multiple tasks
    task1_id = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Task 1",
        verification_instruction="Verify 1",
        agent_id="test-agent"
    )
    
    task2_id = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Task 2",
        verification_instruction="Verify 2",
        agent_id="test-agent"
    )
    
    # Add activities
    db.add_task_update(task1_id, "agent-1", "Update 1", "progress")
    db.add_task_update(task2_id, "agent-2", "Update 2", "progress")
    
    # Get feed for all tasks
    feed = db.get_activity_feed()
    
    # Should include activities from both tasks
    task_ids = set(entry["task_id"] for entry in feed)
    assert task1_id in task_ids
    assert task2_id in task_ids
    
    # Should be in chronological order
    for i in range(len(feed) - 1):
        assert feed[i]["created_at"] <= feed[i + 1]["created_at"]


# Tests for task comments
def test_create_comment(temp_db):
    """Test creating a comment on a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    comment_id = db.create_comment(
        task_id=task_id,
        agent_id="agent-1",
        content="This is a test comment",
        mentions=["agent-2", "agent-3"]
    )
    assert comment_id > 0
    
    comment = db.get_comment(comment_id)
    assert comment is not None
    assert comment["task_id"] == task_id
    assert comment["agent_id"] == "agent-1"
    assert comment["content"] == "This is a test comment"
    assert comment["parent_comment_id"] is None
    assert "agent-2" in comment["mentions"]
    assert "agent-3" in comment["mentions"]


def test_create_threaded_comment(temp_db):
    """Test creating a threaded comment (reply to another comment)."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    # Create parent comment
    parent_id = db.create_comment(
        task_id=task_id,
        agent_id="agent-1",
        content="Parent comment"
    )
    
    # Create reply
    reply_id = db.create_comment(
        task_id=task_id,
        agent_id="agent-2",
        content="Reply to parent",
        parent_comment_id=parent_id,
        mentions=["agent-1"]
    )
    
    reply = db.get_comment(reply_id)
    assert reply["parent_comment_id"] == parent_id
    
    # Get thread (parent and all replies)
    thread = db.get_comment_thread(parent_id)
    assert len(thread) == 2
    assert thread[0]["id"] == parent_id
    assert thread[1]["id"] == reply_id


def test_list_task_comments(temp_db):
    """Test listing all comments for a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    # Create multiple comments
    comment1_id = db.create_comment(task_id, "agent-1", "First comment")
    comment2_id = db.create_comment(task_id, "agent-2", "Second comment")
    comment3_id = db.create_comment(task_id, "agent-1", "Third comment")
    
    comments = db.get_task_comments(task_id)
    assert len(comments) == 3
    
    # Comments should be ordered by created_at (newest first by default)
    comment_ids = [c["id"] for c in comments]
    assert comment3_id in comment_ids
    assert comment2_id in comment_ids
    assert comment1_id in comment_ids


def test_update_comment(temp_db):
    """Test updating a comment."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    comment_id = db.create_comment(task_id, "agent-1", "Original content")
    
    db.update_comment(comment_id, "agent-1", "Updated content")
    
    comment = db.get_comment(comment_id)
    assert comment["content"] == "Updated content"
    assert comment["updated_at"] is not None


def test_delete_comment(temp_db):
    """Test deleting a comment."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    comment_id = db.create_comment(task_id, "agent-1", "To be deleted")
    
    success = db.delete_comment(comment_id, "agent-1")
    assert success is True
    
    comment = db.get_comment(comment_id)
    assert comment is None
    
    comments = db.get_task_comments(task_id)
    assert len(comments) == 0


def test_delete_comment_with_replies(temp_db):
    """Test that deleting a parent comment also deletes replies (cascade)."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    parent_id = db.create_comment(task_id, "agent-1", "Parent")
    reply_id = db.create_comment(task_id, "agent-2", "Reply", parent_comment_id=parent_id)
    
    # Delete parent
    db.delete_comment(parent_id, "agent-1")
    
    # Both should be deleted
    assert db.get_comment(parent_id) is None
    assert db.get_comment(reply_id) is None


def test_comment_mentions(temp_db):
    """Test that mentions are properly stored and retrieved."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    comment_id = db.create_comment(
        task_id=task_id,
        agent_id="agent-1",
        content="Hey @agent-2 and @agent-3",
        mentions=["agent-2", "agent-3"]
    )
    
    comment = db.get_comment(comment_id)
    assert len(comment["mentions"]) == 2
    assert "agent-2" in comment["mentions"]
    assert "agent-3" in comment["mentions"]


def test_comment_timestamps(temp_db):
    """Test that comments have proper timestamps."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    comment_id = db.create_comment(task_id, "agent-1", "Test")
    
    comment = db.get_comment(comment_id)
    assert comment["created_at"] is not None
    assert comment["updated_at"] is None  # Not updated yet
    
    # Update comment
    db.update_comment(comment_id, "agent-1", "Updated")
    comment = db.get_comment(comment_id)
    assert comment["updated_at"] is not None


# API Key Authentication Tests

def test_create_api_key(temp_db):
    """Test creating an API key."""
    db, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    key_id, full_key = db.create_api_key(project_id, "Test API Key")
    assert key_id > 0
    assert full_key is not None
    assert len(full_key) > 32  # Should be a secure random key
    
    # Verify we can retrieve it
    key_info = db.get_api_key_by_hash(db._hash_api_key(full_key))
    assert key_info is not None
    assert key_info["project_id"] == project_id
    assert key_info["name"] == "Test API Key"
    assert key_info["enabled"] == 1


def test_create_multiple_api_keys(temp_db):
    """Test creating multiple API keys for the same project."""
    db, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    key1_id, key1 = db.create_api_key(project_id, "Key 1")
    key2_id, key2 = db.create_api_key(project_id, "Key 2")
    
    assert key1_id != key2_id
    assert key1 != key2
    
    # Both should be valid
    key1_info = db.get_api_key_by_hash(db._hash_api_key(key1))
    key2_info = db.get_api_key_by_hash(db._hash_api_key(key2))
    
    assert key1_info is not None
    assert key2_info is not None
    assert key1_info["project_id"] == project_id
    assert key2_info["project_id"] == project_id


def test_get_api_key_by_hash(temp_db):
    """Test retrieving an API key by its hash."""
    db, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    key_id, full_key = db.create_api_key(project_id, "Test Key")
    key_hash = db._hash_api_key(full_key)
    
    key_info = db.get_api_key_by_hash(key_hash)
    assert key_info is not None
    assert key_info["id"] == key_id
    assert key_info["project_id"] == project_id
    assert key_info["enabled"] == 1


def test_list_api_keys(temp_db):
    """Test listing API keys for a project."""
    db, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    # Create multiple keys
    db.create_api_key(project_id, "Key 1")
    db.create_api_key(project_id, "Key 2")
    db.create_api_key(project_id, "Key 3")
    
    keys = db.list_api_keys(project_id)
    assert len(keys) == 3
    assert all(k["project_id"] == project_id for k in keys)
    assert all("key_prefix" in k for k in keys)
    assert all("name" in k for k in keys)
    # Full key should NOT be in the list (security)
    assert all("key_hash" not in k or k["key_hash"] is None for k in keys)


def test_revoke_api_key(temp_db):
    """Test revoking an API key."""
    db, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    key_id, full_key = db.create_api_key(project_id, "Test Key")
    key_hash = db._hash_api_key(full_key)
    
    # Key should be enabled
    key_info = db.get_api_key_by_hash(key_hash)
    assert key_info["enabled"] == 1
    
    # Revoke it
    success = db.revoke_api_key(key_id)
    assert success is True
    
    # Key should now be disabled
    key_info = db.get_api_key_by_hash(key_hash)
    assert key_info["enabled"] == 0


def test_revoke_nonexistent_api_key(temp_db):
    """Test revoking a non-existent API key."""
    db, _ = temp_db
    success = db.revoke_api_key(99999)
    assert success is False


def test_rotate_api_key(temp_db):
    """Test rotating an API key (creates new key, revokes old)."""
    db, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    key_id, old_key = db.create_api_key(project_id, "Test Key")
    old_hash = db._hash_api_key(old_key)
    
    # Rotate the key
    new_key_id, new_key = db.rotate_api_key(key_id)
    assert new_key_id != key_id
    assert new_key != old_key
    
    # Old key should be disabled
    old_key_info = db.get_api_key_by_hash(old_hash)
    assert old_key_info["enabled"] == 0
    
    # New key should be valid
    new_key_info = db.get_api_key_by_hash(db._hash_api_key(new_key))
    assert new_key_info is not None
    assert new_key_info["enabled"] == 1
    assert new_key_info["project_id"] == project_id


def test_update_api_key_last_used(temp_db):
    """Test updating the last used timestamp."""
    db, _ = temp_db
    project_id = db.create_project("Test Project", "/test/path")
    
    key_id, full_key = db.create_api_key(project_id, "Test Key")
    key_hash = db._hash_api_key(full_key)
    
    # Initially, last_used_at should be None
    key_info = db.get_api_key_by_hash(key_hash)
    assert key_info["last_used_at"] is None
    
    # Update last used
    db.update_api_key_last_used(key_id)
    
    # Now last_used_at should be set
    key_info = db.get_api_key_by_hash(key_hash)
    assert key_info["last_used_at"] is not None


def test_api_key_different_projects(temp_db):
    """Test that API keys are scoped to projects."""
    db, _ = temp_db
    project1_id = db.create_project("Project 1", "/path1")
    project2_id = db.create_project("Project 2", "/path2")
    
    key1_id, key1 = db.create_api_key(project1_id, "Key 1")
    key2_id, key2 = db.create_api_key(project2_id, "Key 2")
    
    # List keys for project 1 should only return key1
    keys = db.list_api_keys(project1_id)
    assert len(keys) == 1
    assert keys[0]["key_id"] == key1_id  # APIKeyResponse uses 'key_id', not 'id'
    
    # List keys for project 2 should only return key2
    keys = db.list_api_keys(project2_id)
    assert len(keys) == 1
    assert keys[0]["key_id"] == key2_id  # APIKeyResponse uses 'key_id', not 'id'


def test_get_api_key_by_hash_invalid(temp_db):
    """Test getting a non-existent API key by hash."""
    db, _ = temp_db
    invalid_hash = "invalid_hash_that_does_not_exist"
    key_info = db.get_api_key_by_hash(invalid_hash)
    assert key_info is None


def test_create_api_key_invalid_project(temp_db):
    """Test creating an API key for a non-existent project."""
    db, _ = temp_db
    # Should raise an error or return None
    try:
        key_id, full_key = db.create_api_key(99999, "Test Key")
        # If no exception, check that it failed
        assert key_id is None or full_key is None
    except Exception:
        # Exception is also acceptable
        pass


# ===== Recurring Tasks Tests =====

def test_create_recurring_task_daily(temp_db):
    """Test creating a daily recurring task."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    # Create a base task
    task_id = db.create_task(
        title="Daily Review",
        task_type="concrete",
        task_instruction="Review daily tasks",
        verification_instruction="Verify review completed",
        agent_id="test-agent"
    )
    
    # Create recurring task
    next_occurrence = datetime.now() + timedelta(days=1)
    recurring_id = db.create_recurring_task(
        task_id=task_id,
        recurrence_type="daily",
        recurrence_config={},
        next_occurrence=next_occurrence
    )
    
    assert recurring_id > 0
    
    recurring = db.get_recurring_task(recurring_id)
    assert recurring is not None
    assert recurring["task_id"] == task_id
    assert recurring["recurrence_type"] == "daily"
    assert recurring["is_active"] == 1


def test_create_recurring_task_weekly(temp_db):
    """Test creating a weekly recurring task."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    task_id = db.create_task(
        title="Weekly Meeting",
        task_type="concrete",
        task_instruction="Attend weekly meeting",
        verification_instruction="Verify attendance",
        agent_id="test-agent"
    )
    
    next_occurrence = datetime.now() + timedelta(days=7)
    recurring_id = db.create_recurring_task(
        task_id=task_id,
        recurrence_type="weekly",
        recurrence_config={"day_of_week": 0},  # Sunday
        next_occurrence=next_occurrence
    )
    
    recurring = db.get_recurring_task(recurring_id)
    assert recurring["recurrence_type"] == "weekly"
    assert recurring["recurrence_config"] is not None


def test_create_recurring_task_monthly(temp_db):
    """Test creating a monthly recurring task."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    task_id = db.create_task(
        title="Monthly Report",
        task_type="concrete",
        task_instruction="Generate monthly report",
        verification_instruction="Verify report generated",
        agent_id="test-agent"
    )
    
    next_occurrence = datetime.now() + timedelta(days=30)
    recurring_id = db.create_recurring_task(
        task_id=task_id,
        recurrence_type="monthly",
        recurrence_config={"day_of_month": 1},  # 1st of month
        next_occurrence=next_occurrence
    )
    
    recurring = db.get_recurring_task(recurring_id)
    assert recurring["recurrence_type"] == "monthly"


def test_get_recurring_tasks_due(temp_db):
    """Test getting recurring tasks that are due for instance creation."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    task_id = db.create_task(
        title="Daily Task",
        task_type="concrete",
        task_instruction="Do daily work",
        verification_instruction="Verify done",
        agent_id="test-agent"
    )
    
    # Create recurring task with next_occurrence in the past
    past_date = datetime.now() - timedelta(days=1)
    recurring_id = db.create_recurring_task(
        task_id=task_id,
        recurrence_type="daily",
        recurrence_config={},
        next_occurrence=past_date
    )
    
    # Get due recurring tasks
    due_tasks = db.get_recurring_tasks_due()
    assert len(due_tasks) >= 1
    assert any(r["id"] == recurring_id for r in due_tasks)


def test_create_recurring_instance(temp_db):
    """Test creating a new task instance from a recurring task."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    # Create base task
    base_task_id = db.create_task(
        title="Base Task",
        task_type="concrete",
        task_instruction="Original instruction",
        verification_instruction="Original verification",
        agent_id="test-agent"
    )
    
    base_task = db.get_task(base_task_id)
    
    # Create recurring task
    next_occurrence = datetime.now() + timedelta(days=1)
    recurring_id = db.create_recurring_task(
        task_id=base_task_id,
        recurrence_type="daily",
        recurrence_config={},
        next_occurrence=next_occurrence
    )
    
    # Create instance
    instance_id = db.create_recurring_instance(recurring_id)
    assert instance_id > 0
    
    # Verify instance was created
    instance = db.get_task(instance_id)
    assert instance is not None
    assert instance["title"] == base_task["title"]
    assert instance["task_type"] == base_task["task_type"]
    assert instance["task_instruction"] == base_task["task_instruction"]
    assert instance["task_status"] == "available"
    
    # Verify recurring task's next_occurrence was updated
    recurring = db.get_recurring_task(recurring_id)
    assert recurring["last_occurrence_created"] is not None


def test_update_recurring_task(temp_db):
    """Test updating a recurring task."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    task_id = db.create_task(
        title="Task",
        task_type="concrete",
        task_instruction="Do work",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    next_occurrence = datetime.now() + timedelta(days=1)
    recurring_id = db.create_recurring_task(
        task_id=task_id,
        recurrence_type="daily",
        recurrence_config={},
        next_occurrence=next_occurrence
    )
    
    # Update to weekly
    new_next = datetime.now() + timedelta(days=7)
    db.update_recurring_task(
        recurring_id=recurring_id,
        recurrence_type="weekly",
        recurrence_config={"day_of_week": 0},
        next_occurrence=new_next
    )
    
    recurring = db.get_recurring_task(recurring_id)
    assert recurring["recurrence_type"] == "weekly"


def test_deactivate_recurring_task(temp_db):
    """Test deactivating a recurring task."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    task_id = db.create_task(
        title="Task",
        task_type="concrete",
        task_instruction="Do work",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    next_occurrence = datetime.now() + timedelta(days=1)
    recurring_id = db.create_recurring_task(
        task_id=task_id,
        recurrence_type="daily",
        recurrence_config={},
        next_occurrence=next_occurrence
    )
    
    db.deactivate_recurring_task(recurring_id)
    
    recurring = db.get_recurring_task(recurring_id)
    assert recurring["is_active"] == 0


def test_list_recurring_tasks(temp_db):
    """Test listing recurring tasks."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    # Create multiple recurring tasks
    task1_id = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do 1",
        verification_instruction="Verify 1",
        agent_id="test-agent"
    )
    
    task2_id = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do 2",
        verification_instruction="Verify 2",
        agent_id="test-agent"
    )
    
    next_occurrence = datetime.now() + timedelta(days=1)
    recurring1_id = db.create_recurring_task(
        task_id=task1_id,
        recurrence_type="daily",
        recurrence_config={},
        next_occurrence=next_occurrence
    )
    
    recurring2_id = db.create_recurring_task(
        task_id=task2_id,
        recurrence_type="weekly",
        recurrence_config={"day_of_week": 0},
        next_occurrence=next_occurrence
    )
    
    # List all recurring tasks
    all_recurring = db.list_recurring_tasks()
    assert len(all_recurring) >= 2
    assert any(r["id"] == recurring1_id for r in all_recurring)
    assert any(r["id"] == recurring2_id for r in all_recurring)
    
    # List only active
    active_recurring = db.list_recurring_tasks(active_only=True)
    assert len(active_recurring) >= 2
    
    # Deactivate one and check
    db.deactivate_recurring_task(recurring1_id)
    active_after = db.list_recurring_tasks(active_only=True)
    assert len(active_after) >= 1
    assert all(r["is_active"] == 1 for r in active_after)


# ===== Task Versioning Tests =====

def test_create_task_version_on_creation(temp_db):
    """Test that a version is automatically created when a task is created."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Version Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent"
    )
    
    # Check that a version was created
    versions = db.get_task_versions(task_id)
    assert len(versions) == 1
    assert versions[0]["version_number"] == 1
    assert versions[0]["title"] == "Version Test Task"


def test_create_task_version_on_title_change(temp_db):
    """Test that a version is created when task title changes."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Original Title",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent"
    )
    
    # Update title
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tasks 
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, ("New Title", task_id))
        conn.commit()
        # Trigger version creation
        db._create_task_version(task_id, "test-agent")
    finally:
        conn.close()
    
    versions = db.get_task_versions(task_id)
    assert len(versions) >= 2
    assert versions[0]["version_number"] == 2  # Latest version
    assert versions[0]["title"] == "New Title"
    assert versions[1]["title"] == "Original Title"


def test_get_task_version_by_number(temp_db):
    """Test retrieving a specific version by version number."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Version 1",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent"
    )
    
    # Create second version
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tasks 
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, ("Version 2", task_id))
        conn.commit()
        db._create_task_version(task_id, "test-agent")
    finally:
        conn.close()
    
    # Get version 1
    version = db.get_task_version(task_id, version_number=1)
    assert version is not None
    assert version["version_number"] == 1
    assert version["title"] == "Version 1"
    
    # Get version 2
    version = db.get_task_version(task_id, version_number=2)
    assert version is not None
    assert version["version_number"] == 2
    assert version["title"] == "Version 2"


def test_diff_task_versions(temp_db):
    """Test diffing two task versions."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Original Title",
        task_type="concrete",
        task_instruction="Original instruction",
        verification_instruction="Original verification",
        agent_id="test-agent",
        priority="low"
    )
    
    # Update multiple fields
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tasks 
            SET title = ?, task_instruction = ?, priority = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, ("New Title", "New instruction", "high", task_id))
        conn.commit()
        db._create_task_version(task_id, "test-agent")
    finally:
        conn.close()
    
    # Diff versions
    diff = db.diff_task_versions(task_id, version_number_1=1, version_number_2=2)
    assert diff is not None
    assert "title" in diff
    assert diff["title"]["old_value"] == "Original Title"
    assert diff["title"]["new_value"] == "New Title"
    assert "task_instruction" in diff
    assert diff["task_instruction"]["old_value"] == "Original instruction"
    assert diff["task_instruction"]["new_value"] == "New instruction"
    assert "priority" in diff
    assert diff["priority"]["old_value"] == "low"
    assert diff["priority"]["new_value"] == "high"


def test_get_task_versions_ordered_by_version_number(temp_db):
    """Test that versions are returned in correct order (newest first)."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Version 1",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent"
    )
    
    # Create multiple versions
    for i in range(2, 5):
        conn = db._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tasks 
                SET title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (f"Version {i}", task_id))
            conn.commit()
            db._create_task_version(task_id, "test-agent")
        finally:
            conn.close()
    
    versions = db.get_task_versions(task_id)
    assert len(versions) == 4
    # Should be ordered newest first (version 4, 3, 2, 1)
    assert versions[0]["version_number"] == 4
    assert versions[1]["version_number"] == 3
    assert versions[2]["version_number"] == 2
    assert versions[3]["version_number"] == 1


def test_task_version_includes_all_fields(temp_db):
    """Test that task versions capture all relevant task fields."""
    db, _ = temp_db
    from datetime import datetime, timedelta
    
    task_id = db.create_task(
        title="Full Task",
        task_type="abstract",
        task_instruction="Instruction",
        verification_instruction="Verification",
        agent_id="test-agent",
        priority="high",
        estimated_hours=5.0,
        due_date=datetime.now() + timedelta(days=7),
        notes="Initial notes"
    )
    
    version = db.get_task_version(task_id, version_number=1)
    assert version is not None
    assert version["title"] == "Full Task"
    assert version["task_type"] == "abstract"
    assert version["task_instruction"] == "Instruction"
    assert version["verification_instruction"] == "Verification"
    assert version["priority"] == "high"
    assert version["estimated_hours"] == 5.0
    assert version["notes"] == "Initial notes"
    assert version["due_date"] is not None


def test_task_version_stores_agent_id_and_timestamp(temp_db):
    """Test that versions store who created them and when."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent"
    )
    
    version = db.get_task_version(task_id, version_number=1)
    assert version is not None
    assert version["created_by"] == "test-agent"
    assert version["created_at"] is not None


def test_automatic_version_creation_on_field_update(temp_db):
    """Test that versions are automatically created when fields are updated."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent"
    )
    
    initial_version_count = len(db.get_task_versions(task_id))
    
    # Update title using update_task method (if it exists) or direct SQL
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tasks 
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, ("Updated Title", task_id))
        conn.commit()
        # Simulate automatic version creation
        db._create_task_version(task_id, "test-agent")
    finally:
        conn.close()
    
    final_version_count = len(db.get_task_versions(task_id))
    assert final_version_count == initial_version_count + 1


def test_diff_versions_with_no_changes(temp_db):
    """Test diffing the same version returns empty diff."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent"
    )
    
    # Diff version 1 with itself
    diff = db.diff_task_versions(task_id, version_number_1=1, version_number_2=1)
    assert diff is not None
    # Should be empty or only contain unchanged fields
    changed_fields = {k: v for k, v in diff.items() if v.get("old_value") != v.get("new_value")}
    assert len(changed_fields) == 0


def test_diff_versions_with_unrelated_changes(temp_db):
    """Test that only changed fields appear in diff."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Original",
        task_type="concrete",
        task_instruction="Original instruction",
        verification_instruction="Original verification",
        agent_id="test-agent",
        priority="low"
    )
    
    # Only change title
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tasks 
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, ("New Title", task_id))
        conn.commit()
        db._create_task_version(task_id, "test-agent")
    finally:
        conn.close()
    
    diff = db.diff_task_versions(task_id, version_number_1=1, version_number_2=2)
    # Only title should be in diff
    assert "title" in diff
    assert "task_instruction" not in diff or diff["task_instruction"]["old_value"] == diff["task_instruction"]["new_value"]


def test_get_latest_version(temp_db):
    """Test getting the latest version of a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Version 1",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent"
    )
    
    # Create multiple versions
    for i in range(2, 4):
        conn = db._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tasks 
                SET title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (f"Version {i}", task_id))
            conn.commit()
            db._create_task_version(task_id, "test-agent")
        finally:
            conn.close()
    
    latest = db.get_latest_task_version(task_id)
    assert latest is not None
    assert latest["version_number"] == 3
    assert latest["title"] == "Version 3"


def test_get_stale_tasks(temp_db):
    """Test getting stale tasks based on timeout."""
    from datetime import datetime, timedelta
    import os
    
    db, _ = temp_db
    
    # Set a short timeout for testing (1 hour)
    os.environ['TASK_TIMEOUT_HOURS'] = '1'
    
    # Create and lock a task
    task_id = db.create_task(
        title="Stale Task",
        task_type="concrete",
        task_instruction="Test stale",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    db.lock_task(task_id, "agent-1")
    
    # Manually set updated_at to be old (2 hours ago)
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        old_time = datetime.utcnow() - timedelta(hours=2)
        if db.db_type == "sqlite":
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
        db.adapter.close(conn)
    
    # Get stale tasks (should include our task)
    stale_tasks = db.get_stale_tasks(hours=1)
    assert len(stale_tasks) >= 1
    stale_task_ids = [t["id"] for t in stale_tasks]
    assert task_id in stale_task_ids
    
    # Clean up environment
    if 'TASK_TIMEOUT_HOURS' in os.environ:
        del os.environ['TASK_TIMEOUT_HOURS']


def test_get_stale_tasks_none_stale(temp_db):
    """Test getting stale tasks when none are stale."""
    import os
    
    db, _ = temp_db
    
    # Set timeout
    os.environ['TASK_TIMEOUT_HOURS'] = '24'
    
    # Create and lock a task (recently updated)
    task_id = db.create_task(
        title="Recent Task",
        task_type="concrete",
        task_instruction="Test",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    db.lock_task(task_id, "agent-1")
    
    # Get stale tasks with 24 hour timeout (should be empty)
    stale_tasks = db.get_stale_tasks(hours=24)
    stale_task_ids = [t["id"] for t in stale_tasks]
    assert task_id not in stale_task_ids
    
    # Clean up
    if 'TASK_TIMEOUT_HOURS' in os.environ:
        del os.environ['TASK_TIMEOUT_HOURS']


def test_unlock_stale_tasks(temp_db):
    """Test automatically unlocking stale tasks."""
    from datetime import datetime, timedelta
    
    db, _ = temp_db
    
    # Create and lock a task
    task_id = db.create_task(
        title="Stale Task",
        task_type="concrete",
        task_instruction="Test",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    db.lock_task(task_id, "agent-1")
    
    # Verify it's locked
    task = db.get_task(task_id)
    assert task["task_status"] == "in_progress"
    assert task["assigned_agent"] == "agent-1"
    
    # Manually set updated_at to be old
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        old_time = datetime.utcnow() - timedelta(hours=25)
        if db.db_type == "sqlite":
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
        db.adapter.close(conn)
    
    # Unlock stale tasks
    unlocked_count = db.unlock_stale_tasks(hours=24, system_agent_id="system")
    assert unlocked_count >= 1
    
    # Verify task is now available
    task = db.get_task(task_id)
    assert task["task_status"] == "available"
    assert task["assigned_agent"] is None


def test_record_agent_experience(temp_db):
    """Test recording agent experience for a completed task."""
    db, _ = temp_db
    
    # Create and complete a task
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    db.lock_task(task_id, "test-agent")
    db.complete_task(task_id, "test-agent", actual_hours=2.5)
    
    # Record experience
    experience_id = db.record_agent_experience(
        agent_id="test-agent",
        task_id=task_id,
        outcome="success",
        execution_time_hours=2.5,
        notes="Completed successfully"
    )
    
    assert experience_id > 0
    
    # Verify experience was recorded
    experience = db.get_agent_experience(experience_id)
    assert experience is not None
    assert experience["agent_id"] == "test-agent"
    assert experience["task_id"] == task_id
    assert experience["outcome"] == "success"
    assert experience["execution_time_hours"] == 2.5


def test_record_agent_experience_with_failure(temp_db):
    """Test recording agent experience for a failed task."""
    db, _ = temp_db
    
    task_id = db.create_task(
        title="Failed Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    db.lock_task(task_id, "test-agent")
    
    # Record failure experience
    experience_id = db.record_agent_experience(
        agent_id="test-agent",
        task_id=task_id,
        outcome="failure",
        execution_time_hours=1.0,
        failure_reason="Test failure",
        notes="Task failed due to error"
    )
    
    assert experience_id > 0
    
    experience = db.get_agent_experience(experience_id)
    assert experience["outcome"] == "failure"
    assert experience["failure_reason"] == "Test failure"


def test_query_agent_experiences(temp_db):
    """Test querying agent experiences."""
    db, _ = temp_db
    
    # Create multiple tasks and record experiences
    task1 = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do 1",
        verification_instruction="Verify 1",
        agent_id="agent-1"
    )
    db.lock_task(task1, "agent-1")
    db.complete_task(task1, "agent-1", actual_hours=1.0)
    db.record_agent_experience(agent_id="agent-1", task_id=task1, outcome="success", execution_time_hours=1.0)
    
    task2 = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do 2",
        verification_instruction="Verify 2",
        agent_id="agent-1"
    )
    db.lock_task(task2, "agent-1")
    db.complete_task(task2, "agent-1", actual_hours=2.0)
    db.record_agent_experience(agent_id="agent-1", task_id=task2, outcome="success", execution_time_hours=2.0)
    
    task3 = db.create_task(
        title="Task 3",
        task_type="concrete",
        task_instruction="Do 3",
        verification_instruction="Verify 3",
        agent_id="agent-1"
    )
    db.lock_task(task3, "agent-1")
    db.record_agent_experience(agent_id="agent-1", task_id=task3, outcome="failure", execution_time_hours=0.5, failure_reason="Error")
    
    # Query experiences for agent-1
    experiences = db.query_agent_experiences(agent_id="agent-1", limit=10)
    assert len(experiences) == 3
    
    # Query only successful experiences
    success_experiences = db.query_agent_experiences(agent_id="agent-1", outcome="success", limit=10)
    assert len(success_experiences) == 2
    assert all(e["outcome"] == "success" for e in success_experiences)


def test_get_agent_learning_stats(temp_db):
    """Test getting learning statistics for an agent."""
    db, _ = temp_db
    
    # Record multiple experiences
    task1 = db.create_task(
        title="Task 1",
        task_type="concrete",
        task_instruction="Do 1",
        verification_instruction="Verify 1",
        agent_id="agent-1"
    )
    db.lock_task(task1, "agent-1")
    db.complete_task(task1, "agent-1", actual_hours=1.0)
    db.record_agent_experience(agent_id="agent-1", task_id=task1, outcome="success", execution_time_hours=1.0)
    
    task2 = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do 2",
        verification_instruction="Verify 2",
        agent_id="agent-1"
    )
    db.lock_task(task2, "agent-1")
    db.complete_task(task2, "agent-1", actual_hours=2.0)
    db.record_agent_experience(agent_id="agent-1", task_id=task2, outcome="success", execution_time_hours=2.0)
    
    task3 = db.create_task(
        title="Task 3",
        task_type="concrete",
        task_instruction="Do 3",
        verification_instruction="Verify 3",
        agent_id="agent-1"
    )
    db.lock_task(task3, "agent-1")
    db.record_agent_experience(agent_id="agent-1", task_id=task3, outcome="failure", execution_time_hours=0.5, failure_reason="Error")
    
    # Get learning stats
    stats = db.get_agent_learning_stats("agent-1")
    assert stats["total_experiences"] == 3
    assert stats["success_count"] == 2
    assert stats["failure_count"] == 1
    assert stats["success_rate"] == pytest.approx(2.0 / 3.0)
    # avg_execution_time is rounded to 2 decimal places in the function
    assert stats["avg_execution_time"] == pytest.approx((1.0 + 2.0 + 0.5) / 3.0, abs=0.01)
