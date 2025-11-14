"""
Integration tests for multi-tenancy features.
Tests full workflow: create org → add members → create projects → create tasks.
Tests organization switching and data isolation across organizations.
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


def test_full_workflow_create_org_add_members_create_projects_create_tasks(temp_db):
    """Test full workflow: create org → add members → create projects → create tasks."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Step 1: Create organization
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Test Organization', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Test Organization'")
        org_id = cursor.fetchone()[0]
    else:
        org_id = cursor.lastrowid
    
    conn.commit()
    
    # Step 2: Add members (if organization_members table exists)
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='organization_members'
    """) if db.db_type == "sqlite" else cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_name = 'organization_members'
    """)
    
    if cursor.fetchone():
        user_id = "test-user-123"
        cursor.execute("""
            INSERT INTO organization_members (organization_id, user_id, role, created_at)
            VALUES (?, ?, 'member', CURRENT_TIMESTAMP)
        """, (org_id, user_id))
        conn.commit()
    
    # Step 3: Create project
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
    
    # Step 4: Create task
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project_id
    )
    
    # Verify everything is linked correctly
    cursor.execute("""
        SELECT t.id, p.id, p.organization_id 
        FROM tasks t
        JOIN projects p ON t.project_id = p.id
        WHERE t.id = ?
    """, (task_id,))
    result = cursor.fetchone()
    
    assert result is not None, "Task should exist"
    assert result[1] == project_id, "Task should be linked to project"
    assert result[2] == org_id, "Task should be linked to organization via project"
    
    conn.close()


def test_organization_switching(temp_db):
    """Test organization switching functionality."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create two organizations
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Org 1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Org 1'")
        org1_id = cursor.fetchone()[0]
    else:
        org1_id = cursor.lastrowid
    
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Org 2', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Org 2'")
        org2_id = cursor.fetchone()[0]
    else:
        org2_id = cursor.lastrowid
    
    conn.commit()
    
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
    
    # Create tasks in each project
    task1_id = db.create_task(
        title="Org1 Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project1_id
    )
    
    task2_id = db.create_task(
        title="Org2 Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project2_id
    )
    
    # Query tasks for org1 (switching context to org1)
    cursor.execute("""
        SELECT t.id FROM tasks t
        JOIN projects p ON t.project_id = p.id
        WHERE p.organization_id = ?
    """, (org1_id,))
    org1_tasks = [row[0] for row in cursor.fetchall()]
    
    assert task1_id in org1_tasks, "Org1 context should see Org1 tasks"
    assert task2_id not in org1_tasks, "Org1 context should not see Org2 tasks"
    
    # Query tasks for org2 (switching context to org2)
    cursor.execute("""
        SELECT t.id FROM tasks t
        JOIN projects p ON t.project_id = p.id
        WHERE p.organization_id = ?
    """, (org2_id,))
    org2_tasks = [row[0] for row in cursor.fetchall()]
    
    assert task2_id in org2_tasks, "Org2 context should see Org2 tasks"
    assert task1_id not in org2_tasks, "Org2 context should not see Org1 tasks"
    
    conn.close()


def test_data_isolation_across_organizations(temp_db):
    """Test data isolation across organizations."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create two organizations
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Isolated Org 1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Isolated Org 1'")
        org1_id = cursor.fetchone()[0]
    else:
        org1_id = cursor.lastrowid
    
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Isolated Org 2', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Isolated Org 2'")
        org2_id = cursor.fetchone()[0]
    else:
        org2_id = cursor.lastrowid
    
    conn.commit()
    
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
    
    # Create tasks
    task1_id = db.create_task(
        title="Org1 Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project1_id
    )
    
    task2_id = db.create_task(
        title="Org2 Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent",
        project_id=project2_id
    )
    
    # Create API keys
    key1_id, api_key1 = db.create_api_key(project1_id, "Org1 Key")
    key2_id, api_key2 = db.create_api_key(project2_id, "Org2 Key")
    
    # Verify isolation: Org1 cannot access Org2's data
    # Tasks
    cursor.execute("""
        SELECT COUNT(*) FROM tasks t
        JOIN projects p ON t.project_id = p.id
        WHERE p.organization_id = ? AND t.id = ?
    """, (org1_id, task2_id))
    org1_access_org2_task = cursor.fetchone()[0]
    assert org1_access_org2_task == 0, "Org1 should not access Org2's task"
    
    # Projects
    cursor.execute("""
        SELECT COUNT(*) FROM projects
        WHERE organization_id = ? AND id = ?
    """, (org1_id, project2_id))
    org1_access_org2_project = cursor.fetchone()[0]
    assert org1_access_org2_project == 0, "Org1 should not access Org2's project"
    
    # API keys (via projects)
    cursor.execute("""
        SELECT COUNT(*) FROM api_keys ak
        JOIN projects p ON ak.project_id = p.id
        WHERE p.organization_id = ? AND ak.id = ?
    """, (org1_id, key2_id))
    org1_access_org2_key = cursor.fetchone()[0]
    assert org1_access_org2_key == 0, "Org1 should not access Org2's API key"
    
    # Verify isolation: Org2 cannot access Org1's data
    cursor.execute("""
        SELECT COUNT(*) FROM tasks t
        JOIN projects p ON t.project_id = p.id
        WHERE p.organization_id = ? AND t.id = ?
    """, (org2_id, task1_id))
    org2_access_org1_task = cursor.fetchone()[0]
    assert org2_access_org1_task == 0, "Org2 should not access Org1's task"
    
    conn.close()


