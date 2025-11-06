"""
Response Strategy Pattern for handling different HTTP response types.
Provides strategies for 2xx (success), 4xx (client errors), and 5xx (server errors).
"""
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, Response, status
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger(__name__)


class ResponseStrategy:
    """Base class for response strategies."""
    
    def render(self, data: Any, status_code: int = None) -> Response:
        """Render response with appropriate status code."""
        raise NotImplementedError


class SuccessStrategy(ResponseStrategy):
    """
    Strategy for 2xx success responses.
    Default: 200 OK
    Special cases: 201 Created for resource creation
    """
    
    def __init__(self, default_status: int = status.HTTP_200_OK):
        self.default_status = default_status
    
    def render(self, data: Any, status_code: Optional[int] = None) -> Response:
        """Render success response."""
        code = status_code or self.default_status
        return JSONResponse(content=data, status_code=code)


class CreatedStrategy(SuccessStrategy):
    """
    Strategy for 201 Created responses.
    Used when new resources are created.
    """
    
    def __init__(self):
        super().__init__(default_status=status.HTTP_201_CREATED)
    
    def render(self, data: Any, status_code: Optional[int] = None) -> Response:
        """Render created response with 201 status."""
        # Always use 201 for created resources unless explicitly overridden
        code = status_code if status_code and status_code != 200 else status.HTTP_201_CREATED
        return JSONResponse(content=data, status_code=code)


class ClientErrorStrategy(ResponseStrategy):
    """
    Strategy for 4xx client error responses.
    Handles validation errors, not found, unauthorized, etc.
    """
    
    def render(self, data: Any, status_code: Optional[int] = None) -> Response:
        """Render client error response."""
        code = status_code or status.HTTP_400_BAD_REQUEST
        
        # Ensure error format is consistent
        if isinstance(data, dict):
            error_data = data
        else:
            error_data = {
                "error": "Client error",
                "detail": str(data) if data else "Bad request"
            }
        
        return JSONResponse(content=error_data, status_code=code)


class ServerErrorStrategy(ResponseStrategy):
    """
    Strategy for 5xx server error responses.
    Handles internal server errors, service unavailable, etc.
    """
    
    def render(self, data: Any, status_code: Optional[int] = None) -> Response:
        """Render server error response."""
        code = status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        
        # Log the error
        logger.error(f"Server error: {data}")
        
        # Ensure error format is consistent
        if isinstance(data, dict):
            error_data = data
        else:
            error_data = {
                "error": "Internal server error",
                "detail": str(data) if data else "An unexpected error occurred"
            }
        
        return JSONResponse(content=error_data, status_code=code)


class ResponseContext:
    """
    Context class that uses response strategies.
    Determines which strategy to use based on the operation type and result.
    """
    
    def __init__(self):
        self.success_strategy = SuccessStrategy()
        self.created_strategy = CreatedStrategy()
        self.client_error_strategy = ClientErrorStrategy()
        self.server_error_strategy = ServerErrorStrategy()
    
    def render_success(self, data: Any, status_code: Optional[int] = None) -> Response:
        """Render successful response (default 200)."""
        return self.success_strategy.render(data, status_code)
    
    def render_created(self, data: Any, status_code: Optional[int] = None) -> Response:
        """Render created response (201)."""
        return self.created_strategy.render(data, status_code)
    
    def render_client_error(self, error: Any, status_code: Optional[int] = None) -> Response:
        """Render client error response (4xx)."""
        return self.client_error_strategy.render(error, status_code)
    
    def render_server_error(self, error: Any, status_code: Optional[int] = None) -> Response:
        """Render server error response (5xx)."""
        return self.server_error_strategy.render(error, status_code)
    
    def render_from_exception(self, exc: Exception) -> Response:
        """Render response from exception, determining strategy automatically."""
        if isinstance(exc, HTTPException):
            # Use the status code from HTTPException
            # HTTPException.detail should be returned directly (FastAPI format)
            detail = exc.detail
            
            if 400 <= exc.status_code < 500:
                # For 4xx, return detail directly (FastAPI format)
                return JSONResponse(content={"detail": detail} if not isinstance(detail, dict) else detail, status_code=exc.status_code)
            elif 500 <= exc.status_code < 600:
                return self.render_server_error(detail, exc.status_code)
            else:
                # 2xx or other - treat as success
                return self.render_success(detail, exc.status_code)
        else:
            # Unknown exception - treat as server error
            return self.render_server_error(str(exc))


# Global response context instance
response_context = ResponseContext()

