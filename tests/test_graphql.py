"""
Tests for GraphQL API endpoints.
"""
import pytest
import os
import tempfile
import shutil
import json
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
    import mcp_api
    main.db = db
    main.backup_manager = backup_manager
    mcp_api.set_db(db)
    
    yield db, db_path, backups_dir
    
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    return TestClient(app)


def test_graphql_query_project(client):
    """Test GraphQL query for a single project."""
    # Create a project via REST API
    response = client.post("/projects", json={
        "name": "test-project",
        "local_path": "/tmp/test",
        "description": "Test project"
    })
    assert response.status_code == 201
    project_data = response.json()
    project_id = project_data["id"]
    
    # Query via GraphQL
    query = """
    query {
        project(id: %d) {
            id
            name
            local_path
            description
        }
    }
    """ % project_id
    
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert data["data"]["project"]["id"] == project_id
    assert data["data"]["project"]["name"] == "test-project"
    assert data["data"]["project"]["local_path"] == "/tmp/test"
    assert data["data"]["project"]["description"] == "Test project"


def test_graphql_query_projects(client):
    """Test GraphQL query for listing projects."""
    # Create multiple projects via REST API
    for i in range(3):
        response = client.post("/projects", json={
            "name": f"project-{i}",
            "local_path": f"/tmp/test-{i}",
            "description": f"Test project {i}"
        })
        assert response.status_code == 201
    
    # Query via GraphQL
    query = """
    query {
        projects {
            id
            name
            local_path
        }
    }
    """
    
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]["projects"]) >= 3
    # Verify projects match (names should be present)
    names = {p["name"] for p in data["data"]["projects"]}
    assert "project-0" in names
    assert "project-1" in names
    assert "project-2" in names


def test_graphql_query_task(client):
    """Test GraphQL query for a single task."""
    # Create a task via REST API
    response = client.post("/tasks", json={
        "title": "GraphQL Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent"
    })
    assert response.status_code == 201
    task_data = response.json()
    task_id = task_data["id"]
    
    # Query via GraphQL
    query = """
    query {
        task(id: %d) {
            id
            title
            taskType
            taskStatus
            priority
        }
    }
    """ % task_id
    
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert data["data"]["task"]["id"] == task_id
    assert data["data"]["task"]["title"] == "GraphQL Test Task"
    assert data["data"]["task"]["taskType"] == "concrete"
    assert data["data"]["task"]["taskStatus"] == "available"
    assert data["data"]["task"]["priority"] == "medium"


def test_graphql_query_tasks_with_filter(client):
    """Test GraphQL query for tasks with filtering."""
    # Create tasks with different types
    for task_type in ["concrete", "abstract", "epic"]:
        response = client.post("/tasks", json={
            "title": f"{task_type} Task",
            "task_type": task_type,
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
        assert response.status_code == 201
    
    # Query via GraphQL with filter
    query = """
    query {
        tasks(filter: {taskType: "concrete"}) {
            tasks {
                id
                title
                taskType
            }
            pageInfo {
                limit
                hasMore
            }
        }
    }
    """
    
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]["tasks"]["tasks"]) >= 1
    # Verify all returned tasks are concrete type
    for task in data["data"]["tasks"]["tasks"]:
        assert task["taskType"] == "concrete"


def test_graphql_query_tasks_with_pagination(client):
    """Test GraphQL query for tasks with pagination."""
    # Create multiple tasks
    for i in range(5):
        response = client.post("/tasks", json={
            "title": f"Task {i}",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "agent_id": "test-agent"
        })
        assert response.status_code == 201
    
    # Query with limit
    query = """
    query {
        tasks(limit: 3) {
            tasks {
                id
                title
            }
            pageInfo {
                limit
                hasMore
            }
        }
    }
    """
    
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]["tasks"]["tasks"]) == 3
    assert data["data"]["tasks"]["pageInfo"]["limit"] == 3
    # Should have more since we created 5 tasks
    assert data["data"]["tasks"]["pageInfo"]["hasMore"] is True


