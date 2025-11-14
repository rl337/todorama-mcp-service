"""
Repository for project operations.

This module extracts project-related database operations from TodoDatabase
to improve separation of concerns and maintainability.
"""
import logging
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)


class ProjectRepository:
    """Repository for project operations."""
    
    def __init__(
        self,
        db_type: str,
        get_connection: Callable[[], Any],
        adapter: Any,
        execute_insert: Callable[[Any, str, tuple], int],
        execute_with_logging: Callable[[Any, str, tuple], Any]
    ):
        """
        Initialize ProjectRepository.
        
        Args:
            db_type: Database type ('sqlite' or 'postgresql')
            get_connection: Function to get database connection
            adapter: Database adapter (for closing connections)
            execute_insert: Function to execute INSERT queries and return ID
            execute_with_logging: Function to execute queries with logging
        """
        self.db_type = db_type
        self._get_connection = get_connection
        self.adapter = adapter
        self._execute_insert = execute_insert
        self._execute_with_logging = execute_with_logging
    
    def create(
        self,
        name: str,
        local_path: str,
        origin_url: Optional[str] = None,
        description: Optional[str] = None,
        organization_id: Optional[int] = None
    ) -> int:
        """
        Create a new project and return its ID.
        
        Args:
            name: Project name
            local_path: Local filesystem path
            origin_url: Optional origin URL (e.g., GitHub repository)
            description: Optional project description
            organization_id: Organization ID (required for multi-tenancy)
        
        Returns:
            Project ID
        
        Raises:
            ValueError: If organization_id is required but not provided
        """
        if organization_id is None:
            raise ValueError("organization_id is required for project creation")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            project_id = self._execute_insert(cursor, """
                INSERT INTO projects (name, local_path, origin_url, description, organization_id)
                VALUES (?, ?, ?, ?, ?)
            """, (name, local_path, origin_url, description, organization_id))
            conn.commit()
            logger.info(f"Created project {project_id}: {name} (organization: {organization_id})")
            return project_id
        finally:
            self.adapter.close(conn)
    
    def get_by_id(
        self,
        project_id: int,
        organization_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get a project by ID.
        
        Args:
            project_id: Project ID
            organization_id: Optional organization ID for tenant isolation. If provided,
                           only returns project if it belongs to this organization.
        
        Returns:
            Project dictionary if found and accessible, None otherwise
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if organization_id is not None:
                query = "SELECT * FROM projects WHERE id = ? AND organization_id = ?"
                params = (project_id, organization_id)
            else:
                query = "SELECT * FROM projects WHERE id = ?"
                params = (project_id,)
            
            self._execute_with_logging(cursor, query, params)
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def get_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get a project by name.
        
        Args:
            name: Project name
        
        Returns:
            Project dictionary if found, None otherwise
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM projects WHERE name = ?"
            params = (name,)
            self._execute_with_logging(cursor, query, params)
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def list(
        self,
        organization_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        List all projects, optionally filtered by organization.
        
        Args:
            organization_id: Optional organization ID to filter projects by tenant
        
        Returns:
            List of project dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if organization_id is not None:
                query = "SELECT * FROM projects WHERE organization_id = ? ORDER BY created_at DESC"
                params = (organization_id,)
            else:
                query = "SELECT * FROM projects ORDER BY created_at DESC"
                params = None
            
            self._execute_with_logging(cursor, query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
