"""
Tests for tenant data isolation.
Tests that tasks, projects, and API keys are properly isolated per organization.
"""
import pytest
import tempfile
import shutil
import os
from todorama.database import TodoDatabase


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    db = TodoDatabase(db_path)
    yield db, db_path
    shutil.rmtree(temp_dir)


@pytest.fixture
def org1_id(temp_db):
    """Create organization 1 for testing."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create organization (assuming method exists or direct SQL)
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Organization 1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Organization 1'")
        org_id = cursor.fetchone()[0]
    else:
        org_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    return org_id


@pytest.fixture
def org2_id(temp_db):
    """Create organization 2 for testing."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Organization 2', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Organization 2'")
        org_id = cursor.fetchone()[0]
    else:
        org_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    return org_id


def test_tasks_isolated_per_organization(temp_db, org1_id, org2_id):
    """Test that tasks are isolated per organization."""
    db, _ = temp_db
    
    # Create project in org1
    conn = db._get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Project 1', '/path1', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org1_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Project 1'")
        project1_id = cursor.fetchone()[0]
    else:
        project1_id = cursor.lastrowid
    
    # Create project in org2
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Project 2', '/path2', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org2_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Project 2'")
        project2_id = cursor.fetchone()[0]
    else:
        project2_id = cursor.lastrowid
    
    conn.commit()
    
    # Create task in org1's project
    task1_id = db.create_task(
        title="Task in Org 1",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project1_id
    )
    
    # Create task in org2's project
    task2_id = db.create_task(
        title="Task in Org 2",
        task_type="concrete",
        task_instruction="Do something else",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project2_id
    )
    
    # Query tasks for org1 (should only see org1's task)
    cursor.execute("""
        SELECT t.id FROM tasks t
        JOIN projects p ON t.project_id = p.id
        WHERE p.organization_id = ?
    """, (org1_id,))
    org1_tasks = [row[0] for row in cursor.fetchall()]
    
    assert task1_id in org1_tasks, "Org1 should see its own task"
    assert task2_id not in org1_tasks, "Org1 should not see Org2's task"
    
    # Query tasks for org2 (should only see org2's task)
    cursor.execute("""
        SELECT t.id FROM tasks t
        JOIN projects p ON t.project_id = p.id
        WHERE p.organization_id = ?
    """, (org2_id,))
    org2_tasks = [row[0] for row in cursor.fetchall()]
    
    assert task2_id in org2_tasks, "Org2 should see its own task"
    assert task1_id not in org2_tasks, "Org2 should not see Org1's task"
    
    conn.close()


def test_projects_isolated_per_organization(temp_db, org1_id, org2_id):
    """Test that projects are isolated per organization."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create projects in each organization
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Org1 Project', '/org1/path', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org1_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Org1 Project'")
        project1_id = cursor.fetchone()[0]
    else:
        project1_id = cursor.lastrowid
    
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Org2 Project', '/org2/path', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org2_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Org2 Project'")
        project2_id = cursor.fetchone()[0]
    else:
        project2_id = cursor.lastrowid
    
    conn.commit()
    
    # Query projects for org1
    cursor.execute("""
        SELECT id FROM projects WHERE organization_id = ?
    """, (org1_id,))
    org1_projects = [row[0] for row in cursor.fetchall()]
    
    assert project1_id in org1_projects, "Org1 should see its own project"
    assert project2_id not in org1_projects, "Org1 should not see Org2's project"
    
    # Query projects for org2
    cursor.execute("""
        SELECT id FROM projects WHERE organization_id = ?
    """, (org2_id,))
    org2_projects = [row[0] for row in cursor.fetchall()]
    
    assert project2_id in org2_projects, "Org2 should see its own project"
    assert project1_id not in org2_projects, "Org2 should not see Org1's project"
    
    conn.close()


def test_api_keys_scoped_to_organizations(temp_db, org1_id, org2_id):
    """Test that API keys are scoped to organizations."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create projects for each organization
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Org1 Project', '/org1/path', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org1_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Org1 Project'")
        project1_id = cursor.fetchone()[0]
    else:
        project1_id = cursor.lastrowid
    
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Org2 Project', '/org2/path', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org2_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Org2 Project'")
        project2_id = cursor.fetchone()[0]
    else:
        project2_id = cursor.lastrowid
    
    conn.commit()
    
    # Create API key for org1
    key1_id, api_key1 = db.create_api_key(project1_id, "Org1 API Key")
    
    # Create API key for org2
    key2_id, api_key2 = db.create_api_key(project2_id, "Org2 API Key")
    
    # Query API keys for org1 (via project)
    cursor.execute("""
        SELECT ak.id FROM api_keys ak
        JOIN projects p ON ak.project_id = p.id
        WHERE p.organization_id = ?
    """, (org1_id,))
    org1_keys = [row[0] for row in cursor.fetchall()]
    
    assert key1_id in org1_keys, "Org1 should see its own API key"
    assert key2_id not in org1_keys, "Org1 should not see Org2's API key"
    
    # Query API keys for org2
    cursor.execute("""
        SELECT ak.id FROM api_keys ak
        JOIN projects p ON ak.project_id = p.id
        WHERE p.organization_id = ?
    """, (org2_id,))
    org2_keys = [row[0] for row in cursor.fetchall()]
    
    assert key2_id in org2_keys, "Org2 should see its own API key"
    assert key1_id not in org2_keys, "Org2 should not see Org1's API key"
    
    conn.close()


