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

# Set environment variables before importing main to avoid permission errors
import tempfile as tf
test_db_dir = tf.mkdtemp()
os.environ["TODO_DB_PATH"] = os.path.join(test_db_dir, "test_todos.db")
os.environ["TODO_BACKUPS_DIR"] = os.path.join(test_db_dir, "test_backups")

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

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
    from conversation_storage import ConversationStorage
    conversation_storage = ConversationStorage(conv_db_path)
    
    # Override the database, backup manager, and conversation storage in the app
    import main
    import mcp_api
    main.db = db
    main.backup_manager = backup_manager
    main.conversation_storage = conversation_storage
    mcp_api.set_db(db)
    
    # Also override the service container so get_db() returns the test database
    from dependencies.services import _service_instance, ServiceContainer
    # Create a mock service container with our test database
    class MockServiceContainer:
        def __init__(self, db, backup_manager, conversation_storage):
            self.db = db
            self.backup_manager = backup_manager
            self.conversation_storage = conversation_storage
    
    # Override the global service instance
    import dependencies.services as services_module
    original_instance = services_module._service_instance
    services_module._service_instance = MockServiceContainer(db, backup_manager, conversation_storage)
    
    yield db, db_path, backups_dir
    
    # Restore original service instance
    services_module._service_instance = original_instance
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def api_key_and_headers(temp_db):
    """Create API key and return headers for authenticated requests."""
    db, _, _ = temp_db
    
    # Create a project for the API key
    project_id = db.create_project("Integration Test Project", "/test/path")
    
    # Create an API key
    key_id, api_key = db.create_api_key(project_id, "Integration Test Key")
    
    # Return headers in both formats
    headers = {"X-API-Key": api_key}
    
    return api_key, headers, project_id


def test_full_workflow_single_agent(client, api_key_and_headers):
    """Test complete workflow: create project ? create task ? reserve ? update ? complete ? verify."""
    _, headers, default_project_id = api_key_and_headers
    
    # 1. Use the default project from the API key (don't create a new one)
    project_id = default_project_id
    
    # 2. Create task
    task_response = client.post("/tasks", json={
        "task": {
            "title": "Integration Test Task",
            "task_type": "concrete",
            "task_instruction": "Complete the integration test workflow",
            "verification_instruction": "Verify all steps completed successfully",
            "agent_id": "test-agent",
            "project_id": project_id
        }
    }, headers=headers)
    if task_response.status_code != 201:
        print(f"Task creation failed with status {task_response.status_code}")
        print(f"Response: {task_response.text}")
    assert task_response.status_code == 201
    task_id = task_response.json()["id"]
    
    # Verify task is created and linked to project
    get_task = client.get(f"/tasks/{task_id}", headers=headers)
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
    final_task = client.get(f"/tasks/{task_id}", headers=headers)
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


def test_full_workflow_with_parent_child(client, api_key_and_headers):
    """Test workflow with parent and child tasks."""
    _, headers, default_project_id = api_key_and_headers
    
    # 1. Use the default project from the API key
    project_id = default_project_id
    
    # 2. Create parent task (abstract)
    parent_response = client.post("/tasks", json={
        "task": {
            "title": "Parent Task",
            "task_type": "abstract",
            "task_instruction": "Break down into subtasks",
            "verification_instruction": "Verify all subtasks complete",
            "agent_id": "breakdown-agent",
            "project_id": project_id
        }
    }, headers=headers)
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
    parent_task = client.get(f"/tasks/{parent_id}", headers=headers)
    assert parent_task.status_code == 200
    parent_data = parent_task.json()
    # Parent should auto-complete when all subtasks are done
    assert parent_data["task_status"] == "complete"


def test_workflow_multiple_agents(client, api_key_and_headers):
    """Test workflow with multiple agents working on different tasks."""
    _, headers, default_project_id = api_key_and_headers
    
    # Use the default project from the API key
    project_id = default_project_id
    
    # Create multiple tasks
    task1_response = client.post("/tasks", json={
        "task": {
            "title": "Task 1",
            "task_type": "concrete",
            "task_instruction": "Task for agent-1",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": project_id
        }
    }, headers=headers)
    task1_id = task1_response.json()["id"]

    task2_response = client.post("/tasks", json={
        "task": {
            "title": "Task 2",
            "task_type": "concrete",
            "task_instruction": "Task for agent-2",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": project_id
        }
    }, headers=headers)
    task2_id = task2_response.json()["id"]

    task3_response = client.post("/tasks", json={
        "task": {
            "title": "Task 3",
            "task_type": "concrete",
            "task_instruction": "Task for agent-3",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": project_id
        }
    }, headers=headers)
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
        task_response = client.get(f"/tasks/{task_id}", headers=headers)
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


def test_concurrent_reserve_operations(client, api_key_and_headers):
    """Test concurrent reserve operations - only one should succeed."""
    _, headers, default_project_id = api_key_and_headers
    
    # Create a task
    task_response = client.post("/tasks", json={
        "task": {
            "title": "Concurrent Test Task",
            "task_type": "concrete",
            "task_instruction": "Test concurrent access",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": default_project_id
        }
    }, headers=headers)
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
    task_response = client.get(f"/tasks/{task_id}", headers=headers)
    task_data = task_response.json()
    assert task_data["task_status"] == "in_progress"
    assert task_data["assigned_agent"] in [r[0] for r in successful_reserves]


