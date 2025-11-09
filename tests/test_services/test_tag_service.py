"""
Unit tests for TagService.
Tests business logic in isolation without HTTP framework dependencies.
"""
import pytest
import sys
import os
from unittest.mock import Mock, MagicMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from todorama.services.tag_service import TagService
import sqlite3


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = MagicMock()
    return db


@pytest.fixture
def tag_service(mock_db):
    """Create a TagService instance with mocked database."""
    return TagService(mock_db)


class TestCreateTag:
    """Tests for create_tag method."""
    
    def test_create_tag_success(self, tag_service, mock_db):
        """Test successful tag creation."""
        # Setup
        mock_db.create_tag.return_value = 1
        mock_db.get_tag.return_value = {
            "id": 1,
            "name": "bug"
        }
        
        # Execute
        result = tag_service.create_tag("bug")
        
        # Verify
        assert result["id"] == 1
        assert result["name"] == "bug"
        mock_db.create_tag.assert_called_once_with("bug")
        mock_db.get_tag.assert_called_once_with(1)
    
    def test_create_tag_strips_whitespace(self, tag_service, mock_db):
        """Test that tag name is stripped of whitespace."""
        # Setup
        mock_db.create_tag.return_value = 1
        mock_db.get_tag.return_value = {
            "id": 1,
            "name": "feature"
        }
        
        # Execute
        result = tag_service.create_tag("  feature  ")
        
        # Verify
        mock_db.create_tag.assert_called_once_with("feature")
        assert result["name"] == "feature"
    
    def test_create_tag_empty_name_raises_value_error(self, tag_service, mock_db):
        """Test that empty tag name raises ValueError."""
        # Execute & Verify
        with pytest.raises(ValueError, match="Tag name cannot be empty or whitespace"):
            tag_service.create_tag("")
        
        mock_db.create_tag.assert_not_called()
    
    def test_create_tag_whitespace_only_raises_value_error(self, tag_service, mock_db):
        """Test that whitespace-only tag name raises ValueError."""
        # Execute & Verify
        with pytest.raises(ValueError, match="Tag name cannot be empty or whitespace"):
            tag_service.create_tag("   ")
        
        mock_db.create_tag.assert_not_called()
    
    def test_create_tag_database_error(self, tag_service, mock_db):
        """Test tag creation with database error."""
        # Setup
        mock_db.create_tag.side_effect = Exception("Database connection failed")
        
        # Execute & Verify
        with pytest.raises(Exception, match="Failed to create tag"):
            tag_service.create_tag("bug")
    
    def test_create_tag_retrieval_failure(self, tag_service, mock_db):
        """Test tag creation when retrieval fails."""
        # Setup
        mock_db.create_tag.return_value = 1
        mock_db.get_tag.return_value = None  # Retrieval fails
        
        # Execute & Verify
        with pytest.raises(Exception, match="Tag was created but could not be retrieved"):
            tag_service.create_tag("bug")


class TestGetTag:
    """Tests for get_tag method."""
    
    def test_get_tag_success(self, tag_service, mock_db):
        """Test successful tag retrieval."""
        # Setup
        mock_db.get_tag.return_value = {
            "id": 1,
            "name": "bug"
        }
        
        # Execute
        result = tag_service.get_tag(1)
        
        # Verify
        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "bug"
        mock_db.get_tag.assert_called_once_with(1)
    
    def test_get_tag_not_found(self, tag_service, mock_db):
        """Test tag retrieval when tag doesn't exist."""
        # Setup
        mock_db.get_tag.return_value = None
        
        # Execute
        result = tag_service.get_tag(999)
        
        # Verify
        assert result is None
        mock_db.get_tag.assert_called_once_with(999)


class TestGetTagByName:
    """Tests for get_tag_by_name method."""
    
    def test_get_tag_by_name_success(self, tag_service, mock_db):
        """Test successful tag retrieval by name."""
        # Setup
        mock_db.get_tag_by_name.return_value = {
            "id": 1,
            "name": "bug"
        }
        
        # Execute
        result = tag_service.get_tag_by_name("bug")
        
        # Verify
        assert result is not None
        assert result["id"] == 1
        assert result["name"] == "bug"
        mock_db.get_tag_by_name.assert_called_once_with("bug")
    
    def test_get_tag_by_name_not_found(self, tag_service, mock_db):
        """Test tag retrieval by name when tag doesn't exist."""
        # Setup
        mock_db.get_tag_by_name.return_value = None
        
        # Execute
        result = tag_service.get_tag_by_name("non-existent")
        
        # Verify
        assert result is None
        mock_db.get_tag_by_name.assert_called_once_with("non-existent")


