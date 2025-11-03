"""
Pydantic models for comment-related requests and responses.
"""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class CommentCreate(BaseModel):
    """Comment creation model."""
    agent_id: str = Field(..., description="Agent ID creating the comment", min_length=1)
    content: str = Field(..., description="Comment content", min_length=1)
    parent_comment_id: Optional[int] = Field(None, description="Parent comment ID for threaded replies", gt=0)
    mentions: Optional[List[str]] = Field(None, description="List of agent IDs mentioned in the comment")
    
    @field_validator('agent_id', 'content')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: str) -> str:
        """Validate that string fields are not empty or only whitespace."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or contain only whitespace")
        return v.strip()


class CommentUpdate(BaseModel):
    """Comment update model."""
    content: str = Field(..., description="Updated comment content", min_length=1)
    
    @field_validator('content')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: str) -> str:
        """Validate that string fields are not empty or only whitespace."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or contain only whitespace")
        return v.strip()


class CommentResponse(BaseModel):
    """Comment response model."""
    id: int
    task_id: int
    agent_id: str
    content: str
    parent_comment_id: Optional[int]
    mentions: List[str]
    created_at: str
    updated_at: Optional[str]

