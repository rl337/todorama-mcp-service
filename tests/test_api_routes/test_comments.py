"""
Mock-based unit tests for comment route handlers.
Tests the HTTP layer in isolation without real database or HTTP connections.
"""
import pytest
import sys
import os

# Add src to path BEFORE importing FastAPI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from unittest.mock import Mock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import comments
from models.comment_models import CommentCreate, CommentResponse


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = Mock()
    db.get_task.return_value = {"id": 1, "title": "Test Task"}
    db.get_comment.return_value = {
        "id": 1,
        "task_id": 1,
        "agent_id": "test-agent",
        "content": "Test comment",
        "parent_comment_id": None,
        "mentions": []
    }
    db.create_comment.return_value = 1
    db.list_task_comments.return_value = [
        {
            "id": 1,
            "task_id": 1,
            "agent_id": "test-agent",
            "content": "Test comment 1",
            "parent_comment_id": None,
            "mentions": []
        },
        {
            "id": 2,
            "task_id": 1,
            "agent_id": "test-agent-2",
            "content": "Test comment 2",
            "parent_comment_id": None,
            "mentions": []
        }
    ]
    db.get_comment_thread.return_value = [
        {
            "id": 1,
            "task_id": 1,
            "agent_id": "test-agent",
            "content": "Parent comment",
            "parent_comment_id": None,
            "mentions": []
        },
        {
            "id": 2,
            "task_id": 1,
            "agent_id": "test-agent-2",
            "content": "Reply comment",
            "parent_comment_id": 1,
            "mentions": []
        }
    ]
    return db


@pytest.fixture
def mock_auth():
    """Create a mock authentication result."""
    return {"api_key": "test-key", "user_id": "test-user"}


@pytest.fixture
def app():
    """Create a FastAPI app with comments router."""
    app = FastAPI()
    app.include_router(comments.router)
    app.include_router(comments.comment_router)
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestCreateComment:
    """Test POST /tasks/{task_id}/comments endpoint."""
    
    @patch('api.routes.comments.get_db')
    @patch('api.routes.comments.verify_user_auth')
    def test_create_comment_success(
        self, mock_verify_auth, mock_get_db, client, mock_db, mock_auth
    ):
        """Test successful comment creation."""
        mock_get_db.return_value = mock_db
        mock_verify_auth.return_value = mock_auth
        
        response = client.post(
            "/tasks/1/comments",
            json={
                "agent_id": "test-agent",
                "content": "Test comment",
                "parent_comment_id": None,
                "mentions": []
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["task_id"] == 1
        assert data["content"] == "Test comment"
        mock_db.get_task.assert_called_once_with(1)
        mock_db.create_comment.assert_called_once()
        mock_db.get_comment.assert_called_once_with(1)
    
    @patch('api.routes.comments.get_db')
    @patch('api.routes.comments.verify_user_auth')
    def test_create_comment_task_not_found(
        self, mock_verify_auth, mock_get_db, client, mock_db, mock_auth
    ):
        """Test comment creation when task not found."""
        mock_get_db.return_value = mock_db
        mock_verify_auth.return_value = mock_auth
        mock_db.get_task.return_value = None
        
        response = client.post(
            "/tasks/999/comments",
            json={
                "agent_id": "test-agent",
                "content": "Test comment",
                "parent_comment_id": None,
                "mentions": []
            }
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        assert "999" in response.json()["detail"]
    
    @patch('api.routes.comments.get_db')
    @patch('api.routes.comments.verify_user_auth')
    def test_create_comment_validation_error(
        self, mock_verify_auth, mock_get_db, client, mock_db, mock_auth
    ):
        """Test comment creation with validation error."""
        mock_get_db.return_value = mock_db
        mock_verify_auth.return_value = mock_auth
        
        # Missing required fields
        response = client.post("/tasks/1/comments", json={})
        
        assert response.status_code == 422  # Validation error
    
    @patch('api.routes.comments.get_db')
    @patch('api.routes.comments.verify_user_auth')
    def test_create_comment_authentication_required(
        self, mock_verify_auth, mock_get_db, client, mock_db
    ):
        """Test that authentication is required."""
        mock_get_db.return_value = mock_db
        mock_verify_auth.side_effect = Exception("Unauthorized")
        
        response = client.post(
            "/tasks/1/comments",
            json={
                "agent_id": "test-agent",
                "content": "Test comment",
                "parent_comment_id": None,
                "mentions": []
            }
        )
        
        # Should fail authentication
        assert response.status_code in [401, 403, 500]


class TestGetTaskComments:
    """Test GET /tasks/{task_id}/comments endpoint."""
    
    @patch('api.routes.comments.get_db')
    def test_get_task_comments_success(self, mock_get_db, client, mock_db):
        """Test successful task comments retrieval."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/tasks/1/comments")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[1]["id"] == 2
        mock_db.list_task_comments.assert_called_once_with(1)
    
    @patch('api.routes.comments.get_db')
    def test_get_task_comments_empty(self, mock_get_db, client, mock_db):
        """Test task comments retrieval when no comments exist."""
        mock_get_db.return_value = mock_db
        mock_db.list_task_comments.return_value = []
        
        response = client.get("/tasks/1/comments")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0


class TestGetCommentThread:
    """Test GET /comments/{comment_id}/thread endpoint."""
    
    @patch('api.routes.comments.get_db')
    def test_get_comment_thread_success(self, mock_get_db, client, mock_db):
        """Test successful comment thread retrieval."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/comments/1/thread")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[0]["parent_comment_id"] is None
        assert data[1]["id"] == 2
        assert data[1]["parent_comment_id"] == 1
        mock_db.get_comment_thread.assert_called_once_with(1)
    
    @patch('api.routes.comments.get_db')
    def test_get_comment_thread_not_found(self, mock_get_db, client, mock_db):
        """Test comment thread retrieval when comment not found."""
        mock_get_db.return_value = mock_db
        mock_db.get_comment_thread.return_value = []
        
        response = client.get("/comments/999/thread")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0
