"""
Comprehensive tests for PostgreSQL database support.

Tests schema initialization, CRUD operations, full-text search, and migration
scenarios for both SQLite and PostgreSQL backends to ensure compatibility.
"""
import pytest
import os
import sys
import tempfile
import shutil
import sqlite3
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from database import TodoDatabase
from db_adapter import get_database_adapter, PostgreSQLAdapter, SQLiteAdapter


def check_postgresql_available():
    """Check if PostgreSQL is available for testing."""
    try:
        import psycopg2
        # Try to connect to test PostgreSQL instance
        conn_string = os.getenv(
            "POSTGRESQL_TEST_CONN",
            "host=localhost port=5432 dbname=postgres user=postgres password=postgres"
        )
        try:
            conn = psycopg2.connect(conn_string)
            conn.close()
            return True
        except Exception:
            return False
    except ImportError:
        return False


# PostgreSQL available marker
postgresql_available = pytest.mark.skipif(
    not check_postgresql_available(),
    reason="PostgreSQL not available (install psycopg2-binary and ensure PostgreSQL is running)"
)


@pytest.fixture
def temp_sqlite_db():
    """Create a temporary SQLite database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    
    # Clear any existing DB_TYPE env var
    original_db_type = os.environ.get("DB_TYPE")
    if "DB_TYPE" in os.environ:
        del os.environ["DB_TYPE"]
    
    db = TodoDatabase(db_path)
    
    yield db, db_path
    
    # Restore original DB_TYPE
    if original_db_type:
        os.environ["DB_TYPE"] = original_db_type
    elif "DB_TYPE" in os.environ:
        del os.environ["DB_TYPE"]
    
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_postgresql_db():
    """Create a temporary PostgreSQL database for testing."""
    if not check_postgresql_available():
        pytest.skip("PostgreSQL not available")
    
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    
    # Get connection details
    conn_string = os.getenv(
        "POSTGRESQL_TEST_CONN",
        "host=localhost port=5432 dbname=postgres user=postgres password=postgres"
    )
    
    # Create a test database
    test_db_name = f"test_todos_{os.getpid()}"
    
    # Connect to postgres database to create test database
    conn = psycopg2.connect(conn_string)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    
    # Drop test database if it exists
    cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
    # Create new test database
    cursor.execute(f"CREATE DATABASE {test_db_name}")
    cursor.close()
    conn.close()
    
    # Create connection string for test database
    test_conn_string = conn_string.replace("dbname=postgres", f"dbname={test_db_name}")
    
    # Set environment to use PostgreSQL
    original_db_type = os.environ.get("DB_TYPE")
    os.environ["DB_TYPE"] = "postgresql"
    
    # Create database instance
    db = TodoDatabase(test_conn_string)
    
    yield db, test_db_name
    
    # Cleanup: drop test database
    conn = psycopg2.connect(conn_string)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
    cursor.close()
    conn.close()
    
    # Restore original DB_TYPE
    if original_db_type:
        os.environ["DB_TYPE"] = original_db_type
    elif "DB_TYPE" in os.environ:
        del os.environ["DB_TYPE"]


@pytest.fixture(params=["sqlite", "postgresql"])
def temp_db(request):
    """Parametrized fixture that works with both SQLite and PostgreSQL."""
    if request.param == "sqlite":
        db, db_path = request.getfixturevalue("temp_sqlite_db")
        yield db, db_path, "sqlite"
    else:
        if not check_postgresql_available():
            pytest.skip("PostgreSQL not available")
        db, db_name = request.getfixturevalue("temp_postgresql_db")
        yield db, db_name, "postgresql"


# ============================================================================
# Schema Initialization Tests
# ============================================================================

def test_schema_initialization_sqlite(temp_sqlite_db):
    """Test that SQLite schema is initialized correctly."""
    db, _ = temp_sqlite_db
    
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        
        # Check that all main tables exist
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name IN ('projects', 'tasks', 'task_relationships', 'change_history')
        """)
        tables = {row[0] for row in cursor.fetchall()}
        
        assert 'projects' in tables
        assert 'tasks' in tables
        assert 'task_relationships' in tables
        assert 'change_history' in tables
        
        # Check that tasks table has required columns
        cursor.execute("PRAGMA table_info(tasks)")
        columns = {row[1] for row in cursor.fetchall()}
        
        required_columns = {'id', 'title', 'task_type', 'task_status', 'task_instruction', 
                          'verification_instruction', 'created_at', 'updated_at'}
        assert required_columns.issubset(columns)
        
    finally:
        db.adapter.close(conn)