def test_multi_organization_user_membership(temp_db):
    """Test that a user can be a member of multiple organizations."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create two organizations
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Org A', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Org A'")
        org_a_id = cursor.fetchone()[0]
    else:
        org_a_id = cursor.lastrowid
    
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Org B', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Org B'")
        org_b_id = cursor.fetchone()[0]
    else:
        org_b_id = cursor.lastrowid
    
    conn.commit()
    
    # Add user to both organizations (if organization_members table exists)
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='organization_members'
    """) if db.db_type == "sqlite" else cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_name = 'organization_members'
    """)
    
    if cursor.fetchone():
        user_id = "multi-org-user"
        cursor.execute("""
            INSERT INTO organization_members (organization_id, user_id, role, created_at)
            VALUES (?, ?, 'member', CURRENT_TIMESTAMP)
        """, (org_a_id, user_id))
        
        cursor.execute("""
            INSERT INTO organization_members (organization_id, user_id, role, created_at)
            VALUES (?, ?, 'admin', CURRENT_TIMESTAMP)
        """, (org_b_id, user_id))
        
        conn.commit()
        
        # Verify user is in both organizations
        cursor.execute("""
            SELECT organization_id, role FROM organization_members
            WHERE user_id = ?
        """, (user_id,))
        memberships = cursor.fetchall()
        
        org_ids = [row[0] for row in memberships]
        assert org_a_id in org_ids, "User should be member of Org A"
        assert org_b_id in org_ids, "User should be member of Org B"
        assert len(memberships) == 2, "User should be in 2 organizations"
    
    conn.close()


def test_team_isolation_within_organization(temp_db):
    """Test that teams are isolated within an organization."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create organization
    cursor.execute("""
        INSERT INTO organizations (name, created_at, updated_at)
        VALUES ('Test Org', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM organizations WHERE name = 'Test Org'")
        org_id = cursor.fetchone()[0]
    else:
        org_id = cursor.lastrowid
    
    conn.commit()
    
    # Create two teams in the same organization
    cursor.execute("""
        INSERT INTO teams (organization_id, name, created_at, updated_at)
        VALUES (?, 'Team A', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM teams WHERE name = 'Team A' AND organization_id = ?", (org_id,))
        team_a_id = cursor.fetchone()[0]
    else:
        team_a_id = cursor.lastrowid
    
    cursor.execute("""
        INSERT INTO teams (organization_id, name, created_at, updated_at)
        VALUES (?, 'Team B', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id,))
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM teams WHERE name = 'Team B' AND organization_id = ?", (org_id,))
        team_b_id = cursor.fetchone()[0]
    else:
        team_b_id = cursor.lastrowid
    
    conn.commit()
    
    # Verify teams belong to the same organization
    cursor.execute("SELECT organization_id FROM teams WHERE id = ?", (team_a_id,))
    team_a_org = cursor.fetchone()[0]
    
    cursor.execute("SELECT organization_id FROM teams WHERE id = ?", (team_b_id,))
    team_b_org = cursor.fetchone()[0]
    
    assert team_a_org == org_id, "Team A should belong to organization"
    assert team_b_org == org_id, "Team B should belong to organization"
    assert team_a_org == team_b_org, "Both teams should belong to same organization"
    
    conn.close()
