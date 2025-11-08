"""
Mock-based unit tests for task route handlers.
Tests the HTTP layer in isolation without real database or HTTP connections.
"""
import pytest
import sys
import os

# Add src to path BEFORE importing FastAPI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from unittest.mock import Mock, MagicMock, patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.exceptions import RequestValidationError

from api.routes import tasks
from models.task_models import TaskCreate, TaskResponse
from services.task_service import TaskService


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = Mock()
    db.get_project.return_value = {"id": 1, "name": "Test Project", "local_path": "/test"}
    db.get_task.return_value = {"id": 1, "title": "Test Task", "task_type": "concrete"}
    db.query_tasks.return_value = [
        {"id": 1, "title": "Test Task 1", "task_type": "concrete"},
        {"id": 2, "title": "Test Task 2", "task_type": "abstract"}
    ]
    return db


@pytest.fixture
def mock_task_service():
    """Create a mock task service."""
    service = Mock(spec=TaskService)
    service.create_task.return_value = {
        "id": 1,
        "title": "Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify it",
        "agent_id": "test-agent",
        "project_id": 1,
        "task_status": "available"
    }
    service.get_task.return_value = {
        "id": 1,
        "title": "Test Task",
        "task_type": "concrete",
        "task_status": "available"
    }
    return service


@pytest.fixture
def mock_auth():
    """Create a mock authentication result."""
    return {"api_key": "test-key", "user_id": "test-user"}


@pytest.fixture
def app():
    """Create a FastAPI app with tasks router."""
    app = FastAPI()
    app.include_router(tasks.router)
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestCreateTask:
    """Test POST /tasks endpoint."""
    
    @patch('api.routes.tasks.get_db')
    @patch('api.routes.tasks.verify_api_key')
    @patch('api.routes.tasks.notify_webhooks')
    @patch('api.routes.tasks.send_task_notification')
    def test_create_task_success(
        self, mock_slack, mock_webhooks, mock_verify_auth, mock_get_db,
        client, mock_db, mock_task_service, mock_auth
    ):
        """Test successful task creation."""
        # Setup mocks
        mock_get_db.return_value = mock_db
        mock_verify_auth.return_value = mock_auth
        mock_webhooks.return_value = None
        
        # Mock TaskService dependency
        with patch('api.routes.tasks.get_task_service', return_value=mock_task_service):
            response = client.post(
                "/tasks",
                json={
                    "title": "Test Task",
                    "task_type": "concrete",
                    "task_instruction": "Do something",
                    "verification_instruction": "Verify it",
                    "agent_id": "test-agent",
                    "project_id": 1
                }
            )
        
        # Verify response
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["title"] == "Test Task"
        assert data["task_type"] == "concrete"
        
        # Verify service was called
        mock_task_service.create_task.assert_called_once()
        call_args = mock_task_service.create_task.call_args
        assert isinstance(call_args[0][0], TaskCreate)
        assert call_args[0][0].title == "Test Task"
        assert call_args[0][1] == mock_auth
    
    @patch('api.routes.tasks.get_db')
    @patch('api.routes.tasks.verify_api_key')
    def test_create_task_validation_error(
        self, mock_verify_auth, mock_get_db, client, mock_db, mock_auth
    ):
        """Test task creation with validation error."""
        mock_get_db.return_value = mock_db
        mock_verify_auth.return_value = mock_auth
        
        # Missing required fields
        response = client.post("/tasks", json={})
        
        assert response.status_code == 422  # Validation error
    
    @patch('api.routes.tasks.get_db')
    @patch('api.routes.tasks.verify_api_key')
    def test_create_task_not_found_error(
        self, mock_verify_auth, mock_get_db, client, mock_db, mock_task_service, mock_auth
    ):
        """Test task creation when project not found."""
        mock_get_db.return_value = mock_db
        mock_verify_auth.return_value = mock_auth
        mock_task_service.create_task.side_effect = ValueError("Project not found")
        
        with patch('api.routes.tasks.get_task_service', return_value=mock_task_service):
            response = client.post(
                "/tasks",
                json={
                    "title": "Test Task",
                    "task_type": "concrete",
                    "task_instruction": "Do something",
                    "verification_instruction": "Verify it",
                    "agent_id": "test-agent",
                    "project_id": 999
                }
            )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    @patch('api.routes.tasks.get_db')
    @patch('api.routes.tasks.verify_api_key')
    def test_create_task_unauthorized_error(
        self, mock_verify_auth, mock_get_db, client, mock_db, mock_task_service, mock_auth
    ):
        """Test task creation when not authorized."""
        mock_get_db.return_value = mock_db
        mock_verify_auth.return_value = mock_auth
        mock_task_service.create_task.side_effect = ValueError("not authorized")
        
        with patch('api.routes.tasks.get_task_service', return_value=mock_task_service):
            response = client.post(
                "/tasks",
                json={
                    "title": "Test Task",
                    "task_type": "concrete",
                    "task_instruction": "Do something",
                    "verification_instruction": "Verify it",
                    "agent_id": "test-agent",
                    "project_id": 1
                }
            )
        
        assert response.status_code == 403
        assert "not authorized" in response.json()["detail"].lower()
    
    @patch('api.routes.tasks.get_db')
    @patch('api.routes.tasks.verify_api_key')
    def test_create_task_unexpected_error(
        self, mock_verify_auth, mock_get_db, client, mock_db, mock_task_service, mock_auth
    ):
        """Test task creation with unexpected error."""
        mock_get_db.return_value = mock_db
        mock_verify_auth.return_value = mock_auth
        mock_task_service.create_task.side_effect = Exception("Unexpected error")
        
        with patch('api.routes.tasks.get_task_service', return_value=mock_task_service):
            response = client.post(
                "/tasks",
                json={
                    "title": "Test Task",
                    "task_type": "concrete",
                    "task_instruction": "Do something",
                    "verification_instruction": "Verify it",
                    "agent_id": "test-agent",
                    "project_id": 1
                }
            )
        
        assert response.status_code == 500
        assert "Failed to create task" in response.json()["detail"]
    
    @patch('api.routes.tasks.get_db')
    @patch('api.routes.tasks.verify_api_key')
    def test_create_task_authentication_required(
        self, mock_verify_auth, mock_get_db, client, mock_db
    ):
        """Test that authentication is required."""
        mock_get_db.return_value = mock_db
        mock_verify_auth.side_effect = Exception("Unauthorized")
        
        response = client.post(
            "/tasks",
            json={
                "title": "Test Task",
                "task_type": "concrete",
                "task_instruction": "Do something",
                "verification_instruction": "Verify it",
                "agent_id": "test-agent",
                "project_id": 1
            }
        )
        
        # Should fail authentication
        assert response.status_code in [401, 403, 500]


