"""
Unit tests for RecurringTaskService.
Tests business logic in isolation without HTTP framework dependencies.
"""
import pytest
import sys
import os
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from todorama.services.recurring_task_service import RecurringTaskService


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = MagicMock()
    return db


@pytest.fixture
def recurring_task_service(mock_db):
    """Create a RecurringTaskService instance with mocked database."""
    return RecurringTaskService(mock_db)


class TestCreateRecurringTask:
    """Tests for create_recurring_task method."""
    
    def test_create_recurring_task_daily_success(self, recurring_task_service, mock_db):
        """Test successful daily recurring task creation."""
        # Setup
        task_id = 1
        next_occurrence = datetime.now() + timedelta(days=1)
        mock_db.get_task.return_value = {
            "id": task_id,
            "title": "Daily Review",
            "task_type": "concrete"
        }
        mock_db.create_recurring_task.return_value = 1
        mock_db.get_recurring_task.return_value = {
            "id": 1,
            "task_id": task_id,
            "recurrence_type": "daily",
            "recurrence_config": {},
            "next_occurrence": next_occurrence,
            "is_active": 1
        }
        
        # Execute
        result = recurring_task_service.create_recurring_task(
            task_id=task_id,
            recurrence_type="daily",
            next_occurrence=next_occurrence
        )
        
        # Verify
        assert result["id"] == 1
        assert result["task_id"] == task_id
        assert result["recurrence_type"] == "daily"
        mock_db.get_task.assert_called_once_with(task_id)
        mock_db.create_recurring_task.assert_called_once()
        mock_db.get_recurring_task.assert_called_once_with(1)
    
    def test_create_recurring_task_weekly_with_config(self, recurring_task_service, mock_db):
        """Test successful weekly recurring task creation with day_of_week config."""
        # Setup
        task_id = 2
        next_occurrence = datetime.now() + timedelta(days=1)
        mock_db.get_task.return_value = {
            "id": task_id,
            "title": "Weekly Review",
            "task_type": "concrete"
        }
        mock_db.create_recurring_task.return_value = 2
        mock_db.get_recurring_task.return_value = {
            "id": 2,
            "task_id": task_id,
            "recurrence_type": "weekly",
            "recurrence_config": {"day_of_week": 0},
            "next_occurrence": next_occurrence,
            "is_active": 1
        }
        
        # Execute
        result = recurring_task_service.create_recurring_task(
            task_id=task_id,
            recurrence_type="weekly",
            next_occurrence=next_occurrence,
            recurrence_config={"day_of_week": 0}
        )
        
        # Verify
        assert result["recurrence_type"] == "weekly"
        assert result["recurrence_config"]["day_of_week"] == 0
        call_args = mock_db.create_recurring_task.call_args
        assert call_args[1]["recurrence_config"]["day_of_week"] == 0
    
    def test_create_recurring_task_monthly_with_config(self, recurring_task_service, mock_db):
        """Test successful monthly recurring task creation with day_of_month config."""
        # Setup
        task_id = 3
        next_occurrence = datetime.now() + timedelta(days=1)
        mock_db.get_task.return_value = {
            "id": task_id,
            "title": "Monthly Review",
            "task_type": "concrete"
        }
        mock_db.create_recurring_task.return_value = 3
        mock_db.get_recurring_task.return_value = {
            "id": 3,
            "task_id": task_id,
            "recurrence_type": "monthly",
            "recurrence_config": {"day_of_month": 15},
            "next_occurrence": next_occurrence,
            "is_active": 1
        }
        
        # Execute
        result = recurring_task_service.create_recurring_task(
            task_id=task_id,
            recurrence_type="monthly",
            next_occurrence=next_occurrence,
            recurrence_config={"day_of_month": 15}
        )
        
        # Verify
        assert result["recurrence_type"] == "monthly"
        assert result["recurrence_config"]["day_of_month"] == 15
    
    def test_create_recurring_task_invalid_type_raises_value_error(self, recurring_task_service, mock_db):
        """Test that invalid recurrence_type raises ValueError."""
        # Execute & Verify
        with pytest.raises(ValueError, match="Invalid recurrence_type"):
            recurring_task_service.create_recurring_task(
                task_id=1,
                recurrence_type="invalid",
                next_occurrence=datetime.now() + timedelta(days=1)
            )
        
        mock_db.create_recurring_task.assert_not_called()
    
    def test_create_recurring_task_task_not_found_raises_value_error(self, recurring_task_service, mock_db):
        """Test that non-existent task raises ValueError."""
        # Setup
        mock_db.get_task.return_value = None
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Task 1 not found"):
            recurring_task_service.create_recurring_task(
                task_id=1,
                recurrence_type="daily",
                next_occurrence=datetime.now() + timedelta(days=1)
            )
        
        mock_db.create_recurring_task.assert_not_called()
    
    def test_create_recurring_task_invalid_day_of_week_raises_value_error(self, recurring_task_service, mock_db):
        """Test that invalid day_of_week raises ValueError."""
        # Setup
        mock_db.get_task.return_value = {"id": 1, "title": "Test", "task_type": "concrete"}
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Invalid day_of_week"):
            recurring_task_service.create_recurring_task(
                task_id=1,
                recurrence_type="weekly",
                next_occurrence=datetime.now() + timedelta(days=1),
                recurrence_config={"day_of_week": 10}  # Invalid: > 6
            )
        
        mock_db.create_recurring_task.assert_not_called()
    
    def test_create_recurring_task_invalid_day_of_month_raises_value_error(self, recurring_task_service, mock_db):
        """Test that invalid day_of_month raises ValueError."""
        # Setup
        mock_db.get_task.return_value = {"id": 1, "title": "Test", "task_type": "concrete"}
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Invalid day_of_month"):
            recurring_task_service.create_recurring_task(
                task_id=1,
                recurrence_type="monthly",
                next_occurrence=datetime.now() + timedelta(days=1),
                recurrence_config={"day_of_month": 32}  # Invalid: > 31
            )
        
        mock_db.create_recurring_task.assert_not_called()
    
    def test_create_recurring_task_database_error_raises_value_error(self, recurring_task_service, mock_db):
        """Test that database errors are caught and re-raised as ValueError."""
        # Setup
        mock_db.get_task.return_value = {"id": 1, "title": "Test", "task_type": "concrete"}
        mock_db.create_recurring_task.side_effect = Exception("Database error")
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Failed to create recurring task"):
            recurring_task_service.create_recurring_task(
                task_id=1,
                recurrence_type="daily",
                next_occurrence=datetime.now() + timedelta(days=1)
            )


