"""
Tenancy API routes (organizations, teams, roles, authentication).
"""
from typing import List, Dict, Any, Optional
import logging
import sqlite3

from todorama.adapters.http_framework import HTTPFrameworkAdapter
from todorama.models.tenant_models import (
    OrganizationCreate, OrganizationUpdate, OrganizationResponse, OrganizationMemberResponse,
    AddOrganizationMemberRequest,
    TeamCreate, TeamUpdate, TeamResponse, TeamMemberResponse, AddTeamMemberRequest,
    RoleCreate, RoleUpdate, RoleResponse
)
from todorama.dependencies.services import get_db
from todorama.services.organization_service import OrganizationService
from todorama.services.team_service import TeamService
from todorama.services.role_service import RoleService
from todorama.auth.dependencies import (
    verify_api_key, optional_api_key, verify_admin_api_key,
    verify_user_auth, verify_session_token,
    require_permission
)
from todorama.auth.permissions import ADMIN

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
Path = http_adapter.Path
Depends = http_adapter.Depends
Query = http_adapter.Query
Body = http_adapter.Body
HTTPException = http_adapter.HTTPException
Request = http_adapter.Request

# Create router using adapter, expose underlying router for compatibility
router_adapter = http_adapter.create_router(prefix="", tags=["tenancy"])
router = router_adapter.router

logger = logging.getLogger(__name__)


# ============================================================================
# Organization Routes
# ============================================================================

@router.post("/organizations", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    request: Request,
    organization: OrganizationCreate,
    auth: Dict[str, Any] = Depends(verify_user_auth),
    _: None = Depends(require_permission(ADMIN))
) -> OrganizationResponse:
    """Create a new organization (requires ADMIN permission)."""
    db = get_db()
    organization_service = OrganizationService(db)
    try:
        created = organization_service.create_organization(organization)
        return OrganizationResponse(**created)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create organization: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create organization: {str(e)}")


@router.get("/organizations", response_model=List[OrganizationResponse])
async def list_organizations(
    auth: Optional[Dict[str, Any]] = Depends(optional_api_key)
) -> List[OrganizationResponse]:
    """List organizations. If authenticated, only return organizations the user is a member of."""
    db = get_db()
    organization_service = OrganizationService(db)
    # Get user_id from auth if available (would need to be added to auth dict)
    user_id = None  # TODO: Extract user_id from auth when user authentication is implemented
    organizations = organization_service.list_organizations(user_id=user_id)
    return [OrganizationResponse(**org) for org in organizations]


@router.get("/organizations/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: int = Path(..., gt=0),
    auth: Optional[Dict[str, Any]] = Depends(optional_api_key)
) -> OrganizationResponse:
    """Get an organization by ID."""
    db = get_db()
    organization_service = OrganizationService(db)
    organization = organization_service.get_organization(organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail=f"Organization {organization_id} not found")
    return OrganizationResponse(**organization)


