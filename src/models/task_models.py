"""
Pydantic models for task-related requests and responses.
"""
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class TaskCreate(BaseModel):
    """Request model for creating a task."""
    title: str = Field(..., description="Task title", min_length=1)
    task_type: str = Field(..., description="Task type: concrete, abstract, or epic")
    task_instruction: str = Field(..., description="What to do", min_length=1)
    verification_instruction: str = Field(..., description="How to verify completion (idempotent)", min_length=1)
    agent_id: str = Field(..., description="Agent ID creating this task", min_length=1)
    project_id: Optional[int] = Field(None, description="Project ID (optional)", gt=0)
    notes: Optional[str] = Field(None, description="Optional notes")
    priority: Optional[str] = Field("medium", description="Task priority: low, medium, high, or critical")
    estimated_hours: Optional[float] = Field(None, description="Optional estimated hours for the task", gt=0)
    due_date: Optional[str] = Field(None, description="Optional due date (ISO format timestamp)")
    
    @field_validator('title', 'task_instruction', 'verification_instruction', 'agent_id')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: str) -> str:
        """Validate that string fields are not empty or only whitespace."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or contain only whitespace")
        return v.strip()
    
    @field_validator('task_type')
    @classmethod
    def validate_task_type(cls, v: str) -> str:
        """Validate task_type enum."""
        valid_types = ["concrete", "abstract", "epic"]
        if v not in valid_types:
            raise ValueError(f"Invalid task_type '{v}'. Must be one of: {', '.join(valid_types)}")
        return v
    
    @field_validator('priority')
    @classmethod
    def validate_priority(cls, v: Optional[str]) -> Optional[str]:
        """Validate priority enum."""
        if v is None:
            return "medium"
        valid_priorities = ["low", "medium", "high", "critical"]
        if v not in valid_priorities:
            raise ValueError(f"Invalid priority '{v}'. Must be one of: {', '.join(valid_priorities)}")
        return v
    
    @field_validator('project_id')
    @classmethod
    def validate_project_id(cls, v: Optional[int]) -> Optional[int]:
        """Validate project_id is positive if provided."""
        if v is not None and v <= 0:
            raise ValueError("project_id must be a positive integer")
        return v
    
    @field_validator('estimated_hours')
    @classmethod
    def validate_estimated_hours(cls, v: Optional[float]) -> Optional[float]:
        """Validate estimated_hours is positive if provided."""
        if v is not None and v <= 0:
            raise ValueError("estimated_hours must be a positive number")
        return v


class TaskUpdate(BaseModel):
    """Request model for updating a task."""
    task_status: Optional[str] = None
    verification_status: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = None
    
    @field_validator('task_status')
    @classmethod
    def validate_task_status(cls, v: Optional[str]) -> Optional[str]:
        """Validate task_status enum."""
        if v is None:
            return v
        valid_statuses = ["available", "in_progress", "complete", "blocked", "cancelled"]
        if v not in valid_statuses:
            raise ValueError(f"Invalid task_status '{v}'. Must be one of: {', '.join(valid_statuses)}")
        return v
    
    @field_validator('verification_status')
    @classmethod
    def validate_verification_status(cls, v: Optional[str]) -> Optional[str]:
        """Validate verification_status enum."""
        if v is None:
            return v
        valid_statuses = ["unverified", "verified"]
        if v not in valid_statuses:
            raise ValueError(f"Invalid verification_status '{v}'. Must be one of: {', '.join(valid_statuses)}")
        return v
    
    @field_validator('priority')
    @classmethod
    def validate_priority(cls, v: Optional[str]) -> Optional[str]:
        """Validate priority enum."""
        if v is None:
            return v
        valid_priorities = ["low", "medium", "high", "critical"]
        if v not in valid_priorities:
            raise ValueError(f"Invalid priority '{v}'. Must be one of: {', '.join(valid_priorities)}")
        return v


class TaskResponse(BaseModel):
    """Task response model."""
    id: int
    project_id: Optional[int]
    title: str
    task_type: str
    task_instruction: str
    verification_instruction: str
    task_status: str
    verification_status: str
    priority: str
    assigned_agent: Optional[str]
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    notes: Optional[str]
    due_date: Optional[str]
    estimated_hours: Optional[float]
    actual_hours: Optional[float]
    time_delta_hours: Optional[float]
    started_at: Optional[str]

