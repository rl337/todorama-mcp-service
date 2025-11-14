"""
Role service - business logic for role operations.
"""
import logging
from typing import Optional, Dict, Any, List

from todorama.database import TodoDatabase
from todorama.storage import OrganizationRepository
from todorama.models.tenant_models import RoleCreate, RoleUpdate

logger = logging.getLogger(__name__)


class RoleService:
    """Service for role business logic."""
    
    def __init__(
        self,
        organization_repository: Optional[OrganizationRepository] = None,
        db: Optional[TodoDatabase] = None,
    ):
        """
        Initialize role service with repository dependency.
        
        Args:
            organization_repository: OrganizationRepository instance for organization operations
            db: TodoDatabase instance (required for role operations, optional if repository provided)
            
        Note: For backward compatibility, if repository is not provided, db is required.
        If db is provided, repository will be created from it.
        """
        if organization_repository is None:
            if db is None:
                raise ValueError("Either organization_repository or db must be provided")
            # Create repository from db for backward compatibility
            self.organization_repository = OrganizationRepository(db)
            self.db = db
        else:
            self.organization_repository = organization_repository
            # Keep db reference for role operations (no RoleRepository yet)
            self.db = db if db is not None else organization_repository.db
    
    def create_role(
        self,
        organization_id: Optional[int],
        role_data: RoleCreate
    ) -> Dict[str, Any]:
        """
        Create a new role.
        
        Args:
            organization_id: Organization ID (optional)
            role_data: Role creation data
            
        Returns:
            Created role data as dictionary
            
        Raises:
            ValueError: If organization not found (when organization_id is provided)
            Exception: If role creation fails
        """
        # Check if organization exists (if provided)
        if organization_id is not None:
            org = self.organization_repository.get_by_id(organization_id)
            if not org:
                raise ValueError(f"Organization {organization_id} not found")
        
        # Create role
        try:
            role_id = self.db.create_role(
                organization_id=organization_id,
                name=role_data.name,
                permissions=role_data.permissions
            )
        except Exception as e:
            logger.error(f"Failed to create role: {str(e)}", exc_info=True)
            raise Exception("Failed to create role. Please try again or contact support if the issue persists.")
        
        # Retrieve created role
        created_role = self.db.get_role(role_id)
        if not created_role:
            logger.error(f"Role {role_id} was created but could not be retrieved")
            raise Exception("Role was created but could not be retrieved. Please check role status.")
        
        return dict(created_role)
    
    def get_role(self, role_id: int) -> Optional[Dict[str, Any]]:
        """Get a role by ID."""
        role = self.db.get_role(role_id)
        return dict(role) if role else None
    
    def list_roles(self, organization_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """List roles. If organization_id is provided, only return roles for that organization."""
        # Check if organization exists (if provided)
        if organization_id is not None:
            org = self.organization_repository.get_by_id(organization_id)
            if not org:
                raise ValueError(f"Organization {organization_id} not found")
        
        roles = self.db.list_roles(organization_id=organization_id)
        return [dict(role) for role in roles]
    
    def update_role(
        self,
        role_id: int,
        role_data: RoleUpdate
    ) -> Dict[str, Any]:
        """
        Update a role.
        
        Args:
            role_id: Role ID
            role_data: Role update data
            
        Returns:
            Updated role data as dictionary
            
        Raises:
            ValueError: If role not found
        """
        # Check if role exists
        existing = self.db.get_role(role_id)
        if not existing:
            raise ValueError(f"Role {role_id} not found")
        
        # Update role
        updated = self.db.update_role(
            role_id=role_id,
            name=role_data.name,
            permissions=role_data.permissions
        )
        
        if not updated:
            raise ValueError(f"Failed to update role {role_id}")
        
        # Retrieve updated role
        updated_role = self.db.get_role(role_id)
        if not updated_role:
            raise ValueError(f"Role {role_id} was updated but could not be retrieved")
        
        return dict(updated_role)
    
    def delete_role(self, role_id: int) -> bool:
        """Delete a role."""
        # Check if role exists
        existing = self.db.get_role(role_id)
        if not existing:
            raise ValueError(f"Role {role_id} not found")
        
        return self.db.delete_role(role_id)
    
    def assign_role_to_organization_member(
        self,
        organization_id: int,
        user_id: int,
        role_id: Optional[int]
    ) -> bool:
        """
        Assign a role to a user in an organization.
        
        Args:
            organization_id: Organization ID
            user_id: User ID
            role_id: Role ID to assign (None to remove role)
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If organization or role not found
        """
        # Check if organization exists
        org = self.organization_repository.get_by_id(organization_id)
        if not org:
            raise ValueError(f"Organization {organization_id} not found")
        
        # Check if role exists (if provided)
        if role_id is not None:
            role = self.db.get_role(role_id)
            if not role:
                raise ValueError(f"Role {role_id} not found")
        
        return self.db.assign_role_to_organization_member(organization_id, user_id, role_id)
    
    def assign_role_to_team_member(
        self,
        team_id: int,
        user_id: int,
        role_id: Optional[int]
    ) -> bool:
        """
        Assign a role to a user in a team.
        
        Args:
            team_id: Team ID
            user_id: User ID
            role_id: Role ID to assign (None to remove role)
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If team or role not found
        """
        # Check if team exists
        team = self.db.get_team(team_id)
        if not team:
            raise ValueError(f"Team {team_id} not found")
        
        # Check if role exists (if provided)
        if role_id is not None:
            role = self.db.get_role(role_id)
            if not role:
                raise ValueError(f"Role {role_id} not found")
        
        return self.db.assign_role_to_team_member(team_id, user_id, role_id)
    
    def get_user_roles(
        self,
        user_id: int,
        organization_id: Optional[int] = None,
        team_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get roles for a user.
        
        Args:
            user_id: User ID
            organization_id: Optional organization ID (returns org + team roles)
            team_id: Optional team ID (returns only team roles)
            
        Returns:
            List of role dictionaries
        """
        if team_id is not None:
            roles = self.db.get_user_team_roles(user_id, team_id)
        elif organization_id is not None:
            roles = self.db.get_user_roles_in_organization(user_id, organization_id)
            # Deduplicate roles by ID
            seen = set()
            unique_roles = []
            for role in roles:
                if role["id"] not in seen:
                    seen.add(role["id"])
                    unique_roles.append(role)
            return unique_roles
        else:
            # No scope provided - return empty list
            return []
        
        return [dict(role) for role in roles]
