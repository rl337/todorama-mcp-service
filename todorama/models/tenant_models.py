"""
Pydantic models for multi-tenancy (organizations, teams, roles) requests and responses.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Organization Models
# ============================================================================

class OrganizationCreate(BaseModel):
    """Request model for creating an organization."""
    name: str = Field(..., description="Organization name", min_length=1)
    description: Optional[str] = Field(None, description="Organization description")
    
    @field_validator('name')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: str) -> str:
        """Validate that name is not empty or only whitespace."""
        if not v or not v.strip():
            raise ValueError("Organization name cannot be empty or contain only whitespace")
        return v.strip()


class OrganizationUpdate(BaseModel):
    """Request model for updating an organization."""
    name: Optional[str] = Field(None, description="Organization name", min_length=1)
    description: Optional[str] = Field(None, description="Organization description")
    
    @field_validator('name')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: Optional[str]) -> Optional[str]:
        """Validate that name is not empty or only whitespace if provided."""
        if v is not None:
            if not v or not v.strip():
                raise ValueError("Organization name cannot be empty or contain only whitespace")
            return v.strip()
        return v


class OrganizationResponse(BaseModel):
    """Organization response model."""
    id: int
    name: str
    slug: str
    description: Optional[str]
    created_at: str
    updated_at: str


class OrganizationMemberResponse(BaseModel):
    """Organization member response model."""
    id: int
    organization_id: int
    user_id: int
    role_id: Optional[int]
    joined_at: str


class AddOrganizationMemberRequest(BaseModel):
    """Request model for adding a member to an organization."""
    user_id: int = Field(..., description="User ID to add", gt=0)
    role_id: Optional[int] = Field(None, description="Role ID to assign", gt=0)


# ============================================================================
# Team Models
# ============================================================================

class TeamCreate(BaseModel):
    """Request model for creating a team."""
    name: str = Field(..., description="Team name", min_length=1)
    description: Optional[str] = Field(None, description="Team description")
    
    @field_validator('name')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: str) -> str:
        """Validate that name is not empty or only whitespace."""
        if not v or not v.strip():
            raise ValueError("Team name cannot be empty or contain only whitespace")
        return v.strip()


class TeamUpdate(BaseModel):
    """Request model for updating a team."""
    name: Optional[str] = Field(None, description="Team name", min_length=1)
    description: Optional[str] = Field(None, description="Team description")
    
    @field_validator('name')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: Optional[str]) -> Optional[str]:
        """Validate that name is not empty or only whitespace if provided."""
        if v is not None:
            if not v or not v.strip():
                raise ValueError("Team name cannot be empty or contain only whitespace")
            return v.strip()
        return v


class TeamResponse(BaseModel):
    """Team response model."""
    id: int
    organization_id: int
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str


class TeamMemberResponse(BaseModel):
    """Team member response model."""
    id: int
    team_id: int
    user_id: int
    role_id: Optional[int]
    joined_at: str


class AddTeamMemberRequest(BaseModel):
    """Request model for adding a member to a team."""
    user_id: int = Field(..., description="User ID to add", gt=0)
    role_id: Optional[int] = Field(None, description="Role ID to assign", gt=0)


# ============================================================================
# Role Models
# ============================================================================

class RoleCreate(BaseModel):
    """Request model for creating a role."""
    name: str = Field(..., description="Role name", min_length=1)
    permissions: str = Field(..., description="Permissions JSON string", min_length=1)
    
    @field_validator('name')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: str) -> str:
        """Validate that name is not empty or only whitespace."""
        if not v or not v.strip():
            raise ValueError("Role name cannot be empty or contain only whitespace")
        return v.strip()
    
    @field_validator('permissions')
    @classmethod
    def validate_permissions(cls, v: str) -> str:
        """Validate that permissions is valid JSON."""
        import json
        try:
            json.loads(v)
        except json.JSONDecodeError:
            raise ValueError("permissions must be valid JSON")
        return v


class RoleUpdate(BaseModel):
    """Request model for updating a role."""
    name: Optional[str] = Field(None, description="Role name", min_length=1)
    permissions: Optional[str] = Field(None, description="Permissions JSON string", min_length=1)
    
    @field_validator('name')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: Optional[str]) -> Optional[str]:
        """Validate that name is not empty or only whitespace if provided."""
        if v is not None:
            if not v or not v.strip():
                raise ValueError("Role name cannot be empty or contain only whitespace")
            return v.strip()
        return v
    
    @field_validator('permissions')
    @classmethod
    def validate_permissions(cls, v: Optional[str]) -> Optional[str]:
        """Validate that permissions is valid JSON if provided."""
        if v is not None:
            import json
            try:
                json.loads(v)
            except json.JSONDecodeError:
                raise ValueError("permissions must be valid JSON")
        return v


class RoleResponse(BaseModel):
    """Role response model."""
    id: int
    organization_id: Optional[int]
    name: str
    permissions: str
    created_at: str
    updated_at: str
