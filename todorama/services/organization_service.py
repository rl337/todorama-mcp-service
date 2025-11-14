"""
Organization service - business logic for organization operations.
"""
import logging
from typing import Optional, Dict, Any, List

from todorama.database import TodoDatabase
from todorama.storage import OrganizationRepository
from todorama.models.tenant_models import OrganizationCreate, OrganizationUpdate

logger = logging.getLogger(__name__)


class OrganizationService:
    """Service for organization business logic."""
    
    def __init__(
        self,
        organization_repository: Optional[OrganizationRepository] = None,
        db: Optional[TodoDatabase] = None,
    ):
        """
        Initialize organization service with repository dependency.
        
        Args:
            organization_repository: OrganizationRepository instance for organization operations
            db: TodoDatabase instance (optional, for backward compatibility and complex operations)
            
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
            # Keep db reference for complex operations not yet in repositories
            # (members, etc.)
            self.db = db if db is not None else organization_repository.db
    
    def create_organization(self, organization_data: OrganizationCreate) -> Dict[str, Any]:
        """
        Create a new organization.
        
        Args:
            organization_data: Organization creation data
            
        Returns:
            Created organization data as dictionary
            
        Raises:
            ValueError: If organization name already exists
            Exception: If organization creation fails
        """
        # Create organization
        try:
            organization_id = self.organization_repository.create(
                name=organization_data.name,
                description=organization_data.description
            )
        except Exception as e:
            logger.error(f"Failed to create organization: {str(e)}", exc_info=True)
            raise Exception("Failed to create organization. Please try again or contact support if the issue persists.")
        
        # Retrieve created organization
        created_org = self.organization_repository.get_by_id(organization_id)
        if not created_org:
            logger.error(f"Organization {organization_id} was created but could not be retrieved")
            raise Exception("Organization was created but could not be retrieved. Please check organization status.")
        
        return dict(created_org)
    
    def get_organization(self, organization_id: int) -> Optional[Dict[str, Any]]:
        """Get an organization by ID."""
        org = self.organization_repository.get_by_id(organization_id)
        return dict(org) if org else None
    
    def list_organizations(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """List organizations. If user_id is provided, only return organizations the user is a member of."""
        orgs = self.organization_repository.list(user_id=user_id)
        return [dict(org) for org in orgs]
    
    def update_organization(
        self,
        organization_id: int,
        organization_data: OrganizationUpdate
    ) -> Dict[str, Any]:
        """
        Update an organization.
        
        Args:
            organization_id: Organization ID
            organization_data: Organization update data
            
        Returns:
            Updated organization data as dictionary
            
        Raises:
            ValueError: If organization not found
        """
        # Check if organization exists
        existing = self.organization_repository.get_by_id(organization_id)
        if not existing:
            raise ValueError(f"Organization {organization_id} not found")
        
        # Update organization
        updated = self.organization_repository.update(
            organization_id=organization_id,
            name=organization_data.name,
            description=organization_data.description
        )
        
        if not updated:
            raise ValueError(f"Failed to update organization {organization_id}")
        
        # Retrieve updated organization
        updated_org = self.organization_repository.get_by_id(organization_id)
        if not updated_org:
            raise ValueError(f"Organization {organization_id} was updated but could not be retrieved")
        
        return dict(updated_org)
    
    def delete_organization(self, organization_id: int) -> bool:
        """Delete an organization."""
        # Check if organization exists
        existing = self.organization_repository.get_by_id(organization_id)
        if not existing:
            raise ValueError(f"Organization {organization_id} not found")
        
        return self.organization_repository.delete(organization_id)
    
    def add_member(
        self,
        organization_id: int,
        user_id: int,
        role_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Add a member to an organization."""
        # Check if organization exists
        existing = self.organization_repository.get_by_id(organization_id)
        if not existing:
            raise ValueError(f"Organization {organization_id} not found")
        
        try:
            membership_id = self.db.add_organization_member(
                organization_id=organization_id,
                user_id=user_id,
                role_id=role_id
            )
            # Retrieve membership
            members = self.db.list_organization_members(organization_id)
            membership = next((m for m in members if m["id"] == membership_id), None)
            if not membership:
                raise ValueError(f"Membership {membership_id} was created but could not be retrieved")
            return dict(membership)
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to add member to organization: {str(e)}", exc_info=True)
            raise Exception("Failed to add member to organization")
    
    def list_members(self, organization_id: int) -> List[Dict[str, Any]]:
        """List all members of an organization."""
        # Check if organization exists
        existing = self.organization_repository.get_by_id(organization_id)
        if not existing:
            raise ValueError(f"Organization {organization_id} not found")
        
        members = self.db.list_organization_members(organization_id)
        return [dict(member) for member in members]
    
    def remove_member(self, organization_id: int, user_id: int) -> bool:
        """Remove a member from an organization."""
        # Check if organization exists
        existing = self.organization_repository.get_by_id(organization_id)
        if not existing:
            raise ValueError(f"Organization {organization_id} not found")
        
        return self.db.remove_organization_member(organization_id, user_id)