def test_concurrent_complete_operations(client, api_key_and_headers):
    """Test concurrent complete operations - only assigned agent should succeed."""
    _, headers, default_project_id = api_key_and_headers
    
    # Create and reserve task
    task_response = client.post("/tasks", json={
        "task": {
            "title": "Concurrent Complete Task",
            "task_type": "concrete",
            "task_instruction": "Test concurrent completion",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": default_project_id
        }
    }, headers=headers)
    if task_response.status_code != 201:
        print(f"Task creation failed with status {task_response.status_code}")
        print(f"Response: {task_response.text}")
        print(f"Response JSON: {task_response.json()}")
    assert task_response.status_code == 201, f"Expected 201, got {task_response.status_code}: {task_response.text}"
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
    task_response = client.get(f"/tasks/{task_id}", headers=headers)
    task_data = task_response.json()
    assert task_data["task_status"] == "complete"


def test_workflow_with_error_scenarios(client, api_key_and_headers):
    """Test workflow error scenarios and edge cases."""
    _, headers, default_project_id = api_key_and_headers
    
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
        "task": {
            "title": "Error Test Task",
            "task_type": "concrete",
            "task_instruction": "Test errors",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": default_project_id
        }
    }, headers=headers)
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
        "task": {
            "title": "Empty Update Test",
            "task_type": "concrete",
            "task_instruction": "Test",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": default_project_id
        }
    }, headers=headers)
    task2_id = task2_response.json()["id"]
    
    empty_update = client.post("/mcp/add_task_update", json={
        "task_id": task2_id,
        "agent_id": "agent-1",
        "content": "",  # Empty content
        "update_type": "progress"
    })
    assert empty_update.json()["success"] is False


def test_workflow_with_followup_task(client, api_key_and_headers):
    """Test workflow with followup task creation."""
    _, headers, default_project_id = api_key_and_headers
    
    # Create and reserve task
    task_response = client.post("/tasks", json={
        "task": {
            "title": "Parent Followup Task",
            "task_type": "concrete",
            "task_instruction": "Complete and create followup",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": default_project_id
        }
    }, headers=headers)
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
    followup_response = client.get(f"/tasks/{followup_id}", headers=headers)
    assert followup_response.status_code == 200
    followup_data = followup_response.json()
    assert followup_data["title"] == "Followup Task"
    
    # Verify relationship exists
    relationships_response = client.get(f"/tasks/{task_id}/relationships", headers=headers)
    assert relationships_response.status_code == 200
    relationships = relationships_response.json()["relationships"]
    followup_rels = [r for r in relationships if r["child_task_id"] == followup_id]
    assert len(followup_rels) == 1
    assert followup_rels[0]["relationship_type"] == "followup"


def test_full_workflow_with_unlock(client, api_key_and_headers):
    """Test workflow where agent unlocks task instead of completing."""
    _, headers, default_project_id = api_key_and_headers
    
    # Create and reserve task
    task_response = client.post("/tasks", json={
        "task": {
            "title": "Unlock Test Task",
            "task_type": "concrete",
            "task_instruction": "Test unlock workflow",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": default_project_id
        }
    }, headers=headers)
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
    task_response = client.get(f"/tasks/{task_id}", headers=headers)
    task_data = task_response.json()
    assert task_data["task_status"] == "available"
    assert task_data["assigned_agent"] is None
    
    # Another agent can now reserve it
    reserve2_response = client.post("/mcp/reserve_task", json={
        "task_id": task_id,
        "agent_id": "agent-2"
    })
    assert reserve2_response.json()["success"] is True


def test_workflow_query_and_search(client, api_key_and_headers):
    """Test workflow including query and search operations."""
    _, headers, default_project_id = api_key_and_headers
    
    # Use the default project from the API key
    project_id = default_project_id
    
    # Create multiple tasks with different attributes
    task1 = client.post("/tasks", json={
        "task": {
            "title": "High Priority Task",
            "task_type": "concrete",
            "task_instruction": "Do important work",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": project_id,
            "priority": "high"
        }
    }, headers=headers).json()["id"]

    task2 = client.post("/tasks", json={
        "task": {
            "title": "Low Priority Task",
            "task_type": "concrete",
            "task_instruction": "Do less important work",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": project_id,
            "priority": "low"
        }
    }, headers=headers).json()["id"]
    
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


def test_workflow_with_context_retrieval(client, api_key_and_headers):
    """Test workflow including context retrieval at various stages."""
    _, headers, default_project_id = api_key_and_headers
    
    # Use the default project from the API key
    project_id = default_project_id
    
    # Create parent task
    parent = client.post("/tasks", json={
        "task": {
            "title": "Parent Context Task",
            "task_type": "abstract",
            "task_instruction": "Parent task",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": project_id
        }
    }, headers=headers).json()["id"]
    
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
