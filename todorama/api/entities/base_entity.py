"""
Base class for all entity command handlers.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from todorama.adapters.http_framework import HTTPFrameworkAdapter
import logging

logger = logging.getLogger(__name__)

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
HTTPException = http_adapter.HTTPException


class BaseEntity(ABC):
    """Base class for entity command handlers."""
    
    def __init__(self, db, auth_info: Optional[Dict[str, Any]] = None):
        """
        Initialize entity with database and optional auth info.
        
        Args:
            db: Database instance
            auth_info: Authentication information (project_id, etc.)
        """
        self.db = db
        self.auth_info = auth_info or {}
    
    def _require_auth(self) -> Dict[str, Any]:
        """Require authentication and return auth info."""
        if not self.auth_info:
            raise HTTPException(status_code=401, detail="Authentication required")
        return self.auth_info
    
    def _get_project_id(self) -> Optional[int]:
        """Get project ID from auth info."""
        return self.auth_info.get("project_id") if self.auth_info else None
    
    def _handle_error(self, error: Exception, default_message: str = "Operation failed") -> None:
        """
        Handle errors and convert to appropriate HTTP exceptions.
        Uses proper status codes:
        - 404 for not found
        - 403 for unauthorized/forbidden
        - 400 for validation/bad request
        - 422 for validation errors (Pydantic)
        - 500 for server errors
        """
        # HTTPException should be re-raised as-is
        if isinstance(error, HTTPException):
            raise error
        
        # Handle ValueError (business logic errors)
        if isinstance(error, ValueError):
            error_msg = str(error)
            if "not found" in error_msg.lower():
                raise HTTPException(status_code=404, detail=error_msg)
            elif "not authorized" in error_msg.lower() or "forbidden" in error_msg.lower():
                raise HTTPException(status_code=403, detail=error_msg)
            raise HTTPException(status_code=400, detail=error_msg)
        else:
            # Unknown errors become 500
            logger.error(f"{default_message}: {error}", exc_info=True)
            raise HTTPException(status_code=500, detail=default_message)

