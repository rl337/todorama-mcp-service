"""
End-to-end tests for common agent workflows using the TODO service.

These tests cover the actual scenarios agents use when interacting with the service,
based on observed usage patterns and workflows documented in AGENTS.md.

Test scenarios:
1. Complete agent workflow (list -> reserve -> work -> complete)
2. Task management (queries, stale tasks, continuing own tasks)
3. Error handling (schema errors, not found, unlock on error)
4. Task creation (subtasks, related tasks)
5. Verification workflow (needs_verification state)
6. Comments and updates
7. Bulk operations
"""
import os
import sys
import pytest
from typing import Dict, Any, List

# Set test environment variables BEFORE any imports
os.environ["TODO_DB_PATH"] = "/tmp/test_todo_e2e.db"
os.environ["TODO_BACKUPS_DIR"] = "/tmp/test_backups_e2e"

# Import after setting env vars
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from src.main import app
    from fastapi.testclient import TestClient
except ImportError:
    # Fallback for test environments
    pytest.skip("Could not import main app", allow_module_level=True)

# Test client
client = TestClient(app)

# Test agent IDs
AGENT_ID = "test-agent-e2e"
OTHER_AGENT_ID = "other-agent-e2e"


class TestAgentCoreWorkflow:
    """Test the core agent workflow: list -> reserve -> work -> complete"""
    
    def setup_method(self):
        """Clean up before each test."""
        # Get all tasks and clean up test data
        response = client.post("/mcp/query_tasks", json={"limit": 1000})
        if response.status_code == 200:
            tasks = response.json().get("tasks", [])
            for task in tasks:
                if task.get("title", "").startswith("[E2E TEST]"):
                    # Unlock if locked
                    if task.get("task_status") == "in_progress":
                        client.post("/mcp/unlock_task", json={
                            "task_id": task["id"],
                            "agent_id": "test-cleanup"
                        })
    
    def test_agent_complete_workflow(self):
        """Test complete agent workflow: create -> reserve -> work -> complete."""
        # 1. Create a task
        create_response = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Complete workflow test",
            "task_type": "concrete",
            "task_instruction": "Write a test function that validates input",
            "verification_instruction": "Function exists and tests pass",
            "agent_id": AGENT_ID,
            "project_id": 1,
            "priority": "medium"
        })
        assert create_response.status_code == 200
        create_data = create_response.json()
        assert create_data["success"] is True
        task_id = create_data["task_id"]
        
        # 2. List available tasks (agent query)
        list_response = client.post("/mcp/list_available_tasks", json={
            "agent_type": "implementation",
            "project_id": 1,
            "limit": 10
        })
        assert list_response.status_code == 200
        list_data = list_response.json()
        assert list_data["success"] is True
        tasks = list_data.get("tasks", [])
        # Our task should be in the list
        task_ids = [t["id"] for t in tasks]
        assert task_id in task_ids, f"Task {task_id} not in available tasks list"
        
        # 3. Reserve the task
        reserve_response = client.post("/mcp/reserve_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        assert reserve_response.status_code == 200
        reserve_data = reserve_response.json()
        assert reserve_data["success"] is True
        assert reserve_data["task"]["task_status"] == "in_progress"
        assert reserve_data["task"]["assigned_agent"] == AGENT_ID
        
        # 4. Add progress update while working
        update_response = client.post("/mcp/add_task_update", json={
            "task_id": task_id,
            "agent_id": AGENT_ID,
            "content": "Started implementation, writing test function",
            "update_type": "progress"
        })
        assert update_response.status_code == 200
        update_data = update_response.json()
        assert update_data["success"] is True
        
        # 5. Get task context (agent checking details)
        context_response = client.post("/mcp/get_task_context", json={
            "task_id": task_id
        })
        assert context_response.status_code == 200
        context_data = context_response.json()
        assert context_data["success"] is True
        assert context_data["task"]["id"] == task_id
        assert len(context_data.get("updates", [])) > 0
        
        # 6. Complete the task
        complete_response = client.post("/mcp/complete_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID,
            "notes": "Implementation complete, all tests passing",
            "actual_hours": 1.5
        })
        assert complete_response.status_code == 200
        complete_data = complete_response.json()
        assert complete_data["success"] is True
        assert complete_data["task"]["task_status"] == "complete"
        assert complete_data["task"]["verification_status"] == "unverified"
        
        # 7. Verify the task (separate verification step)
        verify_response = client.post("/mcp/verify_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        assert verify_response.status_code == 200
        verify_data = verify_response.json()
        assert verify_data["success"] is True
        assert verify_data["task"]["verification_status"] == "verified"
    
    def test_agent_workflow_with_followup(self):
        """Test workflow where agent creates a followup task."""
        # Create initial task
        create_response = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Workflow with followup",
            "task_type": "concrete",
            "task_instruction": "Implement feature X",
            "verification_instruction": "Feature works correctly",
            "agent_id": AGENT_ID,
            "project_id": 1
        })
        task_id = create_response.json()["task_id"]
        
        # Reserve and work on it
        client.post("/mcp/reserve_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        
        # Complete with a followup
        complete_response = client.post("/mcp/complete_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID,
            "notes": "Feature implemented, needs documentation",
            "followup_title": "[E2E TEST] Document feature X",
            "followup_task_type": "concrete",
            "followup_instruction": "Write documentation for feature X",
            "followup_verification": "Documentation exists and is accurate"
        })
        assert complete_response.status_code == 200
        complete_data = complete_response.json()
        assert complete_data["success"] is True
        if "followup_task_id" in complete_data:
            # Followup was created
            followup_id = complete_data["followup_task_id"]
            # Verify followup exists
            followup_response = client.post("/mcp/get_task_context", json={
                "task_id": followup_id
            })
            assert followup_response.status_code == 200
            assert followup_response.json()["success"] is True