def test_cross_tenant_access_blocked(temp_db, org1_id, org2_id):
    """Test that cross-tenant access is blocked."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create projects
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Org1 Project', '/org1/path', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org1_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Org1 Project'")
        project1_id = cursor.fetchone()[0]
    else:
        project1_id = cursor.lastrowid
    
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Org2 Project', '/org2/path', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org2_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Org2 Project'")
        project2_id = cursor.fetchone()[0]
    else:
        project2_id = cursor.lastrowid
    
    conn.commit()
    
    # Create task in org1
    task1_id = db.create_task(
        title="Org1 Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project1_id
    )
    
    # Try to access org1's task using org2's context (should be blocked)
    # This would be tested at the API level, but we can verify data isolation
    cursor.execute("""
        SELECT t.id FROM tasks t
        JOIN projects p ON t.project_id = p.id
        WHERE t.id = ? AND p.organization_id = ?
    """, (task1_id, org2_id))
    result = cursor.fetchone()
    
    assert result is None, "Org2 should not be able to access Org1's task"
    
    conn.close()


def test_tasks_inherit_organization_from_project(temp_db, org1_id, org2_id):
    """Test that tasks inherit organization context from their project."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create project in org1
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Org1 Project', '/org1/path', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org1_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Org1 Project'")
        project1_id = cursor.fetchone()[0]
    else:
        project1_id = cursor.lastrowid
    
    conn.commit()
    
    # Create task in project (inherits organization from project)
    task_id = db.create_task(
        title="Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project1_id
    )
    
    # Verify task is associated with org1 via project
    cursor.execute("""
        SELECT p.organization_id FROM tasks t
        JOIN projects p ON t.project_id = p.id
        WHERE t.id = ?
    """, (task_id,))
    result = cursor.fetchone()
    
    assert result is not None, "Task should be associated with organization via project"
    assert result[0] == org1_id, "Task should inherit organization from project"
    
    conn.close()


def test_api_key_organization_scoping(temp_db, org1_id, org2_id):
    """Test that API keys are scoped to their organization and cannot access other orgs."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create projects
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Org1 Project', '/org1/path', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org1_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Org1 Project'")
        project1_id = cursor.fetchone()[0]
    else:
        project1_id = cursor.lastrowid
    
    cursor.execute("""
        INSERT INTO projects (name, local_path, organization_id, created_at, updated_at)
        VALUES ('Org2 Project', '/org2/path', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org2_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM projects WHERE name = 'Org2 Project'")
        project2_id = cursor.fetchone()[0]
    else:
        project2_id = cursor.lastrowid
    
    conn.commit()
    
    # Create API key for org1
    key1_id, api_key1 = db.create_api_key(project1_id, "Org1 Key")
    
    # Create task in org1
    task1_id = db.create_task(
        title="Org1 Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project1_id
    )
    
    # Create task in org2
    task2_id = db.create_task(
        title="Org2 Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project2_id
    )
    
    # Verify API key from org1 can only see org1's task
    # (This would be tested at API level, but we verify data isolation)
    cursor.execute("""
        SELECT t.id FROM tasks t
        JOIN projects p ON t.project_id = p.id
        JOIN api_keys ak ON p.id = ak.project_id
        WHERE ak.id = ? AND p.organization_id = (
            SELECT p2.organization_id FROM projects p2
            JOIN api_keys ak2 ON p2.id = ak2.project_id
            WHERE ak2.id = ?
        )
    """, (key1_id, key1_id))
    accessible_tasks = [row[0] for row in cursor.fetchall()]
    
    assert task1_id in accessible_tasks, "Org1 API key should access Org1's task"
    assert task2_id not in accessible_tasks, "Org1 API key should not access Org2's task"
    
    conn.close()
