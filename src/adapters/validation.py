"""
Adapter for validation library (Pydantic).
Isolates Pydantic-specific imports to make library replacement easier.
"""
try:
    from pydantic import BaseModel, Field, field_validator, model_validator
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False
    BaseModel = object
    Field = None
    field_validator = None
    model_validator = None


class ValidationAdapter:
    """Adapter for validation operations."""
    
    def __init__(self):
        if not VALIDATION_AVAILABLE:
            raise ImportError("Pydantic is not available. Install pydantic to use this adapter.")
        
        self.BaseModel = BaseModel
        self.Field = Field
        self.field_validator = field_validator
        self.model_validator = model_validator