class TestGetRecurringTask:
    """Tests for get_recurring_task method."""
    
    def test_get_recurring_task_success(self, recurring_task_service, mock_db):
        """Test successful recurring task retrieval."""
        # Setup
        recurring_id = 1
        mock_db.get_recurring_task.return_value = {
            "id": recurring_id,
            "task_id": 1,
            "recurrence_type": "daily",
            "is_active": 1
        }
        
        # Execute
        result = recurring_task_service.get_recurring_task(recurring_id)
        
        # Verify
        assert result is not None
        assert result["id"] == recurring_id
        mock_db.get_recurring_task.assert_called_once_with(recurring_id)
    
    def test_get_recurring_task_not_found_returns_none(self, recurring_task_service, mock_db):
        """Test that non-existent recurring task returns None."""
        # Setup
        mock_db.get_recurring_task.return_value = None
        
        # Execute
        result = recurring_task_service.get_recurring_task(999)
        
        # Verify
        assert result is None


class TestListRecurringTasks:
    """Tests for list_recurring_tasks method."""
    
    def test_list_recurring_tasks_all(self, recurring_task_service, mock_db):
        """Test listing all recurring tasks."""
        # Setup
        mock_db.list_recurring_tasks.return_value = [
            {"id": 1, "task_id": 1, "recurrence_type": "daily", "is_active": 1},
            {"id": 2, "task_id": 2, "recurrence_type": "weekly", "is_active": 0}
        ]
        
        # Execute
        result = recurring_task_service.list_recurring_tasks(active_only=False)
        
        # Verify
        assert len(result) == 2
        mock_db.list_recurring_tasks.assert_called_once_with(active_only=False)
    
    def test_list_recurring_tasks_active_only(self, recurring_task_service, mock_db):
        """Test listing only active recurring tasks."""
        # Setup
        mock_db.list_recurring_tasks.return_value = [
            {"id": 1, "task_id": 1, "recurrence_type": "daily", "is_active": 1}
        ]
        
        # Execute
        result = recurring_task_service.list_recurring_tasks(active_only=True)
        
        # Verify
        assert len(result) == 1
        mock_db.list_recurring_tasks.assert_called_once_with(active_only=True)
    
    def test_list_recurring_tasks_empty(self, recurring_task_service, mock_db):
        """Test listing when no recurring tasks exist."""
        # Setup
        mock_db.list_recurring_tasks.return_value = []
        
        # Execute
        result = recurring_task_service.list_recurring_tasks()
        
        # Verify
        assert len(result) == 0


class TestUpdateRecurringTask:
    """Tests for update_recurring_task method."""
    
    def test_update_recurring_task_success(self, recurring_task_service, mock_db):
        """Test successful recurring task update."""
        # Setup
        recurring_id = 1
        new_next_occurrence = datetime.now() + timedelta(days=2)
        mock_db.get_recurring_task.return_value = {
            "id": recurring_id,
            "task_id": 1,
            "recurrence_type": "daily",
            "is_active": 1
        }
        mock_db.update_recurring_task.return_value = None
        mock_db.get_recurring_task.side_effect = [
            {"id": recurring_id, "task_id": 1, "recurrence_type": "daily", "is_active": 1},  # First call
            {"id": recurring_id, "task_id": 1, "recurrence_type": "daily", "is_active": 1, "next_occurrence": new_next_occurrence}  # Second call
        ]
        
        # Execute
        result = recurring_task_service.update_recurring_task(
            recurring_id=recurring_id,
            next_occurrence=new_next_occurrence
        )
        
        # Verify
        assert result["id"] == recurring_id
        mock_db.update_recurring_task.assert_called_once()
        assert mock_db.get_recurring_task.call_count == 2
    
    def test_update_recurring_task_not_found_raises_value_error(self, recurring_task_service, mock_db):
        """Test that updating non-existent recurring task raises ValueError."""
        # Setup
        mock_db.get_recurring_task.return_value = None
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Recurring task 999 not found"):
            recurring_task_service.update_recurring_task(
                recurring_id=999,
                recurrence_type="weekly"
            )
        
        mock_db.update_recurring_task.assert_not_called()
    
    def test_update_recurring_task_invalid_type_raises_value_error(self, recurring_task_service, mock_db):
        """Test that invalid recurrence_type raises ValueError."""
        # Setup
        mock_db.get_recurring_task.return_value = {
            "id": 1,
            "task_id": 1,
            "recurrence_type": "daily",
            "is_active": 1
        }
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Invalid recurrence_type"):
            recurring_task_service.update_recurring_task(
                recurring_id=1,
                recurrence_type="invalid"
            )
        
        mock_db.update_recurring_task.assert_not_called()