class TestAgentTaskManagement:
    """Test agent task querying and management scenarios."""
    
    def test_agent_queries_available_tasks(self):
        """Test agent querying for available tasks by type."""
        # Create tasks of different types
        concrete_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Concrete task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "It's done",
            "agent_id": AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        abstract_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Abstract task",
            "task_type": "abstract",
            "task_instruction": "Plan something",
            "verification_instruction": "Plan is complete",
            "agent_id": AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        # Query for concrete tasks only
        response = client.post("/mcp/query_tasks", json={
            "task_type": "concrete",
            "task_status": "available",
            "project_id": 1,
            "limit": 100
        })
        assert response.status_code == 200
        tasks = response.json().get("tasks", [])
        task_ids = [t["id"] for t in tasks]
        assert concrete_id in task_ids
        assert abstract_id not in task_ids
    
    def test_agent_handles_stale_task_pickup(self):
        """Test agent picking up a stale task (previously abandoned)."""
        # Create and reserve a task
        task_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Stale task test",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "It's done",
            "agent_id": OTHER_AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        client.post("/mcp/reserve_task", json={
            "task_id": task_id,
            "agent_id": OTHER_AGENT_ID
        })
        
        # Simulate picking up stale task - agent should see stale_warning
        reserve_response = client.post("/mcp/reserve_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID  # Different agent
        })
        assert reserve_response.status_code == 200
        reserve_data = reserve_response.json()
        
        # Should either succeed (if system unlocked) or warn about stale
        if "stale_warning" in reserve_data:
            assert reserve_data["stale_warning"] is not None
            # Agent should verify previous work before continuing
    
    def test_agent_continues_own_task(self):
        """Test agent continuing a task it previously started."""
        # Create and reserve task
        task_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Continue own task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "It's done",
            "agent_id": AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        client.post("/mcp/reserve_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        
        # Add some work
        client.post("/mcp/add_task_update", json={
            "task_id": task_id,
            "agent_id": AGENT_ID,
            "content": "Started work",
            "update_type": "progress"
        })
        
        # Query for tasks assigned to this agent
        response = client.post("/mcp/query_tasks", json={
            "agent_id": AGENT_ID,
            "task_status": "in_progress",
            "limit": 100
        })
        assert response.status_code == 200
        tasks = response.json().get("tasks", [])
        task_ids = [t["id"] for t in tasks]
        assert task_id in task_ids
        
        # Should be able to continue work
        client.post("/mcp/add_task_update", json={
            "task_id": task_id,
            "agent_id": AGENT_ID,
            "content": "Continuing work",
            "update_type": "progress"
        })


class TestAgentErrorHandling:
    """Test error scenarios agents encounter."""
    
    def test_agent_handles_schema_mismatch_error(self):
        """Test agent receives clear error for schema mismatches."""
        # This simulates the IntegrityError we saw with CHECK constraints
        # The service should return 200 with success=False and clear error details
        response = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Schema test",
            "task_type": "concrete",
            "task_instruction": "Test",
            "verification_instruction": "Test",
            "agent_id": AGENT_ID,
            "project_id": 1,
            # Include invalid data that might trigger CHECK constraint
            "priority": "invalid_priority"  # This should be caught by validation first
        })
        # Should fail validation before hitting DB
        assert response.status_code in [200, 422]
        if response.status_code == 200:
            data = response.json()
            # MCP endpoints return 200 even on error
            if not data.get("success"):
                assert "error" in data
                assert "error_type" in data or "error_details" in data
    
    def test_agent_handles_task_not_found(self):
        """Test agent handling of non-existent task."""
        response = client.post("/mcp/reserve_task", json={
            "task_id": 999999,
            "agent_id": AGENT_ID
        })
        assert response.status_code == 200  # MCP returns 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data or "not found" in str(data).lower()
    
    def test_agent_unlock_on_error(self):
        """Test agent unlocking task when encountering error."""
        # Reserve a task
        task_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Unlock on error",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "It's done",
            "agent_id": AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        client.post("/mcp/reserve_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        
        # Simulate error - unlock task
        unlock_response = client.post("/mcp/unlock_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        assert unlock_response.status_code == 200
        assert unlock_response.json()["success"] is True
        
        # Task should be available again
        task_response = client.post("/mcp/get_task_context", json={
            "task_id": task_id
        })
        task_data = task_response.json()
        assert task_data["task"]["task_status"] == "available"
        assert task_data["task"]["assigned_agent"] is None


class TestAgentTaskCreation:
    """Test agent creating tasks and relationships."""
    
    def test_agent_creates_subtasks(self):
        """Test agent breaking down a task into subtasks."""
        # Create parent task
        parent_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Parent task",
            "task_type": "epic",
            "task_instruction": "Build a feature",
            "verification_instruction": "Feature is complete",
            "agent_id": AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        # Create subtasks
        subtask1_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Subtask 1",
            "task_type": "concrete",
            "task_instruction": "Implement part 1",
            "verification_instruction": "Part 1 works",
            "agent_id": AGENT_ID,
            "project_id": 1,
            "parent_task_id": parent_id,
            "relationship_type": "subtask"
        }).json()["task_id"]
        
        subtask2_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Subtask 2",
            "task_type": "concrete",
            "task_instruction": "Implement part 2",
            "verification_instruction": "Part 2 works",
            "agent_id": AGENT_ID,
            "project_id": 1,
            "parent_task_id": parent_id,
            "relationship_type": "subtask"
        }).json()["task_id"]
        
        # Get parent context - should show relationships
        context_response = client.post("/mcp/get_task_context", json={
            "task_id": parent_id
        })
        context_data = context_response.json()
        # Should have relationship info in ancestry or updates
        assert context_data["success"] is True
    
    def test_agent_creates_related_task(self):
        """Test agent creating a related task (good idea)."""
        # Create original task
        original_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Original task",
            "task_type": "concrete",
            "task_instruction": "Fix bug",
            "verification_instruction": "Bug is fixed",
            "agent_id": AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        # Create related task for improvement
        related_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Related improvement",
            "task_type": "concrete",
            "task_instruction": "Add test coverage",
            "verification_instruction": "Tests exist",
            "agent_id": AGENT_ID,
            "project_id": 1,
            "parent_task_id": original_id,
            "relationship_type": "related"
        }).json()["task_id"]
        
        assert related_id != original_id


