"""
Team service - business logic for team operations.
"""
import logging
from typing import Optional, Dict, Any, List

from todorama.database import TodoDatabase
from todorama.storage import OrganizationRepository
from todorama.models.tenant_models import TeamCreate, TeamUpdate

logger = logging.getLogger(__name__)


class TeamService:
    """Service for team business logic."""
    
    def __init__(
        self,
        organization_repository: Optional[OrganizationRepository] = None,
        db: Optional[TodoDatabase] = None,
    ):
        """
        Initialize team service with repository dependency.
        
        Args:
            organization_repository: OrganizationRepository instance for organization operations
            db: TodoDatabase instance (required for team operations, optional if repository provided)
            
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
            # Keep db reference for team operations (no TeamRepository yet)
            self.db = db if db is not None else organization_repository.db
    
    def create_team(
        self,
        organization_id: int,
        team_data: TeamCreate
    ) -> Dict[str, Any]:
        """
        Create a new team.
        
        Args:
            organization_id: Organization ID
            team_data: Team creation data
            
        Returns:
            Created team data as dictionary
            
        Raises:
            ValueError: If organization not found
            Exception: If team creation fails
        """
        # Check if organization exists
        org = self.organization_repository.get_by_id(organization_id)
        if not org:
            raise ValueError(f"Organization {organization_id} not found")
        
        # Create team
        try:
            team_id = self.db.create_team(
                organization_id=organization_id,
                name=team_data.name,
                description=team_data.description
            )
        except Exception as e:
            logger.error(f"Failed to create team: {str(e)}", exc_info=True)
            raise Exception("Failed to create team. Please try again or contact support if the issue persists.")
        
        # Retrieve created team
        created_team = self.db.get_team(team_id)
        if not created_team:
            logger.error(f"Team {team_id} was created but could not be retrieved")
            raise Exception("Team was created but could not be retrieved. Please check team status.")
        
        return dict(created_team)
    
    def get_team(self, team_id: int) -> Optional[Dict[str, Any]]:
        """Get a team by ID."""
        team = self.db.get_team(team_id)
        return dict(team) if team else None
    
    def list_teams(self, organization_id: int) -> List[Dict[str, Any]]:
        """List all teams in an organization."""
        # Check if organization exists
        org = self.organization_repository.get_by_id(organization_id)
        if not org:
            raise ValueError(f"Organization {organization_id} not found")
        
        teams = self.db.list_teams(organization_id)
        return [dict(team) for team in teams]
    
    def update_team(
        self,
        team_id: int,
        team_data: TeamUpdate
    ) -> Dict[str, Any]:
        """
        Update a team.
        
        Args:
            team_id: Team ID
            team_data: Team update data
            
        Returns:
            Updated team data as dictionary
            
        Raises:
            ValueError: If team not found
        """
        # Check if team exists
        existing = self.db.get_team(team_id)
        if not existing:
            raise ValueError(f"Team {team_id} not found")
        
        # Update team
        updated = self.db.update_team(
            team_id=team_id,
            name=team_data.name,
            description=team_data.description
        )
        
        if not updated:
            raise ValueError(f"Failed to update team {team_id}")
        
        # Retrieve updated team
        updated_team = self.db.get_team(team_id)
        if not updated_team:
            raise ValueError(f"Team {team_id} was updated but could not be retrieved")
        
        return dict(updated_team)
    
    def delete_team(self, team_id: int) -> bool:
        """Delete a team."""
        # Check if team exists
        existing = self.db.get_team(team_id)
        if not existing:
            raise ValueError(f"Team {team_id} not found")
        
        return self.db.delete_team(team_id)
    
    def add_member(
        self,
        team_id: int,
        user_id: int,
        role_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Add a member to a team."""
        # Check if team exists
        existing = self.db.get_team(team_id)
        if not existing:
            raise ValueError(f"Team {team_id} not found")
        
        try:
            membership_id = self.db.add_team_member(
                team_id=team_id,
                user_id=user_id,
                role_id=role_id
            )
            # Retrieve membership
            members = self.db.list_team_members(team_id)
            membership = next((m for m in members if m["id"] == membership_id), None)
            if not membership:
                raise ValueError(f"Membership {membership_id} was created but could not be retrieved")
            return dict(membership)
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to add member to team: {str(e)}", exc_info=True)
            raise Exception("Failed to add member to team")
    
    def list_members(self, team_id: int) -> List[Dict[str, Any]]:
        """List all members of a team."""
        # Check if team exists
        existing = self.db.get_team(team_id)
        if not existing:
            raise ValueError(f"Team {team_id} not found")
        
        members = self.db.list_team_members(team_id)
        return [dict(member) for member in members]
    
    def remove_member(self, team_id: int, user_id: int) -> bool:
        """Remove a member from a team."""
        # Check if team exists
        existing = self.db.get_team(team_id)
        if not existing:
            raise ValueError(f"Team {team_id} not found")
        
        return self.db.remove_team_member(team_id, user_id)
