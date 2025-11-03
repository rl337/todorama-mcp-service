"""
Pydantic models for task relationship requests and responses.
"""
from pydantic import BaseModel, Field, field_validator, model_validator


class RelationshipCreate(BaseModel):
    """Request model for creating a task relationship."""
    parent_task_id: int = Field(..., description="Parent task ID", gt=0)
    child_task_id: int = Field(..., description="Child task ID", gt=0)
    relationship_type: str = Field(..., description="Relationship type: subtask, blocking, blocked_by, followup, related")
    
    @field_validator('relationship_type')
    @classmethod
    def validate_relationship_type(cls, v: str) -> str:
        """Validate relationship_type enum."""
        valid_types = ["subtask", "blocking", "blocked_by", "followup", "related"]
        if v not in valid_types:
            raise ValueError(f"Invalid relationship_type '{v}'. Must be one of: {', '.join(valid_types)}")
        return v
    
    @model_validator(mode='after')
    def validate_different_tasks(self):
        """Validate parent and child are different tasks."""
        if self.parent_task_id == self.child_task_id:
            raise ValueError("parent_task_id and child_task_id cannot be the same")
        return self

