"""
Pydantic models for project-related requests and responses.
"""
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    """Request model for creating a project."""
    name: str = Field(..., description="Project name (unique)", min_length=1)
    local_path: str = Field(..., description="Local path where project is located", min_length=1)
    origin_url: Optional[str] = Field(None, description="Origin URL (GitHub, file://, etc.)")
    description: Optional[str] = Field(None, description="Project description")
    
    @field_validator('name', 'local_path')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: str) -> str:
        """Validate that string fields are not empty or only whitespace."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or contain only whitespace")
        return v.strip()


class ProjectResponse(BaseModel):
    """Project response model."""
    id: int
    name: str
    local_path: str
    origin_url: Optional[str]
    description: Optional[str]
    created_at: str
    updated_at: str