@router.patch("/organizations/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    request: Request,
    organization_id: int = Path(..., gt=0),
    organization: OrganizationUpdate = Body(...),
    auth: Dict[str, Any] = Depends(verify_user_auth),
    _: None = Depends(require_permission(ADMIN))
) -> OrganizationResponse:
    """Update an organization (requires ADMIN permission)."""
    db = get_db()
    organization_service = OrganizationService(db)
    try:
        updated = organization_service.update_organization(organization_id, organization)
        return OrganizationResponse(**updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update organization: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update organization: {str(e)}")


@router.delete("/organizations/{organization_id}")
async def delete_organization(
    request: Request,
    organization_id: int = Path(..., gt=0),
    auth: Dict[str, Any] = Depends(verify_user_auth),
    _: None = Depends(require_permission(ADMIN))
) -> Dict[str, Any]:
    """Delete an organization (requires ADMIN permission)."""
    db = get_db()
    organization_service = OrganizationService(db)
    try:
        deleted = organization_service.delete_organization(organization_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Organization {organization_id} not found")
        return {"success": True, "organization_id": organization_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete organization: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete organization: {str(e)}")


@router.post("/organizations/{organization_id}/members", response_model=OrganizationMemberResponse, status_code=201)
async def add_organization_member(
    organization_id: int = Path(..., gt=0),
    member_data: AddOrganizationMemberRequest = Body(...),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> OrganizationMemberResponse:
    """Add a member to an organization."""
    db = get_db()
    organization_service = OrganizationService(db)
    try:
        membership = organization_service.add_member(
            organization_id=organization_id,
            user_id=member_data.user_id,
            role_id=member_data.role_id
        )
        return OrganizationMemberResponse(**membership)
    except ValueError as e:
        error_msg = str(e).lower()
        if "not found" in error_msg:
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to add organization member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add organization member: {str(e)}")


@router.get("/organizations/{organization_id}/members", response_model=List[OrganizationMemberResponse])
async def list_organization_members(
    organization_id: int = Path(..., gt=0),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> List[OrganizationMemberResponse]:
    """List all members of an organization."""
    db = get_db()
    organization_service = OrganizationService(db)
    try:
        members = organization_service.list_members(organization_id)
        return [OrganizationMemberResponse(**member) for member in members]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list organization members: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list organization members: {str(e)}")


@router.delete("/organizations/{organization_id}/members/{user_id}")
async def remove_organization_member(
    organization_id: int = Path(..., gt=0),
    user_id: int = Path(..., gt=0),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Remove a member from an organization."""
    db = get_db()
    organization_service = OrganizationService(db)
    try:
        removed = organization_service.remove_member(organization_id, user_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"User {user_id} is not a member of organization {organization_id}")
        return {"success": True, "organization_id": organization_id, "user_id": user_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to remove organization member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to remove organization member: {str(e)}")


# ============================================================================
# Team Routes
# ============================================================================

@router.post("/organizations/{org_id}/teams", response_model=TeamResponse, status_code=201)
async def create_team(
    org_id: int = Path(..., gt=0),
    team: TeamCreate = Body(...),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> TeamResponse:
    """Create a new team in an organization."""
    db = get_db()
    team_service = TeamService(db)
    try:
        created = team_service.create_team(org_id, team)
        return TeamResponse(**created)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create team: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create team: {str(e)}")


@router.get("/organizations/{org_id}/teams", response_model=List[TeamResponse])
async def list_teams(
    org_id: int = Path(..., gt=0),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> List[TeamResponse]:
    """List all teams in an organization."""
    db = get_db()
    team_service = TeamService(db)
    try:
        teams = team_service.list_teams(org_id)
        return [TeamResponse(**team) for team in teams]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list teams: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list teams: {str(e)}")


@router.get("/teams/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: int = Path(..., gt=0),
    auth: Optional[Dict[str, Any]] = Depends(optional_api_key)
) -> TeamResponse:
    """Get a team by ID."""
    db = get_db()
    team_service = TeamService(db)
    team = team_service.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found")
    return TeamResponse(**team)


@router.patch("/teams/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: int = Path(..., gt=0),
    team: TeamUpdate = Body(...),
    auth: Dict[str, Any] = Depends(verify_api_key)  # TODO: Add team admin check
) -> TeamResponse:
    """Update a team (requires team admin)."""
    db = get_db()
    team_service = TeamService(db)
    try:
        updated = team_service.update_team(team_id, team)
        return TeamResponse(**updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update team: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update team: {str(e)}")


@router.delete("/teams/{team_id}")
async def delete_team(
    team_id: int = Path(..., gt=0),
    auth: Dict[str, Any] = Depends(verify_api_key)  # TODO: Add team admin check
) -> Dict[str, Any]:
    """Delete a team (requires team admin)."""
    db = get_db()
    team_service = TeamService(db)
    try:
        deleted = team_service.delete_team(team_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Team {team_id} not found")
        return {"success": True, "team_id": team_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete team: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete team: {str(e)}")


@router.post("/teams/{team_id}/members", response_model=TeamMemberResponse, status_code=201)
async def add_team_member(
    team_id: int = Path(..., gt=0),
    member_data: AddTeamMemberRequest = Body(...),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> TeamMemberResponse:
    """Add a member to a team."""
    db = get_db()
    team_service = TeamService(db)
    try:
        membership = team_service.add_member(
            team_id=team_id,
            user_id=member_data.user_id,
            role_id=member_data.role_id
        )
        return TeamMemberResponse(**membership)
    except ValueError as e:
        error_msg = str(e).lower()
        if "not found" in error_msg:
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to add team member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add team member: {str(e)}")


@router.get("/teams/{team_id}/members", response_model=List[TeamMemberResponse])
async def list_team_members(
    team_id: int = Path(..., gt=0),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> List[TeamMemberResponse]:
    """List all members of a team."""
    db = get_db()
    team_service = TeamService(db)
    try:
        members = team_service.list_members(team_id)
        return [TeamMemberResponse(**member) for member in members]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list team members: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list team members: {str(e)}")


@router.delete("/teams/{team_id}/members/{user_id}")
async def remove_team_member(
    team_id: int = Path(..., gt=0),
    user_id: int = Path(..., gt=0),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Remove a member from a team."""
    db = get_db()
    team_service = TeamService(db)
    try:
        removed = team_service.remove_member(team_id, user_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"User {user_id} is not a member of team {team_id}")
        return {"success": True, "team_id": team_id, "user_id": user_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to remove team member: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to remove team member: {str(e)}")


# ============================================================================
# Authentication Routes
# ============================================================================

@router.post("/auth/switch-organization", status_code=200)
async def switch_organization(
    request: Request,
    organization_id: int = Body(..., embed=True),
    auth: Dict[str, Any] = Depends(verify_session_token)
) -> Dict[str, Any]:
    """
    Switch the active organization for the current session.
    
    Requires:
    - Valid session token
    - User must be a member of the target organization
    """
    db = get_db()
    user_id = auth.get("user_id")
    session_id = auth.get("session_id")
    
    if not user_id:
        raise HTTPException(status_code=401, detail="Session authentication required")
    
    # Verify user is a member of the target organization
    orgs = db.list_organizations(user_id=user_id)
    org_ids = [org["id"] for org in orgs]
    
    if organization_id not in org_ids:
        raise HTTPException(
            status_code=403,
            detail=f"User is not a member of organization {organization_id}"
        )
    
    # Update session's organization_id if column exists
    try:
        conn = db._get_connection()
        cursor = conn.cursor()
        # Check if organization_id column exists
        try:
            cursor.execute("SELECT organization_id FROM user_sessions LIMIT 1")
            has_org_column = True
        except (sqlite3.OperationalError, Exception):
            has_org_column = False
        
        if has_org_column:
            cursor.execute("""
                UPDATE user_sessions
                SET organization_id = ?
                WHERE id = ?
            """, (organization_id, session_id))
            conn.commit()
            db.adapter.close(conn)
            
            # Update request state
            request.state.organization_id = organization_id
            
            return {
                "success": True,
                "organization_id": organization_id,
                "message": f"Switched to organization {organization_id}"
            }
        else:
            # Column doesn't exist - return success but note that organization_id is not stored in session
            db.adapter.close(conn)
            return {
                "success": True,
                "organization_id": organization_id,
                "message": f"Organization context set to {organization_id} (not persisted in session - database migration needed)"
            }
    except Exception as e:
        logger.error(f"Failed to switch organization: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to switch organization: {str(e)}")


# ============================================================================
# Role Routes
# ============================================================================

@router.post("/organizations/{org_id}/roles", response_model=RoleResponse, status_code=201)
async def create_role(
    org_id: int = Path(..., gt=0),
    role: RoleCreate = Body(...),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> RoleResponse:
    """Create a new role in an organization."""
    db = get_db()
    role_service = RoleService(db)
    try:
        created = role_service.create_role(org_id, role)
        return RoleResponse(**created)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create role: {str(e)}")


@router.get("/organizations/{org_id}/roles", response_model=List[RoleResponse])
async def list_roles(
    org_id: int = Path(..., gt=0),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> List[RoleResponse]:
    """List all roles in an organization."""
    db = get_db()
    role_service = RoleService(db)
    try:
        roles = role_service.list_roles(org_id)
        return [RoleResponse(**role) for role in roles]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list roles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list roles: {str(e)}")


@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: int = Path(..., gt=0),
    auth: Optional[Dict[str, Any]] = Depends(optional_api_key)
) -> RoleResponse:
    """Get a role by ID."""
    db = get_db()
    role_service = RoleService(db)
    role = role_service.get_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail=f"Role {role_id} not found")
    return RoleResponse(**role)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: int = Path(..., gt=0),
    role: RoleUpdate = Body(...),
    auth: Dict[str, Any] = Depends(verify_admin_api_key)
) -> RoleResponse:
    """Update a role (requires admin)."""
    db = get_db()
    role_service = RoleService(db)
    try:
        updated = role_service.update_role(role_id, role)
        return RoleResponse(**updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update role: {str(e)}")


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: int = Path(..., gt=0),
    auth: Dict[str, Any] = Depends(verify_admin_api_key)
) -> Dict[str, Any]:
    """Delete a role (requires admin)."""
    db = get_db()
    role_service = RoleService(db)
    try:
        deleted = role_service.delete_role(role_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Role {role_id} not found")
        return {"success": True, "role_id": role_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete role: {str(e)}")
