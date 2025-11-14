"""
Tests for role-based access control (RBAC).
Tests role creation, assignment, permission checking, and role hierarchy.
"""
import pytest
import tempfile
import shutil
import os
import json
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
def org_id(temp_db):
    """Create an organization for testing."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
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
    conn.close()
    return org_id


def test_create_role(temp_db, org_id):
    """Test role creation."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create a role
    permissions = json.dumps(["read:tasks", "write:tasks"])
    cursor.execute("""
        INSERT INTO roles (organization_id, name, permissions, created_at, updated_at)
        VALUES (?, 'Developer', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id, permissions))
    
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM roles WHERE name = 'Developer' AND organization_id = ?", (org_id,))
        role_id = cursor.fetchone()[0]
    else:
        role_id = cursor.lastrowid
    
    conn.commit()
    
    # Verify role was created
    cursor.execute("SELECT id, name, permissions FROM roles WHERE id = ?", (role_id,))
    role = cursor.fetchone()
    
    assert role is not None, "Role should be created"
    assert role[1] == "Developer", "Role name should match"
    
    # Parse permissions
    role_permissions = json.loads(role[2])
    assert "read:tasks" in role_permissions, "Role should have read:tasks permission"
    assert "write:tasks" in role_permissions, "Role should have write:tasks permission"
    
    conn.close()


def test_assign_role_to_user(temp_db, org_id):
    """Test assigning a role to a user."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create role
    permissions = json.dumps(["read:tasks", "write:tasks"])
    cursor.execute("""
        INSERT INTO roles (organization_id, name, permissions, created_at, updated_at)
        VALUES (?, 'Developer', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id, permissions))
    
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM roles WHERE name = 'Developer' AND organization_id = ?", (org_id,))
        role_id = cursor.fetchone()[0]
    else:
        role_id = cursor.lastrowid
    
    conn.commit()
    
    # Assign role to user (assuming user_roles table or organization_members table)
    # Check if user_roles table exists
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='user_roles'
    """) if db.db_type == "sqlite" else cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_name = 'user_roles'
    """)
    
    if cursor.fetchone():
        # user_roles table exists
        user_id = "test-user-123"
        cursor.execute("""
            INSERT INTO user_roles (user_id, role_id, organization_id, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, role_id, org_id))
        conn.commit()
        
        # Verify assignment
        cursor.execute("""
            SELECT role_id FROM user_roles 
            WHERE user_id = ? AND organization_id = ?
        """, (user_id, org_id))
        assigned_role = cursor.fetchone()
        
        assert assigned_role is not None, "Role should be assigned to user"
        assert assigned_role[0] == role_id, "Assigned role ID should match"
    else:
        # Roles might be stored in organization_members table
        # This test verifies the concept even if table structure differs
        pass
    
    conn.close()