class TestListTags:
    """Tests for list_tags method."""
    
    def test_list_tags_success(self, tag_service, mock_db):
        """Test successful tag listing."""
        # Setup
        mock_db.list_tags.return_value = [
            {"id": 1, "name": "bug"},
            {"id": 2, "name": "feature"},
            {"id": 3, "name": "enhancement"}
        ]
        
        # Execute
        result = tag_service.list_tags()
        
        # Verify
        assert len(result) == 3
        assert result[0]["id"] == 1
        assert result[0]["name"] == "bug"
        assert result[1]["id"] == 2
        assert result[1]["name"] == "feature"
        mock_db.list_tags.assert_called_once()
    
    def test_list_tags_empty(self, tag_service, mock_db):
        """Test tag listing when no tags exist."""
        # Setup
        mock_db.list_tags.return_value = []
        
        # Execute
        result = tag_service.list_tags()
        
        # Verify
        assert result == []
        mock_db.list_tags.assert_called_once()


class TestAssignTagToTask:
    """Tests for assign_tag_to_task method."""
    
    def test_assign_tag_to_task_success(self, tag_service, mock_db):
        """Test successful tag assignment to task."""
        # Setup
        mock_db.get_task.return_value = {"id": 1, "title": "Test Task"}
        mock_db.get_tag.return_value = {"id": 10, "name": "bug"}
        
        # Execute
        result = tag_service.assign_tag_to_task(task_id=1, tag_id=10)
        
        # Verify
        assert result["success"] is True
        assert result["task_id"] == 1
        assert result["tag_id"] == 10
        assert "message" in result
        mock_db.get_task.assert_called_once_with(1)
        mock_db.get_tag.assert_called_once_with(10)
        mock_db.assign_tag_to_task.assert_called_once_with(1, 10)
    
    def test_assign_tag_to_task_task_not_found(self, tag_service, mock_db):
        """Test tag assignment when task doesn't exist."""
        # Setup
        mock_db.get_task.return_value = None
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Task 1 not found"):
            tag_service.assign_tag_to_task(task_id=1, tag_id=10)
        
        mock_db.get_task.assert_called_once_with(1)
        mock_db.get_tag.assert_not_called()
        mock_db.assign_tag_to_task.assert_not_called()
    
    def test_assign_tag_to_task_tag_not_found(self, tag_service, mock_db):
        """Test tag assignment when tag doesn't exist."""
        # Setup
        mock_db.get_task.return_value = {"id": 1, "title": "Test Task"}
        mock_db.get_tag.return_value = None
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Tag 10 not found"):
            tag_service.assign_tag_to_task(task_id=1, tag_id=10)
        
        mock_db.get_task.assert_called_once_with(1)
        mock_db.get_tag.assert_called_once_with(10)
        mock_db.assign_tag_to_task.assert_not_called()
    
    def test_assign_tag_to_task_database_error(self, tag_service, mock_db):
        """Test tag assignment with database error."""
        # Setup
        mock_db.get_task.return_value = {"id": 1, "title": "Test Task"}
        mock_db.get_tag.return_value = {"id": 10, "name": "bug"}
        mock_db.assign_tag_to_task.side_effect = Exception("Database error")
        
        # Execute & Verify
        with pytest.raises(Exception, match="Failed to assign tag"):
            tag_service.assign_tag_to_task(task_id=1, tag_id=10)


