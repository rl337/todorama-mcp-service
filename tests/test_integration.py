"""
Comprehensive integration tests for full workflows end-to-end.

Tests complete workflows: create project ? create tasks ? reserve ? update ? complete ? verify.
Includes tests with multiple agents and concurrent operations.
"""
import pytest
import os
import tempfile
import shutil
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def test_full_workflow_single_agent(client):
    """Test complete workflow: create project ? create task ? reserve ? update ? complete ? verify."""
    # 1. Create project
    project_response = client.post("/projects", json={
        "name": "Integration Test Project",
        "local_path": "/test/path",
        "origin_url": "https://test.com"
    })
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    
    # 2. Create task
    task_response = client.post("/tasks", json={
        "title": "Integration Test Task",
        "task_type": "concrete",
        "task_instruction": "Complete the integration test workflow",
        "verification_instruction": "Verify all steps completed successfully",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    assert task_response.status_code == 201
    task_id = task_response.json()["id"]
    
    # Verify task is created and linked to project
    get_task = client.get(f"/tasks/{task_id}")
    assert get_task.status_code == 200
    task_data = get_task.json()
    assert task_data["project_id"] == project_id
    assert task_data["task_status"] == "available"
    
    # 3. Reserve task
    reserve_response = client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    assert reserve_response.status_code == 200
    reserve_result = reserve_response.json()
    assert reserve_result["success"] is True
    assert reserve_result["task"]["task_status"] == "in_progress"
    assert reserve_result["task"]["assigned_agent"] == "agent-1"
    
    # 4. Add progress update
    update_response = client.post("/mcp/add_task_update", json={
        "task_id": task_id,
        "agent_id": "agent-1",
        "content": "Starting work on the task",
        "update_type": "progress"
    })
    assert update_response.status_code == 200
    update_result = update_response.json()
    assert update_result["success"] is True
    assert "update_id" in update_result
    
    # 5. Add another update (finding)
    finding_response = client.post("/mcp/add_task_update", json={
        "task_id": task_id,
        "agent_id": "agent-1",
        "content": "Found important information during implementation",
        "update_type": "finding"
    })
    assert finding_response.status_code == 200
    
    # 6. Complete task
    complete_response = client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "agent-1",
        "notes": "Workflow completed successfully"
    })
    assert complete_response.status_code == 200
    complete_result = complete_response.json()
    assert complete_result["success"] is True
    assert complete_result["completed"] is True
    
    # 7. Verify task is complete
    final_task = client.get(f"/tasks/{task_id}")
    assert final_task.status_code == 200
    final_task_data = final_task.json()
    assert final_task_data["task_status"] == "complete"
    assert final_task_data["completed_at"] is not None
    assert final_task_data["notes"] == "Workflow completed successfully"
    
    # 8. Verify updates are present
    context_response = client.post("/mcp/get_task_context", json={
        "task_id": task_id
    })
    assert context_response.status_code == 200
    context = context_response.json()
    assert "updates" in context
    assert len(context["updates"]) >= 2  # At least progress and finding
    update_types = [u["change_type"] for u in context["updates"]]
    assert "progress" in update_types
    assert "finding" in update_types


def test_full_workflow_with_parent_child(client):
    """Test workflow with parent and child tasks."""
    # 1. Create project
    project_response = client.post("/projects", json={
        "name": "Parent-Child Project",
        "local_path": "/test/path",
        "origin_url": "https://test.com"
    })
    project_id = project_response.json()["id"]
    
    # 2. Create parent task (abstract)
    parent_response = client.post("/tasks", json={
        "title": "Parent Task",
        "task_type": "abstract",
        "task_instruction": "Break down into subtasks",
        "verification_instruction": "Verify all subtasks complete",
        "agent_id": "breakdown-agent",
        "project_id": project_id
    })
    parent_id = parent_response.json()["id"]
    
    # 3. Create child task linked to parent
    child_response = client.post("/mcp/create_task", json={
        "title": "Child Task",
        "task_type": "concrete",
        "task_instruction": "Implement child functionality",
        "verification_instruction": "Verify child works",
        "agent_id": "breakdown-agent",
        "project_id": project_id,
        "parent_task_id": parent_id,
        "relationship_type": "subtask"
    })
    assert child_response.status_code == 200
    child_result = child_response.json()
    assert child_result["success"] is True
    child_id = child_result["task_id"]
    assert "relationship_id" in child_result
    
    # 4. Reserve and complete child task
    client.post("/mcp/reserve_task", json={
        "task_id": child_id,
        "agent_id": "implementation-agent"
    })
    
    client.post("/mcp/add_task_update", json={
        "task_id": child_id,
        "agent_id": "implementation-agent",
        "content": "Working on child task",
        "update_type": "progress"
    })
    
    client.post("/mcp/complete_task", json={
        "task_id": child_id,
        "agent_id": "implementation-agent",
        "notes": "Child task complete"
    })
    
    # 5. Verify parent auto-completed (when all children are done)
    parent_task = client.get(f"/tasks/{parent_id}")
    assert parent_task.status_code == 200
    parent_data = parent_task.json()
    # Parent should auto-complete when all subtasks are done
    assert parent_data["task_status"] == "complete"


