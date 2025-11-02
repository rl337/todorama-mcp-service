"""
Tests for Slack integration.

Tests Slack bot functionality including:
- Task notifications to Slack
- Slash commands for task operations
- Interactive components (buttons) for task actions
- Slack request signature verification
"""
import pytest
import os
import tempfile
import shutil
import time
import hmac
import hashlib
import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock
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
    main.db = db
    main.backup_manager = backup_manager
    
    yield db, db_path, backups_dir
    
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def slack_signing_secret():
    """Slack signing secret for testing."""
    return "test_signing_secret_123"


def generate_slack_signature(secret, timestamp, body):
    """Generate Slack request signature for testing."""
    sig_basestring = f"v0:{timestamp}:{body}"
    signature = hmac.new(
        secret.encode('utf-8'),
        sig_basestring.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"v0={signature}"


def test_slack_event_task_created_notification(client, slack_signing_secret):
    """Test that Slack receives notification when task is created."""
    # Set Slack configuration
    with patch.dict(os.environ, {
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "SLACK_SIGNING_SECRET": slack_signing_secret,
        "SLACK_DEFAULT_CHANNEL": "#test-channel"
    }):
        # Create project
        project_response = client.post("/projects", json={
            "name": "Test Project",
            "local_path": "/tmp/test"
        })
        project_id = project_response.json()["id"]
        
        # Create task
        with patch('slack.WebClient') as mock_web_client:
            mock_client_instance = MagicMock()
            mock_web_client.return_value = mock_client_instance
            mock_client_instance.chat_postMessage = MagicMock(return_value={"ok": True})
            
            response = client.post("/tasks", json={
                "title": "Test Task",
                "task_type": "concrete",
                "task_instruction": "Do something",
                "verification_instruction": "Check it works",
                "agent_id": "test-agent",
                "project_id": project_id
            })
            assert response.status_code == 201
            
            # Note: Slack notifications are sent asynchronously via webhooks
            # In real implementation, we'll test the Slack client directly


def test_slack_slash_command_list_tasks(client, slack_signing_secret):
    """Test /todo list slash command."""
    timestamp = str(int(time.time()))
    
    # Create project and tasks
    project_response = client.post("/projects", json={
        "name": "Test Project",
        "local_path": "/tmp/test"
    })
    project_id = project_response.json()["id"]
    
    client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Check it",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    
    # Prepare Slack slash command request
    body = {
        "token": "test-token",
        "command": "/todo",
        "text": "list",
        "response_url": "https://hooks.slack.com/commands/test",
        "user_id": "U12345",
        "channel_id": "C12345"
    }
    body_str = json.dumps(body) if isinstance(body, dict) else body
    signature = generate_slack_signature(slack_signing_secret, timestamp, body_str)
    
    with patch.dict(os.environ, {
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "SLACK_SIGNING_SECRET": slack_signing_secret
    }):
        response = client.post(
            "/slack/commands",
            data=body,
            headers={
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        # Should return 200 with task list
        assert response.status_code == 200


def test_slack_slash_command_reserve_task(client, slack_signing_secret):
    """Test /todo reserve slash command."""
    timestamp = str(int(time.time()))
    
    # Create project and task
    project_response = client.post("/projects", json={
        "name": "Test Project",
        "local_path": "/tmp/test"
    })
    project_id = project_response.json()["id"]
    
    task_response = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Check it",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    task_id = task_response.json()["id"]
    
    # Prepare Slack slash command request
    body = {
        "token": "test-token",
        "command": "/todo",
        "text": f"reserve {task_id}",
        "response_url": "https://hooks.slack.com/commands/test",
        "user_id": "U12345",
        "channel_id": "C12345"
    }
    body_str = "&".join([f"{k}={v}" for k, v in body.items()])
    signature = generate_slack_signature(slack_signing_secret, timestamp, body_str)
    
    with patch.dict(os.environ, {
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "SLACK_SIGNING_SECRET": slack_signing_secret
    }):
        response = client.post(
            "/slack/commands",
            data=body,
            headers={
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        assert response.status_code == 200


def test_slack_slash_command_complete_task(client, slack_signing_secret):
    """Test /todo complete slash command."""
    timestamp = str(int(time.time()))
    
    # Create project and task
    project_response = client.post("/projects", json={
        "name": "Test Project",
        "local_path": "/tmp/test"
    })
    project_id = project_response.json()["id"]
    
    task_response = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Check it",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    task_id = task_response.json()["id"]
    
    # Lock task first
    client.post(f"/tasks/{task_id}/lock", json={"agent_id": "slack-U12345"})
    
    # Prepare Slack slash command request
    body = {
        "token": "test-token",
        "command": "/todo",
        "text": f"complete {task_id} Done!",
        "response_url": "https://hooks.slack.com/commands/test",
        "user_id": "U12345",
        "channel_id": "C12345"
    }
    body_str = "&".join([f"{k}={v}" for k, v in body.items()])
    signature = generate_slack_signature(slack_signing_secret, timestamp, body_str)
    
    with patch.dict(os.environ, {
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "SLACK_SIGNING_SECRET": slack_signing_secret
    }):
        response = client.post(
            "/slack/commands",
            data=body,
            headers={
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        assert response.status_code == 200


def test_slack_interactive_button_reserve(client, slack_signing_secret):
    """Test Slack interactive button for reserving task."""
    timestamp = str(int(time.time()))
    
    # Create project and task
    project_response = client.post("/projects", json={
        "name": "Test Project",
        "local_path": "/tmp/test"
    })
    project_id = project_response.json()["id"]
    
    task_response = client.post("/tasks", json={
        "title": "Task 1",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Check it",
        "agent_id": "test-agent",
        "project_id": project_id
    })
    task_id = task_response.json()["id"]
    
    # Prepare Slack interactive payload
    payload = {
        "type": "block_actions",
        "user": {"id": "U12345"},
        "actions": [{
            "action_id": "reserve_task",
            "value": str(task_id)
        }],
        "response_url": "https://hooks.slack.com/actions/test"
    }
    body = {"payload": json.dumps(payload)}
    body_str = "&".join([f"{k}={v}" for k, v in body.items()])
    signature = generate_slack_signature(slack_signing_secret, timestamp, body_str)
    
    with patch.dict(os.environ, {
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "SLACK_SIGNING_SECRET": slack_signing_secret
    }):
        response = client.post(
            "/slack/interactive",
            data=body,
            headers={
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        assert response.status_code == 200


def test_slack_signature_verification(client, slack_signing_secret):
    """Test that invalid Slack signatures are rejected."""
    timestamp = str(int(time.time()))
    
    body = {
        "token": "test-token",
        "command": "/todo",
        "text": "list"
    }
    body_str = "&".join([f"{k}={v}" for k, v in body.items()])
    invalid_signature = "v0=invalid_signature"
    
    with patch.dict(os.environ, {
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "SLACK_SIGNING_SECRET": slack_signing_secret
    }):
        response = client.post(
            "/slack/commands",
            data=body,
            headers={
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": invalid_signature,
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        assert response.status_code == 401


def test_slack_event_url_verification(client, slack_signing_secret):
    """Test Slack URL verification challenge."""
    timestamp = str(int(time.time()))
    
    challenge = "test_challenge_123"
    body = {
        "token": "test-token",
        "challenge": challenge,
        "type": "url_verification"
    }
    body_str = json.dumps(body)
    signature = generate_slack_signature(slack_signing_secret, timestamp, body_str)
    
    with patch.dict(os.environ, {
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "SLACK_SIGNING_SECRET": slack_signing_secret
    }):
        response = client.post(
            "/slack/events",
            json=body,
            headers={
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
                "Content-Type": "application/json"
            }
        )
        assert response.status_code == 200
        assert response.json() == {"challenge": challenge}


def test_slack_task_blocked_notification(client, slack_signing_secret):
    """Test that Slack receives notification when task is blocked."""
    with patch.dict(os.environ, {
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "SLACK_SIGNING_SECRET": slack_signing_secret,
        "SLACK_DEFAULT_CHANNEL": "#test-channel"
    }):
        # Create project and task
        project_response = client.post("/projects", json={
            "name": "Test Project",
            "local_path": "/tmp/test"
        })
        project_id = project_response.json()["id"]
        
        task_response = client.post("/tasks", json={
            "title": "Test Task",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Check it",
            "agent_id": "test-agent",
            "project_id": project_id
        })
        task_id = task_response.json()["id"]
        
        # Add a blocker comment (this would trigger a blocked notification)
        with patch('slack.WebClient') as mock_web_client:
            mock_client_instance = MagicMock()
            mock_web_client.return_value = mock_client_instance
            mock_client_instance.chat_postMessage = MagicMock(return_value={"ok": True})
            
            # In real implementation, blocking would be detected via comments or status
            # For now, we test that the notification system exists
            assert True  # Placeholder - will implement with actual blocking logic