class TestRemoveTagFromTask:
    """Tests for remove_tag_from_task method."""
    
    def test_remove_tag_from_task_success(self, tag_service, mock_db):
        """Test successful tag removal from task."""
        # Setup
        mock_db.get_task.return_value = {"id": 1, "title": "Test Task"}
        
        # Execute
        result = tag_service.remove_tag_from_task(task_id=1, tag_id=10)
        
        # Verify
        assert result["success"] is True
        assert result["task_id"] == 1
        assert result["tag_id"] == 10
        assert "message" in result
        mock_db.get_task.assert_called_once_with(1)
        mock_db.remove_tag_from_task.assert_called_once_with(1, 10)
    
    def test_remove_tag_from_task_task_not_found(self, tag_service, mock_db):
        """Test tag removal when task doesn't exist."""
        # Setup
        mock_db.get_task.return_value = None
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Task 1 not found"):
            tag_service.remove_tag_from_task(task_id=1, tag_id=10)
        
        mock_db.get_task.assert_called_once_with(1)
        mock_db.remove_tag_from_task.assert_not_called()
    
    def test_remove_tag_from_task_database_error(self, tag_service, mock_db):
        """Test tag removal with database error."""
        # Setup
        mock_db.get_task.return_value = {"id": 1, "title": "Test Task"}
        mock_db.remove_tag_from_task.side_effect = Exception("Database error")
        
        # Execute & Verify
        with pytest.raises(Exception, match="Failed to remove tag"):
            tag_service.remove_tag_from_task(task_id=1, tag_id=10)


class TestGetTaskTags:
    """Tests for get_task_tags method."""
    
    def test_get_task_tags_success(self, tag_service, mock_db):
        """Test successful retrieval of task tags."""
        # Setup
        mock_db.get_task.return_value = {"id": 1, "title": "Test Task"}
        mock_db.get_task_tags.return_value = [
            {"id": 10, "name": "bug"},
            {"id": 11, "name": "feature"}
        ]
        
        # Execute
        result = tag_service.get_task_tags(task_id=1)
        
        # Verify
        assert len(result) == 2
        assert result[0]["id"] == 10
        assert result[0]["name"] == "bug"
        assert result[1]["id"] == 11
        assert result[1]["name"] == "feature"
        mock_db.get_task.assert_called_once_with(1)
        mock_db.get_task_tags.assert_called_once_with(1)
    
    def test_get_task_tags_empty(self, tag_service, mock_db):
        """Test retrieval of task tags when task has no tags."""
        # Setup
        mock_db.get_task.return_value = {"id": 1, "title": "Test Task"}
        mock_db.get_task_tags.return_value = []
        
        # Execute
        result = tag_service.get_task_tags(task_id=1)
        
        # Verify
        assert result == []
        mock_db.get_task.assert_called_once_with(1)
        mock_db.get_task_tags.assert_called_once_with(1)
    
    def test_get_task_tags_task_not_found(self, tag_service, mock_db):
        """Test tag retrieval when task doesn't exist."""
        # Setup
        mock_db.get_task.return_value = None
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Task 1 not found"):
            tag_service.get_task_tags(task_id=1)
        
        mock_db.get_task.assert_called_once_with(1)
        mock_db.get_task_tags.assert_not_called()


class TestDeleteTag:
    """Tests for delete_tag method."""
    
    def test_delete_tag_success(self, tag_service, mock_db):
        """Test successful tag deletion."""
        # Setup
        mock_db.get_tag.return_value = {"id": 10, "name": "bug"}
        
        # Execute
        result = tag_service.delete_tag(tag_id=10)
        
        # Verify
        assert result["success"] is True
        assert result["tag_id"] == 10
        assert "message" in result
        mock_db.get_tag.assert_called_once_with(10)
        mock_db.delete_tag.assert_called_once_with(10)
    
    def test_delete_tag_not_found(self, tag_service, mock_db):
        """Test tag deletion when tag doesn't exist."""
        # Setup
        mock_db.get_tag.return_value = None
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Tag 10 not found"):
            tag_service.delete_tag(tag_id=10)
        
        mock_db.get_tag.assert_called_once_with(10)
        mock_db.delete_tag.assert_not_called()
    
    def test_delete_tag_database_error(self, tag_service, mock_db):
        """Test tag deletion with database error."""
        # Setup
        mock_db.get_tag.return_value = {"id": 10, "name": "bug"}
        mock_db.delete_tag.side_effect = Exception("Database error")
        
        # Execute & Verify
        with pytest.raises(Exception, match="Failed to delete tag"):
            tag_service.delete_tag(tag_id=10)
