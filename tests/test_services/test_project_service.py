"""
Unit tests for ProjectService.
Tests business logic in isolation without HTTP framework dependencies.
"""
import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, UTC

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from todorama.services.project_service import ProjectService
from todorama.models.project_models import ProjectCreate
import sqlite3


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = MagicMock()
    return db


@pytest.fixture
def project_service(mock_db):
    """Create a ProjectService instance with mocked database."""
    return ProjectService(mock_db)


class TestCreateProject:
    """Tests for create_project method."""
    
    def test_create_project_success(self, project_service, mock_db):
        """Test successful project creation."""
        # Setup
        project_data = ProjectCreate(
            name="Test Project",
            local_path="/test/path",
            origin_url="https://github.com/test/project",
            description="Test description"
        )
        mock_db.get_project_by_name.return_value = None  # No existing project
        mock_db.create_project.return_value = 1
        mock_db.get_project.return_value = {
            "id": 1,
            "name": "Test Project",
            "local_path": "/test/path",
            "origin_url": "https://github.com/test/project",
            "description": "Test description",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00"
        }
        
        # Execute
        with patch('todorama.services.project_service.notify_webhooks', new_callable=AsyncMock), \
             patch('todorama.services.project_service.send_task_notification', new_callable=AsyncMock):
            result = project_service.create_project(project_data)
        
        # Verify
        assert result["id"] == 1
        assert result["name"] == "Test Project"
        assert result["local_path"] == "/test/path"
        mock_db.get_project_by_name.assert_called_once_with("Test Project")
        mock_db.create_project.assert_called_once_with(
            name="Test Project",
            local_path="/test/path",
            origin_url="https://github.com/test/project",
            description="Test description"
        )
        mock_db.get_project.assert_called_once_with(1)
    
    def test_create_project_duplicate_name(self, project_service, mock_db):
        """Test project creation with duplicate name raises ValueError."""
        # Setup
        project_data = ProjectCreate(
            name="Existing Project",
            local_path="/test/path",
            origin_url=None,
            description=None
        )
        mock_db.get_project_by_name.return_value = {
            "id": 1,
            "name": "Existing Project"
        }
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Project with name 'Existing Project' already exists"):
            project_service.create_project(project_data)
        
        mock_db.get_project_by_name.assert_called_once_with("Existing Project")
        mock_db.create_project.assert_not_called()
    
    def test_create_project_database_integrity_error(self, project_service, mock_db):
        """Test project creation with database integrity error."""
        # Setup
        project_data = ProjectCreate(
            name="Test Project",
            local_path="/test/path",
            origin_url=None,
            description=None
        )
        mock_db.get_project_by_name.return_value = None
        integrity_error = sqlite3.IntegrityError("UNIQUE constraint failed: projects.name")
        mock_db.create_project.side_effect = integrity_error
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Project with name 'Test Project' already exists"):
            project_service.create_project(project_data)
    
    def test_create_project_database_error(self, project_service, mock_db):
        """Test project creation with general database error."""
        # Setup
        project_data = ProjectCreate(
            name="Test Project",
            local_path="/test/path",
            origin_url=None,
            description=None
        )
        mock_db.get_project_by_name.return_value = None
        mock_db.create_project.side_effect = Exception("Database connection failed")
        
        # Execute & Verify
        with pytest.raises(Exception, match="Failed to create project"):
            project_service.create_project(project_data)
    
    def test_create_project_retrieval_failure(self, project_service, mock_db):
        """Test project creation when retrieval fails."""
        # Setup
        project_data = ProjectCreate(
            name="Test Project",
            local_path="/test/path",
            origin_url=None,
            description=None
        )
        mock_db.get_project_by_name.return_value = None
        mock_db.create_project.return_value = 1
        mock_db.get_project.return_value = None  # Retrieval fails
        
        # Execute & Verify
        with pytest.raises(Exception, match="Project was created but could not be retrieved"):
            project_service.create_project(project_data)