def test_graphql_query_tasks_matches_rest_api(client):
    """Test that GraphQL query results match REST API results."""
    # Create tasks via REST API
    task_ids = []
    for i in range(3):
        response = client.post("/tasks", json={
            "title": f"Matching Test Task {i}",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "priority": "high"
        })
        assert response.status_code == 201
        task_ids.append(response.json()["id"])
    
    # Query via REST API
    rest_response = client.get("/tasks?task_type=concrete&priority=high")
    assert rest_response.status_code == 200
    rest_tasks = rest_response.json()
    rest_task_ids = {task["id"] for task in rest_tasks}
    
    # Query via GraphQL
    query = """
    query {
        tasks(filter: {taskType: "concrete", priority: "high"}) {
            tasks {
                id
                title
                taskType
                priority
            }
        }
    }
    """
    
    graphql_response = client.post("/graphql", json={"query": query})
    assert graphql_response.status_code == 200
    graphql_data = graphql_response.json()
    graphql_tasks = graphql_data["data"]["tasks"]["tasks"]
    graphql_task_ids = {task["id"] for task in graphql_tasks}
    
    # Verify same task IDs are returned
    assert rest_task_ids == graphql_task_ids
    
    # Verify task details match
    rest_task_map = {task["id"]: task for task in rest_tasks}
    for graphql_task in graphql_tasks:
        task_id = graphql_task["id"]
        rest_task = rest_task_map[task_id]
        assert graphql_task["title"] == rest_task["title"]
        assert graphql_task["taskType"] == rest_task["task_type"]
        assert graphql_task["priority"] == rest_task["priority"]


def test_graphql_query_relationships(client):
    """Test GraphQL query for relationships."""
    # Create parent and child tasks
    parent_response = client.post("/tasks", json={
        "title": "Parent Task",
        "task_type": "epic",
        "task_instruction": "Parent",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    assert parent_response.status_code == 201
    parent_id = parent_response.json()["id"]
    
    child_response = client.post("/tasks", json={
        "title": "Child Task",
        "task_type": "concrete",
        "task_instruction": "Child",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    assert child_response.status_code == 201
    child_id = child_response.json()["id"]
    
    # Create relationship via REST API
    rel_response = client.post("/relationships", json={
        "parent_task_id": parent_id,
        "child_task_id": child_id,
        "relationship_type": "subtask",
        "agent_id": "test-agent"
    })
    assert rel_response.status_code == 200
    
    # Query relationships via GraphQL
    query = """
    query {
        relationships(taskId: %d) {
            id
            parentTaskId
            childTaskId
            relationshipType
        }
    }
    """ % parent_id
    
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]["relationships"]) >= 1
    # Verify relationship details
    rel = data["data"]["relationships"][0]
    assert rel["parentTaskId"] == parent_id
    assert rel["childTaskId"] == child_id
    assert rel["relationshipType"] == "subtask"


def test_graphql_query_tasks_with_sorting(client):
    """Test GraphQL query for tasks with sorting."""
    # Create tasks with different priorities
    priorities = ["low", "medium", "high", "critical"]
    for priority in priorities:
        response = client.post("/tasks", json={
            "title": f"{priority} priority task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "priority": priority
        })
        assert response.status_code == 201
    
    # Query with priority sorting (DESC - highest first)
    query = """
    query {
        tasks(orderBy: {field: "priority", direction: DESC}) {
            tasks {
                id
                title
                priority
            }
        }
    }
    """
    
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    tasks = data["data"]["tasks"]["tasks"]
    assert len(tasks) >= 4
    
    # Verify ordering: critical should come first
    priorities_ordered = [task["priority"] for task in tasks[:4]]
    # Should start with critical
    assert priorities_ordered[0] == "critical"


def test_graphql_query_complex_filtering(client):
    """Test GraphQL query with multiple filters."""
    # Create project
    project_response = client.post("/projects", json={
        "name": "test-filter-project",
        "local_path": "/tmp/test",
        "description": "Test project"
    })
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    
    # Create tasks in project with different statuses
    statuses = ["available", "in_progress", "complete"]
    for status in statuses:
        response = client.post("/tasks", json={
            "title": f"{status} task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": project_id
        })
        assert response.status_code == 201
        task_id = response.json()["id"]
        
        # Update status via lock/complete endpoints
        if status == "in_progress":
            client.post(f"/tasks/{task_id}/lock", json={"agent_id": "test-agent"})
        elif status == "complete":
            client.post(f"/tasks/{task_id}/lock", json={"agent_id": "test-agent"})
            client.post(f"/tasks/{task_id}/complete", json={"agent_id": "test-agent"})
    
    # Query with multiple filters
    query = """
    query {
        tasks(filter: {projectId: %d, taskStatus: "in_progress"}) {
            tasks {
                id
                title
                taskStatus
                projectId
            }
        }
    }
    """ % project_id
    
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    tasks = data["data"]["tasks"]["tasks"]
    # Should find the in_progress task
    assert len(tasks) >= 1
    for task in tasks:
        assert task["taskStatus"] == "in_progress"
        assert task["projectId"] == project_id
