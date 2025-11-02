"""
Database schema and management for TODO service.
"""
import sqlite3
import os
import json
import hashlib
import secrets
import time
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from enum import Enum
import logging

from db_adapter import get_database_adapter, BaseDatabaseAdapter, DatabaseType
from tracing import trace_span, add_span_attribute
from opentelemetry import trace

logger = logging.getLogger(__name__)

# Query performance threshold (seconds) - queries slower than this will be logged
QUERY_SLOW_THRESHOLD = float(os.getenv("DB_QUERY_SLOW_THRESHOLD", "0.1"))
# Enable query logging (can be set via environment variable)
ENABLE_QUERY_LOGGING = os.getenv("DB_ENABLE_QUERY_LOGGING", "true").lower() == "true"


class TaskType(Enum):
    """Task type enumeration."""
    CONCRETE = "concrete"
    ABSTRACT = "abstract"
    EPIC = "epic"


class TaskStatus(Enum):
    """Task status enumeration."""
    AVAILABLE = "available"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class VerificationStatus(Enum):
    """Verification status enumeration."""
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class RelationshipType(Enum):
    """Task relationship type enumeration."""
    SUBTASK = "subtask"
    BLOCKING = "blocking"
    BLOCKED_BY = "blocked_by"
    FOLLOWUP = "followup"
    RELATED = "related"


