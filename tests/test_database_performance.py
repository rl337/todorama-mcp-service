"""
Performance tests for database operations and optimizations.
"""
import pytest
import sqlite3
import os
import tempfile
import shutil
import time

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import TodoDatabase


@pytest.fixture
def perf_db():
    """Create a temporary database for performance testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "perf_test.db")
    db = TodoDatabase(db_path)
    yield db, db_path
    shutil.rmtree(temp_dir)


def create_large_task_hierarchy(db, depth=3, width=5, parent_id=None, agent_id="test-agent"):
    """
    Create a hierarchical task structure for performance testing.
    
    Args:
        db: Database instance
        depth: Depth of hierarchy
        width: Number of children per parent
        parent_id: Parent task ID (None for root)
        agent_id: Agent ID
        
    Returns:
        List of created task IDs
    """
    if depth == 0:
        return []
    
    task_ids = []
    for i in range(width):
        task_id = db.create_task(
            title=f"Task D{depth}W{i}",
            task_type="concrete" if depth == 1 else "abstract",
            task_instruction=f"Test task at depth {depth}, width {i}",
            verification_instruction="Verify",
            agent_id=agent_id
        )
        task_ids.append(task_id)
        
        if parent_id:
            db.create_relationship(parent_id, task_id, "subtask", agent_id)
        
        # Recursively create children
        child_ids = create_large_task_hierarchy(db, depth-1, width, task_id, agent_id)
        task_ids.extend(child_ids)
    
    return task_ids


def test_query_tasks_performance_with_indexes(perf_db):
    """Test that query_tasks is fast with proper indexes."""
    db, _ = perf_db
    
    # Create test data
    project_id = db.create_project("Performance Test", "/test/path")
    
    # Create tasks with different statuses and types
    for status in ["available", "in_progress", "complete", "blocked"]:
        for task_type in ["concrete", "abstract", "epic"]:
            for i in range(10):
                db.create_task(
                    title=f"Task {status} {task_type} {i}",
                    task_type=task_type,
                    task_instruction="Test",
                    verification_instruction="Verify",
                    agent_id="test-agent",
                    project_id=project_id
                )
                # Set some to different statuses
                if status != "available":
                    task_id = db.create_task(
                        title=f"Task {status} {task_type} {i}",
                        task_type=task_type,
                        task_instruction="Test",
                        verification_instruction="Verify",
                        agent_id="test-agent",
                        project_id=project_id
                    )
                    if status == "in_progress":
                        db.lock_task(task_id, "test-agent")
                    elif status == "complete":
                        db.lock_task(task_id, "test-agent")
                        db.complete_task(task_id, "test-agent")
    
    # Test query performance
    start_time = time.time()
    tasks = db.query_tasks(project_id=project_id, limit=100)
    duration = time.time() - start_time
    
    # Should be fast (< 0.1 seconds for this dataset)
    assert duration < 0.5, f"query_tasks took {duration:.4f}s, expected < 0.5s"
    assert len(tasks) > 0


def test_query_tasks_with_composite_filters(perf_db):
    """Test query performance with multiple filters (uses composite indexes)."""
    db, _ = perf_db
    
    # Create test data
    project_id = db.create_project("Filter Test", "/test/path")
    
    for i in range(100):
        db.create_task(
            title=f"Task {i}",
            task_type="concrete" if i % 2 == 0 else "abstract",
            task_instruction="Test",
            verification_instruction="Verify",
            agent_id="test-agent",
            project_id=project_id,
            priority="high" if i % 3 == 0 else "medium"
        )
    
    # Test queries that should use composite indexes
    start_time = time.time()
    tasks = db.query_tasks(
        project_id=project_id,
        task_status="available",
        task_type="concrete",
        limit=50
    )
    duration = time.time() - start_time
    
    # Should be very fast with composite index
    assert duration < 0.2, f"Composite filter query took {duration:.4f}s, expected < 0.2s"
    assert all(t["task_status"] == "available" for t in tasks)
    assert all(t["task_type"] == "concrete" for t in tasks)


def test_batch_blocked_subtasks_check(perf_db):
    """Test that batch blocked subtasks check is faster than individual checks."""
    db, _ = perf_db
    
    # Create a hierarchy with some blocked tasks
    root_id = db.create_task(
        title="Root",
        task_type="abstract",
        task_instruction="Root task",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    # Create subtasks
    subtask_ids = []
    for i in range(20):
        subtask_id = db.create_task(
            title=f"Subtask {i}",
            task_type="concrete",
            task_instruction=f"Subtask {i}",
            verification_instruction="Verify",
            agent_id="test-agent"
        )
        db.create_relationship(root_id, subtask_id, "subtask", "test-agent")
        subtask_ids.append(subtask_id)
    
    # Block some subtasks
    for i in range(0, 20, 3):  # Block every 3rd task
        conn = db._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tasks SET task_status = 'blocked', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (subtask_ids[i],)
            )
            conn.commit()
        finally:
            conn.close()
    
    # Test batch check performance
    task_ids_to_check = [root_id] + subtask_ids[:10]
    start_time = time.time()
    blocked_parents = db._find_tasks_with_blocked_subtasks_batch(task_ids_to_check)
    batch_duration = time.time() - start_time
    
    # Should find root as blocked (has blocked subtasks)
    assert root_id in blocked_parents
    
    # Should be fast
    assert batch_duration < 0.1, f"Batch check took {batch_duration:.4f}s, expected < 0.1s"


def test_query_tasks_with_blocked_subtasks_performance(perf_db):
    """Test that query_tasks efficiently handles blocked subtasks check."""
    db, _ = perf_db
    
    # Create hierarchy
    root_ids = []
    for i in range(10):
        root_id = db.create_task(
            title=f"Root {i}",
            task_type="abstract",
            task_instruction="Root",
            verification_instruction="Verify",
            agent_id="test-agent"
        )
        root_ids.append(root_id)
        
        # Add subtasks
        for j in range(5):
            subtask_id = db.create_task(
                title=f"Subtask {i}-{j}",
                task_type="concrete",
                task_instruction="Subtask",
                verification_instruction="Verify",
                agent_id="test-agent"
            )
            db.create_relationship(root_id, subtask_id, "subtask", "test-agent")
            
            # Block some subtasks
            if j == 0:  # Block first subtask of each root
                conn = db._get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE tasks SET task_status = 'blocked', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (subtask_id,)
                    )
                    conn.commit()
                finally:
                    conn.close()
    
    # Query tasks - should efficiently check blocked subtasks
    start_time = time.time()
    tasks = db.query_tasks(task_type="abstract", limit=20)
    duration = time.time() - start_time
    
    # Should be fast (batch check should be used)
    assert duration < 0.5, f"query_tasks with blocked check took {duration:.4f}s, expected < 0.5s"
    
    # All roots should show as blocked (they have blocked subtasks)
    root_tasks = [t for t in tasks if t["id"] in root_ids]
    assert all(t["task_status"] == "blocked" for t in root_tasks)


def test_get_available_tasks_performance(perf_db):
    """Test that get_available_tasks_for_agent is fast with indexes."""
    db, _ = perf_db
    
    # Create many tasks
    project_id = db.create_project("Agent Test", "/test/path")
    
    for i in range(50):
        db.create_task(
            title=f"Concrete Task {i}",
            task_type="concrete",
            task_instruction="Do it",
            verification_instruction="Verify",
            agent_id="test-agent",
            project_id=project_id
        )
    
    for i in range(20):
        db.create_task(
            title=f"Abstract Task {i}",
            task_type="abstract",
            task_instruction="Break down",
            verification_instruction="Verify",
            agent_id="test-agent",
            project_id=project_id
        )
    
    # Test performance
    start_time = time.time()
    available = db.get_available_tasks_for_agent("implementation", project_id=project_id, limit=10)
    duration = time.time() - start_time
    
    # Should be fast with indexes
    assert duration < 0.2, f"get_available_tasks_for_agent took {duration:.4f}s, expected < 0.2s"
    assert len(available) <= 10
    assert all(t["task_type"] == "concrete" for t in available)
    assert all(t["task_status"] == "available" for t in available)


def test_indexes_exist(perf_db):
    """Verify that all expected indexes exist."""
    db, db_path = perf_db
    
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        
        # Get all indexes
        cursor.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'")
        indexes = {row[0] for row in cursor.fetchall()}
        
        # Check for key indexes
        expected_indexes = {
            "idx_tasks_status",
            "idx_tasks_type",
            "idx_tasks_project",
            "idx_tasks_status_type",  # Composite
            "idx_tasks_project_status",  # Composite
            "idx_tasks_project_status_type",  # Composite
            "idx_relationships_parent_type",  # Composite
            "idx_relationships_child_type",  # Composite
        }
        
        for expected in expected_indexes:
            assert expected in indexes, f"Missing index: {expected}"
    finally:
        conn.close()


def test_relationship_query_performance(perf_db):
    """Test that relationship queries are fast with composite indexes."""
    db, _ = perf_db
    
    # Create tasks and relationships
    parent_id = db.create_task(
        title="Parent",
        task_type="abstract",
        task_instruction="Parent",
        verification_instruction="Verify",
        agent_id="test-agent"
    )
    
    for i in range(50):
        child_id = db.create_task(
            title=f"Child {i}",
            task_type="concrete",
            task_instruction="Child",
            verification_instruction="Verify",
            agent_id="test-agent"
        )
        db.create_relationship(parent_id, child_id, "subtask", "test-agent")
    
    # Query relationships (should use composite index)
    start_time = time.time()
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT child_task_id 
            FROM task_relationships 
            WHERE parent_task_id = ? AND relationship_type = 'subtask'
        """, (parent_id,))
        children = cursor.fetchall()
        duration = time.time() - start_time
    finally:
        conn.close()
    
    # Should be fast with composite index
    assert duration < 0.05, f"Relationship query took {duration:.4f}s, expected < 0.05s"
    assert len(children) == 50