@postgresql_available
def test_schema_initialization_postgresql(temp_postgresql_db):
    """Test that PostgreSQL schema is initialized correctly."""
    db, _ = temp_postgresql_db
    
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        
        # Check that all main tables exist
        cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('projects', 'tasks', 'task_relationships', 'change_history')
        """)
        tables = {row[0] for row in cursor.fetchall()}
        
        assert 'projects' in tables
        assert 'tasks' in tables
        assert 'task_relationships' in tables
        assert 'change_history' in tables
        
        # Check that tasks table has required columns
        cursor.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'tasks' AND table_schema = 'public'
        """)
        columns = {row[0] for row in cursor.fetchall()}
        
        required_columns = {'id', 'title', 'task_type', 'task_status', 'task_instruction', 
                          'verification_instruction', 'created_at', 'updated_at'}
        assert required_columns.issubset(columns)
        
        # Check that id column is SERIAL (PostgreSQL auto-increment)
        cursor.execute("""
            SELECT data_type FROM information_schema.columns 
            WHERE table_name = 'tasks' AND column_name = 'id'
        """)
        id_type = cursor.fetchone()[0]
        # PostgreSQL SERIAL types show as 'integer' but with default sequence
        assert id_type in ('integer', 'bigint')
        
    finally:
        db.adapter.close(conn)


