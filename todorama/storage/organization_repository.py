"""
Repository for organization operations.

This module extracts organization-related database operations from TodoDatabase
to improve separation of concerns and maintainability.
"""
import re
import logging
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)


class OrganizationRepository:
    """Repository for organization operations."""
    
    def __init__(
        self,
        db_type: str,
        get_connection: Callable[[], Any],
        adapter: Any,
        execute_insert: Callable[[Any, str, tuple], int],
        execute_with_logging: Callable[[Any, str, tuple], Any]
    ):
        """
        Initialize OrganizationRepository.
        
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
    
    def _generate_slug(self, name: str) -> str:
        """
        Generate a URL-friendly slug from a name.
        
        Args:
            name: Organization name
        
        Returns:
            URL-friendly slug
        """
        # Convert to lowercase and replace spaces with hyphens
        slug = name.lower().strip()
        # Remove special characters, keep only alphanumeric and hyphens
        slug = re.sub(r'[^\w\s-]', '', slug)
        # Replace whitespace with hyphens
        slug = re.sub(r'[-\s]+', '-', slug)
        # Remove leading/trailing hyphens
        slug = slug.strip('-')
        return slug
    
    def _ensure_unique_slug(
        self,
        cursor: Any,
        base_slug: str,
        exclude_organization_id: Optional[int] = None
    ) -> str:
        """
        Ensure slug is unique by appending counter if needed.
        
        Args:
            cursor: Database cursor
            base_slug: Base slug to check
            exclude_organization_id: Optional organization ID to exclude from check
        
        Returns:
            Unique slug
        """
        slug = base_slug
        counter = 1
        while True:
            if exclude_organization_id is not None:
                query = "SELECT id FROM organizations WHERE slug = ? AND id != ?"
                params = (slug, exclude_organization_id)
            else:
                query = "SELECT id FROM organizations WHERE slug = ?"
                params = (slug,)
            self._execute_with_logging(cursor, query, params)
            if not cursor.fetchone():
                break
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug
    
    def create(
        self,
        name: str,
        description: Optional[str] = None
    ) -> int:
        """
        Create a new organization and return its ID.
        
        Args:
            name: Organization name
            description: Optional organization description
        
        Returns:
            Organization ID
        """
        # Generate slug from name
        slug = self._generate_slug(name)
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Ensure slug is unique
            slug = self._ensure_unique_slug(cursor, slug)
            
            organization_id = self._execute_insert(cursor, """
                INSERT INTO organizations (name, slug, description)
                VALUES (?, ?, ?)
            """, (name, slug, description))
            conn.commit()
            logger.info(f"Created organization {organization_id}: {name} (slug: {slug})")
            return organization_id
        finally:
            self.adapter.close(conn)
    
    def get_by_id(self, organization_id: int) -> Optional[Dict[str, Any]]:
        """
        Get an organization by ID.
        
        Args:
            organization_id: Organization ID
        
        Returns:
            Organization dictionary or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM organizations WHERE id = ?"
            params = (organization_id,)
            self._execute_with_logging(cursor, query, params)
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def get_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """
        Get an organization by slug.
        
        Args:
            slug: Organization slug
        
        Returns:
            Organization dictionary or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM organizations WHERE slug = ?"
            params = (slug,)
            self._execute_with_logging(cursor, query, params)
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            self.adapter.close(conn)
    
    def list(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List organizations.
        
        Args:
            user_id: Optional user ID to filter organizations the user is a member of
        
        Returns:
            List of organization dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if user_id:
                query = """
                    SELECT DISTINCT o.* FROM organizations o
                    INNER JOIN organization_members om ON o.id = om.organization_id
                    WHERE om.user_id = ?
                    ORDER BY o.created_at DESC
                """
                params = (user_id,)
            else:
                query = "SELECT * FROM organizations ORDER BY created_at DESC"
                params = None
            self._execute_with_logging(cursor, query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def update(
        self,
        organization_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> bool:
        """
        Update an organization.
        
        Args:
            organization_id: Organization ID
            name: Optional new name
            description: Optional new description
        
        Returns:
            True if updated, False otherwise
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            updates = []
            params = []
            
            if name is not None:
                updates.append("name = ?")
                params.append(name)
                # Update slug if name changed
                slug = self._generate_slug(name)
                # Ensure slug is unique (excluding current org)
                slug = self._ensure_unique_slug(cursor, slug, exclude_organization_id=organization_id)
                updates.append("slug = ?")
                params.append(slug)
            
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            
            if not updates:
                return False
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(organization_id)
            
            query = f"""
                UPDATE organizations 
                SET {', '.join(updates)}
                WHERE id = ?
            """
            self._execute_with_logging(cursor, query, tuple(params))
            conn.commit()
            logger.info(f"Updated organization {organization_id}")
            return cursor.rowcount > 0
        finally:
            self.adapter.close(conn)
    
    def delete(self, organization_id: int) -> bool:
        """
        Delete an organization (cascades to teams, roles, members).
        
        Args:
            organization_id: Organization ID
        
        Returns:
            True if deleted, False otherwise
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = "DELETE FROM organizations WHERE id = ?"
            params = (organization_id,)
            self._execute_with_logging(cursor, query, params)
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted organization {organization_id}")
            return deleted
        finally:
            self.adapter.close(conn)
    
    def add_member(
        self,
        organization_id: int,
        user_id: int,
        role_id: Optional[int] = None
    ) -> int:
        """
        Add a member to an organization and return the membership ID.
        
        Args:
            organization_id: Organization ID
            user_id: User ID
            role_id: Optional role ID
        
        Returns:
            Membership ID
        
        Raises:
            ValueError: If user is already a member
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            membership_id = self._execute_insert(cursor, """
                INSERT INTO organization_members (organization_id, user_id, role_id)
                VALUES (?, ?, ?)
            """, (organization_id, user_id, role_id))
            conn.commit()
            logger.info(f"Added user {user_id} to organization {organization_id}")
            return membership_id
        except Exception as e:
            if "unique constraint" in str(e).lower() or "UNIQUE constraint" in str(e):
                raise ValueError(f"User {user_id} is already a member of organization {organization_id}")
            raise
        finally:
            self.adapter.close(conn)
    
    def list_members(self, organization_id: int) -> List[Dict[str, Any]]:
        """
        List all members of an organization.
        
        Args:
            organization_id: Organization ID
        
        Returns:
            List of member dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = """
                SELECT * FROM organization_members
                WHERE organization_id = ?
                ORDER BY joined_at DESC
            """
            params = (organization_id,)
            self._execute_with_logging(cursor, query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            self.adapter.close(conn)
    
    def remove_member(self, organization_id: int, user_id: int) -> bool:
        """
        Remove a member from an organization.
        
        Args:
            organization_id: Organization ID
            user_id: User ID
        
        Returns:
            True if removed, False otherwise
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = """
                DELETE FROM organization_members
                WHERE organization_id = ? AND user_id = ?
            """
            params = (organization_id, user_id)
            self._execute_with_logging(cursor, query, params)
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Removed user {user_id} from organization {organization_id}")
            return deleted
        finally:
            self.adapter.close(conn)
