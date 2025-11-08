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
def auth_client(client, temp_db):
    """Create authenticated test client with API key."""
    db, _, _ = temp_db
    
    # Create a project and API key for authentication
    project_id = db.create_project("Test Project", "/test/path")
    key_id, api_key = db.create_api_key(project_id, "Test API Key")
    
    # Create a client wrapper that adds auth headers
    class AuthenticatedClient:
        def __init__(self, client, api_key):
            self.client = client
            self.headers = {"X-API-Key": api_key}
            self.project_id = project_id
            self.api_key = api_key
        
        def get(self, url, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"].update(self.headers)
            return self.client.get(url, **kwargs)
        
        def post(self, url, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"].update(self.headers)
            return self.client.post(url, **kwargs)
        
        def put(self, url, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"].update(self.headers)
            return self.client.put(url, **kwargs)
        
        def delete(self, url, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"].update(self.headers)
            return self.client.delete(url, **kwargs)
    
    return AuthenticatedClient(client, api_key)


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
            localPath
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
    assert data["data"]["project"]["localPath"] == "/tmp/test"
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
            localPath
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


def test_graphql_query_task(auth_client, client):
    """Test GraphQL query for a single task."""
    # Create a task via REST API
    # Use /api/Task/create endpoint (same as other tests)
    response = auth_client.post("/api/Task/create", json={
        "title": "GraphQL Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it works",
        "agent_id": "test-agent",
        "project_id": auth_client.project_id
    })
    if response.status_code != 201:
        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.json()}")
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


def test_graphql_query_tasks_with_filter(auth_client, client):
    """Test GraphQL query for tasks with filtering."""
    # Create tasks with different types
    for task_type in ["concrete", "abstract", "epic"]:
        response = auth_client.post("/api/Task/create", json={
            "title": f"{task_type} Task",
            "task_type": task_type,
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": auth_client.project_id
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


def test_graphql_query_tasks_with_pagination(auth_client, client):
    """Test GraphQL query for tasks with pagination."""
    # Create multiple tasks
    for i in range(5):
        response = auth_client.post("/api/Task/create", json={
            "title": f"Task {i}",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": auth_client.project_id
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


def test_graphql_query_tasks_matches_rest_api(auth_client, client):
    """Test that GraphQL query results match REST API results."""
    # Create tasks via REST API
    task_ids = []
    for i in range(3):
        response = auth_client.post("/api/Task/create", json={
            "title": f"Matching Test Task {i}",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "priority": "high",
            "project_id": auth_client.project_id
        })
        assert response.status_code == 201
        task_ids.append(response.json()["id"])
    
    # Query via REST API
    rest_response = auth_client.get("/api/Task/list?task_type=concrete&priority=high")
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
    
    graphql_response = auth_client.post("/graphql", json={"query": query})
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


def test_graphql_query_relationships(auth_client, client):
    """Test GraphQL query for relationships."""
    # Create parent and child tasks
    parent_response = auth_client.post("/api/Task/create", json={
        "title": "Parent Task",
        "task_type": "epic",
        "task_instruction": "Parent",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": auth_client.project_id
    })
    assert parent_response.status_code == 201
    parent_id = parent_response.json()["id"]
    
    child_response = auth_client.post("/api/Task/create", json={
        "title": "Child Task",
        "task_type": "concrete",
        "task_instruction": "Child",
        "verification_instruction": "Verify",
        "agent_id": "test-agent",
        "project_id": auth_client.project_id
    })
    assert child_response.status_code == 201
    child_id = child_response.json()["id"]
    
    # Create relationship via REST API
    rel_response = auth_client.post("/relationships", json={
        "parent_task_id": parent_id,
        "child_task_id": child_id,
        "relationship_type": "subtask",
        "agent_id": "test-agent"
    })
    assert rel_response.status_code == 201
    
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


def test_graphql_query_tasks_with_sorting(auth_client, client):
    """Test GraphQL query for tasks with sorting."""
    # Create tasks with different priorities
    priorities = ["low", "medium", "high", "critical"]
    for priority in priorities:
        response = auth_client.post("/api/Task/create", json={
            "title": f"{priority} priority task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "priority": priority,
            "project_id": auth_client.project_id
        })
        assert response.status_code == 201
    
    # Query with priority sorting (DESC - highest first)
    query = """
    query {
        tasks(orderBy: {field: "priority", direction: "DESC"}) {
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


def test_graphql_query_complex_filtering(auth_client, client, temp_db):
    """Test GraphQL query with multiple filters."""
    db, _, _ = temp_db
    
    # Create project (projects endpoint doesn't require auth)
    project_response = client.post("/projects", json={
        "name": "test-filter-project",
        "local_path": "/tmp/test",
        "description": "Test project"
    })
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    
    # Create API key for the new project so we can create tasks in it
    key_id, api_key = db.create_api_key(project_id, "Test API Key for Project 2")
    
    # Create authenticated client for project 2
    class Project2Client:
        def __init__(self, client, api_key):
            self.client = client
            self.headers = {"X-API-Key": api_key}
            self.project_id = project_id
        
        def post(self, url, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"].update(self.headers)
            return self.client.post(url, **kwargs)
    
    project2_client = Project2Client(client, api_key)
    
    # Create tasks in project with different statuses
    statuses = ["available", "in_progress", "complete"]
    for status in statuses:
        response = project2_client.post("/api/Task/create", json={
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
            project2_client.post("/api/Task/lock", json={"task_id": task_id, "agent_id": "test-agent"})
        elif status == "complete":
            project2_client.post("/api/Task/lock", json={"task_id": task_id, "agent_id": "test-agent"})
            project2_client.post("/api/Task/complete", json={"task_id": task_id, "agent_id": "test-agent"})
    
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
    
    response = auth_client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    tasks = data["data"]["tasks"]["tasks"]
    # Should find the in_progress task
    assert len(tasks) >= 1
    for task in tasks:
        assert task["taskStatus"] == "in_progress"
        assert task["projectId"] == project_id