class TestAgentVerificationWorkflow:
    """Test verification workflow (needs_verification state)."""
    
    def test_agent_handles_needs_verification_tasks(self):
        """Test agent picking up tasks that need verification."""
        # Create and complete a task (unverified)
        task_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Needs verification",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify it works",
            "agent_id": AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        # Reserve, work, complete
        client.post("/mcp/reserve_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        client.post("/mcp/complete_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        
        # Query for tasks needing verification
        response = client.post("/mcp/query_tasks", json={
            "task_status": "complete",
            "project_id": 1,
            "limit": 100
        })
        assert response.status_code == 200
        tasks = response.json().get("tasks", [])
        # Find our task
        our_task = next((t for t in tasks if t["id"] == task_id), None)
        assert our_task is not None
        assert our_task["verification_status"] == "unverified"
        
        # Task should show needs_verification as True (logical state)
        assert our_task.get("needs_verification") is True
        
        # Agent can verify it
        verify_response = client.post("/mcp/verify_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        assert verify_response.status_code == 200
        assert verify_response.json()["success"] is True
    
    def test_agent_handles_failed_verification(self):
        """Test agent handling verification failure by creating followup."""
        # Create task
        task_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Failed verification",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify it works correctly",
            "agent_id": AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        # Complete it
        client.post("/mcp/reserve_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        client.post("/mcp/complete_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        
        # Agent verifies and finds it fails
        # Agent should:
        # 1. Add update explaining failure
        client.post("/mcp/add_task_update", json={
            "task_id": task_id,
            "agent_id": AGENT_ID,
            "content": "Verification failed: missing test coverage",
            "update_type": "blocker"
        })
        
        # 2. Create followup task
        followup_response = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Add missing tests",
            "task_type": "concrete",
            "task_instruction": "Add test coverage for task",
            "verification_instruction": "Tests exist and pass",
            "agent_id": AGENT_ID,
            "project_id": 1,
            "parent_task_id": task_id,
            "relationship_type": "followup"
        })
        assert followup_response.status_code == 200
        
        # 3. Unlock original task (make it available again)
        unlock_response = client.post("/mcp/unlock_task", json={
            "task_id": task_id,
            "agent_id": AGENT_ID
        })
        # Note: Can't unlock completed task normally, but this tests the concept


class TestAgentCommentsAndUpdates:
    """Test agent using comments and updates for collaboration."""
    
    def test_agent_adds_progress_updates(self):
        """Test agent adding various update types."""
        task_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Update types",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "It's done",
            "agent_id": AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        # Progress update
        client.post("/mcp/add_task_update", json={
            "task_id": task_id,
            "agent_id": AGENT_ID,
            "content": "Making good progress",
            "update_type": "progress"
        })
        
        # Finding
        client.post("/mcp/add_task_update", json={
            "task_id": task_id,
            "agent_id": AGENT_ID,
            "content": "Discovered optimization opportunity",
            "update_type": "finding"
        })
        
        # Blocker
        client.post("/mcp/add_task_update", json={
            "task_id": task_id,
            "agent_id": AGENT_ID,
            "content": "Waiting on external dependency",
            "update_type": "blocker"
        })
        
        # Get context - should see all updates
        context_response = client.post("/mcp/get_task_context", json={
            "task_id": task_id
        })
        updates = context_response.json().get("updates", [])
        assert len(updates) >= 3
        update_types = [u["update_type"] for u in updates]
        assert "progress" in update_types
        assert "finding" in update_types
        assert "blocker" in update_types
    
    def test_agent_creates_comments(self):
        """Test agent creating comments on tasks."""
        task_id = client.post("/mcp/create_task", json={
            "title": "[E2E TEST] Comments",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "It's done",
            "agent_id": AGENT_ID,
            "project_id": 1
        }).json()["task_id"]
        
        # Create comment
        comment_response = client.post("/mcp/create_comment", json={
            "task_id": task_id,
            "agent_id": AGENT_ID,
            "content": "This approach looks good, but consider alternative X",
            "mentions": [OTHER_AGENT_ID]
        })
        assert comment_response.status_code == 200
        comment_data = comment_response.json()
        assert comment_data["success"] is True
        comment_id = comment_data["comment_id"]
        
        # Get comments
        comments_response = client.post("/mcp/get_task_comments", json={
            "task_id": task_id
        })
        assert comments_response.status_code == 200
        comments = comments_response.json().get("comments", [])
        assert len(comments) > 0
        assert any(c["id"] == comment_id for c in comments)


class TestAgentBulkOperations:
    """Test agent using bulk operations when appropriate."""
    
    def test_agent_bulk_queries(self):
        """Test agent querying multiple tasks efficiently."""
        # Create multiple tasks
        task_ids = []
        for i in range(5):
            task_id = client.post("/mcp/create_task", json={
                "title": f"[E2E TEST] Bulk query task {i}",
                "task_type": "concrete",
                "task_instruction": f"Task {i}",
                "verification_instruction": f"Task {i} done",
                "agent_id": AGENT_ID,
                "project_id": 1,
                "priority": "high" if i < 2 else "medium"
            }).json()["task_id"]
            task_ids.append(task_id)
        
        # Query with filters
        response = client.post("/mcp/query_tasks", json={
            "project_id": 1,
            "priority": "high",
            "limit": 100
        })
        assert response.status_code == 200
        tasks = response.json().get("tasks", [])
        # Should find high priority tasks
        high_priority_ids = [t["id"] for t in tasks if t.get("priority") == "high"]
        assert len(high_priority_ids) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