class TestQueryTasks:
    """Test GET /tasks endpoint."""
    
    @patch('api.routes.tasks.get_db')
    def test_query_tasks_success(self, mock_get_db, client, mock_db):
        """Test successful task query."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[1]["id"] == 2
    
    @patch('api.routes.tasks.get_db')
    def test_query_tasks_with_filters(self, mock_get_db, client, mock_db):
        """Test task query with filters."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks?task_type=concrete&task_status=available&limit=10")
        
        assert response.status_code == 200
        mock_db.query_tasks.assert_called_once()
        call_kwargs = mock_db.query_tasks.call_args[1]
        assert call_kwargs["task_type"] == "concrete"
        assert call_kwargs["task_status"] == "available"
        assert call_kwargs["limit"] == 10
    
    @patch('api.routes.tasks.get_db')
    def test_query_tasks_invalid_task_type(self, mock_get_db, client, mock_db):
        """Test task query with invalid task_type."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks?task_type=invalid")
        
        assert response.status_code == 400
        assert "Invalid task_type" in response.json()["detail"]
    
    @patch('api.routes.tasks.get_db')
    def test_query_tasks_invalid_task_status(self, mock_get_db, client, mock_db):
        """Test task query with invalid task_status."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks?task_status=invalid")
        
        assert response.status_code == 400
        assert "Invalid task_status" in response.json()["detail"]
    
    @patch('api.routes.tasks.get_db')
    def test_query_tasks_invalid_priority(self, mock_get_db, client, mock_db):
        """Test task query with invalid priority."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks?priority=invalid")
        
        assert response.status_code == 400
        assert "Invalid priority" in response.json()["detail"]
    
    @patch('api.routes.tasks.get_db')
    def test_query_tasks_invalid_order_by(self, mock_get_db, client, mock_db):
        """Test task query with invalid order_by."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks?order_by=invalid")
        
        assert response.status_code == 400
        assert "Invalid order_by" in response.json()["detail"]
    
    @patch('api.routes.tasks.get_db')
    def test_query_tasks_invalid_limit(self, mock_get_db, client, mock_db):
        """Test task query with invalid limit."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks?limit=0")
        
        assert response.status_code == 422  # Validation error
    
    @patch('api.routes.tasks.get_db')
    def test_query_tasks_invalid_tag_ids_format(self, mock_get_db, client, mock_db):
        """Test task query with invalid tag_ids format."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks?tag_ids=invalid")
        
        assert response.status_code == 400
        assert "Invalid tag_ids format" in response.json()["detail"]
    
    @patch('api.routes.tasks.get_db')
    def test_query_tasks_invalid_date_format(self, mock_get_db, client, mock_db):
        """Test task query with invalid date format."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks?created_after=invalid-date")
        
        assert response.status_code == 400
        assert "Invalid date format" in response.json()["detail"]


class TestGetTask:
    """Test GET /tasks/{task_id} endpoint."""
    
    @patch('api.routes.tasks.get_db')
    def test_get_task_success(self, mock_get_db, client, mock_db, mock_task_service):
        """Test successful task retrieval."""
        mock_get_db.return_value = mock_db
        
        with patch('api.routes.tasks.get_task_service', return_value=mock_task_service):
            response = client.get("/tasks/1")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["title"] == "Test Task"
        mock_task_service.get_task.assert_called_once_with(1)
    
    @patch('api.routes.tasks.get_db')
    def test_get_task_not_found(self, mock_get_db, client, mock_db, mock_task_service):
        """Test task retrieval when task not found."""
        mock_get_db.return_value = mock_db
        mock_task_service.get_task.return_value = None
        
        with patch('api.routes.tasks.get_task_service', return_value=mock_task_service):
            response = client.get("/tasks/999")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    @patch('api.routes.tasks.get_db')
    def test_get_task_invalid_id(self, mock_get_db, client, mock_db):
        """Test task retrieval with invalid task_id."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks/0")
        
        assert response.status_code == 422  # Validation error (gt=0 constraint)
    
    @patch('api.routes.tasks.get_db')
    def test_get_task_non_numeric_id(self, mock_get_db, client, mock_db):
        """Test task retrieval with non-numeric task_id."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks/abc")
        
        assert response.status_code == 422  # Validation error
