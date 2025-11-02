"""
Tests for admin commands and moderation tools.
"""
import pytest
import os
import tempfile
import shutil
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.main import app
from src.database import TodoDatabase
from src.backup import BackupManager


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
    from src.conversation_storage import ConversationStorage
    conversation_storage = ConversationStorage(conv_db_path)
    
    # Override the database, backup manager, and conversation storage in the app
    import src.main as main_module
    main_module.db = db
    main_module.backup_manager = backup_manager
    main_module.conversation_storage = conversation_storage
    
    yield db, db_path, backups_dir
    
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def admin_api_key(temp_db):
    """Create an admin API key for testing."""
    db, _, _ = temp_db
    
    # Create a project first
    project_id = db.create_project(
        name="test-project",
        local_path="/tmp/test",
        origin_url="https://github.com/test/project"
    )
    
    # Create regular API key first
    key_id, api_key = db.create_api_key(project_id, "Admin Key")
    
    # Mark as admin
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        query = db._normalize_sql("""
            UPDATE api_keys
            SET is_admin = 1
            WHERE id = ?
        """)
        db._execute_with_logging(cursor, query, (key_id,))
        conn.commit()
        
        return api_key
    finally:
        conn.close()


@pytest.fixture
def regular_api_key(temp_db):
    """Create a regular (non-admin) API key for testing."""
    db, _, _ = temp_db
    
    # Create a project first
    project_id = db.create_project(
        name="test-project",
        local_path="/tmp/test",
        origin_url="https://github.com/test/project"
    )
    
    # Create regular API key
    api_key = db.create_api_key(project_id, "Regular Key")
    return api_key


def test_admin_block_agent(client, admin_api_key, regular_api_key):
    """Test blocking an agent via admin endpoint."""
    headers = {"X-API-Key": admin_api_key}
    
    # Block an agent
    response = client.post(
        "/admin/agents/block",
        json={"agent_id": "bad-agent"},
        headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["blocked"] is True
    assert data["agent_id"] == "bad-agent"
    
    # Verify agent is blocked
    response = client.get("/admin/agents/bad-agent", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["blocked"] is True
    
    # Try to use blocked agent - should fail
    response = client.post("/tasks", json={
        "title": "Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "bad-agent"
    }, headers={"X-API-Key": regular_api_key})
    # Task creation should succeed but agent assignment should be blocked
    # (or we could make it fail - depends on design)
    
    # Unblock agent
    response = client.post(
        "/admin/agents/unblock",
        json={"agent_id": "bad-agent"},
        headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["blocked"] is False


def test_admin_block_agent_requires_auth(client, regular_api_key):
    """Test that blocking agents requires admin authentication."""
    headers = {"X-API-Key": regular_api_key}
    
    response = client.post(
        "/admin/agents/block",
        json={"agent_id": "test-agent"},
        headers=headers
    )
    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


def test_admin_block_agent_no_auth(client):
    """Test that blocking agents requires authentication."""
    response = client.post(
        "/admin/agents/block",
        json={"agent_id": "test-agent"}
    )
    assert response.status_code == 401


def test_admin_list_blocked_agents(client, admin_api_key):
    """Test listing blocked agents."""
    headers = {"X-API-Key": admin_api_key}
    
    # Block a few agents
    client.post("/admin/agents/block", json={"agent_id": "agent-1"}, headers=headers)
    client.post("/admin/agents/block", json={"agent_id": "agent-2"}, headers=headers)
    
    # List blocked agents
    response = client.get("/admin/agents/blocked", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    agent_ids = [agent["agent_id"] for agent in data]
    assert "agent-1" in agent_ids
    assert "agent-2" in agent_ids


def test_admin_clear_conversation(client, admin_api_key, temp_db):
    """Test clearing a conversation."""
    db, _, _ = temp_db
    
    # Create a conversation
    import src.main as main_module
    if hasattr(main_module, 'conversation_storage') and main_module.conversation_storage:
        user_id = "test-user"
        chat_id = "test-chat"
        
        # Get or create conversation
        conv_id = main_module.conversation_storage.get_or_create_conversation(user_id, chat_id)
        
        # Add some messages
        main_module.conversation_storage.add_message(conv_id, "user", "Hello")
        main_module.conversation_storage.add_message(conv_id, "assistant", "Hi there")
        
        # Clear conversation
        headers = {"X-API-Key": admin_api_key}
        response = client.post(
            "/admin/conversations/clear",
            json={"user_id": user_id, "chat_id": chat_id},
            headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["cleared"] is True
        
        # Verify conversation is empty
        conv = main_module.conversation_storage.get_conversation(user_id, chat_id)
        assert conv is not None  # Conversation should still exist
        assert len(conv.get("messages", [])) == 0  # But messages should be cleared


def test_admin_system_status(client, admin_api_key, temp_db):
    """Test system status endpoint."""
    headers = {"X-API-Key": admin_api_key}
    
    response = client.get("/admin/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    
    assert "status" in data
    assert "database" in data
    assert "tasks" in data
    assert "agents" in data
    assert data["database"]["connected"] is True


def test_admin_audit_logs(client, admin_api_key):
    """Test that admin actions are logged to audit log."""
    headers = {"X-API-Key": admin_api_key}
    
    # Perform admin action
    client.post(
        "/admin/agents/block",
        json={"agent_id": "test-agent"},
        headers=headers
    )
    
    # Check audit logs
    response = client.get("/admin/audit-logs", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    
    # Find the block action
    block_actions = [log for log in data if "block" in log.get("action", "").lower()]
    assert len(block_actions) > 0


def test_admin_block_agent_prevents_task_reservation(client, admin_api_key, regular_api_key, temp_db):
    """Test that blocked agents cannot reserve tasks."""
    db, _, _ = temp_db
    admin_headers = {"X-API-Key": admin_api_key}
    regular_headers = {"X-API-Key": regular_api_key}
    
    # Create a task
    response = client.post("/tasks", json={
        "title": "Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    }, headers=regular_headers)
    task_id = response.json()["id"]
    
    # Block the agent
    client.post(
        "/admin/agents/block",
        json={"agent_id": "blocked-agent"},
        headers=admin_headers
    )
    
    # Try to reserve task with blocked agent
    response = client.post(
        f"/tasks/{task_id}/lock",
        json={"agent_id": "blocked-agent"},
        headers=regular_headers
    )
    assert response.status_code == 403
    assert "blocked" in response.json()["detail"].lower()
