"""
Pydantic models for various request operations (locking, completing, bulk operations, etc.).
"""
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, model_validator


class LockTaskRequest(BaseModel):
    """Request model for locking a task."""
    agent_id: str = Field(..., description="Agent ID", min_length=1)
    
    @field_validator('agent_id')
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        """Validate agent_id is not empty."""
        if not v or not v.strip():
            raise ValueError("agent_id cannot be empty or contain only whitespace")
        return v.strip()


class CompleteTaskRequest(BaseModel):
    """Request model for completing a task."""
    agent_id: str = Field(..., description="Agent ID", min_length=1)
    notes: Optional[str] = Field(None, description="Optional completion notes")
    actual_hours: Optional[float] = Field(None, description="Actual hours spent", gt=0)
    
    @field_validator('agent_id')
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        """Validate agent_id is not empty."""
        if not v or not v.strip():
            raise ValueError("agent_id cannot be empty or contain only whitespace")
        return v.strip()
    
    @field_validator('actual_hours')
    @classmethod
    def validate_actual_hours(cls, v: Optional[float]) -> Optional[float]:
        """Validate actual_hours is positive if provided."""
        if v is not None and v <= 0:
            raise ValueError("actual_hours must be a positive number")
        return v


class BulkCompleteRequest(BaseModel):
    """Request model for bulk completing tasks."""
    task_ids: List[int] = Field(..., description="List of task IDs to complete", min_length=1)
    agent_id: str = Field(..., description="Agent ID", min_length=1)
    notes: Optional[str] = Field(None, description="Optional completion notes")
    actual_hours: Optional[float] = Field(None, description="Actual hours spent", gt=0)
    require_all: bool = Field(False, description="If True, all tasks must succeed or none will be completed")
    
    @field_validator('agent_id')
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        """Validate agent_id is not empty."""
        if not v or not v.strip():
            raise ValueError("agent_id cannot be empty or contain only whitespace")
        return v.strip()
    
    @field_validator('task_ids')
    @classmethod
    def validate_task_ids(cls, v: List[int]) -> List[int]:
        """Validate task_ids are positive."""
        if not v:
            raise ValueError("task_ids cannot be empty")
        for task_id in v:
            if task_id <= 0:
                raise ValueError(f"task_id must be positive, got {task_id}")
        return v


class BulkAssignRequest(BaseModel):
    """Request model for bulk assigning tasks."""
    task_ids: List[int] = Field(..., description="List of task IDs to assign", min_length=1)
    agent_id: str = Field(..., description="Agent ID to assign tasks to", min_length=1)
    require_all: bool = Field(False, description="If True, all tasks must succeed or none will be assigned")
    
    @field_validator('agent_id')
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        """Validate agent_id is not empty."""
        if not v or not v.strip():
            raise ValueError("agent_id cannot be empty or contain only whitespace")
        return v.strip()
    
    @field_validator('task_ids')
    @classmethod
    def validate_task_ids(cls, v: List[int]) -> List[int]:
        """Validate task_ids are positive."""
        if not v:
            raise ValueError("task_ids cannot be empty")
        for task_id in v:
            if task_id <= 0:
                raise ValueError(f"task_id must be positive, got {task_id}")
        return v


class BulkUpdateStatusRequest(BaseModel):
    """Request model for bulk updating task status."""
    task_ids: List[int] = Field(..., description="List of task IDs to update", min_length=1)
    task_status: str = Field(..., description="New task status")
    agent_id: str = Field(..., description="Agent ID", min_length=1)
    require_all: bool = Field(False, description="If True, all tasks must succeed or none will be updated")
    
    @field_validator('agent_id')
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        """Validate agent_id is not empty."""
        if not v or not v.strip():
            raise ValueError("agent_id cannot be empty or contain only whitespace")
        return v.strip()
    
    @field_validator('task_ids')
    @classmethod
    def validate_task_ids(cls, v: List[int]) -> List[int]:
        """Validate task_ids are positive."""
        if not v:
            raise ValueError("task_ids cannot be empty")
        for task_id in v:
            if task_id <= 0:
                raise ValueError(f"task_id must be positive, got {task_id}")
        return v
    
    @field_validator('task_status')
    @classmethod
    def validate_task_status(cls, v: str) -> str:
        """Validate task_status is valid."""
        if v not in ["available", "in_progress", "complete", "blocked", "cancelled"]:
            raise ValueError(f"task_status must be one of: available, in_progress, complete, blocked, cancelled")
        return v


class BulkDeleteRequest(BaseModel):
    """Request model for bulk deleting tasks."""
    task_ids: List[int] = Field(..., description="List of task IDs to delete", min_length=1)
    confirm: bool = Field(..., description="Confirmation flag for destructive operation")
    require_all: bool = Field(False, description="If True, all tasks must succeed or none will be deleted")
    
    @field_validator('task_ids')
    @classmethod
    def validate_task_ids(cls, v: List[int]) -> List[int]:
        """Validate task_ids are positive."""
        if not v:
            raise ValueError("task_ids cannot be empty")
        for task_id in v:
            if task_id <= 0:
                raise ValueError(f"task_id must be positive, got {task_id}")
        return v