class TestDeactivateRecurringTask:
    """Tests for deactivate_recurring_task method."""
    
    def test_deactivate_recurring_task_success(self, recurring_task_service, mock_db):
        """Test successful recurring task deactivation."""
        # Setup
        recurring_id = 1
        mock_db.get_recurring_task.return_value = {
            "id": recurring_id,
            "task_id": 1,
            "recurrence_type": "daily",
            "is_active": 1
        }
        mock_db.deactivate_recurring_task.return_value = None
        mock_db.get_recurring_task.side_effect = [
            {"id": recurring_id, "task_id": 1, "recurrence_type": "daily", "is_active": 1},  # First call
            {"id": recurring_id, "task_id": 1, "recurrence_type": "daily", "is_active": 0}  # Second call
        ]
        
        # Execute
        result = recurring_task_service.deactivate_recurring_task(recurring_id)
        
        # Verify
        assert result["id"] == recurring_id
        assert result["is_active"] == 0
        mock_db.deactivate_recurring_task.assert_called_once_with(recurring_id)
    
    def test_deactivate_recurring_task_not_found_raises_value_error(self, recurring_task_service, mock_db):
        """Test that deactivating non-existent recurring task raises ValueError."""
        # Setup
        mock_db.get_recurring_task.return_value = None
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Recurring task 999 not found"):
            recurring_task_service.deactivate_recurring_task(999)
        
        mock_db.deactivate_recurring_task.assert_not_called()


class TestCreateRecurringInstance:
    """Tests for create_recurring_instance method."""
    
    def test_create_recurring_instance_success(self, recurring_task_service, mock_db):
        """Test successful recurring instance creation."""
        # Setup
        recurring_id = 1
        instance_id = 10
        mock_db.get_recurring_task.return_value = {
            "id": recurring_id,
            "task_id": 1,
            "recurrence_type": "daily",
            "is_active": 1,
            "next_occurrence": datetime.now() + timedelta(days=1)
        }
        mock_db.create_recurring_instance.return_value = instance_id
        mock_db.get_recurring_task.side_effect = [
            {"id": recurring_id, "task_id": 1, "recurrence_type": "daily", "is_active": 1},  # First call
            {"id": recurring_id, "task_id": 1, "recurrence_type": "daily", "is_active": 1, "next_occurrence": datetime.now() + timedelta(days=2)}  # Second call
        ]
        
        # Execute
        result = recurring_task_service.create_recurring_instance(recurring_id)
        
        # Verify
        assert result["instance_id"] == instance_id
        assert "recurring_task" in result
        mock_db.create_recurring_instance.assert_called_once_with(recurring_id)
    
    def test_create_recurring_instance_not_found_raises_value_error(self, recurring_task_service, mock_db):
        """Test that creating instance for non-existent recurring task raises ValueError."""
        # Setup
        mock_db.get_recurring_task.return_value = None
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Recurring task 999 not found"):
            recurring_task_service.create_recurring_instance(999)
        
        mock_db.create_recurring_instance.assert_not_called()
    
    def test_create_recurring_instance_not_active_raises_value_error(self, recurring_task_service, mock_db):
        """Test that creating instance for inactive recurring task raises ValueError."""
        # Setup
        mock_db.get_recurring_task.return_value = {
            "id": 1,
            "task_id": 1,
            "recurrence_type": "daily",
            "is_active": 0  # Not active
        }
        
        # Execute & Verify
        with pytest.raises(ValueError, match="is not active"):
            recurring_task_service.create_recurring_instance(1)
        
        mock_db.create_recurring_instance.assert_not_called()
    
    def test_create_recurring_instance_database_error_raises_value_error(self, recurring_task_service, mock_db):
        """Test that database errors are caught and re-raised as ValueError."""
        # Setup
        mock_db.get_recurring_task.return_value = {
            "id": 1,
            "task_id": 1,
            "recurrence_type": "daily",
            "is_active": 1
        }
        mock_db.create_recurring_instance.side_effect = Exception("Database error")
        
        # Execute & Verify
        with pytest.raises(ValueError, match="Failed to create recurring instance"):
            recurring_task_service.create_recurring_instance(1)