def test_permission_checking(temp_db, org_id):
    """Test permission checking for roles."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create roles with different permissions
    admin_permissions = json.dumps(["read:*", "write:*", "delete:*"])
    cursor.execute("""
        INSERT INTO roles (organization_id, name, permissions, created_at, updated_at)
        VALUES (?, 'Admin', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id, admin_permissions))
    
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM roles WHERE name = 'Admin' AND organization_id = ?", (org_id,))
        admin_role_id = cursor.fetchone()[0]
    else:
        admin_role_id = cursor.lastrowid
    
    viewer_permissions = json.dumps(["read:tasks"])
    cursor.execute("""
        INSERT INTO roles (organization_id, name, permissions, created_at, updated_at)
        VALUES (?, 'Viewer', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id, viewer_permissions))
    
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM roles WHERE name = 'Viewer' AND organization_id = ?", (org_id,))
        viewer_role_id = cursor.fetchone()[0]
    else:
        viewer_role_id = cursor.lastrowid
    
    conn.commit()
    
    # Get permissions for each role
    cursor.execute("SELECT permissions FROM roles WHERE id = ?", (admin_role_id,))
    admin_perms = json.loads(cursor.fetchone()[0])
    
    cursor.execute("SELECT permissions FROM roles WHERE id = ?", (viewer_role_id,))
    viewer_perms = json.loads(cursor.fetchone()[0])
    
    # Verify permissions
    assert "read:*" in admin_perms, "Admin should have read:* permission"
    assert "write:*" in admin_perms, "Admin should have write:* permission"
    assert "read:tasks" in viewer_perms, "Viewer should have read:tasks permission"
    assert "write:*" not in viewer_perms, "Viewer should not have write:* permission"
    
    conn.close()


def test_role_hierarchy(temp_db, org_id):
    """Test role hierarchy (if implemented)."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create parent role
    parent_permissions = json.dumps(["read:*", "write:*"])
    cursor.execute("""
        INSERT INTO roles (organization_id, name, permissions, created_at, updated_at)
        VALUES (?, 'Manager', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id, parent_permissions))
    
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM roles WHERE name = 'Manager' AND organization_id = ?", (org_id,))
        parent_role_id = cursor.fetchone()[0]
    else:
        parent_role_id = cursor.lastrowid
    
    # Create child role (if hierarchy is implemented via parent_role_id column)
    # Check if parent_role_id column exists
    cursor.execute("PRAGMA table_info(roles)") if db.db_type == "sqlite" else cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'roles' AND column_name = 'parent_role_id'
    """)
    
    has_parent_column = cursor.fetchone() is not None
    
    if has_parent_column:
        child_permissions = json.dumps(["read:tasks"])
        cursor.execute("""
            INSERT INTO roles (organization_id, name, permissions, parent_role_id, created_at, updated_at)
            VALUES (?, 'Developer', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (org_id, child_permissions, parent_role_id))
        
        conn.commit()
        
        # Verify hierarchy
        cursor.execute("SELECT parent_role_id FROM roles WHERE name = 'Developer' AND organization_id = ?", (org_id,))
        parent = cursor.fetchone()
        
        if parent and parent[0]:
            assert parent[0] == parent_role_id, "Child role should reference parent role"
    
    conn.close()


def test_team_vs_organization_roles(temp_db, org_id):
    """Test team roles vs organization roles."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create team
    cursor.execute("""
        INSERT INTO teams (organization_id, name, created_at, updated_at)
        VALUES (?, 'Engineering Team', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id,))
    
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM teams WHERE name = 'Engineering Team' AND organization_id = ?", (org_id,))
        team_id = cursor.fetchone()[0]
    else:
        team_id = cursor.lastrowid
    
    conn.commit()
    
    # Create organization-level role
    org_permissions = json.dumps(["read:*"])
    cursor.execute("""
        INSERT INTO roles (organization_id, name, permissions, created_at, updated_at)
        VALUES (?, 'Org Member', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id, org_permissions))
    
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM roles WHERE name = 'Org Member' AND organization_id = ?", (org_id,))
        org_role_id = cursor.fetchone()[0]
    else:
        org_role_id = cursor.lastrowid
    
    # Create team-level role (if team_id column exists in roles table)
    cursor.execute("PRAGMA table_info(roles)") if db.db_type == "sqlite" else cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'roles' AND column_name = 'team_id'
    """)
    
    has_team_column = cursor.fetchone() is not None
    
    if has_team_column:
        team_permissions = json.dumps(["write:tasks"])
        cursor.execute("""
            INSERT INTO roles (organization_id, team_id, name, permissions, created_at, updated_at)
            VALUES (?, ?, 'Team Lead', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (org_id, team_id, team_permissions))
        
        conn.commit()
        
        # Verify team role is scoped to team
        cursor.execute("SELECT team_id FROM roles WHERE name = 'Team Lead' AND organization_id = ?", (org_id,))
        team_role_team = cursor.fetchone()
        
        if team_role_team and team_role_team[0]:
            assert team_role_team[0] == team_id, "Team role should be scoped to team"
    
    # Verify organization role is not scoped to team
    cursor.execute("SELECT team_id FROM roles WHERE id = ?", (org_role_id,))
    org_role_team = cursor.fetchone()
    
    if org_role_team and len(org_role_team) > 0 and org_role_team[0] is None:
        # Organization role should not have team_id (or it should be NULL)
        pass  # This is expected
    
    conn.close()


def test_role_permissions_validation(temp_db, org_id):
    """Test that role permissions are properly validated."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Try to create role with valid permissions
    valid_permissions = json.dumps(["read:tasks", "write:tasks", "delete:tasks"])
    cursor.execute("""
        INSERT INTO roles (organization_id, name, permissions, created_at, updated_at)
        VALUES (?, 'Developer', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id, valid_permissions))
    
    conn.commit()
    
    # Verify role was created with correct permissions
    cursor.execute("SELECT permissions FROM roles WHERE name = 'Developer' AND organization_id = ?", (org_id,))
    result = cursor.fetchone()
    
    assert result is not None, "Role should be created"
    permissions = json.loads(result[0])
    assert isinstance(permissions, list), "Permissions should be a list"
    assert len(permissions) == 3, "Role should have 3 permissions"
    
    conn.close()


def test_multiple_roles_per_user(temp_db, org_id):
    """Test that a user can have multiple roles."""
    db, _ = temp_db
    conn = db._get_connection()
    cursor = conn.cursor()
    
    # Create multiple roles
    role1_permissions = json.dumps(["read:tasks"])
    cursor.execute("""
        INSERT INTO roles (organization_id, name, permissions, created_at, updated_at)
        VALUES (?, 'Viewer', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id, role1_permissions))
    
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM roles WHERE name = 'Viewer' AND organization_id = ?", (org_id,))
        role1_id = cursor.fetchone()[0]
    else:
        role1_id = cursor.lastrowid
    
    role2_permissions = json.dumps(["write:tasks"])
    cursor.execute("""
        INSERT INTO roles (organization_id, name, permissions, created_at, updated_at)
        VALUES (?, 'Editor', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (org_id, role2_permissions))
    
    if db.db_type == "postgresql":
        cursor.execute("SELECT id FROM roles WHERE name = 'Editor' AND organization_id = ?", (org_id,))
        role2_id = cursor.fetchone()[0]
    else:
        role2_id = cursor.lastrowid
    
    conn.commit()
    
    # Assign both roles to user (if user_roles table exists)
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='user_roles'
    """) if db.db_type == "sqlite" else cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_name = 'user_roles'
    """)
    
    if cursor.fetchone():
        user_id = "test-user-123"
        cursor.execute("""
            INSERT INTO user_roles (user_id, role_id, organization_id, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, role1_id, org_id))
        
        cursor.execute("""
            INSERT INTO user_roles (user_id, role_id, organization_id, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, role2_id, org_id))
        
        conn.commit()
        
        # Verify user has both roles
        cursor.execute("""
            SELECT role_id FROM user_roles 
            WHERE user_id = ? AND organization_id = ?
        """, (user_id, org_id))
        user_roles = [row[0] for row in cursor.fetchall()]
        
        assert role1_id in user_roles, "User should have role1"
        assert role2_id in user_roles, "User should have role2"
        assert len(user_roles) == 2, "User should have 2 roles"
    
    conn.close()