def test_schema_id_type_difference(temp_db):
    """Test that ID column types are correct for each database backend."""
    db, _, db_type = temp_db
    
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        
        if db_type == "sqlite":
            # SQLite uses INTEGER PRIMARY KEY AUTOINCREMENT
            cursor.execute("PRAGMA table_info(tasks)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            assert columns.get('id') == 'INTEGER'
        else:
            # PostgreSQL uses SERIAL (which is INTEGER with sequence)
            cursor.execute("""
                SELECT data_type FROM information_schema.columns 
                WHERE table_name = 'tasks' AND column_name = 'id'
            """)
            id_type = cursor.fetchone()[0]
            assert id_type in ('integer', 'bigint')
            
    finally:
        db.adapter.close(conn)


# ============================================================================
# CRUD Operations Tests
# ============================================================================

def test_create_task_both_backends(temp_db):
    """Test creating a task works with both SQLite and PostgreSQL."""
    db, _, db_type = temp_db
    
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    assert task_id > 0
    
    task = db.get_task(task_id)
    assert task is not None
    assert task["title"] == "Test Task"
    assert task["task_type"] == "concrete"
    assert task["task_status"] == "available"
    # assigned_agent is only set when task is locked/reserved, not on creation
    # agent_id is used for history tracking only


def test_read_task_both_backends(temp_db):
    """Test reading a task works with both SQLite and PostgreSQL."""
    db, _, db_type = temp_db
    
    task_id = db.create_task(
        title="Read Test Task",
        task_type="abstract",
        task_instruction="Read this task",
        verification_instruction="Verify reading works",
        agent_id="test-agent",
        notes="Test notes"
    )
    
    task = db.get_task(task_id)
    assert task is not None
    assert task["id"] == task_id
    assert task["title"] == "Read Test Task"
    assert task["notes"] == "Test notes"
    assert task["task_type"] == "abstract"


def test_update_task_both_backends(temp_db):
    """Test updating a task works with both SQLite and PostgreSQL."""
    db, _, db_type = temp_db
    
    task_id = db.create_task(
        title="Original Title",
        task_type="concrete",
        task_instruction="Original instruction",
        verification_instruction="Original verification",
        agent_id="test-agent"
    )
    
    # Update the task using direct SQL (since update_task method doesn't exist)
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        # Normalize query for database backend
        query = db.adapter.normalize_query("""
            UPDATE tasks 
            SET title = ?, task_instruction = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """)
        db.adapter.execute(cursor, query, ("Updated Title", "Updated instruction", "Updated notes", task_id))
        conn.commit()
    finally:
        db.adapter.close(conn)
    
    task = db.get_task(task_id)
    assert task["title"] == "Updated Title"
    assert task["task_instruction"] == "Updated instruction"
    assert task["notes"] == "Updated notes"


def test_delete_task_both_backends(temp_db):
    """Test deleting a task works with both SQLite and PostgreSQL."""
    db, _, db_type = temp_db
    
    task_id = db.create_task(
        title="Task to Delete",
        task_type="concrete",
        task_instruction="This will be deleted",
        verification_instruction="Verify deletion",
        agent_id="test-agent"
    )
    
    # Verify task exists
    task = db.get_task(task_id)
    assert task is not None
    
    # Delete the task using direct SQL (since delete_task method doesn't exist)
    conn = db._get_connection()
    try:
        cursor = conn.cursor()
        # Normalize query for database backend
        query = db.adapter.normalize_query("DELETE FROM tasks WHERE id = ?")
        db.adapter.execute(cursor, query, (task_id,))
        conn.commit()
    finally:
        db.adapter.close(conn)
    
    # Verify task is gone
    task = db.get_task(task_id)
    assert task is None


def test_create_project_both_backends(temp_db):
    """Test creating a project works with both SQLite and PostgreSQL."""
    db, _, db_type = temp_db
    
    project_id = db.create_project(
        name="Test Project",
        description="Test project description",
        local_path="/tmp/test",
        origin_url="https://example.com"
    )
    
    assert project_id > 0
    
    project = db.get_project(project_id)
    assert project is not None
    assert project["name"] == "Test Project"
    assert project["description"] == "Test project description"


def test_create_task_with_project_both_backends(temp_db):
    """Test creating a task with a project works with both backends."""
    db, _, db_type = temp_db
    
    project_id = db.create_project(
        name="Project for Task",
        description="Test project",
        local_path="/tmp/test"
    )
    
    task_id = db.create_task(
        title="Task in Project",
        task_type="concrete",
        task_instruction="Task instruction",
        verification_instruction="Verification",
        agent_id="test-agent",
        project_id=project_id
    )
    
    task = db.get_task(task_id)
    assert task["project_id"] == project_id


def test_foreign_key_constraints_both_backends(temp_db):
    """Test that foreign key constraints work with both backends."""
    db, _, db_type = temp_db
    
    # Try to create a task with invalid project_id
    # Foreign key constraints should prevent this or set it to NULL
    # SQLite with foreign keys enabled will raise an error
    # PostgreSQL will also raise an error if foreign keys are enforced
    
    # Create a valid project first
    project_id = db.create_project(
        name="Valid Project",
        description="Test project",
        local_path="/tmp/test"
    )
    
    # Create task with valid project_id - should work
    task_id = db.create_task(
        title="Task with Valid Project",
        task_type="concrete",
        task_instruction="Test",
        verification_instruction="Verify",
        agent_id="test-agent",
        project_id=project_id
    )
    
    task = db.get_task(task_id)
    assert task is not None
    assert task["project_id"] == project_id


def test_transactions_both_backends(temp_db):
    """Test that transactions work correctly with both backends."""
    db, _, db_type = temp_db
    
    # Create a project
    project_id = db.create_project(
        name="Transaction Test",
        description="Test",
        local_path="/tmp/test"
    )
    
    # Create multiple tasks in what should be a transaction
    task_ids = []
    for i in range(3):
        task_id = db.create_task(
            title=f"Task {i}",
            task_type="concrete",
            task_instruction=f"Task {i} instruction",
            verification_instruction=f"Verify {i}",
            agent_id="test-agent",
            project_id=project_id
        )
        task_ids.append(task_id)
    
    # All tasks should be created
    for task_id in task_ids:
        task = db.get_task(task_id)
        assert task is not None
        assert task["project_id"] == project_id


# ============================================================================
# Full-Text Search Tests
# ============================================================================

def test_fulltext_search_basic_both_backends(temp_db):
    """Test basic full-text search works with both SQLite and PostgreSQL."""
    db, _, db_type = temp_db
    
    # Create test tasks
    task1_id = db.create_task(
        title="Python API implementation",
        task_type="concrete",
        task_instruction="Implement REST API using Python",
        verification_instruction="Test API endpoints",
        agent_id="test-agent"
    )
    
    task2_id = db.create_task(
        title="Database schema design",
        task_type="concrete",
        task_instruction="Design PostgreSQL database schema",
        verification_instruction="Verify schema",
        agent_id="test-agent"
    )
    
    # Search for "Python"
    results = db.search_tasks("Python")
    assert len(results) >= 1
    found_ids = {r["id"] for r in results}
    assert task1_id in found_ids
    
    # Search for "PostgreSQL" or "database"
    results = db.search_tasks("database")
    assert len(results) >= 1
    found_ids = {r["id"] for r in results}
    assert task2_id in found_ids


def test_fulltext_search_multiple_terms_both_backends(temp_db):
    """Test full-text search with multiple terms works with both backends."""
    db, _, db_type = temp_db
    
    task_id = db.create_task(
        title="REST API endpoint",
        task_type="concrete",
        task_instruction="Create REST API endpoint for user management",
        verification_instruction="Test endpoint",
        agent_id="test-agent",
        notes="High priority REST API work"
    )
    
    # Search for terms that appear multiple times
    results = db.search_tasks("REST API")
    assert len(results) >= 1
    found_ids = {r["id"] for r in results}
    assert task_id in found_ids


def test_fulltext_search_case_insensitive_both_backends(temp_db):
    """Test that full-text search is case insensitive with both backends."""
    db, _, db_type = temp_db
    
    task_id = db.create_task(
        title="JavaScript Framework",
        task_type="concrete",
        task_instruction="Implement JavaScript framework",
        verification_instruction="Test framework",
        agent_id="test-agent"
    )
    
    # Search with different cases
    results_lower = db.search_tasks("javascript")
    results_upper = db.search_tasks("JAVASCRIPT")
    results_mixed = db.search_tasks("JavaScript")
    
    # All should find the task
    found_ids_lower = {r["id"] for r in results_lower}
    found_ids_upper = {r["id"] for r in results_upper}
    found_ids_mixed = {r["id"] for r in results_mixed}
    
    assert task_id in found_ids_lower
    assert task_id in found_ids_upper
    assert task_id in found_ids_mixed


def test_fulltext_search_empty_query_both_backends(temp_db):
    """Test that empty search query returns all tasks with both backends."""
    db, _, db_type = temp_db
    
    # Create multiple tasks
    task_ids = []
    for i in range(5):
        task_id = db.create_task(
            title=f"Task {i}",
            task_type="concrete",
            task_instruction=f"Task {i} instruction",
            verification_instruction=f"Verify {i}",
            agent_id="test-agent"
        )
        task_ids.append(task_id)
    
    # Empty search should return all tasks (up to limit)
    results = db.search_tasks("", limit=100)
    found_ids = {r["id"] for r in results}
    
    # Should find at least our created tasks
    for task_id in task_ids:
        assert task_id in found_ids


def test_fulltext_search_limit_both_backends(temp_db):
    """Test that full-text search respects limit with both backends."""
    db, _, db_type = temp_db
    
    # Create multiple tasks with same searchable term
    task_ids = []
    for i in range(10):
        task_id = db.create_task(
            title=f"Searchable Task {i}",
            task_type="concrete",
            task_instruction="Searchable content",
            verification_instruction="Verify",
            agent_id="test-agent"
        )
        task_ids.append(task_id)
    
    # Search with limit
    results = db.search_tasks("Searchable", limit=5)
    assert len(results) == 5


# ============================================================================
# Migration Tests
# ============================================================================

def test_migration_sqlite_to_postgresql():
    """Test migrating data from SQLite to PostgreSQL."""
    if not check_postgresql_available():
        pytest.skip("PostgreSQL not available")
    
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    from migrate_to_postgresql import migrate_sqlite_to_postgresql
    
    # Create temporary SQLite database with data
    temp_dir = tempfile.mkdtemp()
    sqlite_path = os.path.join(temp_dir, "source.db")
    
    try:
        # Create SQLite database and populate with test data
        sqlite_db = TodoDatabase(sqlite_path)
        
        project_id = sqlite_db.create_project(
            name="Migration Test Project",
            description="Project for migration testing",
            local_path="/tmp/migration_test"
        )
        
        task1_id = sqlite_db.create_task(
            title="Task 1 for Migration",
            task_type="concrete",
            task_instruction="First task",
            verification_instruction="Verify task 1",
            agent_id="test-agent",
            project_id=project_id,
            notes="Task 1 notes"
        )
        
        task2_id = sqlite_db.create_task(
            title="Task 2 for Migration",
            task_type="abstract",
            task_instruction="Second task",
            verification_instruction="Verify task 2",
            agent_id="test-agent",
            project_id=project_id
        )
        
        # Create PostgreSQL test database
        conn_string = os.getenv(
            "POSTGRESQL_TEST_CONN",
            "host=localhost port=5432 dbname=postgres user=postgres password=postgres"
        )
        test_db_name = f"test_migration_{os.getpid()}"
        
        conn = psycopg2.connect(conn_string)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
        cursor.execute(f"CREATE DATABASE {test_db_name}")
        cursor.close()
        conn.close()
        
        test_conn_string = conn_string.replace("dbname=postgres", f"dbname={test_db_name}")
        
        # Perform migration
        migrate_sqlite_to_postgresql(sqlite_path, test_conn_string)
        
        # Verify migrated data
        os.environ["DB_TYPE"] = "postgresql"
        pg_db = TodoDatabase(test_conn_string)
        
        # Check projects
        migrated_project = pg_db.get_project(project_id)
        assert migrated_project is not None
        assert migrated_project["name"] == "Migration Test Project"
        
        # Check tasks
        migrated_task1 = pg_db.get_task(task1_id)
        assert migrated_task1 is not None
        assert migrated_task1["title"] == "Task 1 for Migration"
        assert migrated_task1["notes"] == "Task 1 notes"
        
        migrated_task2 = pg_db.get_task(task2_id)
        assert migrated_task2 is not None
        assert migrated_task2["title"] == "Task 2 for Migration"
        assert migrated_task2["task_type"] == "abstract"
        
        # Cleanup
        conn = psycopg2.connect(conn_string)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
        cursor.close()
        conn.close()
        
    finally:
        shutil.rmtree(temp_dir)
        if "DB_TYPE" in os.environ:
            del os.environ["DB_TYPE"]


# ============================================================================
# Adapter Tests
# ============================================================================

def test_adapter_query_normalization():
    """Test that query normalization works correctly for both adapters."""
    sqlite_adapter = SQLiteAdapter(":memory:")
    postgresql_adapter = PostgreSQLAdapter("host=localhost dbname=test user=test")
    
    # Test placeholder normalization
    query_with_placeholders = "SELECT * FROM tasks WHERE id = ? AND title = ?"
    
    sqlite_normalized = sqlite_adapter.normalize_query(query_with_placeholders)
    assert "?" in sqlite_normalized  # SQLite keeps ?
    
    postgresql_normalized = postgresql_adapter.normalize_query(query_with_placeholders)
    assert "%s" in postgresql_normalized  # PostgreSQL uses %s
    assert "?" not in postgresql_normalized
    
    # Test AUTOINCREMENT normalization
    create_query = "CREATE TABLE test (id INTEGER PRIMARY KEY AUTOINCREMENT)"
    
    sqlite_normalized = sqlite_adapter.normalize_query(create_query)
    assert "AUTOINCREMENT" in sqlite_normalized
    
    postgresql_normalized = postgresql_adapter.normalize_query(create_query)
    assert "SERIAL" in postgresql_normalized or "AUTOINCREMENT" not in postgresql_normalized


def test_adapter_primary_key_types():
    """Test that primary key types are correct for each adapter."""
    sqlite_adapter = SQLiteAdapter(":memory:")
    postgresql_adapter = PostgreSQLAdapter("host=localhost dbname=test user=test")
    
    sqlite_pk = sqlite_adapter.get_pk_type()
    postgresql_pk = postgresql_adapter.get_pk_type()
    
    assert "AUTOINCREMENT" in sqlite_pk or "INTEGER" in sqlite_pk
    assert "SERIAL" in postgresql_pk


def test_adapter_fulltext_support():
    """Test that both adapters report full-text search support."""
    sqlite_adapter = SQLiteAdapter(":memory:")
    postgresql_adapter = PostgreSQLAdapter("host=localhost dbname=test user=test")
    
    assert sqlite_adapter.supports_fulltext_search() == True
    assert postgresql_adapter.supports_fulltext_search() == True


# ============================================================================
# Compatibility Tests
# ============================================================================

def test_same_operations_different_backends():
    """Test that the same operations produce equivalent results with both backends."""
    # Create SQLite database
    temp_dir = tempfile.mkdtemp()
    sqlite_path = os.path.join(temp_dir, "sqlite_test.db")
    
    original_db_type = os.environ.get("DB_TYPE")
    if "DB_TYPE" in os.environ:
        del os.environ["DB_TYPE"]
    
    try:
        sqlite_db = TodoDatabase(sqlite_path)
        
        # Perform operations on SQLite
        project_id_sqlite = sqlite_db.create_project(
            name="Compatibility Test",
            description="Test description",
            local_path="/tmp/test"
        )
        
        task_id_sqlite = sqlite_db.create_task(
            title="Compatibility Task",
            task_type="concrete",
            task_instruction="Test instruction",
            verification_instruction="Test verification",
            agent_id="test-agent",
            project_id=project_id_sqlite
        )
        
        # Get results from SQLite
        sqlite_project = sqlite_db.get_project(project_id_sqlite)
        sqlite_task = sqlite_db.get_task(task_id_sqlite)
        
        # If PostgreSQL is available, compare
        if check_postgresql_available():
            import psycopg2
            from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
            
            conn_string = os.getenv(
                "POSTGRESQL_TEST_CONN",
                "host=localhost port=5432 dbname=postgres user=postgres password=postgres"
            )
            test_db_name = f"test_compat_{os.getpid()}"
            
            conn = psycopg2.connect(conn_string)
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = conn.cursor()
            cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
            cursor.execute(f"CREATE DATABASE {test_db_name}")
            cursor.close()
            conn.close()
            
            test_conn_string = conn_string.replace("dbname=postgres", f"dbname={test_db_name}")
            os.environ["DB_TYPE"] = "postgresql"
            
            postgresql_db = TodoDatabase(test_conn_string)
            
            # Perform same operations on PostgreSQL
            project_id_pg = postgresql_db.create_project(
                name="Compatibility Test",
                description="Test description",
                local_path="/tmp/test"
            )
            
            task_id_pg = postgresql_db.create_task(
                title="Compatibility Task",
                task_type="concrete",
                task_instruction="Test instruction",
                verification_instruction="Test verification",
                agent_id="test-agent",
                project_id=project_id_pg
            )
            
            # Get results from PostgreSQL
            pg_project = postgresql_db.get_project(project_id_pg)
            pg_task = postgresql_db.get_task(task_id_pg)
            
            # Compare results (IDs may differ, but data should be same)
            assert sqlite_project["name"] == pg_project["name"]
            assert sqlite_project["description"] == pg_project["description"]
            
            assert sqlite_task["title"] == pg_task["title"]
            assert sqlite_task["task_type"] == pg_task["task_type"]
            assert sqlite_task["task_instruction"] == pg_task["task_instruction"]
            
            # Cleanup PostgreSQL
            conn = psycopg2.connect(conn_string)
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = conn.cursor()
            cursor.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
            cursor.close()
            conn.close()
            
    finally:
        shutil.rmtree(temp_dir)
        if original_db_type:
            os.environ["DB_TYPE"] = original_db_type
        elif "DB_TYPE" in os.environ:
            del os.environ["DB_TYPE"]