def test_workflow_multiple_agents(client):
    """Test workflow with multiple agents working on different tasks."""
    # Create project
    project_response = client.post("/projects", json={
        "name": "Multi-Agent Project",
        "local_path": "/test/path",
        "origin_url": "https://test.com"
    })
    project_id = project_response.json()["id"]
    
    # Create multiple tasks
    task1_response = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Task for agent-1",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    task1_id = task1_response.json()["id"]
    
    task2_response = client.post("/tasks", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Task for agent-2",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    task2_id = task2_response.json()["id"]
    
    task3_response = client.post("/tasks", json={
        "title": "Task 3",
        "task_type": "concrete",
        "task_instruction": "Task for agent-3",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    task3_id = task3_response.json()["id"]
    
    # Agent 1 reserves and completes task 1
    client.post("/mcp/reserve_task", json={"task_id": task1_id, "agent_id": "agent-1"})
    client.post("/mcp/add_task_update", json={
        "task_id": task1_id,
        "agent_id": "agent-1",
        "content": "Agent-1 working",
        "update_type": "progress"
    })
    client.post("/mcp/complete_task", json={
        "task_id": task1_id,
        "agent_id": "agent-1",
        "notes": "Done by agent-1"
    })
    
    # Agent 2 reserves and completes task 2
    client.post("/mcp/reserve_task", json={"task_id": task2_id, "agent_id": "agent-2"})
    client.post("/mcp/add_task_update", json={
        "task_id": task2_id,
        "agent_id": "agent-2",
        "content": "Agent-2 working",
        "update_type": "progress"
    })
    client.post("/mcp/complete_task", json={
        "task_id": task2_id,
        "agent_id": "agent-2",
        "notes": "Done by agent-2"
    })
    
    # Agent 3 reserves and completes task 3
    client.post("/mcp/reserve_task", json={"task_id": task3_id, "agent_id": "agent-3"})
    client.post("/mcp/add_task_update", json={
        "task_id": task3_id,
        "agent_id": "agent-3",
        "content": "Agent-3 working",
        "update_type": "progress"
    })
    client.post("/mcp/complete_task", json={
        "task_id": task3_id,
        "agent_id": "agent-3",
        "notes": "Done by agent-3"
    })
    
    # Verify all tasks are complete
    for task_id in [task1_id, task2_id, task3_id]:
        task_response = client.get(f"/tasks/{task_id}")
        assert task_response.status_code == 200
        task_data = task_response.json()
        assert task_data["task_status"] == "complete"
        assert task_data["completed_at"] is not None
    
    # Verify agent performance tracking
    for agent_id in ["agent-1", "agent-2", "agent-3"]:
        perf_response = client.post("/mcp/get_agent_performance", json={
            "agent_id": agent_id
        })
        assert perf_response.status_code == 200
        perf_data = perf_response.json()
        assert perf_data["agent_id"] == agent_id
        assert perf_data["tasks_completed"] >= 1


def test_concurrent_reserve_operations(client):
    """Test concurrent reserve operations - only one should succeed."""
    # Create a task
    task_response = client.post("/tasks", json={
        "title": "Concurrent Test Task",
        "task_type": "concrete",
        "task_instruction": "Test concurrent access",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = task_response.json()["id"]
    
    # Try to reserve from multiple agents concurrently
    results = []
    
    def reserve_task(agent_id):
        response = client.post("/mcp/reserve_task", json={
            "task_id": task_id,
            "agent_id": agent_id
        })
        return agent_id, response.json()
    
    # Use ThreadPoolExecutor to run concurrent reserves
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(reserve_task, f"agent-{i}") for i in range(5)]
        for future in as_completed(futures):
            agent_id, result = future.result()
            results.append((agent_id, result))
    
    # Only one agent should successfully reserve
    successful_reserves = [r for r in results if r[1].get("success") is True]
    assert len(successful_reserves) == 1
    
    # Verify the task is locked
    task_response = client.get(f"/tasks/{task_id}")
    task_data = task_response.json()
    assert task_data["task_status"] == "in_progress"
    assert task_data["assigned_agent"] in [r[0] for r in successful_reserves]


def test_concurrent_complete_operations(client):
    """Test concurrent complete operations - only assigned agent should succeed."""
    # Create and reserve task
    task_response = client.post("/tasks", json={
        "title": "Concurrent Complete Task",
        "task_type": "concrete",
        "task_instruction": "Test concurrent completion",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = task_response.json()["id"]
    
    # Reserve with agent-1
    client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    
    # Try to complete from multiple agents
    results = []
    
    def complete_task(agent_id):
        response = client.post("/mcp/complete_task", json={
            "task_id": task_id,
            "agent_id": agent_id,
            "notes": f"Completed by {agent_id}"
        })
        return agent_id, response.json()
    
    # Use ThreadPoolExecutor for concurrent completes
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(complete_task, f"agent-{i}") for i in range(1, 4)]
        for future in as_completed(futures):
            agent_id, result = future.result()
            results.append((agent_id, result))
    
    # Only agent-1 should successfully complete
    successful_completes = [r for r in results if r[1].get("success") is True]
    assert len(successful_completes) == 1
    assert successful_completes[0][0] == "agent-1"
    
    # Verify task is complete
    task_response = client.get(f"/tasks/{task_id}")
    task_data = task_response.json()
    assert task_data["task_status"] == "complete"


def test_workflow_with_error_scenarios(client):
    """Test workflow error scenarios and edge cases."""
    # 1. Try to reserve non-existent task
    reserve_response = client.post("/mcp/reserve_task", json={
        "task_id": 99999,
        "agent_id": "agent-1"
    })
    assert reserve_response.status_code == 200
    result = reserve_response.json()
    assert result["success"] is False
    assert "not found" in result["error"].lower()
    
    # 2. Create task, reserve, then try to reserve again
    task_response = client.post("/tasks", json={
        "title": "Error Test Task",
        "task_type": "concrete",
        "task_instruction": "Test errors",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = task_response.json()["id"]
    
    # First reserve should succeed
    reserve1 = client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    assert reserve1.json()["success"] is True
    
    # Second reserve should fail
    reserve2 = client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert reserve2.json()["success"] is False
    
    # 3. Try to complete with wrong agent
    complete_wrong = client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "agent-2",  # Wrong agent
        "notes": "Should fail"
    })
    assert complete_wrong.json()["success"] is False
    
    # 4. Complete with correct agent
    complete_correct = client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "agent-1",  # Correct agent
        "notes": "Completed successfully"
    })
    assert complete_correct.json()["success"] is True
    
    # 5. Try to add update with empty content (should fail)
    task2_response = client.post("/tasks", json={
        "title": "Empty Update Test",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = task2_response.json()["id"]
    
    empty_update = client.post("/mcp/add_task_update", json={
        "task_id": task2_id,
        "agent_id": "agent-1",
        "content": "",  # Empty content
        "update_type": "progress"
    })
    assert empty_update.json()["success"] is False


def test_workflow_with_followup_task(client):
    """Test workflow with followup task creation."""
    # Create and reserve task
    task_response = client.post("/tasks", json={
        "title": "Parent Followup Task",
        "task_type": "concrete",
        "task_instruction": "Complete and create followup",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = task_response.json()["id"]
    
    client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    
    # Complete with followup
    complete_response = client.post("/mcp/complete_task", json={
        "task_id": task_id,
        "agent_id": "agent-1",
        "notes": "Completed with followup",
        "followup_title": "Followup Task",
        "followup_task_type": "concrete",
        "followup_instruction": "Do followup work",
        "followup_verification": "Verify followup"
    })
    assert complete_response.status_code == 200
    complete_result = complete_response.json()
    assert complete_result["success"] is True
    assert "followup_task_id" in complete_result
    
    # Verify followup task exists
    followup_id = complete_result["followup_task_id"]
    followup_response = client.get(f"/tasks/{followup_id}")
    assert followup_response.status_code == 200
    followup_data = followup_response.json()
    assert followup_data["title"] == "Followup Task"
    
    # Verify relationship exists
    relationships_response = client.get(f"/tasks/{task_id}/relationships")
    assert relationships_response.status_code == 200
    relationships = relationships_response.json()["relationships"]
    followup_rels = [r for r in relationships if r["child_task_id"] == followup_id]
    assert len(followup_rels) == 1
    assert followup_rels[0]["relationship_type"] == "followup"


def test_full_workflow_with_unlock(client):
    """Test workflow where agent unlocks task instead of completing."""
    # Create and reserve task
    task_response = client.post("/tasks", json={
        "title": "Unlock Test Task",
        "task_type": "concrete",
        "task_instruction": "Test unlock workflow",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task_id = task_response.json()["id"]
    
    # Reserve task
    reserve_response = client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    assert reserve_response.json()["success"] is True
    
    # Add some updates
    client.post("/mcp/add_task_update", json={
        "task_id": task_id,
        "agent_id": "agent-1",
        "content": "Working on it but need to unlock",
        "update_type": "progress"
    })
    
    client.post("/mcp/add_task_update", json={
        "task_id": task_id,
        "agent_id": "agent-1",
        "content": "Blocked by dependency",
        "update_type": "blocker"
    })
    
    # Unlock task
    unlock_response = client.post("/mcp/unlock_task", json={
        "task_id": task_id,
        "agent_id": "agent-1"
    })
    assert unlock_response.json()["success"] is True
    
    # Verify task is available again
    task_response = client.get(f"/tasks/{task_id}")
    task_data = task_response.json()
    assert task_data["task_status"] == "available"
    assert task_data["assigned_agent"] is None
    
    # Another agent can now reserve it
    reserve2_response = client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert reserve2_response.json()["success"] is True


def test_workflow_query_and_search(client):
    """Test workflow including query and search operations."""
    # Create project
    project_response = client.post("/projects", json={
        "name": "Query Test Project",
        "local_path": "/test/path",
        "origin_url": "https://test.com"
    })
    project_id = project_response.json()["id"]
    
    # Create multiple tasks with different attributes
    task1 = client.post("/tasks", json={
        "title": "High Priority Task",
        "task_type": "concrete",
        "task_instruction": "Do important work",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id,
        "priority": "high"
    }).json()["id"]
    
    task2 = client.post("/tasks", json={
        "title": "Low Priority Task",
        "task_type": "concrete",
        "task_instruction": "Do less important work",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id,
        "priority": "low"
    }).json()["id"]
    
    # Query tasks by priority
    query_response = client.post("/mcp/query_tasks", json={
        "priority": "high",
        "limit": 10
    })
    assert query_response.status_code == 200
    high_priority_tasks = query_response.json()["tasks"]
    task_ids = [t["id"] for t in high_priority_tasks]
    assert task1 in task_ids
    assert task2 not in task_ids
    
    # Search tasks
    search_response = client.post("/mcp/search_tasks", json={
        "query": "High Priority",
        "limit": 10
    })
    assert search_response.status_code == 200
    search_results = search_response.json()["tasks"]
    search_ids = [t["id"] for t in search_results]
    assert task1 in search_ids
    
    # Complete one task and query by status
    client.post("/mcp/reserve_task", json={"task_id": task1, "agent_id": "agent-1"})
    client.post("/mcp/complete_task", json={"task_id": task1, "agent_id": "agent-1"})
    
    complete_query = client.post("/mcp/query_tasks", json={
        "task_status": "complete",
        "limit": 10
    })
    complete_tasks = complete_query.json()["tasks"]
    complete_ids = [t["id"] for t in complete_tasks]
    assert task1 in complete_ids
    assert task2 not in complete_ids


def test_workflow_with_context_retrieval(client):
    """Test workflow including context retrieval at various stages."""
    # Create project and task
    project_response = client.post("/projects", json={
        "name": "Context Test Project",
        "local_path": "/test/path",
        "origin_url": "https://test.com"
    })
    project_id = project_response.json()["id"]
    
    # Create parent task
    parent = client.post("/tasks", json={
        "title": "Parent Context Task",
        "task_type": "abstract",
        "task_instruction": "Parent task",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id
    }).json()["id"]
    
    # Create child task with relationship
    child_result = client.post("/mcp/create_task", json={
        "title": "Child Context Task",
        "task_type": "concrete",
        "task_instruction": "Child task",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": project_id,
        "parent_task_id": parent,
        "relationship_type": "subtask"
    }).json()
    child = child_result["task_id"]
    
    # Get context before any updates
    context1 = client.post("/mcp/get_task_context", json={"task_id": child}).json()
    assert context1["success"] is True
    assert context1["task"]["id"] == child
    assert context1["project"]["id"] == project_id
    assert len(context1["ancestry"]) >= 1  # Should include parent
    
    # Reserve, add updates, complete
    client.post("/mcp/reserve_task", json={"task_id": child, "agent_id": "agent-1"})
    client.post("/mcp/add_task_update", json={
        "task_id": child,
        "agent_id": "agent-1",
        "content": "Update 1",
        "update_type": "progress"
    })
    client.post("/mcp/add_task_update", json={
        "task_id": child,
        "agent_id": "agent-1",
        "content": "Update 2",
        "update_type": "finding"
    })
    client.post("/mcp/complete_task", json={"task_id": child, "agent_id": "agent-1"})
    
    # Get context after completion
    context2 = client.post("/mcp/get_task_context", json={"task_id": child}).json()
    assert len(context2["updates"]) >= 2
    assert context2["task"]["task_status"] == "complete"
    
    # Verify updates are in context
    update_types = [u["change_type"] for u in context2["updates"]]
    assert "progress" in update_types
    assert "finding" in update_types
