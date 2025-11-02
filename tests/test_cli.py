"""
Tests for CLI tool.
"""
import pytest
import os
import tempfile
import shutil
import json
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.cli import cli


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_env(monkeypatch):
    """Set up environment variables for testing."""
    monkeypatch.setenv("TODO_SERVICE_URL", "http://localhost:8004")
    monkeypatch.setenv("TODO_API_KEY", "test-api-key")


def test_cli_list_tasks_no_auth(runner, mock_env):
    """Test listing tasks without authentication."""
    with patch('src.cli.httpx.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "id": 1,
                "title": "Test Task",
                "task_type": "concrete",
                "task_status": "available"
            }
        ]
        mock_get.return_value = mock_response
        
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "Test Task" in result.output
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "http://localhost:8004/tasks"


def test_cli_list_tasks_with_filters(runner, mock_env):
    """Test listing tasks with filters."""
    with patch('src.cli.httpx.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get.return_value = mock_response
        
        result = runner.invoke(cli, [
            "list",
            "--status", "in_progress",
            "--type", "concrete",
            "--project-id", "1"
        ])
        assert result.exit_code == 0
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "http://localhost:8004/tasks"
        assert "task_status=in_progress" in str(call_args.kwargs["params"]) or \
               call_args.kwargs["params"]["task_status"] == "in_progress"


def test_cli_create_task(runner, mock_env):
    """Test creating a task."""
    with patch('src.cli.httpx.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 123,
            "title": "New Task",
            "task_type": "concrete",
            "task_status": "available"
        }
        mock_post.return_value = mock_response
        
        result = runner.invoke(cli, [
            "create",
            "--title", "New Task",
            "--type", "concrete",
            "--instruction", "Do something",
            "--verification", "Verify it",
            "--agent-id", "test-agent",
            "--project-id", "1"
        ])
        assert result.exit_code == 0
        assert "123" in result.output or "New Task" in result.output
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:8004/tasks"
        assert call_args.kwargs["json"]["title"] == "New Task"


def test_cli_complete_task(runner, mock_env):
    """Test completing a task."""
    with patch('src.cli.httpx.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "task_id": 123,
            "completed": True
        }
        mock_post.return_value = mock_response
        
        result = runner.invoke(cli, [
            "complete",
            "--task-id", "123",
            "--agent-id", "test-agent",
            "--notes", "Done!"
        ])
        assert result.exit_code == 0
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:8004/tasks/123/complete"
        assert call_args.kwargs["json"]["agent_id"] == "test-agent"


def test_cli_show_task(runner, mock_env):
    """Test showing task details."""
    with patch('src.cli.httpx.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 123,
            "title": "Test Task",
            "task_type": "concrete",
            "task_status": "available",
            "task_instruction": "Do something",
            "verification_instruction": "Verify it"
        }
        mock_get.return_value = mock_response
        
        result = runner.invoke(cli, ["show", "--task-id", "123"])
        assert result.exit_code == 0
        assert "Test Task" in result.output
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "http://localhost:8004/tasks/123"


def test_cli_reserve_task(runner, mock_env):
    """Test reserving a task."""
    with patch('src.cli.httpx.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "task_id": 123,
            "agent_id": "test-agent",
            "status": "locked"
        }
        mock_post.return_value = mock_response
        
        result = runner.invoke(cli, [
            "reserve",
            "--task-id", "123",
            "--agent-id", "test-agent"
        ])
        assert result.exit_code == 0
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:8004/tasks/123/lock"


def test_cli_unlock_task(runner, mock_env):
    """Test unlocking a task."""
    with patch('src.cli.httpx.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "task_id": 123,
            "agent_id": "test-agent",
            "status": "unlocked"
        }
        mock_post.return_value = mock_response
        
        result = runner.invoke(cli, [
            "unlock",
            "--task-id", "123",
            "--agent-id", "test-agent"
        ])
        assert result.exit_code == 0
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:8004/tasks/123/unlock"


def test_cli_with_api_key_flag(runner, mock_env):
    """Test CLI with API key passed as flag."""
    with patch('src.cli.httpx.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get.return_value = mock_response
        
        result = runner.invoke(cli, [
            "list",
            "--api-key", "custom-key"
        ])
        assert result.exit_code == 0
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        headers = call_args.kwargs.get("headers", {})
        assert headers.get("X-API-Key") == "custom-key"


def test_cli_with_custom_url(runner, mock_env):
    """Test CLI with custom service URL."""
    with patch('src.cli.httpx.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get.return_value = mock_response
        
        result = runner.invoke(cli, [
            "list",
            "--url", "http://custom:9000"
        ])
        assert result.exit_code == 0
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "http://custom:9000/tasks"


def test_cli_error_handling(runner, mock_env):
    """Test CLI error handling."""
    with patch('src.cli.httpx.get') as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {
            "error": "Not Found",
            "detail": "Task not found"
        }
        mock_get.return_value = mock_response
        
        result = runner.invoke(cli, ["show", "--task-id", "999"])
        assert result.exit_code != 0
        assert "404" in result.output or "Not Found" in result.output
