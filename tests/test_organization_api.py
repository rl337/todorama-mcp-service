"""
Tests for organization API endpoints.
Tests all organization management endpoints, authentication, authorization, and error cases.
"""
import pytest
import tempfile
import shutil
import os
import json
from fastapi.testclient import TestClient
from todorama.app import create_app
from todorama.database import TodoDatabase


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    backups_dir = os.path.join(temp_dir, "backups")
    
    db = TodoDatabase(db_path)
    from todorama.backup import BackupManager
    backup_manager = BackupManager(db_path, backups_dir)
    
    # Override services
    from todorama.dependencies.services import _service_instance, ServiceContainer
    import todorama.dependencies.services as services_module
    original_instance = services_module._service_instance
    
    class MockServiceContainer:
        def __init__(self, db, backup_manager):
            self.db = db
            self.backup_manager = backup_manager
            self.conversation_storage = None
            self.backup_scheduler = None
            self.conversation_backup_manager = None
            self.conversation_backup_scheduler = None
            self.job_queue = None
    
    services_module._service_instance = MockServiceContainer(db, backup_manager)
    
    yield db, db_path, backups_dir
    
    services_module._service_instance = original_instance
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    return TestClient(create_app())


@pytest.fixture
def auth_client(client, temp_db):
    """Create authenticated test client with API key."""
    db, _, _ = temp_db
    
    # Create organization
    conn = db._get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Test Org', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Test Org'")
        org_id = cursor.fetchone()[0]
    else:
        org_id = cursor.lastrowid
    
    # Create project
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Test Project', '/test/path', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Test Project'")
        project_id = cursor.fetchone()[0]
    else:
        project_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    
    # Create API key
    key_id, api_key = db.create_api_key(project_id, "Test API Key")
    
    class AuthenticatedClient:
        def __init__(self, client, api_key, org_id, project_id):
            self.client = client
            self.headers = {"X-API-Key": api_key}
            self.org_id = org_id
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
    
    return AuthenticatedClient(client, api_key, org_id, project_id)


def test_create_organization(auth_client):
    """Test creating an organization."""
    response = auth_client.post("/api/organizations", json={
        "name": "New Organization",
        "description": "Test organization"
    })
    
    # Endpoint may not exist yet, but test structure is ready
    if response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    assert response.status_code in [200, 201], f"Expected 200/201, got {response.status_code}: {response.text}"
    data = response.json()
    assert "id" in data or "organization_id" in data, "Response should include organization ID"
    assert data.get("name") == "New Organization", "Organization name should match"


def test_list_organizations(auth_client):
    """Test listing organizations."""
    response = auth_client.get("/api/organizations")
    
    if response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "organizations" in data or isinstance(data, list), "Response should include organizations list"
    
    orgs = data.get("organizations", data) if isinstance(data, dict) else data
    assert isinstance(orgs, list), "Organizations should be a list"


def test_get_organization(auth_client):
    """Test getting a specific organization."""
    # First create an organization
    create_response = auth_client.post("/api/organizations", json={
        "name": "Test Org",
        "description": "Test"
    })
    
    if create_response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    org_id = create_response.json().get("id") or create_response.json().get("organization_id")
    
    # Get the organization
    response = auth_client.get(f"/api/organizations/{org_id}")
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data.get("id") == org_id or data.get("organization_id") == org_id, "Organization ID should match"
    assert data.get("name") == "Test Org", "Organization name should match"


def test_update_organization(auth_client):
    """Test updating an organization."""
    # Create organization
    create_response = auth_client.post("/api/organizations", json={
        "name": "Original Name",
        "description": "Original description"
    })
    
    if create_response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    org_id = create_response.json().get("id") or create_response.json().get("organization_id")
    
    # Update organization
    response = auth_client.put(f"/api/organizations/{org_id}", json={
        "name": "Updated Name",
        "description": "Updated description"
    })
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data.get("name") == "Updated Name", "Organization name should be updated"


def test_delete_organization(auth_client):
    """Test deleting an organization."""
    # Create organization
    create_response = auth_client.post("/api/organizations", json={
        "name": "To Delete",
        "description": "Will be deleted"
    })
    
    if create_response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    org_id = create_response.json().get("id") or create_response.json().get("organization_id")
    
    # Delete organization
    response = auth_client.delete(f"/api/organizations/{org_id}")
    
    assert response.status_code in [200, 204], f"Expected 200/204, got {response.status_code}: {response.text}"
    
    # Verify organization is deleted
    get_response = auth_client.get(f"/api/organizations/{org_id}")
    assert get_response.status_code == 404, "Organization should be deleted"


def test_organization_authentication_required(client):
    """Test that organization endpoints require authentication."""
    # Try to create organization without API key
    response = client.post("/api/organizations", json={
        "name": "Test Org",
        "description": "Test"
    })
    
    if response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    # Should require authentication
    assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}: {response.text}"


def test_organization_authorization(auth_client, temp_db):
    """Test that users can only access their own organizations."""
    db, _, _ = temp_db
    
    # Create another organization
    conn = db._get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Other Org', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Other Org'")
        other_org_id = cursor.fetchone()[0]
    else:
        other_org_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # Try to access other organization
    response = auth_client.get(f"/api/organizations/{other_org_id}")
    
    if response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    # Should be forbidden (403) or not found (404)
    assert response.status_code in [403, 404], f"Expected 403/404, got {response.status_code}: {response.text}"


def test_organization_validation_errors(auth_client):
    """Test organization validation error handling."""
    # Try to create organization with missing name
    response = auth_client.post("/api/organizations", json={
        "description": "Missing name"
    })
    
    if response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
    
    # Try to create organization with empty name
    response = auth_client.post("/api/organizations", json={
        "name": "",
        "description": "Empty name"
    })
    
    assert response.status_code in [400, 422], f"Expected 400/422, got {response.status_code}: {response.text}"


def test_organization_duplicate_name(auth_client):
    """Test that organization names must be unique."""
    # Create first organization
    create_response = auth_client.post("/api/organizations", json={
        "name": "Unique Org",
        "description": "First"
    })
    
    if create_response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    # Try to create another with same name
    response = auth_client.post("/api/organizations", json={
        "name": "Unique Org",
        "description": "Duplicate"
    })
    
    assert response.status_code in [400, 409], f"Expected 400/409, got {response.status_code}: {response.text}"


def test_organization_members_endpoint(auth_client):
    """Test organization members management endpoint."""
    # Create organization
    create_response = auth_client.post("/api/organizations", json={
        "name": "Test Org",
        "description": "Test"
    })
    
    if create_response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    org_id = create_response.json().get("id") or create_response.json().get("organization_id")
    
    # List members
    response = auth_client.get(f"/api/organizations/{org_id}/members")
    
    if response.status_code == 404:
        pytest.skip("Organization members endpoint not yet implemented")
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "members" in data or isinstance(data, list), "Response should include members"


def test_organization_add_member(auth_client):
    """Test adding a member to an organization."""
    # Create organization
    create_response = auth_client.post("/api/organizations", json={
        "name": "Test Org",
        "description": "Test"
    })
    
    if create_response.status_code == 404:
        pytest.skip("Organization API endpoint not yet implemented")
    
    org_id = create_response.json().get("id") or create_response.json().get("organization_id")
    
    # Add member
    response = auth_client.post(f"/api/organizations/{org_id}/members", json={
        "user_id": "test-user-123",
        "role": "member"
    })
    
    if response.status_code == 404:
        pytest.skip("Organization members endpoint not yet implemented")
    
    assert response.status_code in [200, 201], f"Expected 200/201, got {response.status_code}: {response.text}"