class TestGetProject:
    """Tests for get_project method."""
    
    def test_get_project_success(self, project_service, mock_db):
        """Test successful project retrieval."""
        # Setup
        mock_db.get_project.return_value = {
            "id": 1,
            "name": "Test Project",
            "local_path": "/test/path",
            "origin_url": "https://github.com/test/project",
            "description": "Test description",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00"
        }
        
        # Execute
        result = project_service.get_project(1)
        
        # Verify
        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "Test Project"
        mock_db.get_project.assert_called_once_with(1)
    
    def test_get_project_not_found(self, project_service, mock_db):
        """Test project retrieval when project doesn't exist."""
        # Setup
        mock_db.get_project.return_value = None
        
        # Execute
        result = project_service.get_project(999)
        
        # Verify
        assert result is None
        mock_db.get_project.assert_called_once_with(999)


class TestGetProjectByName:
    """Tests for get_project_by_name method."""
    
    def test_get_project_by_name_success(self, project_service, mock_db):
        """Test successful project retrieval by name."""
        # Setup
        mock_db.get_project_by_name.return_value = {
            "id": 1,
            "name": "Test Project",
            "local_path": "/test/path",
            "origin_url": "https://github.com/test/project",
            "description": "Test description",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00"
        }
        
        # Execute
        result = project_service.get_project_by_name("Test Project")
        
        # Verify
        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "Test Project"
        mock_db.get_project_by_name.assert_called_once_with("Test Project")
    
    def test_get_project_by_name_strips_whitespace(self, project_service, mock_db):
        """Test that project name is stripped of whitespace."""
        # Setup
        mock_db.get_project_by_name.return_value = {
            "id": 1,
            "name": "Test Project",
            "local_path": "/test/path",
            "origin_url": None,
            "description": None,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00"
        }
        
        # Execute
        result = project_service.get_project_by_name("  Test Project  ")
        
        # Verify
        mock_db.get_project_by_name.assert_called_once_with("Test Project")
    
    def test_get_project_by_name_not_found(self, project_service, mock_db):
        """Test project retrieval by name when project doesn't exist."""
        # Setup
        mock_db.get_project_by_name.return_value = None
        
        # Execute
        result = project_service.get_project_by_name("Non-existent Project")
        
        # Verify
        assert result is None
        mock_db.get_project_by_name.assert_called_once_with("Non-existent Project")


class TestListProjects:
    """Tests for list_projects method."""
    
    def test_list_projects_success(self, project_service, mock_db):
        """Test successful project listing."""
        # Setup
        mock_db.list_projects.return_value = [
            {
                "id": 1,
                "name": "Project 1",
                "local_path": "/path1",
                "origin_url": None,
                "description": None,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00"
            },
            {
                "id": 2,
                "name": "Project 2",
                "local_path": "/path2",
                "origin_url": "https://github.com/test/project2",
                "description": "Description 2",
                "created_at": "2024-01-02T00:00:00",
                "updated_at": "2024-01-02T00:00:00"
            }
        ]
        
        # Execute
        result = project_service.list_projects()
        
        # Verify
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["name"] == "Project 1"
        assert result[1]["id"] == 2
        assert result[1]["name"] == "Project 2"
        mock_db.list_projects.assert_called_once()
    
    def test_list_projects_empty(self, project_service, mock_db):
        """Test project listing when no projects exist."""
        # Setup
        mock_db.list_projects.return_value = []
        
        # Execute
        result = project_service.list_projects()
        
        # Verify
        assert result == []
        mock_db.list_projects.assert_called_once()
    
    def test_list_projects_with_filters(self, project_service, mock_db):
        """Test project listing with filters (reserved for future use)."""
        # Setup
        mock_db.list_projects.return_value = [
            {
                "id": 1,
                "name": "Project 1",
                "local_path": "/path1",
                "origin_url": None,
                "description": None,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00"
            }
        ]
        
        # Execute
        result = project_service.list_projects(filters={"name": "Project 1"})
        
        # Verify
        # Filters are currently not used, but method accepts them for future use
        assert len(result) == 1
        mock_db.list_projects.assert_called_once()
