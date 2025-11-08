"""
Mock-based unit tests for project route handlers.
Tests the HTTP layer in isolation without real database or HTTP connections.
"""
import pytest
import sys
import os
import sqlite3

# Add src to path BEFORE importing FastAPI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from unittest.mock import Mock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import projects
from models.project_models import ProjectCreate, ProjectResponse


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = Mock()
    db.create_project.return_value = 1
    db.get_project.return_value = {
        "id": 1,
        "name": "Test Project",
        "local_path": "/test",
        "origin_url": "https://github.com/test/project",
        "description": "Test description"
    }
    db.get_project_by_name.return_value = {
        "id": 1,
        "name": "Test Project",
        "local_path": "/test",
        "origin_url": "https://github.com/test/project",
        "description": "Test description"
    }
    db.list_projects.return_value = [
        {
            "id": 1,
            "name": "Test Project 1",
            "local_path": "/test1",
            "origin_url": "https://github.com/test/project1",
            "description": "Test description 1"
        },
        {
            "id": 2,
            "name": "Test Project 2",
            "local_path": "/test2",
            "origin_url": "https://github.com/test/project2",
            "description": "Test description 2"
        }
    ]
    return db


@pytest.fixture
def mock_auth():
    """Create a mock authentication result."""
    return {"api_key": "test-key", "user_id": "test-user"}


@pytest.fixture
def app():
    """Create a FastAPI app with projects router."""
    app = FastAPI()
    app.include_router(projects.router)
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestCreateProject:
    """Test POST /projects endpoint."""
    
    @patch('api.routes.projects.get_db')
    def test_create_project_success(self, mock_get_db, client, mock_db):
        """Test successful project creation."""
        mock_get_db.return_value = mock_db
        
        response = client.post(
            "/projects",
            json={
                "name": "Test Project",
                "local_path": "/test",
                "origin_url": "https://github.com/test/project",
                "description": "Test description"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["name"] == "Test Project"
        assert data["local_path"] == "/test"
        mock_db.create_project.assert_called_once()
        mock_db.get_project.assert_called_once_with(1)
    
    @patch('api.routes.projects.get_db')
    def test_create_project_validation_error(self, mock_get_db, client, mock_db):
        """Test project creation with validation error."""
        mock_get_db.return_value = mock_db
        
        # Missing required fields
        response = client.post("/projects", json={})
        
        assert response.status_code == 422  # Validation error
    
    @patch('api.routes.projects.get_db')
    def test_create_project_duplicate_name(self, mock_get_db, client, mock_db):
        """Test project creation with duplicate name."""
        mock_get_db.return_value = mock_db
        mock_db.create_project.side_effect = sqlite3.IntegrityError("UNIQUE constraint failed")
        
        response = client.post(
            "/projects",
            json={
                "name": "Existing Project",
                "local_path": "/test",
                "origin_url": "https://github.com/test/project",
                "description": "Test description"
            }
        )
        
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()
    
    @patch('api.routes.projects.get_db')
    def test_create_project_retrieval_failure(self, mock_get_db, client, mock_db):
        """Test project creation when retrieval fails."""
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = None
        
        response = client.post(
            "/projects",
            json={
                "name": "Test Project",
                "local_path": "/test",
                "origin_url": "https://github.com/test/project",
                "description": "Test description"
            }
        )
        
        assert response.status_code == 500
        assert "Failed to retrieve" in response.json()["detail"]


class TestListProjects:
    """Test GET /projects endpoint."""
    
    @patch('api.routes.projects.get_db')
    @patch('api.routes.projects.optional_api_key')
    def test_list_projects_success_without_auth(
        self, mock_optional_auth, mock_get_db, client, mock_db
    ):
        """Test successful project listing without authentication."""
        mock_get_db.return_value = mock_db
        mock_optional_auth.return_value = None
        
        response = client.get("/projects")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[1]["id"] == 2
        mock_db.list_projects.assert_called_once()
    
    @patch('api.routes.projects.get_db')
    @patch('api.routes.projects.optional_api_key')
    def test_list_projects_success_with_auth(
        self, mock_optional_auth, mock_get_db, client, mock_db, mock_auth
    ):
        """Test successful project listing with authentication."""
        mock_get_db.return_value = mock_db
        mock_optional_auth.return_value = mock_auth
        
        response = client.get("/projects")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        mock_db.list_projects.assert_called_once()
    
    @patch('api.routes.projects.get_db')
    @patch('api.routes.projects.optional_api_key')
    def test_list_projects_empty(self, mock_optional_auth, mock_get_db, client, mock_db):
        """Test project listing when no projects exist."""
        mock_get_db.return_value = mock_db
        mock_optional_auth.return_value = None
        mock_db.list_projects.return_value = []
        
        response = client.get("/projects")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0


class TestGetProject:
    """Test GET /projects/{project_id} endpoint."""
    
    @patch('api.routes.projects.get_db')
    def test_get_project_success(self, mock_get_db, client, mock_db):
        """Test successful project retrieval by ID."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/projects/1")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["name"] == "Test Project"
        mock_db.get_project.assert_called_once_with(1)
    
    @patch('api.routes.projects.get_db')
    def test_get_project_not_found(self, mock_get_db, client, mock_db):
        """Test project retrieval when project not found."""
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = None
        
        response = client.get("/projects/999")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        assert "999" in response.json()["detail"]
    
    @patch('api.routes.projects.get_db')
    def test_get_project_invalid_id(self, mock_get_db, client, mock_db):
        """Test project retrieval with invalid project_id."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/projects/0")
        
        assert response.status_code == 422  # Validation error (gt=0 constraint)
    
    @patch('api.routes.projects.get_db')
    def test_get_project_non_numeric_id(self, mock_get_db, client, mock_db):
        """Test project retrieval with non-numeric project_id."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/projects/abc")
        
        assert response.status_code == 422  # Validation error


class TestGetProjectByName:
    """Test GET /projects/name/{project_name} endpoint."""
    
    @patch('api.routes.projects.get_db')
    def test_get_project_by_name_success(self, mock_get_db, client, mock_db):
        """Test successful project retrieval by name."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/projects/name/Test%20Project")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["name"] == "Test Project"
        mock_db.get_project_by_name.assert_called_once_with("Test Project")
    
    @patch('api.routes.projects.get_db')
    def test_get_project_by_name_not_found(self, mock_get_db, client, mock_db):
        """Test project retrieval when project name not found."""
        mock_get_db.return_value = mock_db
        mock_db.get_project_by_name.return_value = None
        
        response = client.get("/projects/name/Nonexistent")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        assert "Nonexistent" in response.json()["detail"]
    
    @patch('api.routes.projects.get_db')
    def test_get_project_by_name_empty(self, mock_get_db, client, mock_db):
        """Test project retrieval with empty project name."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/projects/name/")
        
        # Empty path parameter should be caught by FastAPI validation
        assert response.status_code in [404, 422]
    
    @patch('api.routes.projects.get_db')
    def test_get_project_by_name_whitespace(self, mock_get_db, client, mock_db):
        """Test project retrieval with whitespace-only name."""
        mock_get_db.return_value = mock_db
        
        response = client.get("/projects/name/%20%20")
        
        assert response.status_code == 400
        assert "cannot be empty" in response.json()["detail"].lower()