class Priority(Enum):
    """Task priority enumeration."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TodoDatabase:
    """Database for TODO management - supports both SQLite and PostgreSQL."""
    
    def __init__(self, db_path: str = None):
        """
        Initialize database connection and create schema if needed.
        
        Args:
            db_path: Database path (for SQLite) or connection string (for PostgreSQL).
                     If None, uses environment variables.
        """
        # Determine database type and get adapter
        db_type = os.getenv("DB_TYPE", "sqlite").lower()
        
        if db_path is None:
            if db_type == "postgresql":
                # Use PostgreSQL connection string from environment
                db_host = os.getenv("DB_HOST", "localhost")
                db_port = os.getenv("DB_PORT", "5432")
                db_name = os.getenv("DB_NAME", "todos")
                db_user = os.getenv("DB_USER", "postgres")
                db_password = os.getenv("DB_PASSWORD", "")
                
                if db_password:
                    self.db_path = f"host={db_host} port={db_port} dbname={db_name} user={db_user} password={db_password}"
                else:
                    self.db_path = f"host={db_host} port={db_port} dbname={db_name} user={db_user}"
            else:
                self.db_path = os.getenv("TODO_DB_PATH", "/app/data/todos.db")
        else:
            self.db_path = db_path
        
        self.db_type = db_type
        self.adapter = get_database_adapter(self.db_path)
        
        if db_type == "sqlite":
            self._ensure_db_directory()
        
        self._init_schema()
    
    def _ensure_db_directory(self):
        """Ensure database directory exists (SQLite only)."""
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    
    def _get_connection(self):
        """Get database connection using adapter."""
        return self.adapter.connect()
    
    def _log_query(self, query: str, params: Tuple, duration: float, rows_returned: int = None):
        """
        Log query performance information.
        
        Args:
            query: SQL query string
            params: Query parameters
            duration: Query duration in seconds
            rows_returned: Number of rows returned (if known)
        """
        if not ENABLE_QUERY_LOGGING:
            return
        
        # Log slow queries at WARNING level, others at DEBUG
        log_level = logging.WARNING if duration >= QUERY_SLOW_THRESHOLD else logging.DEBUG
        
        # Truncate very long queries for readability
        query_preview = query[:200] + "..." if len(query) > 200 else query
        
        message = f"Query executed in {duration:.4f}s"
        if rows_returned is not None:
            message += f" ({rows_returned} rows)"
        
        logger.log(log_level, message, extra={
            "query": query_preview,
            "duration": duration,
            "rows": rows_returned
        })
        
        # For very slow queries, log full details
        if duration >= QUERY_SLOW_THRESHOLD * 2:  # 2x threshold
            logger.warning(
                f"Slow query detected ({duration:.4f}s): {query[:500]}",
                extra={"params": params[:10] if params else None}  # Limit param logging
            )
    
    def _execute_with_logging(self, cursor, query: str, params: Tuple = None):
        """
        Execute a query with performance logging and tracing.
        
        Args:
            cursor: Database cursor
            query: SQL query string
            params: Query parameters
            
        Returns:
            Cursor after execution
        """
        # Determine query type for span name
        query_type = "unknown"
        query_lower = query.strip().upper()
        if query_lower.startswith("SELECT"):
            query_type = "select"
        elif query_lower.startswith("INSERT"):
            query_type = "insert"
        elif query_lower.startswith("UPDATE"):
            query_type = "update"
        elif query_lower.startswith("DELETE"):
            query_type = "delete"
        
        # Extract table name if possible (simple heuristic)
        table_name = "unknown"
        for keyword in ["FROM", "INTO", "UPDATE"]:
            if keyword in query_lower:
                parts = query_lower.split(keyword, 1)
                if len(parts) > 1:
                    table_name = parts[1].split()[0].strip()
                    break
        
        start_time = time.time()
        with trace_span(
            f"db.{query_type}",
            attributes={
                "db.system": self.db_type,
                "db.statement.type": query_type,
                "db.sql.table": table_name,
                "db.operation": query_type,
            },
            kind=trace.SpanKind.CLIENT
        ) as span:
            try:
                result = self.adapter.execute(cursor, query, params)
                duration = time.time() - start_time
                
                # Add duration to span
                add_span_attribute("db.duration_ms", duration * 1000)
                
                # Log query performance
                if ENABLE_QUERY_LOGGING and duration >= QUERY_SLOW_THRESHOLD:
                    query_preview = query[:200] + "..." if len(query) > 200 else query
                    logger.warning(
                        f"Slow query: {duration:.4f}s - {query_preview}",
                        extra={"duration": duration, "params_count": len(params) if params else 0}
                    )
                    add_span_attribute("db.slow_query", True)
                
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(
                    f"Query failed after {duration:.4f}s: {query[:200]}",
                    exc_info=True
                )
                raise
    
    def _normalize_sql(self, query: str) -> str:
        """Normalize SQL query for the current database backend."""
        return self.adapter.normalize_query(query)
    
    def _execute_insert(self, cursor, query: str, params: Tuple = None) -> int:
        """
        Execute an INSERT query and return the inserted ID.
        Works for both SQLite (lastrowid) and PostgreSQL (RETURNING).
        
        Args:
            cursor: Database cursor
            query: INSERT query (will be modified for PostgreSQL to add RETURNING)
            params: Query parameters
            
        Returns:
            Inserted row ID
        """
        if self.db_type == "postgresql":
            # Add RETURNING id to INSERT statement if not present
            if "RETURNING" not in query.upper():
                # Find the INSERT statement and add RETURNING id
                query = query.rstrip().rstrip(';')
                query += " RETURNING id"
            
            self._execute_with_logging(cursor, query, params)
            result = cursor.fetchone()
            if result:
                # Handle both dict-like and tuple results
                if hasattr(result, 'keys'):
                    return result['id']
                elif isinstance(result, (list, tuple)):
                    return result[0]
                return result
            return None
        else:
            # SQLite: use lastrowid
            self._execute_with_logging(cursor, query, params)
            return cursor.lastrowid
    
    def _init_schema(self):
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Projects table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    origin_url TEXT,
                    local_path TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Tasks table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    title TEXT NOT NULL,
                    task_type TEXT NOT NULL CHECK(task_type IN ('concrete', 'abstract', 'epic')),
                    task_instruction TEXT NOT NULL,
                    verification_instruction TEXT NOT NULL,
                    task_status TEXT NOT NULL DEFAULT 'available' 
                        CHECK(task_status IN ('available', 'in_progress', 'complete', 'blocked', 'cancelled')),
                    verification_status TEXT NOT NULL DEFAULT 'unverified'
                        CHECK(verification_status IN ('unverified', 'verified')),
                    priority TEXT DEFAULT 'medium' 
                        CHECK(priority IN ('low', 'medium', 'high', 'critical')),
                    assigned_agent TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    notes TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Migration: Add priority column if it doesn't exist (for existing databases)
            if self.db_type == "sqlite":
                try:
                    cursor.execute("SELECT priority FROM tasks LIMIT 1")
                except (sqlite3.OperationalError, Exception):
                    # Column doesn't exist, add it
                    logger.info("Adding priority column to tasks table (migration)")
                    query = self._normalize_sql("""
                        ALTER TABLE tasks 
                        ADD COLUMN priority TEXT DEFAULT 'medium' 
                        CHECK(priority IN ('low', 'medium', 'high', 'critical'))
                    """)
                    self._execute_with_logging(cursor, query)
                    # Update existing tasks to have medium priority
                    self._execute_with_logging(cursor, "UPDATE tasks SET priority = 'medium' WHERE priority IS NULL")
            else:
                # PostgreSQL: Check if column exists using information_schema
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'tasks' AND column_name = 'priority'
                """)
                if not cursor.fetchone():
                    logger.info("Adding priority column to tasks table (migration)")
                    query = self._normalize_sql("ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'medium'")
                    self._execute_with_logging(cursor, query)
                    self._execute_with_logging(cursor, "UPDATE tasks SET priority = 'medium' WHERE priority IS NULL")
            
            # Migration: Add time tracking columns if they don't exist
            if self.db_type == "sqlite":
                try:
                    cursor.execute("SELECT estimated_hours FROM tasks LIMIT 1")
                except (sqlite3.OperationalError, Exception):
                    logger.info("Adding time tracking columns to tasks table (migration)")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN estimated_hours REAL")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN actual_hours REAL")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN started_at TIMESTAMP")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN time_delta_hours REAL")
            else:
                # PostgreSQL
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'tasks' AND column_name = 'estimated_hours'
                """)
                if not cursor.fetchone():
                    logger.info("Adding time tracking columns to tasks table (migration)")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN estimated_hours REAL")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN actual_hours REAL")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN started_at TIMESTAMP")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN time_delta_hours REAL")
            
            # Migration: Add due_date column if it doesn't exist
            if self.db_type == "sqlite":
                try:
                    cursor.execute("SELECT due_date FROM tasks LIMIT 1")
                except (sqlite3.OperationalError, Exception):
                    logger.info("Adding due_date column to tasks table (migration)")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN due_date TIMESTAMP")
                    # Add index for due_date queries
                    self._execute_with_logging(cursor, "CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)")
            else:
                # PostgreSQL
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'tasks' AND column_name = 'due_date'
                """)
                if not cursor.fetchone():
                    logger.info("Adding due_date column to tasks table (migration)")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN due_date TIMESTAMP")
                    self._execute_with_logging(cursor, "CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)")
            
            # Migration: Add metadata column if it doesn't exist (for storing GitHub URLs and other metadata)
            if self.db_type == "sqlite":
                try:
                    cursor.execute("SELECT metadata FROM tasks LIMIT 1")
                except (sqlite3.OperationalError, Exception):
                    logger.info("Adding metadata column to tasks table (migration)")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN metadata TEXT")
            else:
                # PostgreSQL
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'tasks' AND column_name = 'metadata'
                """)
                if not cursor.fetchone():
                    logger.info("Adding metadata column to tasks table (migration)")
                    self._execute_with_logging(cursor, "ALTER TABLE tasks ADD COLUMN metadata TEXT")
            
            # Task relationships table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS task_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_task_id INTEGER NOT NULL,
                    child_task_id INTEGER NOT NULL,
                    relationship_type TEXT NOT NULL
                        CHECK(relationship_type IN ('subtask', 'blocking', 'blocked_by', 'followup', 'related')),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (child_task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    UNIQUE(parent_task_id, child_task_id, relationship_type)
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Change history table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS change_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    change_type TEXT NOT NULL
                        CHECK(change_type IN ('created', 'locked', 'unlocked', 'updated', 'completed', 'verified', 'status_changed', 'relationship_added', 'progress', 'note', 'blocker', 'question', 'finding')),
                    field_name TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    notes TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Tags table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Task tags junction table (many-to-many)
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS task_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE,
                    UNIQUE(task_id, tag_id)
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Task templates table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS task_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    task_type TEXT NOT NULL CHECK(task_type IN ('concrete', 'abstract', 'epic')),
                    task_instruction TEXT NOT NULL,
                    verification_instruction TEXT NOT NULL,
                    priority TEXT DEFAULT 'medium' 
                        CHECK(priority IN ('low', 'medium', 'high', 'critical')),
                    estimated_hours REAL,
                    notes TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Webhooks table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS webhooks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    events TEXT NOT NULL,
                    secret TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    retry_count INTEGER NOT NULL DEFAULT 3,
                    timeout_seconds INTEGER NOT NULL DEFAULT 10,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Webhook delivery history table (for tracking deliveries and retries)
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    webhook_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'success', 'failed')),
                    response_code INTEGER,
                    response_body TEXT,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    delivered_at TIMESTAMP,
                    FOREIGN KEY (webhook_id) REFERENCES webhooks(id) ON DELETE CASCADE
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Task versions table (for versioning task states)
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS task_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    version_number INTEGER NOT NULL,
                    title TEXT,
                    task_type TEXT,
                    task_instruction TEXT,
                    verification_instruction TEXT,
                    task_status TEXT,
                    verification_status TEXT,
                    priority TEXT,
                    assigned_agent TEXT,
                    notes TEXT,
                    estimated_hours REAL,
                    actual_hours REAL,
                    time_delta_hours REAL,
                    due_date TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    UNIQUE(task_id, version_number)
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # File attachments table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS file_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    description TEXT,
                    uploaded_by TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Task comments table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS task_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    parent_comment_id INTEGER,
                    mentions TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (parent_comment_id) REFERENCES task_comments(id) ON DELETE CASCADE
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # API keys table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    key_prefix TEXT NOT NULL,
                    name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Migration: Add is_admin column if it doesn't exist
            if self.db_type == "sqlite":
                try:
                    cursor.execute("SELECT is_admin FROM api_keys LIMIT 1")
                except (sqlite3.OperationalError, Exception):
                    logger.info("Adding is_admin column to api_keys table (migration)")
                    self._execute_with_logging(cursor, "ALTER TABLE api_keys ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            else:
                # PostgreSQL
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'api_keys' AND column_name = 'is_admin'
                """)
                if not cursor.fetchone():
                    logger.info("Adding is_admin column to api_keys table (migration)")
                    self._execute_with_logging(cursor, "ALTER TABLE api_keys ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            
            # Blocked agents table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS blocked_agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL UNIQUE,
                    reason TEXT,
                    blocked_by TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    unblocked_at TIMESTAMP
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Audit logs table for admin actions
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    actor_type TEXT NOT NULL CHECK(actor_type IN ('api_key', 'user', 'system')),
                    target_type TEXT,
                    target_id TEXT,
                    details TEXT,
                    ip_address TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Users table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_login_at TIMESTAMP
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # User sessions table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    session_token TEXT NOT NULL UNIQUE,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Recurring tasks table
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS recurring_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    recurrence_type TEXT NOT NULL CHECK(recurrence_type IN ('daily', 'weekly', 'monthly')),
                    recurrence_config TEXT NOT NULL,
                    next_occurrence TIMESTAMP NOT NULL,
                    last_occurrence_created TIMESTAMP,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                )
            """)
            self._execute_with_logging(cursor, query)
            
            # Migration: Add recurring_tasks table if it doesn't exist (for existing databases)
            if self.db_type == "sqlite":
                try:
                    cursor.execute("SELECT id FROM recurring_tasks LIMIT 1")
                except (sqlite3.OperationalError, Exception):
                    logger.info("Recurring tasks table already exists or will be created")
            else:
                # PostgreSQL: Check if table exists
                cursor.execute("""
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_name = 'recurring_tasks'
                """)
                if not cursor.fetchone():
                    logger.info("Recurring tasks table will be created")
            
            # Indexes for performance
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(task_status)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_agent)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date)",
                "CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name)",
                "CREATE INDEX IF NOT EXISTS idx_relationships_parent ON task_relationships(parent_task_id)",
                "CREATE INDEX IF NOT EXISTS idx_relationships_child ON task_relationships(child_task_id)",
                "CREATE INDEX IF NOT EXISTS idx_change_history_task ON change_history(task_id)",
                "CREATE INDEX IF NOT EXISTS idx_change_history_agent ON change_history(agent_id)",
                "CREATE INDEX IF NOT EXISTS idx_change_history_created ON change_history(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_task_versions_task ON task_versions(task_id)",
                "CREATE INDEX IF NOT EXISTS idx_task_versions_number ON task_versions(task_id, version_number)",
                "CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name)",
                "CREATE INDEX IF NOT EXISTS idx_task_tags_task ON task_tags(task_id)",
                "CREATE INDEX IF NOT EXISTS idx_task_tags_tag ON task_tags(tag_id)",
                "CREATE INDEX IF NOT EXISTS idx_task_templates_name ON task_templates(name)",
                "CREATE INDEX IF NOT EXISTS idx_task_templates_type ON task_templates(task_type)",
                "CREATE INDEX IF NOT EXISTS idx_webhooks_project ON webhooks(project_id)",
                "CREATE INDEX IF NOT EXISTS idx_webhooks_enabled ON webhooks(enabled)",
                "CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook ON webhook_deliveries(webhook_id)",
                "CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status)",
                "CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_created ON webhook_deliveries(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_file_attachments_task ON file_attachments(task_id)",
                "CREATE INDEX IF NOT EXISTS idx_file_attachments_created ON file_attachments(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_task_comments_task ON task_comments(task_id)",
                "CREATE INDEX IF NOT EXISTS idx_task_comments_parent ON task_comments(parent_comment_id)",
                "CREATE INDEX IF NOT EXISTS idx_task_comments_agent ON task_comments(agent_id)",
                "CREATE INDEX IF NOT EXISTS idx_task_comments_created ON task_comments(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_api_keys_project ON api_keys(project_id)",
                "CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)",
                "CREATE INDEX IF NOT EXISTS idx_api_keys_enabled ON api_keys(enabled)",
                "CREATE INDEX IF NOT EXISTS idx_api_keys_admin ON api_keys(is_admin)",
                "CREATE INDEX IF NOT EXISTS idx_blocked_agents_agent_id ON blocked_agents(agent_id)",
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor)",
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action)",
                "CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
                "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(session_token)",
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at)",
                "CREATE INDEX IF NOT EXISTS idx_recurring_tasks_task ON recurring_tasks(task_id)",
                "CREATE INDEX IF NOT EXISTS idx_recurring_tasks_next ON recurring_tasks(next_occurrence)",
                "CREATE INDEX IF NOT EXISTS idx_recurring_tasks_active ON recurring_tasks(is_active)",
                # Composite indexes
                "CREATE INDEX IF NOT EXISTS idx_tasks_status_type ON tasks(task_status, task_type)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, task_status)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_project_status_type ON tasks(project_id, task_status, task_type)",
                "CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(task_status, priority)",
                "CREATE INDEX IF NOT EXISTS idx_relationships_parent_type ON task_relationships(parent_task_id, relationship_type)",
                "CREATE INDEX IF NOT EXISTS idx_relationships_child_type ON task_relationships(child_task_id, relationship_type)",
                "CREATE INDEX IF NOT EXISTS idx_task_tags_task_tag ON task_tags(task_id, tag_id)",
            ]
            
            # PostgreSQL doesn't support DESC in CREATE INDEX, need separate handling
            if self.db_type == "postgresql":
                indexes.append("CREATE INDEX IF NOT EXISTS idx_tasks_created_status ON tasks(created_at DESC, task_status)")
            else:
                indexes.append("CREATE INDEX IF NOT EXISTS idx_tasks_created_status ON tasks(created_at DESC, task_status)")
            
            for index_query in indexes:
                self._execute_with_logging(cursor, index_query)
            
            # Full-text search setup
            if self.db_type == "sqlite":
                # FTS5 virtual table for SQLite
                try:
                    self._execute_with_logging(cursor, """
                        CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
                            title,
                            task_instruction,
                            notes,
                            content='tasks',
                            content_rowid='id'
                        )
                    """)
                    # Rebuild FTS5 index if needed
                    try:
                        self._execute_with_logging(cursor, "SELECT COUNT(*) FROM tasks_fts")
                        count = cursor.fetchone()[0] if hasattr(cursor.fetchone(), '__getitem__') else cursor.fetchone()['count']
                        if count == 0:
                            self._execute_with_logging(cursor, "SELECT COUNT(*) FROM tasks")
                            task_count = cursor.fetchone()[0] if hasattr(cursor.fetchone(), '__getitem__') else cursor.fetchone()['count']
                            if task_count > 0:
                                self._execute_with_logging(cursor, "INSERT INTO tasks_fts(tasks_fts) VALUES('rebuild')")
                    except Exception:
                        pass
                except Exception:
                    logger.warning("FTS5 not available, full-text search will use fallback")
            else:
                # PostgreSQL full-text search
                if self.adapter.supports_fulltext_search():
                    self.adapter.create_fulltext_index(cursor, "tasks", ["title", "task_instruction", "notes"])
            
            conn.commit()
            logger.info(f"Database schema initialized")
        except Exception as e:
            logger.error(f"Failed to initialize schema: {e}")
            raise
        finally:
            self.adapter.close(conn)
    
    def create_project(
        self,
        name: str,
        local_path: str,
        origin_url: Optional[str] = None,
        description: Optional[str] = None
    ) -> int:
        """Create a new project and return its ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            project_id = self._execute_insert(cursor, """
                INSERT INTO projects (name, local_path, origin_url, description)
                VALUES (?, ?, ?, ?)
            """, (name, local_path, origin_url, description))
            conn.commit()
            logger.info(f"Created project {project_id}: {name}")
            return project_id
        finally:
            self.adapter.close(conn)
    
    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get a project by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def get_project_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a project by name."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def list_projects(self) -> List[Dict[str, Any]]:
        """List all projects."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def create_task(
        self,
        title: str,
        task_type: str,
        task_instruction: str,
        verification_instruction: str,
        agent_id: str,
        project_id: Optional[int] = None,
        notes: Optional[str] = None,
        priority: Optional[str] = None,
        estimated_hours: Optional[float] = None,
        due_date: Optional[datetime] = None
    ) -> int:
        """Create a new task and return its ID."""
        if priority is None:
            priority = "medium"
        if priority not in ["low", "medium", "high", "critical"]:
            raise ValueError(f"Invalid priority: {priority}. Must be one of: low, medium, high, critical")
        
        # Convert due_date to ISO format string if provided
        due_date_str = None
        if due_date:
            if isinstance(due_date, str):
                due_date_str = due_date
            else:
                due_date_str = due_date.isoformat()
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            task_id = self._execute_insert(cursor, """
                INSERT INTO tasks (title, task_type, task_instruction, verification_instruction, project_id, notes, priority, estimated_hours, due_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, task_type, task_instruction, verification_instruction, project_id, notes, priority, estimated_hours, due_date_str))
            
            # Record creation in history
            self._execute_insert(cursor, """
                INSERT INTO change_history (task_id, agent_id, change_type, notes)
                VALUES (?, ?, 'created', ?)
            """, (task_id, agent_id, notes))
            
            # Create initial version (version 1) before committing
            self._create_task_version(task_id, agent_id, conn)
            
            conn.commit()
            logger.info(f"Created task {task_id}: {title} by agent {agent_id}")
            
            return task_id
        finally:
            self.adapter.close(conn)
    
    def _find_tasks_with_blocked_subtasks_batch(self, task_ids: List[int]) -> set:
        """
        Efficiently find all tasks in the given list that have blocked subtasks (recursively).
        Uses batch queries instead of individual recursive checks to avoid N+1 problem.
        
        Args:
            task_ids: List of task IDs to check
            
        Returns:
            Set of task IDs that have blocked subtasks
        """
        if not task_ids:
            return set()
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Find all directly blocked tasks first
            cursor.execute("""
                SELECT id FROM tasks WHERE task_status = 'blocked'
            """)
            directly_blocked = {row[0] for row in cursor.fetchall()}
            
            # Find all parent tasks that have directly blocked children
            if directly_blocked:
                placeholders = ",".join("?" * len(directly_blocked))
                cursor.execute(f"""
                    SELECT DISTINCT parent_task_id 
                    FROM task_relationships 
                    WHERE relationship_type = 'subtask' 
                        AND child_task_id IN ({placeholders})
                """, list(directly_blocked))
                parent_ids = {row[0] for row in cursor.fetchall() if row[0] is not None}
            else:
                parent_ids = set()
            
            # Recursively find all ancestors (parents of parents, etc.)
            all_blocked_parents = parent_ids.copy()
            current_level = parent_ids
            
            # Traverse up the hierarchy (max depth limit for safety)
            max_depth = 100
            depth = 0
            while current_level and depth < max_depth:
                placeholders = ",".join("?" * len(current_level))
                cursor.execute(f"""
                    SELECT DISTINCT parent_task_id 
                    FROM task_relationships 
                    WHERE relationship_type = 'subtask' 
                        AND child_task_id IN ({placeholders})
                        AND parent_task_id IS NOT NULL
                """, list(current_level))
                next_level = {row[0] for row in cursor.fetchall() if row[0] is not None}
                next_level -= all_blocked_parents  # Only new ones
                current_level = next_level
                all_blocked_parents.update(next_level)
                depth += 1
            
            # Return intersection of requested task_ids and blocked parents
            return all_blocked_parents & set(task_ids)
        finally:
            self.adapter.close(conn)
    
    def _has_blocked_subtasks(self, task_id: int, visited: Optional[set] = None) -> bool:
        """
        Recursively check if a task has any blocked subtasks.
        For single task checks (used by get_task).
        
        Args:
            task_id: Task ID to check
            visited: Set of visited task IDs to prevent infinite loops
            
        Returns:
            True if any subtask (recursively) has status 'blocked', False otherwise
        """
        if visited is None:
            visited = set()
        
        # Prevent infinite loops (shouldn't happen with proper relationships, but safety check)
        if task_id in visited:
            return False
        visited.add(task_id)
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Find all subtasks of this task
            cursor.execute("""
                SELECT child_task_id 
                FROM task_relationships 
                WHERE parent_task_id = ? AND relationship_type = 'subtask'
            """, (task_id,))
            
            subtask_ids = [row[0] for row in cursor.fetchall()]
            
            # Check each subtask
            for subtask_id in subtask_ids:
                # Get subtask status
                cursor.execute("SELECT task_status FROM tasks WHERE id = ?", (subtask_id,))
                subtask_row = cursor.fetchone()
                if subtask_row:
                    subtask_status = subtask_row[0]
                    # If subtask is blocked, return True
                    if subtask_status == "blocked":
                        return True
                    # Recursively check if this subtask has blocked subtasks
                    if self._has_blocked_subtasks(subtask_id, visited.copy()):
                        return True
            
            return False
        finally:
            self.adapter.close(conn)
    
    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get a task by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                task = dict(row)
                # Check if task has blocked subtasks - if so, override status to blocked
                if self._has_blocked_subtasks(task_id):
                    task["task_status"] = "blocked"
                return task
            return None
        finally:
            self.adapter.close(conn)
    
    def _validate_github_url(self, url: str) -> bool:
        """Validate that URL is a valid GitHub issue or PR URL."""
        if not url or not isinstance(url, str):
            return False
        # Check for GitHub domain and either /issues/ or /pull/
        return "github.com" in url.lower() and ("/issues/" in url.lower() or "/pull/" in url.lower())
    
    def _get_task_metadata(self, task_id: int) -> Dict[str, Any]:
        """Get task metadata as a dictionary."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT metadata FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    return json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
                    return {}
            return {}
        finally:
            self.adapter.close(conn)
    
    def _set_task_metadata(self, task_id: int, metadata: Dict[str, Any]) -> None:
        """Set task metadata."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            metadata_json = json.dumps(metadata) if metadata else None
            cursor.execute("""
                UPDATE tasks 
                SET metadata = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (metadata_json, task_id))
            conn.commit()
            logger.info(f"Updated metadata for task {task_id}")
        finally:
            self.adapter.close(conn)
    
    def link_github_issue(self, task_id: int, github_url: str) -> None:
        """
        Link a GitHub issue to a task.
        
        Args:
            task_id: Task ID
            github_url: GitHub issue URL (e.g., https://github.com/owner/repo/issues/123)
            
        Raises:
            ValueError: If task not found or URL is invalid
        """
        if not self.get_task(task_id):
            raise ValueError(f"Task {task_id} not found")
        
        if not self._validate_github_url(github_url):
            raise ValueError("Invalid GitHub URL: must be a valid GitHub URL")
        if "/pull/" in github_url.lower():
            raise ValueError("Invalid GitHub URL: must be an issue URL (not PR)")
        
        metadata = self._get_task_metadata(task_id)
        metadata["github_issue_url"] = github_url
        self._set_task_metadata(task_id, metadata)
        logger.info(f"Linked GitHub issue {github_url} to task {task_id}")
    
    def link_github_pr(self, task_id: int, github_url: str) -> None:
        """
        Link a GitHub PR to a task.
        
        Args:
            task_id: Task ID
            github_url: GitHub PR URL (e.g., https://github.com/owner/repo/pull/456)
            
        Raises:
            ValueError: If task not found or URL is invalid
        """
        if not self.get_task(task_id):
            raise ValueError(f"Task {task_id} not found")
        
        if not self._validate_github_url(github_url):
            raise ValueError("Invalid GitHub URL: must be a valid GitHub URL")
        if "/issues/" in github_url.lower() and "/pull/" not in github_url.lower():
            raise ValueError("Invalid GitHub URL: must be a PR URL (not issue)")
        
        metadata = self._get_task_metadata(task_id)
        metadata["github_pr_url"] = github_url
        self._set_task_metadata(task_id, metadata)
        logger.info(f"Linked GitHub PR {github_url} to task {task_id}")
    
    def unlink_github_issue(self, task_id: int) -> None:
        """
        Unlink a GitHub issue from a task.
        
        Args:
            task_id: Task ID
            
        Raises:
            ValueError: If task not found
        """
        if not self.get_task(task_id):
            raise ValueError(f"Task {task_id} not found")
        
        metadata = self._get_task_metadata(task_id)
        metadata.pop("github_issue_url", None)
        self._set_task_metadata(task_id, metadata)
        logger.info(f"Unlinked GitHub issue from task {task_id}")
    
    def unlink_github_pr(self, task_id: int) -> None:
        """
        Unlink a GitHub PR from a task.
        
        Args:
            task_id: Task ID
            
        Raises:
            ValueError: If task not found
        """
        if not self.get_task(task_id):
            raise ValueError(f"Task {task_id} not found")
        
        metadata = self._get_task_metadata(task_id)
        metadata.pop("github_pr_url", None)
        self._set_task_metadata(task_id, metadata)
        logger.info(f"Unlinked GitHub PR from task {task_id}")
    
    def get_github_links(self, task_id: int) -> Dict[str, Optional[str]]:
        """
        Get GitHub issue and PR links for a task.
        
        Args:
            task_id: Task ID
            
        Returns:
            Dictionary with github_issue_url and github_pr_url keys
            
        Raises:
            ValueError: If task not found
        """
        if not self.get_task(task_id):
            raise ValueError(f"Task {task_id} not found")
        
        metadata = self._get_task_metadata(task_id)
        return {
            "github_issue_url": metadata.get("github_issue_url"),
            "github_pr_url": metadata.get("github_pr_url")
        }
    
    def query_tasks(
        self,
        task_type: Optional[str] = None,
        task_status: Optional[str] = None,
        assigned_agent: Optional[str] = None,
        project_id: Optional[int] = None,
        priority: Optional[str] = None,
        tag_id: Optional[int] = None,
        tag_ids: Optional[List[int]] = None,
        order_by: Optional[str] = None,
        has_due_date: Optional[bool] = None,
        limit: int = 100,
        # Advanced filtering: date ranges
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        updated_after: Optional[str] = None,
        updated_before: Optional[str] = None,
        completed_after: Optional[str] = None,
        completed_before: Optional[str] = None,
        # Advanced filtering: text search
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query tasks with filters including advanced date range and text search."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            if task_type:
                conditions.append("t.task_type = ?")
                params.append(task_type)
            # Handle task_status filter - if 'blocked', we'll add it after finding parents with blocked subtasks
            filter_task_status = task_status
            if task_status == "blocked":
                # Don't add task_status filter yet - we'll modify it to include parents with blocked subtasks
                pass
            elif task_status:
                conditions.append("t.task_status = ?")
                params.append(task_status)
            if assigned_agent:
                conditions.append("t.assigned_agent = ?")
                params.append(assigned_agent)
            if project_id is not None:
                conditions.append("t.project_id = ?")
                params.append(project_id)
            if priority:
                conditions.append("t.priority = ?")
                params.append(priority)
            
            # Handle due_date filtering
            if has_due_date is not None:
                if has_due_date:
                    conditions.append("t.due_date IS NOT NULL")
                else:
                    conditions.append("t.due_date IS NULL")
            
            # Handle date range filtering
            if created_after:
                conditions.append("t.created_at >= ?")
                params.append(created_after)
            if created_before:
                conditions.append("t.created_at <= ?")
                params.append(created_before)
            if updated_after:
                conditions.append("t.updated_at >= ?")
                params.append(updated_after)
            if updated_before:
                conditions.append("t.updated_at <= ?")
                params.append(updated_before)
            if completed_after:
                conditions.append("t.completed_at >= ?")
                params.append(completed_after)
            if completed_before:
                conditions.append("t.completed_at <= ?")
                params.append(completed_before)
            
            # Handle text search (case-insensitive search in title and task_instruction)
            if search:
                search_term = f"%{search.lower()}%"
                # SQLite LIKE is case-insensitive by default, but use LOWER for consistency
                conditions.append("(LOWER(t.title) LIKE ? OR LOWER(t.task_instruction) LIKE ?)")
                params.append(search_term)
                params.append(search_term)
            
            # Handle tag filtering
            join_clause = ""
            group_by_clause = ""
            if tag_id:
                join_clause = "INNER JOIN task_tags tt ON t.id = tt.task_id"
                conditions.append("tt.tag_id = ?")
                params.append(tag_id)
            elif tag_ids:
                # Multiple tags: task must have all specified tags
                join_clause = "INNER JOIN task_tags tt ON t.id = tt.task_id"
                placeholders = ",".join("?" * len(tag_ids))
                conditions.append(f"tt.tag_id IN ({placeholders})")
                params.extend(tag_ids)
                # Group by to ensure we get tasks that have all tags
                group_by_clause = "GROUP BY t.id HAVING COUNT(DISTINCT tt.tag_id) = ?"
                params.append(len(tag_ids))
            
            # If querying for task_status='blocked', also include tasks with blocked subtasks
            if filter_task_status == "blocked":
                # Get all tasks that have blocked subtasks (recursively)
                # First, find direct parents of blocked tasks
                cursor.execute("""
                    SELECT DISTINCT tr.parent_task_id as id
                    FROM task_relationships tr
                    JOIN tasks t_child ON tr.child_task_id = t_child.id
                    WHERE tr.relationship_type = 'subtask' 
                        AND t_child.task_status = 'blocked'
                """)
                all_blocked_parent_ids = {row[0] for row in cursor.fetchall()}
                
                # Recursively find grandparents, etc. with blocked descendants
                new_parents = all_blocked_parent_ids
                while new_parents:
                    placeholders = ",".join("?" * len(new_parents))
                    cursor.execute(f"""
                        SELECT DISTINCT tr.parent_task_id as id
                        FROM task_relationships tr
                        WHERE tr.relationship_type = 'subtask' 
                            AND tr.child_task_id IN ({placeholders})
                            AND tr.parent_task_id IS NOT NULL
                    """, list(new_parents))
                    next_level = {row[0] for row in cursor.fetchall() if row[0] is not None}
                    next_level -= all_blocked_parent_ids  # Only new ones
                    new_parents = next_level
                    all_blocked_parent_ids.update(next_level)
                
                # Add condition: task_status = 'blocked' OR id in (blocked parent ids)
                if all_blocked_parent_ids:
                    parent_placeholders = ",".join("?" * len(all_blocked_parent_ids))
                    conditions.append(f"(t.task_status = 'blocked' OR t.id IN ({parent_placeholders}))")
                    params.extend(all_blocked_parent_ids)
                else:
                    conditions.append("t.task_status = 'blocked'")
            
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            
            # Default ordering by created_at DESC
            order_clause = "ORDER BY t.created_at DESC"
            if order_by == "priority":
                # Order by priority: critical > high > medium > low
                order_clause = """ORDER BY 
                    CASE t.priority 
                        WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 1
                        ELSE 0
                    END DESC, t.created_at DESC"""
            elif order_by == "priority_asc":
                # Order by priority ascending: low > medium > high > critical
                order_clause = """ORDER BY 
                    CASE t.priority 
                        WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 1
                        ELSE 0
                    END ASC, t.created_at DESC"""
            
            params.append(limit)
            query = f"SELECT DISTINCT t.* FROM tasks t {join_clause} {where_clause} {group_by_clause} {order_clause} LIMIT ?"
            
            start_time = time.time()
            cursor.execute(query, params)
            tasks = [dict(row) for row in cursor.fetchall()]
            query_duration = time.time() - start_time
            
            if ENABLE_QUERY_LOGGING and query_duration >= QUERY_SLOW_THRESHOLD:
                logger.warning(f"query_tasks took {query_duration:.4f}s, returned {len(tasks)} tasks")
            
            # Batch check all tasks for blocked subtasks (much more efficient than individual checks)
            if tasks:
                task_ids = [task["id"] for task in tasks]
                blocked_parent_ids = self._find_tasks_with_blocked_subtasks_batch(task_ids)
                
                # Override status for tasks with blocked subtasks
                for task in tasks:
                    if task["id"] in blocked_parent_ids:
                        task["task_status"] = "blocked"
            
            # If filtering by task_status and we overrode some statuses, re-filter if needed
            if filter_task_status and filter_task_status != "blocked":
                # Only return tasks that match the requested status (after propagation check)
                tasks = [t for t in tasks if t["task_status"] == filter_task_status]
            
            return tasks
        finally:
            self.adapter.close(conn)
    
    def get_overdue_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get tasks that are overdue (due_date < current time and task_status != 'complete').
        
        Args:
            limit: Maximum number of results to return
            
        Returns:
            List of overdue task dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get tasks where due_date is in the past and task is not complete
            cursor.execute("""
                SELECT * FROM tasks
                WHERE due_date IS NOT NULL
                    AND due_date < datetime('now')
                    AND task_status != 'complete'
                ORDER BY due_date ASC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def get_tasks_approaching_deadline(self, days_ahead: int = 3, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get tasks that are approaching their deadline.
        
        Args:
            days_ahead: Number of days ahead to look for approaching deadlines (default: 3)
            limit: Maximum number of results to return
            
        Returns:
            List of task dictionaries with approaching deadlines
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get tasks where due_date is within the next N days and task is not complete
            cursor.execute("""
                SELECT * FROM tasks
                WHERE due_date IS NOT NULL
                    AND due_date >= datetime('now')
                    AND due_date <= datetime('now', '+' || ? || ' days')
                    AND task_status != 'complete'
                ORDER BY due_date ASC
                LIMIT ?
            """, (days_ahead, limit))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def search_tasks(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Search tasks using full-text search across title, task_instruction, and notes.
        Supports both SQLite (FTS5) and PostgreSQL (tsvector) backends.
        
        Args:
            query: Search query string
            limit: Maximum number of results to return
            
        Returns:
            List of task dictionaries ranked by relevance
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # If query is empty, return all tasks (fallback to regular query)
            if not query or not query.strip():
                query_sql = self._normalize_sql("""
                    SELECT * FROM tasks
                    ORDER BY created_at DESC
                    LIMIT ?
                """)
                self._execute_with_logging(cursor, query_sql, (limit,))
                return [dict(row) for row in cursor.fetchall()]
            
            search_query = query.strip()
            
            # Use different full-text search based on database backend
            if self.db_type == "postgresql":
                # PostgreSQL uses tsvector with GIN index
                # Use to_tsquery for proper query parsing
                query_sql = """
                    SELECT *
                    FROM tasks
                    WHERE fts_vector @@ to_tsquery('english', %s)
                    ORDER BY ts_rank(fts_vector, to_tsquery('english', %s)) DESC, created_at DESC
                    LIMIT %s
                """
                # Escape special characters for tsquery (replace spaces with & for AND, | for OR)
                # For simplicity, join words with & to require all terms
                tsquery = " & ".join(search_query.split())
                self._execute_with_logging(cursor, query_sql, (tsquery, tsquery, limit))
            else:
                # SQLite uses FTS5
                try:
                    # Use FTS5 MATCH with ranking
                    # Join with tasks table to get full task data
                    # bm25() provides BM25 ranking (lower is better, so we order ASC)
                    query_sql = """
                        SELECT t.*
                        FROM tasks t
                        JOIN tasks_fts fts ON t.id = fts.rowid
                        WHERE fts MATCH ?
                        ORDER BY bm25(fts) ASC, t.created_at DESC
                        LIMIT ?
                    """
                    self._execute_with_logging(cursor, query_sql, (search_query, limit))
                except sqlite3.OperationalError:
                    # If FTS5 isn't available or table doesn't exist, fall back to LIKE search
                    logger.warning(f"FTS5 search failed, falling back to LIKE")
                    search_pattern = f"%{search_query}%"
                    query_sql = """
                        SELECT * FROM tasks
                        WHERE title LIKE ? 
                           OR task_instruction LIKE ?
                           OR notes LIKE ?
                        ORDER BY created_at DESC
                        LIMIT ?
                    """
                    self._execute_with_logging(cursor, query_sql, (search_pattern, search_pattern, search_pattern, limit))
            
            results = []
            for row in cursor.fetchall():
                results.append(dict(row))
            
            return results
        except Exception as e:
            # Fallback to LIKE search for any errors
            logger.warning(f"Full-text search failed, falling back to LIKE: {e}")
            try:
                cursor = conn.cursor()
                search_pattern = f"%{query.strip()}%"
                query_sql = self._normalize_sql("""
                    SELECT * FROM tasks
                    WHERE title LIKE ? 
                       OR task_instruction LIKE ?
                       OR notes LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """)
                self._execute_with_logging(cursor, query_sql, (search_pattern, search_pattern, search_pattern, limit))
                return [dict(row) for row in cursor.fetchall()]
            except Exception as fallback_error:
                logger.error(f"LIKE search also failed: {fallback_error}")
                return []
        finally:
            self.adapter.close(conn)
    
    def lock_task(self, task_id: int, agent_id: str) -> bool:
        """Lock a task for an agent (set to in_progress). Returns True if successful."""
        if not agent_id:
            raise ValueError("agent_id is required for locking tasks")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get current status for history
            cursor.execute("SELECT task_status, assigned_agent FROM tasks WHERE id = ?", (task_id,))
            current = cursor.fetchone()
            old_status = current["task_status"] if current else None
            
            # Only lock if task is available
            # Set started_at only if it's NULL (first time locking)
            cursor.execute("""
                UPDATE tasks 
                SET task_status = 'in_progress', 
                    assigned_agent = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
                WHERE id = ? AND task_status = 'available'
            """, (agent_id, task_id))
            success = cursor.rowcount > 0
            
            if success:
                # Record in history
                cursor.execute("""
                    INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                    VALUES (?, ?, 'locked', 'task_status', ?, 'in_progress')
                """, (task_id, agent_id, old_status))
            
            conn.commit()
            if success:
                logger.info(f"Task {task_id} locked by agent {agent_id}")
            return success
        finally:
            self.adapter.close(conn)
    
    def unlock_task(self, task_id: int, agent_id: str):
        """Unlock a task (set back to available)."""
        if not agent_id:
            raise ValueError("agent_id is required for unlocking tasks")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get current assigned agent for verification
            cursor.execute("SELECT assigned_agent, task_status FROM tasks WHERE id = ?", (task_id,))
            current = cursor.fetchone()
            if not current:
                raise ValueError(f"Task {task_id} not found")
            
            old_status = current["task_status"]
            old_agent = current["assigned_agent"]
            
            cursor.execute("""
                UPDATE tasks 
                SET task_status = 'available',
                    assigned_agent = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (task_id,))
            
            # Record in history
            cursor.execute("""
                INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                VALUES (?, ?, 'unlocked', 'task_status', ?, 'available')
            """, (task_id, agent_id, old_status))
            
            conn.commit()
            logger.info(f"Task {task_id} unlocked by agent {agent_id}")
        finally:
            self.adapter.close(conn)
    
    def get_stale_tasks(self, hours: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get tasks that are stale (in_progress longer than timeout).
        
        Args:
            hours: Hours threshold for stale tasks (defaults to TASK_TIMEOUT_HOURS env var or 24)
            
        Returns:
            List of stale task dictionaries
        """
        # Get timeout from environment variable or use provided hours or default
        if hours is None:
            hours = int(os.getenv("TASK_TIMEOUT_HOURS", "24"))
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            if self.db_type == "sqlite":
                # SQLite: Use datetime subtraction with julianday
                cursor.execute("""
                    SELECT * FROM tasks
                    WHERE task_status = 'in_progress'
                    AND julianday('now') - julianday(updated_at) > ? / 24.0
                    ORDER BY updated_at ASC
                """, (hours,))
            else:
                # PostgreSQL: Use interval arithmetic with make_interval
                cursor.execute("""
                    SELECT * FROM tasks
                    WHERE task_status = 'in_progress'
                    AND updated_at < CURRENT_TIMESTAMP - make_interval(hours => ?)
                    ORDER BY updated_at ASC
                """, (hours,))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            self.adapter.close(conn)
    
    def unlock_stale_tasks(self, hours: Optional[int] = None, system_agent_id: str = "system") -> int:
        """
        Automatically unlock stale tasks (tasks in_progress longer than timeout).
        Creates a finding update for each unlocked task indicating it was stale.
        
        Args:
            hours: Hours threshold for stale tasks (defaults to TASK_TIMEOUT_HOURS env var or 24)
            system_agent_id: Agent ID to use for system unlocks (default: "system")
            
        Returns:
            Number of tasks unlocked
        """
        stale_tasks = self.get_stale_tasks(hours=hours)
        unlocked_count = 0
        
        for task in stale_tasks:
            task_id = task["id"]
            old_agent = task.get("assigned_agent", "unknown")
            
            # Unlock the task
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Update task status
                cursor.execute("""
                    UPDATE tasks 
                    SET task_status = 'available',
                        assigned_agent = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (task_id,))
                
                # Record in history
                cursor.execute("""
                    INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                    VALUES (?, ?, 'unlocked', 'task_status', 'in_progress', 'available')
                """, (task_id, system_agent_id,))
                
                # Add finding update indicating task was stale
                stale_message = f"Task automatically unlocked due to timeout. Previously assigned to agent '{old_agent}'. Task was in_progress for more than {hours} hours."
                metadata_json = json.dumps({"auto_unlocked": True, "previous_agent": old_agent, "timeout_hours": hours})
                cursor.execute("""
                    INSERT INTO change_history (task_id, agent_id, change_type, notes, new_value)
                    VALUES (?, ?, 'finding', ?, ?)
                """, (task_id, system_agent_id, stale_message, metadata_json,))
                
                conn.commit()
                unlocked_count += 1
                logger.info(f"Stale task {task_id} automatically unlocked (was assigned to {old_agent})")
            except Exception as e:
                logger.error(f"Error unlocking stale task {task_id}: {e}", exc_info=True)
                conn.rollback()
            finally:
                self.adapter.close(conn)
        
        return unlocked_count
    
    def complete_task(self, task_id: int, agent_id: str, notes: Optional[str] = None, actual_hours: Optional[float] = None):
        """Mark a task as complete and auto-complete parent tasks if all subtasks are done."""
        if not agent_id:
            raise ValueError("agent_id is required for completing tasks")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get current status, estimated_hours, and started_at for history and time calculation
            cursor.execute("SELECT task_status, estimated_hours, started_at FROM tasks WHERE id = ?", (task_id,))
            current = cursor.fetchone()
            old_status = current["task_status"] if current else None
            estimated_hours = current["estimated_hours"] if current else None
            started_at = current["started_at"] if current else None
            
            # If actual_hours is not provided but started_at exists, calculate from started_at to now
            if actual_hours is None and started_at is not None:
                if self.db_type == "sqlite":
                    # SQLite: Calculate hours using julianday
                    cursor.execute("""
                        SELECT (julianday('now') - julianday(started_at)) * 24 as calculated_hours
                        FROM tasks WHERE id = ?
                    """, (task_id,))
                else:
                    # PostgreSQL: Calculate hours using EXTRACT
                    cursor.execute("""
                        SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)) / 3600.0 as calculated_hours
                        FROM tasks WHERE id = ?
                    """, (task_id,))
                result = cursor.fetchone()
                if result and result["calculated_hours"] is not None:
                    actual_hours = float(result["calculated_hours"])
            
            # Calculate time_delta_hours if both estimated_hours and actual_hours are present
            time_delta_hours = None
            if actual_hours is not None and estimated_hours is not None:
                time_delta_hours = actual_hours - estimated_hours
            
            cursor.execute("""
                UPDATE tasks 
                SET task_status = 'complete',
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    notes = COALESCE(?, notes),
                    actual_hours = COALESCE(?, actual_hours),
                    time_delta_hours = COALESCE(?, time_delta_hours)
                WHERE id = ?
            """, (notes, actual_hours, time_delta_hours, task_id))
            
            # Record in history
            cursor.execute("""
                INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value, notes)
                VALUES (?, ?, 'completed', 'task_status', ?, 'complete', ?)
            """, (task_id, agent_id, old_status, notes))
            
            conn.commit()
            logger.info(f"Task {task_id} marked as complete by agent {agent_id}")
            
            # Auto-complete parent tasks if all subtasks are complete
            self._check_and_auto_complete_parents(task_id, agent_id)
        finally:
            self.adapter.close(conn)
    
    def _check_and_auto_complete_parents(self, completed_task_id: int, agent_id: str):
        """
        Check if parent tasks should be auto-completed when all their subtasks are done.
        This works recursively up the chain.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Find all parent tasks where this task is a subtask
            cursor.execute("""
                SELECT DISTINCT parent_task_id
                FROM task_relationships
                WHERE child_task_id = ? AND relationship_type = 'subtask'
            """, (completed_task_id,))
            
            parent_ids = [row[0] for row in cursor.fetchall()]
            
            for parent_id in parent_ids:
                # Get all sibling subtasks (including the one just completed)
                cursor.execute("""
                    SELECT child_task_id, task_status
                    FROM task_relationships tr
                    JOIN tasks t ON tr.child_task_id = t.id
                    WHERE tr.parent_task_id = ? AND tr.relationship_type = 'subtask'
                """, (parent_id,))
                
                siblings = cursor.fetchall()
                
                # Check if all sibling subtasks are complete
                all_complete = all(
                    row[1] == 'complete' 
                    for row in siblings
                )
                
                if all_complete:
                    # Get parent task to check current status
                    cursor.execute("SELECT task_status FROM tasks WHERE id = ?", (parent_id,))
                    parent_task = cursor.fetchone()
                    
                    if parent_task and parent_task[0] != 'complete':
                        # Auto-complete the parent
                        cursor.execute("""
                            UPDATE tasks 
                            SET task_status = 'complete',
                                completed_at = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (parent_id,))
                        
                        # Record in history
                        cursor.execute("""
                            INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value, notes)
                            VALUES (?, ?, 'completed', 'task_status', ?, 'complete', ?)
                        """, (parent_id, agent_id, parent_task[0], "Auto-completed: all subtasks are complete"))
                        
                        conn.commit()
                        logger.info(f"Parent task {parent_id} auto-completed (all subtasks complete) by agent {agent_id}")
                        
                        # Recursively check the parent's parents
                        self._check_and_auto_complete_parents(parent_id, agent_id)
        finally:
            self.adapter.close(conn)
    
    def verify_task(self, task_id: int, agent_id: str) -> bool:
        """Mark a task as verified (verification check passed)."""
        if not agent_id:
            raise ValueError("agent_id is required for verifying tasks")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get current verification status for history
            cursor.execute("SELECT verification_status FROM tasks WHERE id = ?", (task_id,))
            current = cursor.fetchone()
            old_status = current["verification_status"] if current else None
            
            cursor.execute("""
                UPDATE tasks 
                SET verification_status = 'verified',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (task_id,))
            
            # Record in history
            cursor.execute("""
                INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                VALUES (?, ?, 'verified', 'verification_status', ?, 'verified')
            """, (task_id, agent_id, old_status))
            
            conn.commit()
            logger.info(f"Task {task_id} verified by agent {agent_id}")
            return True
        finally:
            self.adapter.close(conn)
    
    def _check_circular_dependency(
        self,
        cursor: sqlite3.Cursor,
        blocker_task_id: int,
        blocked_task_id: int
    ) -> bool:
        """
        Check if creating a blocked_by relationship from blocked_task_id to blocker_task_id
        would create a circular dependency.
        
        Returns True if a circular dependency would be created, False otherwise.
        """
        # Use BFS to check if blocker_task_id (or anything it's blocked by) can reach blocked_task_id
        visited = set()
        queue = [blocker_task_id]
        
        while queue:
            current_task_id = queue.pop(0)
            
            # If we reach the blocked task, we have a cycle
            if current_task_id == blocked_task_id:
                return True
            
            if current_task_id in visited:
                continue
            visited.add(current_task_id)
            
            # Find all tasks that this task is blocked by
            cursor.execute("""
                SELECT child_task_id
                FROM task_relationships
                WHERE parent_task_id = ? AND relationship_type = 'blocked_by'
            """, (current_task_id,))
            
            blocking_tasks = [row[0] for row in cursor.fetchall()]
            
            # Also check for "blocking" relationships (which are inverse of blocked_by)
            cursor.execute("""
                SELECT parent_task_id
                FROM task_relationships
                WHERE child_task_id = ? AND relationship_type = 'blocking'
            """, (current_task_id,))
            
            # "blocking" relationship means: if A blocks B, then B is blocked_by A
            blocking_from_blocking = [row[0] for row in cursor.fetchall()]
            
            # Add all blocking tasks to the queue
            for task_id in blocking_tasks + blocking_from_blocking:
                if task_id not in visited:
                    queue.append(task_id)
        
        return False
    
    def create_relationship(
        self,
        parent_task_id: int,
        child_task_id: int,
        relationship_type: str,
        agent_id: str
    ) -> int:
        """Create a relationship between two tasks."""
        if not agent_id:
            raise ValueError("agent_id is required for creating relationships")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Check for circular dependencies for blocking relationships
            if relationship_type == "blocked_by":
                # parent_task_id is blocked by child_task_id
                # Check if child_task_id (or anything blocking it) can reach parent_task_id
                if self._check_circular_dependency(cursor, child_task_id, parent_task_id):
                    raise ValueError(
                        f"Circular dependency detected: Cannot create blocked_by relationship "
                        f"from task {parent_task_id} to task {child_task_id}. "
                        f"Task {child_task_id} (or something blocking it) already blocks task {parent_task_id}."
                    )
            elif relationship_type == "blocking":
                # parent_task_id blocks child_task_id (equivalent to child_task_id is blocked_by parent_task_id)
                # Check if parent_task_id (or anything blocking it) can reach child_task_id
                if self._check_circular_dependency(cursor, parent_task_id, child_task_id):
                    raise ValueError(
                        f"Circular dependency detected: Cannot create blocking relationship "
                        f"from task {parent_task_id} to task {child_task_id}. "
                        f"Task {parent_task_id} (or something blocking it) already blocks task {child_task_id}."
                    )
            
            rel_id = self._execute_insert(cursor, """
                INSERT INTO task_relationships (parent_task_id, child_task_id, relationship_type)
                VALUES (?, ?, ?)
            """, (parent_task_id, child_task_id, relationship_type))
            
            # Record in history for both tasks
            cursor.execute("""
                INSERT INTO change_history (task_id, agent_id, change_type, field_name, new_value)
                VALUES (?, ?, 'relationship_added', 'relationship', ?)
            """, (parent_task_id, agent_id, f"{relationship_type}:{child_task_id}"))
            
            # Auto-update blocking status
            if relationship_type == "blocked_by":
                cursor.execute("""
                    UPDATE tasks SET task_status = 'blocked', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (parent_task_id,))
            
            conn.commit()
            logger.info(f"Created relationship {relationship_type} from task {parent_task_id} to {child_task_id} by agent {agent_id}")
            return rel_id
        finally:
            self.adapter.close(conn)
    
    def get_change_history(
        self,
        task_id: Optional[int] = None,
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get change history with optional filters."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            if task_id:
                conditions.append("task_id = ?")
                params.append(task_id)
            if agent_id:
                conditions.append("agent_id = ?")
                params.append(agent_id)
            
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            query = f"SELECT * FROM change_history {where_clause} ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def get_activity_feed(
        self,
        task_id: Optional[int] = None,
        agent_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Get activity feed showing all task updates, completions, and relationship changes
        in chronological order.
        
        Args:
            task_id: Optional task ID to filter by (None for all tasks)
            agent_id: Optional agent ID to filter by
            start_date: Optional start date filter (ISO format string)
            end_date: Optional end date filter (ISO format string)
            limit: Maximum number of results to return
            
        Returns:
            List of activity entries in chronological order (oldest first)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            if task_id:
                conditions.append("ch.task_id = ?")
                params.append(task_id)
            if agent_id:
                conditions.append("ch.agent_id = ?")
                params.append(agent_id)
            if start_date:
                conditions.append("ch.created_at >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("ch.created_at <= ?")
                params.append(end_date)
            
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            
            # Query change_history with task title for context
            query = f"""
                SELECT 
                    ch.*,
                    t.title as task_title
                FROM change_history ch
                LEFT JOIN tasks t ON ch.task_id = t.id
                {where_clause}
                ORDER BY ch.created_at ASC
                LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            results = [dict(row) for row in cursor.fetchall()]
            return results
        finally:
            self.adapter.close(conn)
    
    def add_task_update(
        self,
        task_id: int,
        agent_id: str,
        content: str,
        update_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Add a task update (progress, note, blocker, question, finding).
        
        Args:
            task_id: Task ID
            agent_id: Agent ID making the update
            content: Update content
            update_type: Type of update (progress, note, blocker, question, finding)
            metadata: Optional metadata dictionary (stored as JSON in new_value)
            
        Returns:
            Update ID
        """
        if not agent_id:
            raise ValueError("agent_id is required for adding task updates")
        
        if update_type not in ["progress", "note", "blocker", "question", "finding"]:
            raise ValueError(f"Invalid update_type: {update_type}")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Store metadata as JSON string in new_value field
            metadata_json = None
            if metadata:
                metadata_json = json.dumps(metadata)
            
            update_id = self._execute_insert(cursor, """
                INSERT INTO change_history (task_id, agent_id, change_type, notes, new_value)
                VALUES (?, ?, ?, ?, ?)
            """, (task_id, agent_id, update_type, content, metadata_json))
            conn.commit()
            logger.info(f"Added {update_type} update {update_id} to task {task_id} by agent {agent_id}")
            return update_id
        finally:
            self.adapter.close(conn)
    
    def get_task_updates(self, task_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get task updates (progress, note, blocker, question, finding entries)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM change_history
                WHERE task_id = ? AND change_type IN ('progress', 'note', 'blocker', 'question', 'finding')
                ORDER BY created_at DESC
                LIMIT ?
            """, (task_id, limit))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def _create_task_version(self, task_id: int, agent_id: str, conn=None) -> int:
        """
        Create a new version snapshot of a task.
        
        Args:
            task_id: Task ID to version
            agent_id: Agent creating the version
            conn: Optional database connection (if provided, won't close it)
            
        Returns:
            Version number of the created version
        """
        should_close = conn is None
        if conn is None:
            conn = self._get_connection()
        
        try:
            cursor = conn.cursor()
            
            # Get the current task state
            cursor.execute("""
                SELECT 
                    title, task_type, task_instruction, verification_instruction,
                    task_status, verification_status, priority, assigned_agent,
                    notes, estimated_hours, actual_hours, time_delta_hours,
                    due_date, started_at, completed_at
                FROM tasks
                WHERE id = ?
            """, (task_id,))
            task = cursor.fetchone()
            
            if not task:
                raise ValueError(f"Task {task_id} not found")
            
            # Get the next version number
            cursor.execute("""
                SELECT COALESCE(MAX(version_number), 0) + 1 as next_version
                FROM task_versions
                WHERE task_id = ?
            """, (task_id,))
            result = cursor.fetchone()
            version_number = result["next_version"] if result else 1
            
            # Insert version
            cursor.execute("""
                INSERT INTO task_versions (
                    task_id, version_number, title, task_type, task_instruction,
                    verification_instruction, task_status, verification_status,
                    priority, assigned_agent, notes, estimated_hours, actual_hours,
                    time_delta_hours, due_date, started_at, completed_at, created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id, version_number,
                task["title"], task["task_type"], task["task_instruction"],
                task["verification_instruction"], task["task_status"], task["verification_status"],
                task["priority"], task["assigned_agent"], task["notes"],
                task["estimated_hours"], task["actual_hours"], task["time_delta_hours"],
                task["due_date"], task["started_at"], task["completed_at"],
                agent_id
            ))
            
            if should_close:
                conn.commit()
            logger.info(f"Created version {version_number} for task {task_id} by agent {agent_id}")
            
            return version_number
        finally:
            if should_close:
                self.adapter.close(conn)
    
    def get_task_versions(self, task_id: int) -> List[Dict[str, Any]]:
        """
        Get all versions for a task, ordered by version number (newest first).
        
        Args:
            task_id: Task ID
            
        Returns:
            List of version dictionaries, ordered by version_number DESC
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM task_versions
                WHERE task_id = ?
                ORDER BY version_number DESC
            """, (task_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def get_task_version(self, task_id: int, version_number: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific version of a task.
        
        Args:
            task_id: Task ID
            version_number: Version number to retrieve
            
        Returns:
            Version dictionary or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM task_versions
                WHERE task_id = ? AND version_number = ?
            """, (task_id, version_number))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            self.adapter.close(conn)
    
    def get_latest_task_version(self, task_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the latest version of a task.
        
        Args:
            task_id: Task ID
            
        Returns:
            Latest version dictionary or None if no versions exist
        """
        versions = self.get_task_versions(task_id)
        return versions[0] if versions else None
    
    def diff_task_versions(
        self,
        task_id: int,
        version_number_1: int,
        version_number_2: int
    ) -> Dict[str, Dict[str, Any]]:
        """
        Diff two task versions and return changed fields.
        
        Args:
            task_id: Task ID
            version_number_1: First version number (older, used as baseline)
            version_number_2: Second version number (newer, compared against baseline)
            
        Returns:
            Dictionary mapping field names to {old_value, new_value} dictionaries.
            Only includes fields that differ between versions.
        """
        version1 = self.get_task_version(task_id, version_number_1)
        version2 = self.get_task_version(task_id, version_number_2)
        
        if not version1 or not version2:
            raise ValueError(f"One or both versions not found: v{version_number_1}, v{version_number_2}")
        
        # Fields to compare
        fields_to_compare = [
            "title", "task_type", "task_instruction", "verification_instruction",
            "task_status", "verification_status", "priority", "assigned_agent",
            "notes", "estimated_hours", "actual_hours", "time_delta_hours",
            "due_date", "started_at", "completed_at"
        ]
        
        diff = {}
        for field in fields_to_compare:
            val1 = version1.get(field)
            val2 = version2.get(field)
            
            # Normalize None and empty strings for comparison
            if val1 is None:
                val1 = None
            if val2 is None:
                val2 = None
            
            # Compare values (handle date strings)
            if val1 != val2:
                diff[field] = {
                    "old_value": val1,
                    "new_value": val2,
                    "version_1": version_number_1,
                    "version_2": version_number_2
                }
        
        return diff
    
    def get_agent_stats(
        self,
        agent_id: str,
        task_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get statistics for an agent's performance."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Get completed tasks count
            completed_query = """
                SELECT COUNT(*) as count FROM change_history
                WHERE agent_id = ? AND change_type = 'completed'
            """
            params = [agent_id]
            if task_type:
                completed_query = """
                    SELECT COUNT(*) as count FROM change_history ch
                    JOIN tasks t ON ch.task_id = t.id
                    WHERE ch.agent_id = ? AND ch.change_type = 'completed' AND t.task_type = ?
                """
                params.append(task_type)
            
            cursor.execute(completed_query, params)
            completed = cursor.fetchone()["count"]
            
            # Get verified tasks count
            verified_query = """
                SELECT COUNT(*) as count FROM change_history
                WHERE agent_id = ? AND change_type = 'verified'
            """
            verified_params = [agent_id]
            if task_type:
                verified_query = """
                    SELECT COUNT(*) as count FROM change_history ch
                    JOIN tasks t ON ch.task_id = t.id
                    WHERE ch.agent_id = ? AND ch.change_type = 'verified' AND t.task_type = ?
                """
                verified_params.append(task_type)
            
            cursor.execute(verified_query, verified_params)
            verified = cursor.fetchone()["count"]
            
            # Get success rate (completed and verified)
            cursor.execute("""
                SELECT COUNT(DISTINCT ch1.task_id) as count FROM change_history ch1
                JOIN change_history ch2 ON ch1.task_id = ch2.task_id
                WHERE ch1.agent_id = ? AND ch1.change_type = 'completed'
                    AND ch2.agent_id = ? AND ch2.change_type = 'verified'
            """, (agent_id, agent_id))
            success_count = cursor.fetchone()["count"]
            
            # Get average time delta for completed tasks
            avg_delta_query = """
                SELECT AVG(t.time_delta_hours) as avg_delta FROM tasks t
                JOIN change_history ch ON t.id = ch.task_id
                WHERE ch.agent_id = ? AND ch.change_type = 'completed'
                    AND t.time_delta_hours IS NOT NULL
            """
            avg_delta_params = [agent_id]
            if task_type:
                avg_delta_query = """
                    SELECT AVG(t.time_delta_hours) as avg_delta FROM tasks t
                    JOIN change_history ch ON t.id = ch.task_id
                    WHERE ch.agent_id = ? AND ch.change_type = 'completed'
                        AND t.task_type = ? AND t.time_delta_hours IS NOT NULL
                """
                avg_delta_params.append(task_type)
            
            cursor.execute(avg_delta_query, avg_delta_params)
            avg_delta_result = cursor.fetchone()
            avg_time_delta = float(avg_delta_result["avg_delta"]) if avg_delta_result["avg_delta"] is not None else None
            
            return {
                "agent_id": agent_id,
                "tasks_completed": completed,
                "tasks_verified": verified,
                "success_rate": (success_count / completed * 100) if completed > 0 else 0.0,
                "avg_time_delta": avg_time_delta,
                "task_type_filter": task_type
            }
        finally:
            self.adapter.close(conn)
    
    def get_completion_rates(
        self,
        project_id: Optional[int] = None,
        task_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get completion rates for tasks."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            conditions = []
            params = []
            
            if project_id:
                conditions.append("project_id = ?")
                params.append(project_id)
            
            if task_type:
                conditions.append("task_type = ?")
                params.append(task_type)
            
            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
            
            # Get total tasks
            cursor.execute(f"SELECT COUNT(*) as count FROM tasks{where_clause}", params)
            total_tasks = cursor.fetchone()["count"]
            
            # Get completed tasks
            completed_params = params + ["complete"]
            cursor.execute(
                f"SELECT COUNT(*) as count FROM tasks{where_clause} AND task_status = ?",
                completed_params
            )
            completed_tasks = cursor.fetchone()["count"]
            
            # Calculate percentage
            completion_percentage = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
            
            # Get status breakdown
            status_params = params + []
            cursor.execute(
                f"""
                SELECT task_status, COUNT(*) as count 
                FROM tasks{where_clause}
                GROUP BY task_status
                """,
                status_params if where_clause else []
            )
            status_breakdown = {row["task_status"]: row["count"] for row in cursor.fetchall()}
            
            # Get type breakdown
            type_params = params + []
            cursor.execute(
                f"""
                SELECT task_type, COUNT(*) as count,
                       SUM(CASE WHEN task_status = 'complete' THEN 1 ELSE 0 END) as completed
                FROM tasks{where_clause}
                GROUP BY task_type
                """,
                type_params if where_clause else []
            )
            tasks_by_type = {}
            for row in cursor.fetchall():
                tasks_by_type[row["task_type"]] = {
                    "total": row["count"],
                    "completed": row["completed"],
                    "completion_percentage": (row["completed"] / row["count"] * 100) if row["count"] > 0 else 0.0
                }
            
            return {
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "completion_percentage": round(completion_percentage, 2),
                "status_breakdown": status_breakdown,
                "tasks_by_type": tasks_by_type
            }
        finally:
            self.adapter.close(conn)
    
    def get_average_time_to_complete(
        self,
        project_id: Optional[int] = None,
        task_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get average time to complete tasks (from created_at to completed_at)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            conditions = ["task_status = 'complete'", "completed_at IS NOT NULL", "created_at IS NOT NULL"]
            params = []
            
            if project_id:
                conditions.append("project_id = ?")
                params.append(project_id)
            
            if task_type:
                conditions.append("task_type = ?")
                params.append(task_type)
            
            where_clause = " WHERE " + " AND ".join(conditions)
            
            # Calculate average hours
            cursor.execute(
                f"""
                SELECT 
                    AVG((julianday(completed_at) - julianday(created_at)) * 24) as avg_hours,
                    COUNT(*) as completed_count,
                    MIN((julianday(completed_at) - julianday(created_at)) * 24) as min_hours,
                    MAX((julianday(completed_at) - julianday(created_at)) * 24) as max_hours
                FROM tasks
                {where_clause}
                """,
                params
            )
            result = cursor.fetchone()
            
            avg_hours = float(result["avg_hours"]) if result["avg_hours"] else None
            min_hours = float(result["min_hours"]) if result["min_hours"] else None
            max_hours = float(result["max_hours"]) if result["max_hours"] else None
            completed_count = result["completed_count"]
            
            return {
                "average_hours": round(avg_hours, 2) if avg_hours else None,
                "min_hours": round(min_hours, 2) if min_hours else None,
                "max_hours": round(max_hours, 2) if max_hours else None,
                "completed_count": completed_count
            }
        finally:
            self.adapter.close(conn)
    
    def get_bottlenecks(
        self,
        long_running_hours: float = 24.0,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Identify bottlenecks: long-running tasks and blocking tasks."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Find long-running in_progress tasks
            cursor.execute(
                """
                SELECT t.*, 
                       (julianday('now') - julianday(t.updated_at)) * 24 as hours_in_progress
                FROM tasks t
                WHERE t.task_status = 'in_progress'
                  AND (julianday('now') - julianday(t.updated_at)) * 24 > ?
                ORDER BY hours_in_progress DESC
                LIMIT ?
                """,
                (long_running_hours, limit)
            )
            long_running_tasks = [dict(row) for row in cursor.fetchall()]
            
            # Find tasks with blocking relationships
            cursor.execute(
                """
                SELECT DISTINCT t.*,
                       COUNT(DISTINCT tr2.id) as blocking_count
                FROM tasks t
                JOIN task_relationships tr1 ON t.id = tr1.child_task_id
                LEFT JOIN task_relationships tr2 ON t.id = tr2.child_task_id AND tr2.relationship_type = 'blocking'
                WHERE tr1.relationship_type = 'blocking'
                  AND t.task_status != 'complete'
                GROUP BY t.id
                ORDER BY blocking_count DESC, t.updated_at ASC
                LIMIT ?
                """,
                (limit,)
            )
            blocking_tasks = [dict(row) for row in cursor.fetchall()]
            
            # Find tasks blocked by incomplete tasks
            cursor.execute(
                """
                SELECT t.*, 
                       COUNT(DISTINCT tr.parent_task_id) as blockers_count
                FROM tasks t
                JOIN task_relationships tr ON t.id = tr.child_task_id
                JOIN tasks parent ON tr.parent_task_id = parent.id
                WHERE tr.relationship_type IN ('blocking', 'blocked_by')
                  AND parent.task_status != 'complete'
                  AND t.task_status != 'complete'
                GROUP BY t.id
                ORDER BY blockers_count DESC
                LIMIT ?
                """,
                (limit,)
            )
            blocked_tasks = [dict(row) for row in cursor.fetchall()]
            
            return {
                "long_running_tasks": long_running_tasks,
                "blocking_tasks": blocking_tasks,
                "blocked_tasks": blocked_tasks
            }
        finally:
            self.adapter.close(conn)
    
    def get_agent_comparisons(
        self,
        task_type: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get performance comparisons for all agents."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Get agent stats for all agents
            type_condition = "AND t.task_type = ?" if task_type else ""
            type_params = [task_type] if task_type else []
            
            cursor.execute(
                f"""
                SELECT 
                    ch.agent_id,
                    COUNT(DISTINCT CASE WHEN ch.change_type = 'completed' THEN ch.task_id END) as tasks_completed,
                    COUNT(DISTINCT CASE WHEN ch2.change_type = 'verified' THEN ch.task_id END) as tasks_verified,
                    AVG(CASE WHEN ch.change_type = 'completed' AND t.time_delta_hours IS NOT NULL 
                        THEN t.time_delta_hours END) as avg_time_delta,
                    AVG(CASE WHEN ch.change_type = 'completed' AND t.actual_hours IS NOT NULL 
                        THEN t.actual_hours END) as avg_actual_hours,
                    AVG(CASE WHEN ch.change_type = 'completed' AND t.estimated_hours IS NOT NULL 
                        THEN t.estimated_hours END) as avg_estimated_hours
                FROM change_history ch
                JOIN tasks t ON ch.task_id = t.id
                LEFT JOIN change_history ch2 ON ch.task_id = ch2.task_id AND ch2.change_type = 'verified'
                WHERE ch.change_type = 'completed'
                    {type_condition}
                GROUP BY ch.agent_id
                HAVING tasks_completed > 0
                ORDER BY tasks_completed DESC
                LIMIT ?
                """,
                type_params + [limit]
            )
            
            agents = []
            for row in cursor.fetchall():
                agent_data = {
                    "agent_id": row["agent_id"],
                    "tasks_completed": row["tasks_completed"],
                    "tasks_verified": row["tasks_verified"] or 0,
                    "avg_time_delta": round(float(row["avg_time_delta"]), 2) if row["avg_time_delta"] else None,
                    "avg_actual_hours": round(float(row["avg_actual_hours"]), 2) if row["avg_actual_hours"] else None,
                    "avg_estimated_hours": round(float(row["avg_estimated_hours"]), 2) if row["avg_estimated_hours"] else None
                }
                # Calculate success rate
                if agent_data["tasks_completed"] > 0:
                    agent_data["success_rate"] = round(
                        (agent_data["tasks_verified"] / agent_data["tasks_completed"]) * 100, 2
                    )
                else:
                    agent_data["success_rate"] = 0.0
                agents.append(agent_data)
            
            return {
                "agents": agents,
                "total_agents": len(agents),
                "task_type_filter": task_type
            }
        finally:
            self.adapter.close(conn)
    
    def get_visualization_data(
        self,
        project_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get data formatted for visualization/charts."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            conditions = []
            params = []
            
            if project_id:
                conditions.append("project_id = ?")
                params.append(project_id)
            
            if start_date:
                conditions.append("DATE(created_at) >= DATE(?)")
                params.append(start_date)
            
            if end_date:
                conditions.append("DATE(created_at) <= DATE(?)")
                params.append(end_date)
            
            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
            
            # Status distribution
            cursor.execute(
                f"""
                SELECT task_status, COUNT(*) as count
                FROM tasks
                {where_clause}
                GROUP BY task_status
                """,
                params if where_clause else []
            )
            status_distribution = {row["task_status"]: row["count"] for row in cursor.fetchall()}
            
            # Type distribution
            cursor.execute(
                f"""
                SELECT task_type, COUNT(*) as count
                FROM tasks
                {where_clause}
                GROUP BY task_type
                """,
                params if where_clause else []
            )
            type_distribution = {row["task_type"]: row["count"] for row in cursor.fetchall()}
            
            # Completion timeline (by day)
            timeline_conditions = ["completed_at IS NOT NULL"]
            timeline_params = []
            
            if project_id:
                timeline_conditions.append("project_id = ?")
                timeline_params.append(project_id)
            
            if start_date:
                timeline_conditions.append("DATE(completed_at) >= DATE(?)")
                timeline_params.append(start_date)
            
            if end_date:
                timeline_conditions.append("DATE(completed_at) <= DATE(?)")
                timeline_params.append(end_date)
            
            timeline_where = " WHERE " + " AND ".join(timeline_conditions)
            
            cursor.execute(
                f"""
                SELECT DATE(completed_at) as date, COUNT(*) as count
                FROM tasks
                {timeline_where}
                GROUP BY DATE(completed_at)
                ORDER BY date ASC
                """,
                timeline_params
            )
            completion_timeline = [
                {"date": row["date"], "count": row["count"]}
                for row in cursor.fetchall()
            ]
            
            # Priority distribution
            cursor.execute(
                f"""
                SELECT priority, COUNT(*) as count
                FROM tasks
                {where_clause}
                GROUP BY priority
                """,
                params if where_clause else []
            )
            priority_distribution = {row["priority"]: row["count"] for row in cursor.fetchall()}
            
            return {
                "status_distribution": status_distribution,
                "type_distribution": type_distribution,
                "priority_distribution": priority_distribution,
                "completion_timeline": completion_timeline
            }
        finally:
            self.adapter.close(conn)
    
    def get_related_tasks(self, task_id: int, relationship_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get tasks related to a given task."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = ["(parent_task_id = ? OR child_task_id = ?)"]
            params = [task_id, task_id]
            
            if relationship_type:
                conditions.append("relationship_type = ?")
                params.append(relationship_type)
            
            query = f"""
                SELECT tr.*, 
                       t1.title as parent_title,
                       t2.title as child_title
                FROM task_relationships tr
                JOIN tasks t1 ON tr.parent_task_id = t1.id
                JOIN tasks t2 ON tr.child_task_id = t2.id
                WHERE {' AND '.join(conditions)}
            """
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def get_blocking_tasks(self, task_id: int) -> List[Dict[str, Any]]:
        """Get tasks that are blocking the given task."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.* FROM tasks t
                JOIN task_relationships tr ON t.id = tr.parent_task_id
                WHERE tr.child_task_id = ? AND tr.relationship_type = 'blocked_by'
            """, (task_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def get_available_tasks_for_agent(
        self,
        agent_type: str,
        project_id: Optional[int] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get available tasks for an agent type.
        
        - 'breakdown': Returns abstract/epic tasks that need to be broken down
        - 'implementation': Returns concrete tasks ready for implementation
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            project_filter = "AND t.project_id = ?" if project_id is not None else ""
            params = []
            
            if project_id is not None:
                params.append(project_id)
            
            if agent_type == "breakdown":
                # Abstract or epic tasks that are available and have no blocking tasks
                cursor.execute(f"""
                    SELECT t.* FROM tasks t
                    LEFT JOIN task_relationships tr ON t.id = tr.child_task_id 
                        AND tr.relationship_type = 'blocked_by'
                    WHERE t.task_status = 'available'
                        AND t.task_type IN ('abstract', 'epic')
                        AND tr.id IS NULL
                        {project_filter}
                    ORDER BY t.created_at ASC
                    LIMIT ?
                """, params + [limit])
            elif agent_type == "implementation":
                # Concrete tasks that are available and have no blocking tasks
                cursor.execute(f"""
                    SELECT t.* FROM tasks t
                    LEFT JOIN task_relationships tr ON t.id = tr.child_task_id 
                        AND tr.relationship_type = 'blocked_by'
                    WHERE t.task_status = 'available'
                        AND t.task_type = 'concrete'
                        AND tr.id IS NULL
                        {project_filter}
                    ORDER BY t.created_at ASC
                    LIMIT ?
                """, params + [limit])
            else:
                return []
            
            tasks = [dict(row) for row in cursor.fetchall()]
            
            # Batch check for blocked subtasks (much more efficient than individual checks)
            if tasks:
                task_ids = [task["id"] for task in tasks]
                blocked_parent_ids = self._find_tasks_with_blocked_subtasks_batch(task_ids)
                
                # Filter out tasks that have blocked subtasks (they're effectively blocked)
                available_tasks = [
                    task for task in tasks 
                    if task["id"] not in blocked_parent_ids
                ]
            else:
                available_tasks = []
            
            return available_tasks
        finally:
            self.adapter.close(conn)
    
    # Tags methods
    def create_tag(self, name: str) -> int:
        """Create a tag (or return existing tag ID if name already exists)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Check if tag already exists
            cursor.execute("SELECT id FROM tags WHERE name = ?", (name,))
            existing = cursor.fetchone()
            if existing:
                return existing[0]
            
            # Create new tag
            tag_id = self._execute_insert(cursor, "INSERT INTO tags (name) VALUES (?)", (name,))
            conn.commit()
            logger.info(f"Created tag {tag_id}: {name}")
            return tag_id
        finally:
            self.adapter.close(conn)
    
    def get_tag(self, tag_id: int) -> Optional[Dict[str, Any]]:
        """Get a tag by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tags WHERE id = ?", (tag_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def get_tag_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a tag by name."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tags WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def list_tags(self) -> List[Dict[str, Any]]:
        """List all tags."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tags ORDER BY name ASC")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def assign_tag_to_task(self, task_id: int, tag_id: int):
        """Assign a tag to a task (idempotent - won't create duplicates)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Check if assignment already exists (UNIQUE constraint will prevent duplicates)
            cursor.execute("""
                INSERT OR IGNORE INTO task_tags (task_id, tag_id)
                VALUES (?, ?)
            """, (task_id, tag_id))
            conn.commit()
            logger.info(f"Assigned tag {tag_id} to task {task_id}")
        finally:
            self.adapter.close(conn)
    
    def remove_tag_from_task(self, task_id: int, tag_id: int):
        """Remove a tag from a task."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM task_tags
                WHERE task_id = ? AND tag_id = ?
            """, (task_id, tag_id))
            conn.commit()
            logger.info(f"Removed tag {tag_id} from task {task_id}")
        finally:
            self.adapter.close(conn)
    
    def get_task_tags(self, task_id: int) -> List[Dict[str, Any]]:
        """Get all tags assigned to a task."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT t.* FROM tags t
                INNER JOIN task_tags tt ON t.id = tt.tag_id
                WHERE tt.task_id = ?
                ORDER BY t.name ASC
            """, (task_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def delete_tag(self, tag_id: int):
        """Delete a tag (cascades to task_tags via foreign key)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
            conn.commit()
            logger.info(f"Deleted tag {tag_id}")
        finally:
            self.adapter.close(conn)
    
    # Task templates methods
    def create_template(
        self,
        name: str,
        task_type: str,
        task_instruction: str,
        verification_instruction: str,
        description: Optional[str] = None,
        priority: Optional[str] = None,
        estimated_hours: Optional[float] = None,
        notes: Optional[str] = None
    ) -> int:
        """Create a new task template and return its ID."""
        if priority is None:
            priority = "medium"
        if priority not in ["low", "medium", "high", "critical"]:
            raise ValueError(f"Invalid priority: {priority}. Must be one of: low, medium, high, critical")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            template_id = self._execute_insert(cursor, """
                INSERT INTO task_templates (name, description, task_type, task_instruction, 
                                          verification_instruction, priority, estimated_hours, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, description, task_type, task_instruction, verification_instruction, 
                  priority, estimated_hours, notes))
            conn.commit()
            logger.info(f"Created template {template_id}: {name}")
            return template_id
        finally:
            self.adapter.close(conn)
    
    def get_template(self, template_id: int) -> Optional[Dict[str, Any]]:
        """Get a template by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_templates WHERE id = ?", (template_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def get_template_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a template by name."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_templates WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def list_templates(self, task_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all templates, optionally filtered by task_type."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if task_type:
                cursor.execute("""
                    SELECT * FROM task_templates 
                    WHERE task_type = ?
                    ORDER BY name ASC
                """, (task_type,))
            else:
                cursor.execute("""
                    SELECT * FROM task_templates 
                    ORDER BY name ASC
                """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def create_task_from_template(
        self,
        template_id: int,
        agent_id: str,
        title: Optional[str] = None,
        project_id: Optional[int] = None,
        notes: Optional[str] = None,
        priority: Optional[str] = None,
        estimated_hours: Optional[float] = None,
        due_date: Optional[datetime] = None
    ) -> int:
        """Create a task from a template with pre-filled instructions."""
        # Get template
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        # Use template values as defaults, but allow overrides
        task_title = title if title else template["name"]
        task_type = template["task_type"]
        task_instruction = template["task_instruction"]
        verification_instruction = template["verification_instruction"]
        task_priority = priority if priority is not None else template["priority"]
        task_estimated_hours = estimated_hours if estimated_hours is not None else template.get("estimated_hours")
        
        # Combine template notes with provided notes
        combined_notes = None
        if template.get("notes") and notes:
            combined_notes = f"{template['notes']}\n\n{notes}"
        elif template.get("notes"):
            combined_notes = template["notes"]
        elif notes:
            combined_notes = notes
        
        # Create the task using existing create_task method
        return self.create_task(
            title=task_title,
            task_type=task_type,
            task_instruction=task_instruction,
            verification_instruction=verification_instruction,
            agent_id=agent_id,
            project_id=project_id,
            notes=combined_notes,
            priority=task_priority,
            estimated_hours=task_estimated_hours,
            due_date=due_date
        )
    
    # Webhook methods
    def create_webhook(
        self,
        project_id: int,
        url: str,
        events: List[str],
        secret: Optional[str] = None,
        enabled: bool = True,
        retry_count: int = 3,
        timeout_seconds: int = 10
    ) -> int:
        """Create a webhook for a project and return its ID."""
        import json
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Store events as JSON array
            events_json = json.dumps(events)
            
            webhook_id = self._execute_insert(cursor, """
                INSERT INTO webhooks (project_id, url, events, secret, enabled, retry_count, timeout_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (project_id, url, events_json, secret, 1 if enabled else 0, retry_count, timeout_seconds))
            conn.commit()
            logger.info(f"Created webhook {webhook_id} for project {project_id}")
            return webhook_id
        finally:
            self.adapter.close(conn)
    
    def get_webhook(self, webhook_id: int) -> Optional[Dict[str, Any]]:
        """Get a webhook by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,))
            row = cursor.fetchone()
            if row:
                webhook = dict(row)
                # Parse events JSON
                import json
                webhook["events"] = json.loads(webhook["events"])
                webhook["enabled"] = bool(webhook["enabled"])
                return webhook
            return None
        finally:
            self.adapter.close(conn)
    
    def list_webhooks(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """List webhooks, optionally filtered by project."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            import json
            
            if project_id is not None:
                cursor.execute("SELECT * FROM webhooks WHERE project_id = ? ORDER BY created_at DESC", (project_id,))
            else:
                cursor.execute("SELECT * FROM webhooks ORDER BY created_at DESC")
            
            webhooks = []
            for row in cursor.fetchall():
                webhook = dict(row)
                webhook["events"] = json.loads(webhook["events"])
                webhook["enabled"] = bool(webhook["enabled"])
                webhooks.append(webhook)
            
            return webhooks
        finally:
            self.adapter.close(conn)
    
    def get_webhooks_for_event(self, project_id: Optional[int], event_type: str) -> List[Dict[str, Any]]:
        """Get all enabled webhooks that are subscribed to a specific event type."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            import json
            
            # Get all enabled webhooks for the project (or all if project_id is None)
            if project_id is not None:
                cursor.execute("SELECT * FROM webhooks WHERE project_id = ? AND enabled = 1", (project_id,))
            else:
                cursor.execute("SELECT * FROM webhooks WHERE enabled = 1")
            
            webhooks = []
            for row in cursor.fetchall():
                webhook = dict(row)
                events = json.loads(webhook["events"])
                # Check if this webhook subscribes to the event
                if event_type in events:
                    webhook["events"] = events
                    webhook["enabled"] = bool(webhook["enabled"])
                    webhooks.append(webhook)
            
            return webhooks
        finally:
            self.adapter.close(conn)
    
    def delete_webhook(self, webhook_id: int):
        """Delete a webhook."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
            conn.commit()
            logger.info(f"Deleted webhook {webhook_id}")
        finally:
            self.adapter.close(conn)
    
    def record_webhook_delivery(
        self,
        webhook_id: int,
        event_type: str,
        payload: str,
        status: str,
        response_code: Optional[int] = None,
        response_body: Optional[str] = None,
        attempt_number: int = 1
    ) -> int:
        """Record a webhook delivery attempt."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Use None for failed attempts, CURRENT_TIMESTAMP for success
            if status == "success":
                delivery_id = self._execute_insert(cursor, """
                    INSERT INTO webhook_deliveries 
                    (webhook_id, event_type, payload, status, response_code, response_body, attempt_number, delivered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (webhook_id, event_type, payload, status, response_code, response_body, attempt_number))
            else:
                delivery_id = self._execute_insert(cursor, """
                    INSERT INTO webhook_deliveries 
                    (webhook_id, event_type, payload, status, response_code, response_body, attempt_number, delivered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """, (webhook_id, event_type, payload, status, response_code, response_body, attempt_number))
            conn.commit()
            return delivery_id
        finally:
            self.adapter.close(conn)
    
    def export_tasks(
        self,
        task_type: Optional[str] = None,
        task_status: Optional[str] = None,
        project_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 10000
    ) -> List[Dict[str, Any]]:
        """
        Export tasks with all their fields, relationships, and tags.
        
        Args:
            task_type: Filter by task type
            task_status: Filter by task status
            project_id: Filter by project ID
            start_date: Filter by start date (ISO format)
            end_date: Filter by end date (ISO format)
            limit: Maximum number of tasks to export
            
        Returns:
            List of task dictionaries with relationships and tags
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            if task_type:
                conditions.append("t.task_type = ?")
                params.append(task_type)
            if task_status:
                conditions.append("t.task_status = ?")
                params.append(task_status)
            if project_id is not None:
                conditions.append("t.project_id = ?")
                params.append(project_id)
            if start_date:
                conditions.append("t.created_at >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("t.created_at <= ?")
                params.append(end_date)
            
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            query = f"SELECT t.* FROM tasks t {where_clause} ORDER BY t.created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            tasks = [dict(row) for row in cursor.fetchall()]
            
            # Enrich each task with relationships and tags
            for task in tasks:
                task_id = task["id"]
                
                # Get relationships where this task is parent or child
                relationships = self.get_related_tasks(task_id)
                task["relationships"] = []
                for rel in relationships:
                    if rel["parent_task_id"] == task_id:
                        # This task is the parent
                        task["relationships"].append({
                            "type": rel["relationship_type"],
                            "direction": "parent",
                            "related_task_id": rel["child_task_id"],
                            "related_task_title": rel.get("child_title")
                        })
                    else:
                        # This task is the child
                        task["relationships"].append({
                            "type": rel["relationship_type"],
                            "direction": "child",
                            "related_task_id": rel["parent_task_id"],
                            "related_task_title": rel.get("parent_title")
                        })
                
                # Get tags
                tags = self.get_task_tags(task_id)
                task["tags"] = [{"id": t["id"], "name": t["name"]} for t in tags]
                
                # Convert None values to empty strings for cleaner export (except for numeric fields)
                numeric_fields = ["id", "project_id", "estimated_hours", "actual_hours", "time_delta_hours"]
                for key in task:
                    if task[key] is None:
                        if key in ["relationships", "tags"]:
                            continue  # Already initialized as lists
                        if key not in numeric_fields:
                            task[key] = ""
                        # Keep None for numeric fields - let CSV/JSON handle it
            
            return tasks
        finally:
            self.adapter.close(conn)
    
    # File attachment methods
    def create_attachment(
        self,
        task_id: int,
        filename: str,
        original_filename: str,
        file_path: str,
        file_size: int,
        content_type: str,
        uploaded_by: str,
        description: Optional[str] = None
    ) -> int:
        """Create a file attachment record and return its ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            attachment_id = self._execute_insert(cursor, """
                INSERT INTO file_attachments 
                (task_id, filename, original_filename, file_path, file_size, content_type, description, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (task_id, filename, original_filename, file_path, file_size, content_type, description, uploaded_by))
            conn.commit()
            logger.info(f"Created attachment {attachment_id} for task {task_id}")
            return attachment_id
        finally:
            self.adapter.close(conn)
    
    def get_attachment(self, attachment_id: int) -> Optional[Dict[str, Any]]:
        """Get an attachment by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM file_attachments WHERE id = ?", (attachment_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def get_task_attachments(self, task_id: int) -> List[Dict[str, Any]]:
        """Get all attachments for a task."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM file_attachments 
                WHERE task_id = ? 
                ORDER BY created_at DESC
            """, (task_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def delete_attachment(self, attachment_id: int) -> bool:
        """Delete an attachment record. Returns True if successful."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get file path before deleting record
            cursor.execute("SELECT file_path FROM file_attachments WHERE id = ?", (attachment_id,))
            row = cursor.fetchone()
            file_path = row[0] if row else None
            
            cursor.execute("DELETE FROM file_attachments WHERE id = ?", (attachment_id,))
            success = cursor.rowcount > 0
            conn.commit()
            
            if success and file_path:
                # Delete file from disk
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"Deleted attachment file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete attachment file {file_path}: {e}")
            
            logger.info(f"Deleted attachment {attachment_id}")
            return success
        finally:
            self.adapter.close(conn)
    
    def get_attachment_by_task_and_id(self, task_id: int, attachment_id: int) -> Optional[Dict[str, Any]]:
        """Get an attachment by task ID and attachment ID (for security)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM file_attachments 
                WHERE id = ? AND task_id = ?
            """, (attachment_id, task_id))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    # Task comments methods
    def create_comment(
        self,
        task_id: int,
        agent_id: str,
        content: str,
        parent_comment_id: Optional[int] = None,
        mentions: Optional[List[str]] = None
    ) -> int:
        """Create a comment on a task and return its ID."""
        if not agent_id:
            raise ValueError("agent_id is required for creating comments")
        if not content or not content.strip():
            raise ValueError("comment content cannot be empty")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Verify task exists
            cursor.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
            if not cursor.fetchone():
                raise ValueError(f"Task {task_id} not found")
            
            # Verify parent comment exists if provided
            if parent_comment_id:
                cursor.execute("SELECT id FROM task_comments WHERE id = ?", (parent_comment_id,))
                if not cursor.fetchone():
                    raise ValueError(f"Parent comment {parent_comment_id} not found")
            
            # Store mentions as JSON
            mentions_json = None
            if mentions:
                mentions_json = json.dumps(mentions)
            
            comment_id = self._execute_insert(cursor, """
                INSERT INTO task_comments (task_id, agent_id, content, parent_comment_id, mentions)
                VALUES (?, ?, ?, ?, ?)
            """, (task_id, agent_id, content.strip(), parent_comment_id, mentions_json))
            conn.commit()
            logger.info(f"Created comment {comment_id} on task {task_id} by agent {agent_id}")
            return comment_id
        finally:
            self.adapter.close(conn)
    
    def get_comment(self, comment_id: int) -> Optional[Dict[str, Any]]:
        """Get a comment by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM task_comments WHERE id = ?", (comment_id,))
            row = cursor.fetchone()
            if row:
                comment = dict(row)
                # Parse mentions JSON
                if comment.get("mentions"):
                    try:
                        comment["mentions"] = json.loads(comment["mentions"])
                    except (json.JSONDecodeError, TypeError):
                        comment["mentions"] = []
                else:
                    comment["mentions"] = []
                return comment
            return None
        finally:
            self.adapter.close(conn)
    
    def get_task_comments(self, task_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all top-level comments for a task (not replies)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM task_comments
                WHERE task_id = ? AND parent_comment_id IS NULL
                ORDER BY created_at DESC
                LIMIT ?
            """, (task_id, limit))
            comments = []
            for row in cursor.fetchall():
                comment = dict(row)
                # Parse mentions JSON
                if comment.get("mentions"):
                    try:
                        comment["mentions"] = json.loads(comment["mentions"])
                    except (json.JSONDecodeError, TypeError):
                        comment["mentions"] = []
                else:
                    comment["mentions"] = []
                comments.append(comment)
            return comments
        finally:
            self.adapter.close(conn)
    
    def get_comment_thread(self, parent_comment_id: int) -> List[Dict[str, Any]]:
        """Get a comment thread (parent comment and all its replies)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get parent
            cursor.execute("SELECT * FROM task_comments WHERE id = ?", (parent_comment_id,))
            parent_row = cursor.fetchone()
            if not parent_row:
                return []
            
            # Get all replies
            cursor.execute("""
                SELECT * FROM task_comments
                WHERE parent_comment_id = ?
                ORDER BY created_at ASC
            """, (parent_comment_id,))
            
            thread = [dict(parent_row)]
            for row in cursor.fetchall():
                comment = dict(row)
                # Parse mentions JSON
                if comment.get("mentions"):
                    try:
                        comment["mentions"] = json.loads(comment["mentions"])
                    except (json.JSONDecodeError, TypeError):
                        comment["mentions"] = []
                else:
                    comment["mentions"] = []
                thread.append(comment)
            
            # Also parse mentions for parent
            if thread[0].get("mentions"):
                try:
                    thread[0]["mentions"] = json.loads(thread[0]["mentions"])
                except (json.JSONDecodeError, TypeError):
                    thread[0]["mentions"] = []
            else:
                thread[0]["mentions"] = []
            
            return thread
        finally:
            self.adapter.close(conn)
    
    def update_comment(self, comment_id: int, agent_id: str, content: str) -> bool:
        """Update a comment. Returns True if successful."""
        if not agent_id:
            raise ValueError("agent_id is required for updating comments")
        if not content or not content.strip():
            raise ValueError("comment content cannot be empty")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Verify comment exists and is owned by agent
            cursor.execute("SELECT agent_id FROM task_comments WHERE id = ?", (comment_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Comment {comment_id} not found")
            if row[0] != agent_id:
                raise ValueError(f"Comment {comment_id} is owned by {row[0]}, not {agent_id}")
            
            cursor.execute("""
                UPDATE task_comments
                SET content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (content.strip(), comment_id))
            
            success = cursor.rowcount > 0
            conn.commit()
            if success:
                logger.info(f"Updated comment {comment_id} by agent {agent_id}")
            return success
        finally:
            self.adapter.close(conn)
    
    def delete_comment(self, comment_id: int, agent_id: str) -> bool:
        """Delete a comment. Returns True if successful. Cascades to replies."""
        if not agent_id:
            raise ValueError("agent_id is required for deleting comments")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Verify comment exists and is owned by agent
            cursor.execute("SELECT agent_id FROM task_comments WHERE id = ?", (comment_id,))
            row = cursor.fetchone()
            if not row:
                return False
            if row[0] != agent_id:
                raise ValueError(f"Comment {comment_id} is owned by {row[0]}, not {agent_id}")
            
            # Delete comment (cascade will delete replies)
            cursor.execute("DELETE FROM task_comments WHERE id = ?", (comment_id,))
            success = cursor.rowcount > 0
            conn.commit()
            if success:
                logger.info(f"Deleted comment {comment_id} by agent {agent_id}")
            return success
        finally:
            self.adapter.close(conn)
    
    # Bulk operations methods
    def bulk_complete_tasks(
        self,
        task_ids: List[int],
        agent_id: str,
        notes: Optional[str] = None,
        actual_hours: Optional[float] = None,
        require_all: bool = False
    ) -> Dict[str, Any]:
        """
        Bulk complete multiple tasks.
        
        Args:
            task_ids: List of task IDs to complete
            agent_id: Agent ID performing the operation
            notes: Optional notes for completion
            actual_hours: Optional actual hours worked
            require_all: If True, all tasks must succeed or none will be completed (transaction)
            
        Returns:
            Dictionary with success status, completed count, and failed task IDs
        """
        if not agent_id:
            raise ValueError("agent_id is required for bulk operations")
        if not task_ids:
            raise ValueError("task_ids cannot be empty")
        
        conn = self._get_connection()
        completed = []
        failed = []
        
        try:
            cursor = conn.cursor()
            
            if require_all:
                # Transaction mode: all or nothing
                cursor.execute("BEGIN TRANSACTION")
                try:
                    for task_id in task_ids:
                        try:
                            # Get current status
                            cursor.execute("SELECT task_status, estimated_hours FROM tasks WHERE id = ?", (task_id,))
                            current = cursor.fetchone()
                            if not current:
                                raise ValueError(f"Task {task_id} not found")
                            
                            old_status = current["task_status"]
                            estimated_hours = current["estimated_hours"]
                            
                            # Calculate time_delta_hours
                            time_delta_hours = None
                            if actual_hours is not None and estimated_hours is not None:
                                time_delta_hours = actual_hours - estimated_hours
                            
                            # Complete task
                            cursor.execute("""
                                UPDATE tasks 
                                SET task_status = 'complete',
                                    completed_at = CURRENT_TIMESTAMP,
                                    updated_at = CURRENT_TIMESTAMP,
                                    notes = COALESCE(?, notes),
                                    actual_hours = COALESCE(?, actual_hours),
                                    time_delta_hours = COALESCE(?, time_delta_hours)
                                WHERE id = ?
                            """, (notes, actual_hours, time_delta_hours, task_id))
                            
                            if cursor.rowcount == 0:
                                raise ValueError(f"Task {task_id} could not be completed")
                            
                            # Record in history
                            cursor.execute("""
                                INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value, notes)
                                VALUES (?, ?, 'completed', 'task_status', ?, 'complete', ?)
                            """, (task_id, agent_id, old_status, notes))
                            
                            completed.append(task_id)
                            
                            # Auto-complete parent tasks if all subtasks are complete
                            self._check_and_auto_complete_parents(task_id, agent_id)
                        except Exception as e:
                            conn.rollback()
                            logger.error(f"Bulk complete failed for task {task_id}: {e}")
                            raise
                    
                    conn.commit()
                    logger.info(f"Bulk completed {len(completed)} tasks by agent {agent_id}")
                    return {
                        "success": True,
                        "completed": len(completed),
                        "failed": len(failed),
                        "task_ids": completed,
                        "failed_task_ids": failed
                    }
                except Exception:
                    conn.rollback()
                    raise
            else:
                # Best-effort mode: complete as many as possible
                for task_id in task_ids:
                    try:
                        # Get current status
                        cursor.execute("SELECT task_status, estimated_hours FROM tasks WHERE id = ?", (task_id,))
                        current = cursor.fetchone()
                        if not current:
                            failed.append(task_id)
                            continue
                        
                        old_status = current["task_status"]
                        estimated_hours = current["estimated_hours"]
                        
                        # Calculate time_delta_hours
                        time_delta_hours = None
                        if actual_hours is not None and estimated_hours is not None:
                            time_delta_hours = actual_hours - estimated_hours
                        
                        # Complete task
                        cursor.execute("""
                            UPDATE tasks 
                            SET task_status = 'complete',
                                completed_at = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP,
                                notes = COALESCE(?, notes),
                                actual_hours = COALESCE(?, actual_hours),
                                time_delta_hours = COALESCE(?, time_delta_hours)
                            WHERE id = ?
                        """, (notes, actual_hours, time_delta_hours, task_id))
                        
                        if cursor.rowcount == 0:
                            failed.append(task_id)
                            continue
                        
                        # Record in history
                        cursor.execute("""
                            INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value, notes)
                            VALUES (?, ?, 'completed', 'task_status', ?, 'complete', ?)
                        """, (task_id, agent_id, old_status, notes))
                        
                        completed.append(task_id)
                        
                        # Auto-complete parent tasks if all subtasks are complete
                        self._check_and_auto_complete_parents(task_id, agent_id)
                    except Exception as e:
                        logger.warning(f"Failed to complete task {task_id}: {e}")
                        failed.append(task_id)
                
                conn.commit()
                logger.info(f"Bulk completed {len(completed)} tasks (failed: {len(failed)}) by agent {agent_id}")
                return {
                    "success": True,
                    "completed": len(completed),
                    "failed": len(failed),
                    "task_ids": completed,
                    "failed_task_ids": failed
                }
        finally:
            self.adapter.close(conn)
    
    def bulk_assign_tasks(
        self,
        task_ids: List[int],
        agent_id: str,
        require_all: bool = False
    ) -> Dict[str, Any]:
        """
        Bulk assign (lock) multiple tasks to an agent.
        
        Args:
            task_ids: List of task IDs to assign
            agent_id: Agent ID to assign tasks to
            require_all: If True, all tasks must succeed or none will be assigned (transaction)
            
        Returns:
            Dictionary with success status, assigned count, and failed task IDs
        """
        if not agent_id:
            raise ValueError("agent_id is required for bulk operations")
        if not task_ids:
            raise ValueError("task_ids cannot be empty")
        
        conn = self._get_connection()
        assigned = []
        failed = []
        
        try:
            cursor = conn.cursor()
            
            if require_all:
                # Transaction mode: all or nothing
                cursor.execute("BEGIN TRANSACTION")
                try:
                    for task_id in task_ids:
                        try:
                            # Get current status
                            cursor.execute("SELECT task_status, assigned_agent FROM tasks WHERE id = ?", (task_id,))
                            current = cursor.fetchone()
                            if not current:
                                raise ValueError(f"Task {task_id} not found")
                            
                            old_status = current["task_status"]
                            
                            # Only assign if task is available
                            cursor.execute("""
                                UPDATE tasks 
                                SET task_status = 'in_progress', 
                                    assigned_agent = ?,
                                    updated_at = CURRENT_TIMESTAMP,
                                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
                                WHERE id = ? AND task_status = 'available'
                            """, (agent_id, task_id))
                            
                            if cursor.rowcount == 0:
                                raise ValueError(f"Task {task_id} is not available for assignment")
                            
                            # Record in history
                            cursor.execute("""
                                INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                                VALUES (?, ?, 'locked', 'task_status', ?, 'in_progress')
                            """, (task_id, agent_id, old_status))
                            
                            assigned.append(task_id)
                        except Exception as e:
                            conn.rollback()
                            logger.error(f"Bulk assign failed for task {task_id}: {e}")
                            raise
                    
                    conn.commit()
                    logger.info(f"Bulk assigned {len(assigned)} tasks to agent {agent_id}")
                    return {
                        "success": True,
                        "assigned": len(assigned),
                        "failed": len(failed),
                        "task_ids": assigned,
                        "failed_task_ids": failed
                    }
                except Exception:
                    conn.rollback()
                    raise
            else:
                # Best-effort mode: assign as many as possible
                for task_id in task_ids:
                    try:
                        # Get current status
                        cursor.execute("SELECT task_status, assigned_agent FROM tasks WHERE id = ?", (task_id,))
                        current = cursor.fetchone()
                        if not current:
                            failed.append(task_id)
                            continue
                        
                        old_status = current["task_status"]
                        
                        # Only assign if task is available
                        cursor.execute("""
                            UPDATE tasks 
                            SET task_status = 'in_progress', 
                                assigned_agent = ?,
                                updated_at = CURRENT_TIMESTAMP,
                                started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
                            WHERE id = ? AND task_status = 'available'
                        """, (agent_id, task_id))
                        
                        if cursor.rowcount == 0:
                            failed.append(task_id)
                            continue
                        
                        # Record in history
                        cursor.execute("""
                            INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                            VALUES (?, ?, 'locked', 'task_status', ?, 'in_progress')
                        """, (task_id, agent_id, old_status))
                        
                        assigned.append(task_id)
                    except Exception as e:
                        logger.warning(f"Failed to assign task {task_id}: {e}")
                        failed.append(task_id)
                
                conn.commit()
                logger.info(f"Bulk assigned {len(assigned)} tasks (failed: {len(failed)}) to agent {agent_id}")
                return {
                    "success": True,
                    "assigned": len(assigned),
                    "failed": len(failed),
                    "task_ids": assigned,
                    "failed_task_ids": failed
                }
        finally:
            self.adapter.close(conn)
    
    def bulk_update_status(
        self,
        task_ids: List[int],
        task_status: str,
        agent_id: str,
        require_all: bool = False
    ) -> Dict[str, Any]:
        """
        Bulk update status of multiple tasks.
        
        Args:
            task_ids: List of task IDs to update
            task_status: New task status
            agent_id: Agent ID performing the operation
            require_all: If True, all tasks must succeed or none will be updated (transaction)
            
        Returns:
            Dictionary with success status, updated count, and failed task IDs
        """
        if not agent_id:
            raise ValueError("agent_id is required for bulk operations")
        if not task_ids:
            raise ValueError("task_ids cannot be empty")
        if task_status not in ["available", "in_progress", "complete", "blocked", "cancelled"]:
            raise ValueError(f"Invalid task_status: {task_status}")
        
        conn = self._get_connection()
        updated = []
        failed = []
        
        try:
            cursor = conn.cursor()
            
            if require_all:
                # Transaction mode: all or nothing
                cursor.execute("BEGIN TRANSACTION")
                try:
                    for task_id in task_ids:
                        try:
                            # Get current status
                            cursor.execute("SELECT task_status FROM tasks WHERE id = ?", (task_id,))
                            current = cursor.fetchone()
                            if not current:
                                raise ValueError(f"Task {task_id} not found")
                            
                            old_status = current["task_status"]
                            
                            # Update status
                            cursor.execute("""
                                UPDATE tasks 
                                SET task_status = ?,
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE id = ?
                            """, (task_status, task_id))
                            
                            if cursor.rowcount == 0:
                                raise ValueError(f"Task {task_id} could not be updated")
                            
                            # Record in history
                            cursor.execute("""
                                INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                                VALUES (?, ?, 'status_changed', 'task_status', ?, ?)
                            """, (task_id, agent_id, old_status, task_status))
                            
                            updated.append(task_id)
                        except Exception as e:
                            conn.rollback()
                            logger.error(f"Bulk update status failed for task {task_id}: {e}")
                            raise
                    
                    conn.commit()
                    logger.info(f"Bulk updated status for {len(updated)} tasks by agent {agent_id}")
                    return {
                        "success": True,
                        "updated": len(updated),
                        "failed": len(failed),
                        "task_ids": updated,
                        "failed_task_ids": failed
                    }
                except Exception:
                    conn.rollback()
                    raise
            else:
                # Best-effort mode: update as many as possible
                for task_id in task_ids:
                    try:
                        # Get current status
                        cursor.execute("SELECT task_status FROM tasks WHERE id = ?", (task_id,))
                        current = cursor.fetchone()
                        if not current:
                            failed.append(task_id)
                            continue
                        
                        old_status = current["task_status"]
                        
                        # Update status
                        cursor.execute("""
                            UPDATE tasks 
                            SET task_status = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (task_status, task_id))
                        
                        if cursor.rowcount == 0:
                            failed.append(task_id)
                            continue
                        
                        # Record in history
                        cursor.execute("""
                            INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                            VALUES (?, ?, 'status_changed', 'task_status', ?, ?)
                        """, (task_id, agent_id, old_status, task_status))
                        
                        updated.append(task_id)
                    except Exception as e:
                        logger.warning(f"Failed to update status for task {task_id}: {e}")
                        failed.append(task_id)
                
                conn.commit()
                logger.info(f"Bulk updated status for {len(updated)} tasks (failed: {len(failed)}) by agent {agent_id}")
                return {
                    "success": True,
                    "updated": len(updated),
                    "failed": len(failed),
                    "task_ids": updated,
                    "failed_task_ids": failed
                }
        finally:
            self.adapter.close(conn)
    
    def bulk_delete_tasks(
        self,
        task_ids: List[int],
        require_all: bool = False
    ) -> Dict[str, Any]:
        """
        Bulk delete multiple tasks.
        
        Args:
            task_ids: List of task IDs to delete
            require_all: If True, all tasks must succeed or none will be deleted (transaction)
            
        Returns:
            Dictionary with success status, deleted count, and failed task IDs
        """
        if not task_ids:
            raise ValueError("task_ids cannot be empty")
        
        conn = self._get_connection()
        deleted = []
        failed = []
        
        try:
            cursor = conn.cursor()
            
            if require_all:
                # Transaction mode: all or nothing
                cursor.execute("BEGIN TRANSACTION")
                try:
                    for task_id in task_ids:
                        try:
                            # Verify task exists
                            cursor.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
                            if not cursor.fetchone():
                                raise ValueError(f"Task {task_id} not found")
                            
                            # Delete task (cascade will handle relationships, comments, etc.)
                            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                            
                            if cursor.rowcount == 0:
                                raise ValueError(f"Task {task_id} could not be deleted")
                            
                            deleted.append(task_id)
                        except Exception as e:
                            conn.rollback()
                            logger.error(f"Bulk delete failed for task {task_id}: {e}")
                            raise
                    
                    conn.commit()
                    logger.info(f"Bulk deleted {len(deleted)} tasks")
                    return {
                        "success": True,
                        "deleted": len(deleted),
                        "failed": len(failed),
                        "task_ids": deleted,
                        "failed_task_ids": failed
                    }
                except Exception:
                    conn.rollback()
                    raise
            else:
                # Best-effort mode: delete as many as possible
                for task_id in task_ids:
                    try:
                        # Verify task exists
                        cursor.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
                        if not cursor.fetchone():
                            failed.append(task_id)
                            continue
                        
                        # Delete task (cascade will handle relationships, comments, etc.)
                        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                        
                        if cursor.rowcount == 0:
                            failed.append(task_id)
                            continue
                        
                        deleted.append(task_id)
                    except Exception as e:
                        logger.warning(f"Failed to delete task {task_id}: {e}")
                        failed.append(task_id)
                
                conn.commit()
                logger.info(f"Bulk deleted {len(deleted)} tasks (failed: {len(failed)})")
                return {
                    "success": True,
                    "deleted": len(deleted),
                    "failed": len(failed),
                    "task_ids": deleted,
                    "failed_task_ids": failed
                }
        finally:
            self.adapter.close(conn)

    # User Management Methods
    
    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt."""
        import bcrypt
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against its hash."""
        import bcrypt
        try:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except Exception:
            return False
    
    def _generate_session_token(self) -> str:
        """Generate a secure random session token."""
        return secrets.token_urlsafe(32)
    
    def create_user(self, username: str, email: str, password: str) -> int:
        """
        Create a new user account.
        
        Args:
            username: Unique username
            email: Unique email address
            password: Plain text password (will be hashed)
            
        Returns:
            User ID of created user
            
        Raises:
            ValueError: If username or email already exists, or password is invalid
        """
        # Validate password strength (minimum 8 characters)
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        
        # Check if username or email already exists
        if self.get_user_by_username(username):
            raise ValueError(f"Username '{username}' already exists")
        if self.get_user_by_email(email):
            raise ValueError(f"Email '{email}' already exists")
        
        password_hash = self._hash_password(password)
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            user_id = self._execute_insert(cursor, """
                INSERT INTO users (username, email, password_hash)
                VALUES (?, ?, ?)
            """, (username, email, password_hash))
            conn.commit()
            logger.info(f"Created user {user_id} with username '{username}'")
            return user_id
        finally:
            self.adapter.close(conn)
    
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, username, email, password_hash, created_at, updated_at, last_login_at
                FROM users
                WHERE username = ?
            """)
            self._execute_with_logging(cursor, query, (username,))
            row = cursor.fetchone()
            if not row:
                return None
            
            return {
                "id": row[0],
                "username": row[1],
                "email": row[2],
                "password_hash": row[3],
                "created_at": row[4],
                "updated_at": row[5],
                "last_login_at": row[6]
            }
        finally:
            self.adapter.close(conn)
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, username, email, password_hash, created_at, updated_at, last_login_at
                FROM users
                WHERE email = ?
            """)
            self._execute_with_logging(cursor, query, (email,))
            row = cursor.fetchone()
            if not row:
                return None
            
            return {
                "id": row[0],
                "username": row[1],
                "email": row[2],
                "password_hash": row[3],
                "created_at": row[4],
                "updated_at": row[5],
                "last_login_at": row[6]
            }
        finally:
            self.adapter.close(conn)
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, username, email, password_hash, created_at, updated_at, last_login_at
                FROM users
                WHERE id = ?
            """)
            self._execute_with_logging(cursor, query, (user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            return {
                "id": row[0],
                "username": row[1],
                "email": row[2],
                "password_hash": row[3],
                "created_at": row[4],
                "updated_at": row[5],
                "last_login_at": row[6]
            }
        finally:
            self.adapter.close(conn)
    
    def list_users(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List users."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, username, email, created_at, updated_at, last_login_at
                FROM users
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """)
            self._execute_with_logging(cursor, query, (limit, offset))
            rows = cursor.fetchall()
            
            users = []
            for row in rows:
                users.append({
                    "id": row[0],
                    "username": row[1],
                    "email": row[2],
                    "created_at": row[3],
                    "updated_at": row[4],
                    "last_login_at": row[5]
                })
            return users
        finally:
            self.adapter.close(conn)
    
    def update_user(self, user_id: int, username: Optional[str] = None, email: Optional[str] = None) -> bool:
        """
        Update user information.
        
        Args:
            user_id: User ID
            username: New username (optional)
            email: New email (optional)
            
        Returns:
            True if updated successfully
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            updates = []
            params = []
            
            if username:
                # Check if username is already taken
                existing = self.get_user_by_username(username)
                if existing and existing["id"] != user_id:
                    raise ValueError(f"Username '{username}' already exists")
                updates.append("username = ?")
                params.append(username)
            
            if email:
                # Check if email is already taken
                existing = self.get_user_by_email(email)
                if existing and existing["id"] != user_id:
                    raise ValueError(f"Email '{email}' already exists")
                updates.append("email = ?")
                params.append(email)
            
            if not updates:
                return False
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(user_id)
            
            query = self._normalize_sql(f"""
                UPDATE users
                SET {', '.join(updates)}
                WHERE id = ?
            """)
            self._execute_with_logging(cursor, query, tuple(params))
            conn.commit()
            
            return cursor.rowcount > 0
        finally:
            self.adapter.close(conn)
    
    def delete_user(self, user_id: int) -> bool:
        """Delete a user account (cascades to sessions)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("DELETE FROM users WHERE id = ?")
            self._execute_with_logging(cursor, query, (user_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            self.adapter.close(conn)
    
    def authenticate_user(self, username_or_email: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Authenticate a user with username/email and password.
        
        Args:
            username_or_email: Username or email address
            password: Plain text password
            
        Returns:
            User dict if authentication succeeds, None otherwise
        """
        # Try username first, then email
        user = self.get_user_by_username(username_or_email)
        if not user:
            user = self.get_user_by_email(username_or_email)
        
        if not user:
            return None
        
        if not self._verify_password(password, user["password_hash"]):
            return None
        
        # Update last login timestamp
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                UPDATE users
                SET last_login_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """)
            self._execute_with_logging(cursor, query, (user["id"],))
            conn.commit()
        finally:
            self.adapter.close(conn)
        
        # Return user without password hash
        user.pop("password_hash", None)
        return user
    
    def create_session(self, user_id: int, expires_hours: int = 24) -> Tuple[str, datetime]:
        """
        Create a new session for a user.
        
        Args:
            user_id: User ID
            expires_hours: Hours until session expires (default 24)
            
        Returns:
            Tuple of (session_token, expires_at datetime)
        """
        session_token = self._generate_session_token()
        expires_at_dt = datetime.now()
        expires_at_dt = datetime.fromtimestamp(expires_at_dt.timestamp() + (expires_hours * 3600))
        expires_at_str = expires_at_dt.strftime("%Y-%m-%d %H:%M:%S")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            self._execute_insert(cursor, """
                INSERT INTO user_sessions (user_id, session_token, expires_at)
                VALUES (?, ?, ?)
            """, (user_id, session_token, expires_at_str))
            conn.commit()
            logger.info(f"Created session for user {user_id}")
            return session_token, expires_at_dt
        finally:
            self.adapter.close(conn)
    
    def get_session_by_token(self, session_token: str) -> Optional[Dict[str, Any]]:
        """Get session by token, checking expiration."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, user_id, session_token, expires_at, created_at, last_used_at
                FROM user_sessions
                WHERE session_token = ? AND expires_at > CURRENT_TIMESTAMP
            """)
            self._execute_with_logging(cursor, query, (session_token,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            # Update last_used_at
            cursor.execute("""
                UPDATE user_sessions
                SET last_used_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (row[0],))
            conn.commit()
            
            return {
                "id": row[0],
                "user_id": row[1],
                "session_token": row[2],
                "expires_at": row[3],
                "created_at": row[4],
                "last_used_at": row[5]
            }
        finally:
            self.adapter.close(conn)
    
    def expire_session(self, session_token: str) -> bool:
        """Expire a session immediately (for testing or logout)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                UPDATE user_sessions
                SET expires_at = CURRENT_TIMESTAMP
                WHERE session_token = ?
            """)
            self._execute_with_logging(cursor, query, (session_token,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            self.adapter.close(conn)
    
    def delete_session(self, session_token: str) -> bool:
        """Delete a session."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("DELETE FROM user_sessions WHERE session_token = ?")
            self._execute_with_logging(cursor, query, (session_token,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            self.adapter.close(conn)
    
    def clean_expired_sessions(self) -> int:
        """Delete expired sessions. Returns number of deleted sessions."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("DELETE FROM user_sessions WHERE expires_at <= CURRENT_TIMESTAMP")
            self._execute_with_logging(cursor, query)
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired sessions")
            return deleted_count
        finally:
            self.adapter.close(conn)

    # API Key Management Methods

    def _hash_api_key(self, api_key: str) -> str:
        """Hash an API key using SHA-256."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def _generate_api_key(self) -> str:
        """Generate a secure random API key."""
        return secrets.token_urlsafe(32)  # 32 bytes = 43 characters base64url

    def create_api_key(self, project_id: int, name: str) -> Tuple[int, str]:
        """
        Create a new API key for a project.
        
        Args:
            project_id: Project ID
            name: User-friendly name for the key
            
        Returns:
            Tuple of (key_id, full_api_key)
        """
        # Verify project exists
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        
        # Generate key
        full_key = self._generate_api_key()
        key_hash = self._hash_api_key(full_key)
        key_prefix = full_key[:8]  # First 8 characters for display
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            key_id = self._execute_insert(cursor, """
                INSERT INTO api_keys (project_id, key_hash, key_prefix, name)
                VALUES (?, ?, ?, ?)
            """, (project_id, key_hash, key_prefix, name))
            conn.commit()
            logger.info(f"Created API key {key_id} for project {project_id}")
            return key_id, full_key
        finally:
            self.adapter.close(conn)

    def get_api_key_by_hash(self, key_hash: str) -> Optional[Dict[str, Any]]:
        """
        Get API key information by its hash.
        
        Args:
            key_hash: Hashed API key
            
        Returns:
            API key dictionary or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, project_id, key_hash, key_prefix, name, enabled,
                       created_at, updated_at, last_used_at
                FROM api_keys
                WHERE key_hash = ?
            """, (key_hash,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "key_hash": row["key_hash"],
                    "key_prefix": row["key_prefix"],
                    "name": row["name"],
                    "enabled": row["enabled"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "last_used_at": row["last_used_at"]
                }
            return None
        finally:
            self.adapter.close(conn)

    def list_api_keys(self, project_id: int) -> List[Dict[str, Any]]:
        """
        List all API keys for a project.
        
        Args:
            project_id: Project ID
            
        Returns:
            List of API key dictionaries (without full key)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, project_id, key_prefix, name, enabled,
                       created_at, updated_at, last_used_at
                FROM api_keys
                WHERE project_id = ?
                ORDER BY created_at DESC
            """, (project_id,))
            keys = []
            for row in cursor.fetchall():
                keys.append({
                    "key_id": row["id"],
                    "project_id": row["project_id"],
                    "key_prefix": row["key_prefix"],
                    "name": row["name"],
                    "enabled": row["enabled"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "last_used_at": row["last_used_at"]
                })
            return keys
        finally:
            self.adapter.close(conn)

    def revoke_api_key(self, key_id: int) -> bool:
        """
        Revoke (disable) an API key.
        
        Args:
            key_id: API key ID
            
        Returns:
            True if successful, False if key not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE api_keys
                SET enabled = 0, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (key_id,))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Revoked API key {key_id}")
                return True
            return False
        finally:
            self.adapter.close(conn)

    def rotate_api_key(self, key_id: int) -> Tuple[int, str]:
        """
        Rotate an API key (create new, revoke old).
        
        Args:
            key_id: API key ID to rotate
            
        Returns:
            Tuple of (new_key_id, new_full_api_key)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get existing key info
            cursor.execute("""
                SELECT project_id, name FROM api_keys WHERE id = ?
            """, (key_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"API key {key_id} not found")
            
            project_id = row["project_id"]
            name = row["name"]
            
            # Create new key
            new_key_id, new_key = self.create_api_key(project_id, f"{name} (rotated)")
            
            # Revoke old key
            self.revoke_api_key(key_id)
            
            logger.info(f"Rotated API key {key_id} -> {new_key_id}")
            return new_key_id, new_key
        finally:
            self.adapter.close(conn)

    def update_api_key_last_used(self, key_id: int):
        """
        Update the last_used_at timestamp for an API key.
        
        Args:
            key_id: API key ID
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE api_keys
                SET last_used_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (key_id,))
            conn.commit()
        finally:
            self.adapter.close(conn)

    def is_api_key_admin(self, key_id: int) -> bool:
        """
        Check if an API key has admin privileges.
        
        Args:
            key_id: API key ID
            
        Returns:
            True if key is admin, False otherwise
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT is_admin FROM api_keys WHERE id = ? AND enabled = 1
            """)
            self._execute_with_logging(cursor, query, (key_id,))
            row = cursor.fetchone()
            if row:
                return bool(row["is_admin"])
            return False
        finally:
            self.adapter.close(conn)

    # ===== Admin Methods =====
    
    def block_agent(self, agent_id: str, reason: Optional[str], blocked_by: str) -> bool:
        """
        Block an agent from using the service.
        
        Args:
            agent_id: Agent ID to block
            reason: Optional reason for blocking
            blocked_by: Who is blocking the agent (API key name or user)
            
        Returns:
            True if agent was blocked, False if already blocked
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Check if already blocked
            existing = self.get_agent_block_status(agent_id)
            if existing:
                # Update existing block
                query = self._normalize_sql("""
                    UPDATE blocked_agents
                    SET reason = ?, blocked_by = ?, unblocked_at = NULL
                    WHERE agent_id = ? AND unblocked_at IS NULL
                """)
                self._execute_with_logging(cursor, query, (reason, blocked_by, agent_id))
            else:
                # Insert new block
                query = self._normalize_sql("""
                    INSERT INTO blocked_agents (agent_id, reason, blocked_by)
                    VALUES (?, ?, ?)
                """)
                self._execute_with_logging(cursor, query, (agent_id, reason, blocked_by))
            
            conn.commit()
            logger.info(f"Blocked agent {agent_id} by {blocked_by}")
            return True
        except Exception as e:
            logger.error(f"Failed to block agent {agent_id}: {e}", exc_info=True)
            return False
        finally:
            self.adapter.close(conn)

    def unblock_agent(self, agent_id: str) -> bool:
        """
        Unblock an agent.
        
        Args:
            agent_id: Agent ID to unblock
            
        Returns:
            True if agent was unblocked, False if not blocked
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                UPDATE blocked_agents
                SET unblocked_at = CURRENT_TIMESTAMP
                WHERE agent_id = ? AND unblocked_at IS NULL
            """)
            self._execute_with_logging(cursor, query, (agent_id,))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Unblocked agent {agent_id}")
                return True
            return False
        finally:
            self.adapter.close(conn)

    def is_agent_blocked(self, agent_id: str) -> bool:
        """
        Check if an agent is blocked.
        
        Args:
            agent_id: Agent ID to check
            
        Returns:
            True if agent is blocked, False otherwise
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id FROM blocked_agents
                WHERE agent_id = ? AND unblocked_at IS NULL
            """)
            self._execute_with_logging(cursor, query, (agent_id,))
            row = cursor.fetchone()
            return row is not None
        finally:
            self.adapter.close(conn)

    def get_agent_block_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get agent block status with details.
        
        Args:
            agent_id: Agent ID to check
            
        Returns:
            Dictionary with block info or None if not blocked
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT agent_id, reason, blocked_by, created_at, unblocked_at
                FROM blocked_agents
                WHERE agent_id = ? AND unblocked_at IS NULL
            """)
            self._execute_with_logging(cursor, query, (agent_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "agent_id": row["agent_id"],
                    "reason": row["reason"],
                    "blocked_by": row["blocked_by"],
                    "created_at": row["created_at"],
                    "blocked": True
                }
            return None
        finally:
            self.adapter.close(conn)

    def list_blocked_agents(self) -> List[Dict[str, Any]]:
        """
        List all currently blocked agents.
        
        Returns:
            List of blocked agent dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT agent_id, reason, blocked_by, created_at
                FROM blocked_agents
                WHERE unblocked_at IS NULL
                ORDER BY created_at DESC
            """)
            self._execute_with_logging(cursor, query)
            agents = []
            for row in cursor.fetchall():
                agents.append({
                    "agent_id": row["agent_id"],
                    "reason": row["reason"],
                    "blocked_by": row["blocked_by"],
                    "created_at": row["created_at"],
                    "blocked": True
                })
            return agents
        finally:
            self.adapter.close(conn)

    def add_audit_log(
        self,
        action: str,
        actor: str,
        actor_type: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[str] = None,
        ip_address: Optional[str] = None
    ):
        """
        Add an entry to the audit log.
        
        Args:
            action: Action performed (e.g., 'agent.blocked', 'conversation.cleared')
            actor: Who performed the action (API key name, user ID, etc.)
            actor_type: Type of actor ('api_key', 'user', 'system')
            target_type: Type of target (optional, e.g., 'agent', 'conversation')
            target_id: ID of target (optional)
            details: Additional details (optional, JSON string)
            ip_address: IP address of request (optional)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                INSERT INTO audit_logs (action, actor, actor_type, target_type, target_id, details, ip_address)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """)
            self._execute_with_logging(cursor, query, (
                action, actor, actor_type, target_type, target_id, details, ip_address
            ))
            conn.commit()
        finally:
            self.adapter.close(conn)

    def get_audit_logs(
        self,
        limit: int = 100,
        action: Optional[str] = None,
        actor: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get audit logs.
        
        Args:
            limit: Maximum number of logs to return
            action: Filter by action (optional)
            actor: Filter by actor (optional)
            
        Returns:
            List of audit log entries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            if action:
                conditions.append("action = ?")
                params.append(action)
            if actor:
                conditions.append("actor = ?")
                params.append(actor)
            
            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)
            
            query = self._normalize_sql(f"""
                SELECT action, actor, actor_type, target_type, target_id, details, ip_address, created_at
                FROM audit_logs
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
            """)
            params.append(limit)
            self._execute_with_logging(cursor, query, tuple(params))
            
            logs = []
            for row in cursor.fetchall():
                logs.append({
                    "action": row["action"],
                    "actor": row["actor"],
                    "actor_type": row["actor_type"],
                    "target_type": row["target_type"],
                    "target_id": row["target_id"],
                    "details": row["details"],
                    "ip_address": row["ip_address"],
                    "created_at": row["created_at"]
                })
            return logs
        finally:
            self.adapter.close(conn)

    def get_system_status(self) -> Dict[str, Any]:
        """
        Get system status information.
        
        Returns:
            Dictionary with system status details
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Database connection status
            database_status = {"connected": True}
            
            # Task statistics
            query = self._normalize_sql("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN task_status = 'available' THEN 1 ELSE 0 END) as available,
                    SUM(CASE WHEN task_status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                    SUM(CASE WHEN task_status = 'complete' THEN 1 ELSE 0 END) as complete
                FROM tasks
            """)
            self._execute_with_logging(cursor, query)
            row = cursor.fetchone()
            tasks = {
                "total": row["total"] if row else 0,
                "available": row["available"] if row else 0,
                "in_progress": row["in_progress"] if row else 0,
                "complete": row["complete"] if row else 0
            }
            
            # Agent statistics
            query = self._normalize_sql("""
                SELECT COUNT(DISTINCT assigned_agent) as active_agents
                FROM tasks
                WHERE assigned_agent IS NOT NULL AND task_status = 'in_progress'
            """)
            self._execute_with_logging(cursor, query)
            row = cursor.fetchone()
            agents = {
                "active": row["active_agents"] if row else 0
            }
            
            # Blocked agents count
            query = self._normalize_sql("""
                SELECT COUNT(*) as blocked_count
                FROM blocked_agents
                WHERE unblocked_at IS NULL
            """)
            self._execute_with_logging(cursor, query)
            row = cursor.fetchone()
            agents["blocked"] = row["blocked_count"] if row else 0
            
            return {
                "status": "healthy",
                "database": database_status,
                "tasks": tasks,
                "agents": agents
            }
        except Exception as e:
            logger.error(f"Failed to get system status: {e}", exc_info=True)
            return {
                "status": "error",
                "database": {"connected": False},
                "error": str(e)
            }
        finally:
            self.adapter.close(conn)

    # ===== Recurring Tasks Methods =====
    
    def create_recurring_task(
        self,
        task_id: int,
        recurrence_type: str,
        recurrence_config: Dict[str, Any],
        next_occurrence: datetime
    ) -> int:
        """
        Create a recurring task pattern.
        
        Args:
            task_id: ID of the base task to recur
            recurrence_type: 'daily', 'weekly', or 'monthly'
            recurrence_config: Dictionary with recurrence-specific config
                - For weekly: {'day_of_week': 0-6} (0=Sunday)
                - For monthly: {'day_of_month': 1-31}
            next_occurrence: When to create the next instance
            
        Returns:
            Recurring task ID
        """
        if recurrence_type not in ["daily", "weekly", "monthly"]:
            raise ValueError(f"Invalid recurrence_type: {recurrence_type}. Must be daily, weekly, or monthly")
        
        # Verify task exists
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Store config as JSON string
            config_json = json.dumps(recurrence_config)
            
            recurring_id = self._execute_insert(cursor, """
                INSERT INTO recurring_tasks (
                    task_id, recurrence_type, recurrence_config, 
                    next_occurrence, is_active
                ) VALUES (?, ?, ?, ?, 1)
            """, (task_id, recurrence_type, config_json, next_occurrence))
            
            conn.commit()
            logger.info(f"Created recurring task {recurring_id} for task {task_id}")
            return recurring_id
        finally:
            self.adapter.close(conn)
    
    def get_recurring_task(self, recurring_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a recurring task by ID.
        
        Args:
            recurring_id: Recurring task ID
            
        Returns:
            Recurring task dictionary or None
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, task_id, recurrence_type, recurrence_config,
                       next_occurrence, last_occurrence_created, is_active,
                       created_at, updated_at
                FROM recurring_tasks
                WHERE id = ?
            """, (recurring_id,))
            row = cursor.fetchone()
            if row:
                config = json.loads(row["recurrence_config"]) if row["recurrence_config"] else {}
                return {
                    "id": row["id"],
                    "task_id": row["task_id"],
                    "recurrence_type": row["recurrence_type"],
                    "recurrence_config": config,
                    "next_occurrence": row["next_occurrence"],
                    "last_occurrence_created": row["last_occurrence_created"],
                    "is_active": row["is_active"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
            return None
        finally:
            self.adapter.close(conn)
    
    def list_recurring_tasks(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """
        List all recurring tasks.
        
        Args:
            active_only: If True, only return active recurring tasks
            
        Returns:
            List of recurring task dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if active_only:
                cursor.execute("""
                    SELECT id, task_id, recurrence_type, recurrence_config,
                           next_occurrence, last_occurrence_created, is_active,
                           created_at, updated_at
                    FROM recurring_tasks
                    WHERE is_active = 1
                    ORDER BY next_occurrence ASC
                """)
            else:
                cursor.execute("""
                    SELECT id, task_id, recurrence_type, recurrence_config,
                           next_occurrence, last_occurrence_created, is_active,
                           created_at, updated_at
                    FROM recurring_tasks
                    ORDER BY next_occurrence ASC
                """)
            
            results = []
            for row in cursor.fetchall():
                config = json.loads(row["recurrence_config"]) if row["recurrence_config"] else {}
                results.append({
                    "id": row["id"],
                    "task_id": row["task_id"],
                    "recurrence_type": row["recurrence_type"],
                    "recurrence_config": config,
                    "next_occurrence": row["next_occurrence"],
                    "last_occurrence_created": row["last_occurrence_created"],
                    "is_active": row["is_active"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                })
            return results
        finally:
            self.adapter.close(conn)
    
    def get_recurring_tasks_due(self) -> List[Dict[str, Any]]:
        """
        Get all recurring tasks that are due for instance creation
        (next_occurrence <= now and is_active = 1).
        
        Returns:
            List of recurring task dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, task_id, recurrence_type, recurrence_config,
                       next_occurrence, last_occurrence_created, is_active,
                       created_at, updated_at
                FROM recurring_tasks
                WHERE is_active = 1 AND next_occurrence <= CURRENT_TIMESTAMP
                ORDER BY next_occurrence ASC
            """)
            
            results = []
            for row in cursor.fetchall():
                config = json.loads(row["recurrence_config"]) if row["recurrence_config"] else {}
                results.append({
                    "id": row["id"],
                    "task_id": row["task_id"],
                    "recurrence_type": row["recurrence_type"],
                    "recurrence_config": config,
                    "next_occurrence": row["next_occurrence"],
                    "last_occurrence_created": row["last_occurrence_created"],
                    "is_active": row["is_active"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                })
            return results
        finally:
            self.adapter.close(conn)
    
    def create_recurring_instance(self, recurring_id: int) -> int:
        """
        Create a new task instance from a recurring task pattern.
        Updates next_occurrence based on recurrence type.
        
        Args:
            recurring_id: Recurring task ID
            
        Returns:
            New task instance ID
        """
        from datetime import timedelta
        import calendar
        
        recurring = self.get_recurring_task(recurring_id)
        if not recurring:
            raise ValueError(f"Recurring task {recurring_id} not found")
        
        if recurring["is_active"] != 1:
            raise ValueError(f"Recurring task {recurring_id} is not active")
        
        # Get base task
        base_task = self.get_task(recurring["task_id"])
        if not base_task:
            raise ValueError(f"Base task {recurring['task_id']} not found")
        
        # Create new task instance with same properties as base task
        new_task_id = self.create_task(
            title=base_task["title"],
            task_type=base_task["task_type"],
            task_instruction=base_task["task_instruction"],
            verification_instruction=base_task["verification_instruction"],
            agent_id="system",  # System-created instances
            project_id=base_task.get("project_id"),
            notes=base_task.get("notes"),
            priority=base_task.get("priority", "medium"),
            estimated_hours=base_task.get("estimated_hours")
        )
        
        # Calculate next occurrence
        current_next = recurring["next_occurrence"]
        if isinstance(current_next, str):
            # Parse ISO format datetime string
            current_next = datetime.fromisoformat(current_next.replace('Z', '+00:00'))
        
        if recurring["recurrence_type"] == "daily":
            next_occurrence = current_next + timedelta(days=1)
        elif recurring["recurrence_type"] == "weekly":
            # Add 7 days
            next_occurrence = current_next + timedelta(days=7)
        elif recurring["recurrence_type"] == "monthly":
            # Add approximately one month
            if current_next.month == 12:
                next_occurrence = current_next.replace(year=current_next.year + 1, month=1)
            else:
                next_occurrence = current_next.replace(month=current_next.month + 1)
            
            # Handle day_of_month config if specified
            config = recurring.get("recurrence_config", {})
            if "day_of_month" in config:
                day_of_month = config["day_of_month"]
                # Clamp to valid days in the target month
                last_day = calendar.monthrange(next_occurrence.year, next_occurrence.month)[1]
                day_of_month = min(day_of_month, last_day)
                next_occurrence = next_occurrence.replace(day=day_of_month)
        else:
            raise ValueError(f"Unknown recurrence_type: {recurring['recurrence_type']}")
        
        # Update recurring task
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE recurring_tasks
                SET next_occurrence = ?,
                    last_occurrence_created = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (next_occurrence, recurring_id))
            conn.commit()
            logger.info(f"Created recurring instance {new_task_id} from recurring task {recurring_id}")
        finally:
            self.adapter.close(conn)
        
        return new_task_id
    
    def update_recurring_task(
        self,
        recurring_id: int,
        recurrence_type: Optional[str] = None,
        recurrence_config: Optional[Dict[str, Any]] = None,
        next_occurrence: Optional[datetime] = None
    ) -> None:
        """
        Update a recurring task.
        
        Args:
            recurring_id: Recurring task ID
            recurrence_type: Optional new recurrence type
            recurrence_config: Optional new recurrence config
            next_occurrence: Optional new next occurrence date
        """
        recurring = self.get_recurring_task(recurring_id)
        if not recurring:
            raise ValueError(f"Recurring task {recurring_id} not found")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if recurrence_type:
                if recurrence_type not in ["daily", "weekly", "monthly"]:
                    raise ValueError(f"Invalid recurrence_type: {recurrence_type}")
                updates.append("recurrence_type = ?")
                params.append(recurrence_type)
            
            if recurrence_config is not None:
                config_json = json.dumps(recurrence_config)
                updates.append("recurrence_config = ?")
                params.append(config_json)
            
            if next_occurrence:
                updates.append("next_occurrence = ?")
                params.append(next_occurrence)
            
            if not updates:
                return  # No updates to make
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(recurring_id)
            
            query = f"""
                UPDATE recurring_tasks
                SET {', '.join(updates)}
                WHERE id = ?
            """
            cursor.execute(query, params)
            conn.commit()
            logger.info(f"Updated recurring task {recurring_id}")
        finally:
            self.adapter.close(conn)
    
    def deactivate_recurring_task(self, recurring_id: int) -> None:
        """
        Deactivate a recurring task (stop creating new instances).
        
        Args:
            recurring_id: Recurring task ID
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE recurring_tasks
                SET is_active = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (recurring_id,))
            conn.commit()
            logger.info(f"Deactivated recurring task {recurring_id}")
        finally:
            self.adapter.close(conn)
    
    def process_recurring_tasks(self) -> List[int]:
        """
        Process all due recurring tasks and create instances.
        This should be called periodically (e.g., via cron job).
        
        Returns:
            List of newly created task instance IDs
        """
        due_tasks = self.get_recurring_tasks_due()
        created_task_ids = []
        
        for recurring in due_tasks:
            try:
                instance_id = self.create_recurring_instance(recurring["id"])
                created_task_ids.append(instance_id)
                logger.info(f"Processed recurring task {recurring['id']}, created instance {instance_id}")
            except Exception as e:
                logger.error(f"Failed to process recurring task {recurring['id']}: {e}", exc_info=True)
        
        return created_task_ids
    
    def get_task_statistics(
        self,
        project_id: Optional[int] = None,
        task_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get aggregated statistics about tasks.
        
        Args:
            project_id: Optional project filter
            task_type: Optional task type filter
            start_date: Optional start date filter (ISO format)
            end_date: Optional end date filter (ISO format)
            
        Returns:
            Dictionary with statistics including counts by status, type, project, and completion rate
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Build WHERE clause
            conditions = []
            params = []
            
            if project_id is not None:
                conditions.append("project_id = ?")
                params.append(project_id)
            if task_type:
                conditions.append("task_type = ?")
                params.append(task_type)
            if start_date:
                conditions.append("created_at >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("created_at <= ?")
                params.append(end_date)
            
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            
            # Total count
            cursor.execute(f"SELECT COUNT(*) FROM tasks {where_clause}", params)
            total = cursor.fetchone()[0]
            
            # Counts by status
            status_counts = {}
            for status in ["available", "in_progress", "complete", "blocked", "cancelled"]:
                status_params = params + [status]
                if conditions:
                    status_where = f"{where_clause} AND task_status = ?"
                else:
                    status_where = "WHERE task_status = ?"
                cursor.execute(
                    f"SELECT COUNT(*) FROM tasks {status_where}",
                    status_params
                )
                status_counts[status] = cursor.fetchone()[0]
            
            # Counts by task_type
            type_counts = {}
            for task_type_val in ["concrete", "abstract", "epic"]:
                type_params = params + [task_type_val]
                if conditions:
                    type_where = f"{where_clause} AND task_type = ?"
                else:
                    type_where = "WHERE task_type = ?"
                cursor.execute(
                    f"SELECT COUNT(*) FROM tasks {type_where}",
                    type_params
                )
                type_counts[task_type_val] = cursor.fetchone()[0]
            
            # Counts by project (if not filtering by project)
            project_counts = {}
            if project_id is None:
                cursor.execute("SELECT project_id, COUNT(*) FROM tasks GROUP BY project_id")
                for row in cursor.fetchall():
                    proj_id = row[0]
                    count = row[1]
                    project_counts[proj_id] = count
            
            # Completion rate
            completion_rate = 0.0
            if total > 0:
                completion_rate = (status_counts.get("complete", 0) / total) * 100
            
            return {
                "total": total,
                "by_status": status_counts,
                "by_type": type_counts,
                "by_project": project_counts if project_id is None else {project_id: total},
                "completion_rate": round(completion_rate, 2)
            }
        finally:
            conn.close()
    
    def get_recent_completions(
        self,
        limit: int = 10,
        project_id: Optional[int] = None,
        hours: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recently completed tasks sorted by completion time.
        
        Args:
            limit: Maximum number of tasks to return
            project_id: Optional project filter
            hours: Optional filter for completions within last N hours
            
        Returns:
            List of task dictionaries (lightweight summary format)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            conditions = ["task_status = 'complete'", "completed_at IS NOT NULL"]
            params = []
            
            if project_id is not None:
                conditions.append("project_id = ?")
                params.append(project_id)
            
            if hours is not None:
                if self.db_type == "sqlite":
                    conditions.append(f"completed_at >= datetime('now', '-{hours} hours')")
                else:
                    conditions.append("completed_at >= NOW() - INTERVAL ? HOUR")
                    params.append(hours)
            
            where_clause = "WHERE " + " AND ".join(conditions)
            
            query = f"""
                SELECT id, title, task_status, assigned_agent, project_id, 
                       created_at, updated_at, completed_at
                FROM tasks
                {where_clause}
                ORDER BY completed_at DESC
                LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    
    def get_task_summaries(
        self,
        project_id: Optional[int] = None,
        task_type: Optional[str] = None,
        task_status: Optional[str] = None,
        assigned_agent: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get lightweight task summaries (essential fields only).
        
        Args:
            project_id: Optional project filter
            task_type: Optional task type filter
            task_status: Optional status filter
            assigned_agent: Optional agent filter
            priority: Optional priority filter
            limit: Maximum number of results
            
        Returns:
            List of task summary dictionaries with only essential fields
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            conditions = []
            params = []
            
            if project_id is not None:
                conditions.append("project_id = ?")
                params.append(project_id)
            if task_type:
                conditions.append("task_type = ?")
                params.append(task_type)
            if task_status:
                conditions.append("task_status = ?")
                params.append(task_status)
            if assigned_agent:
                conditions.append("assigned_agent = ?")
                params.append(assigned_agent)
            if priority:
                conditions.append("priority = ?")
                params.append(priority)
            
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            
            query = f"""
                SELECT id, title, task_type, task_status, assigned_agent, 
                       project_id, priority, created_at, updated_at, completed_at
                FROM tasks
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    
    def bulk_unlock_tasks(self, task_ids: List[int], agent_id: str) -> Dict[str, Any]:
        """
        Unlock multiple tasks atomically.
        
        Args:
            task_ids: List of task IDs to unlock
            agent_id: Agent ID performing the unlock
            
        Returns:
            Dictionary with success status and summary of unlocked tasks
        """
        if not task_ids:
            return {
                "success": True,
                "unlocked_count": 0,
                "unlocked_task_ids": [],
                "failed_count": 0,
                "failed_task_ids": []
            }
        
        if not agent_id:
            raise ValueError("agent_id is required for bulk unlock")
        
        conn = self._get_connection()
        unlocked = []
        failed = []
        
        try:
            cursor = conn.cursor()
            
            for task_id in task_ids:
                try:
                    # Get current status
                    cursor.execute("SELECT assigned_agent, task_status FROM tasks WHERE id = ?", (task_id,))
                    current = cursor.fetchone()
                    
                    if not current:
                        failed.append({"task_id": task_id, "error": "Task not found"})
                        continue
                    
                    old_status = current["task_status"]
                    
                    # Unlock the task
                    cursor.execute("""
                        UPDATE tasks 
                        SET task_status = 'available',
                            assigned_agent = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND task_status = 'in_progress'
                    """, (task_id,))
                    
                    if cursor.rowcount > 0:
                        # Record in history
                        cursor.execute("""
                            INSERT INTO change_history (task_id, agent_id, change_type, field_name, old_value, new_value)
                            VALUES (?, ?, 'unlocked', 'task_status', ?, 'available')
                        """, (task_id, agent_id, old_status))
                        unlocked.append(task_id)
                    else:
                        failed.append({"task_id": task_id, "error": "Task not in_progress"})
                
                except Exception as e:
                    logger.error(f"Error unlocking task {task_id}: {e}", exc_info=True)
                    failed.append({"task_id": task_id, "error": str(e)})
            
            conn.commit()
            
            return {
                "success": True,
                "unlocked_count": len(unlocked),
                "unlocked_task_ids": unlocked,
                "failed_count": len(failed),
                "failed_task_ids": failed
            }
        except Exception as e:
            conn.rollback()
            logger.error(f"Bulk unlock failed: {e}", exc_info=True)
            raise
        finally:
            conn.close()

