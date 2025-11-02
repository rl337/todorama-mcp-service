"""
Monitoring and observability utilities for the TODO service.

Provides:
- Prometheus metrics (requests, latencies, errors)
- Request tracing (unique request IDs)
- Structured logging with context
"""
import time
import uuid
import logging
from typing import Callable, Dict, Any
from contextvars import ContextVar

from fastapi import Request, Response, status
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST as OPENMETRICS_CONTENT_TYPE

# Request context variable for tracing
request_id_var: ContextVar[str] = ContextVar('request_id', default='')

# Prometheus metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total number of HTTP requests',
    ['method', 'endpoint', 'status_code']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint', 'status_code'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

http_errors_total = Counter(
    'http_errors_total',
    'Total number of HTTP errors',
    ['method', 'endpoint', 'status_code', 'error_type']
)

service_uptime_seconds = Gauge(
    'service_uptime_seconds',
    'Service uptime in seconds'
)

service_start_time = time.time()

# Logger for structured logging
logger = logging.getLogger(__name__)


def get_request_id() -> str:
    """Get the current request ID from context."""
    return request_id_var.get('')


def set_request_id(request_id: str) -> None:
    """Set the request ID in context."""
    request_id_var.set(request_id)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for collecting Prometheus metrics and request tracing."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate unique request ID for tracing
        request_id = str(uuid.uuid4())[:8]
        set_request_id(request_id)
        
        # Extract endpoint (simplified path for metrics)
        endpoint = self._get_endpoint_path(request.url.path)
        
        # Start timing
        start_time = time.time()
        
        # Update uptime
        service_uptime_seconds.set(time.time() - service_start_time)
        
        # Log request start with structured context
        logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "endpoint": endpoint,
                "client_ip": request.client.host if request.client else None,
            }
        )
        
        # Process request
        try:
            response = await call_next(request)
            status_code = response.status_code
            
            # Log response
            duration = time.time() - start_time
            logger.info(
                "Request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "duration_seconds": duration,
                }
            )
            
            # Record metrics
            http_requests_total.labels(
                method=request.method,
                endpoint=endpoint,
                status_code=status_code
            ).inc()
            
            http_request_duration_seconds.labels(
                method=request.method,
                endpoint=endpoint,
                status_code=status_code
            ).observe(duration)
            
            # Track errors (4xx and 5xx)
            if status_code >= 400:
                error_type = "client_error" if status_code < 500 else "server_error"
                http_errors_total.labels(
                    method=request.method,
                    endpoint=endpoint,
                    status_code=status_code,
                    error_type=error_type
                ).inc()
                
                logger.warning(
                    "Request error",
                    extra={
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "endpoint": endpoint,
                        "status_code": status_code,
                        "error_type": error_type,
                        "duration_seconds": duration,
                    }
                )
            
            # Add request ID to response headers for tracing
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Trace-ID"] = request_id
            
            return response
            
        except Exception as e:
            # Handle exceptions
            duration = time.time() - start_time
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            
            logger.error(
                "Request failed with exception",
                exc_info=True,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "endpoint": endpoint,
                    "status_code": status_code,
                    "error_type": "exception",
                    "duration_seconds": duration,
                    "exception_type": type(e).__name__,
                    "exception_message": str(e),
                }
            )
            
            # Record error metrics
            http_errors_total.labels(
                method=request.method,
                endpoint=endpoint,
                status_code=status_code,
                error_type="exception"
            ).inc()
            
            # Re-raise to let FastAPI handle it
            raise
    
    @staticmethod
    def _get_endpoint_path(path: str) -> str:
        """Normalize endpoint path for metrics (remove IDs, etc.)."""
        # Replace UUIDs and numeric IDs with placeholders
        import re
        # Replace UUIDs
        path = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '{id}', path, flags=re.IGNORECASE)
        # Replace numeric IDs
        path = re.sub(r'/\d+', '/{id}', path)
        # Limit path length
        if len(path) > 100:
            path = path[:100]
        return path


def get_metrics() -> str:
    """Get Prometheus metrics in text format."""
    return generate_latest().decode('utf-8')


def check_database_health(db) -> Dict[str, Any]:
    """
    Check database connectivity and health.
    
    Args:
        db: Database instance (TodoDatabase)
        
    Returns:
        Dictionary with database health status
    """
    start_time = time.time()
    
    try:
        # Try to get a connection and execute a simple query
        conn = db._get_connection()
        try:
            cursor = conn.cursor()
            # Simple query to test connectivity using adapter
            if hasattr(db, 'adapter') and hasattr(db.adapter, 'execute'):
                db.adapter.execute(cursor, "SELECT 1", None)
            else:
                # Fallback for direct connection
                cursor.execute("SELECT 1")
            cursor.fetchone()
            
            response_time_ms = round((time.time() - start_time) * 1000, 2)
            
            return {
                "status": "healthy",
                "connectivity": "connected",
                "response_time_ms": response_time_ms,
                "type": getattr(db, 'db_type', 'unknown')
            }
        finally:
            if hasattr(db, 'adapter') and hasattr(db.adapter, 'close'):
                db.adapter.close(conn)
            elif hasattr(conn, 'close'):
                conn.close()
                
    except Exception as e:
        response_time_ms = round((time.time() - start_time) * 1000, 2)
        logger.warning(
            "Database health check failed",
            extra={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "response_time_ms": response_time_ms
            }
        )
        
        return {
            "status": "unhealthy",
            "connectivity": "disconnected",
            "response_time_ms": response_time_ms,
            "error": str(e),
            "error_type": type(e).__name__
        }


def get_health_info(db=None) -> Dict[str, Any]:
    """
    Get comprehensive health information including uptime and component status.
    
    Args:
        db: Optional database instance for database health checks
        
    Returns:
        Dictionary with health information including component statuses
    """
    uptime = time.time() - service_start_time
    timestamp = time.time()
    
    # Initialize components
    components = {}
    overall_status = "healthy"
    
    # Check service health
    components["service"] = {
        "status": "healthy",
        "uptime_seconds": uptime,
        "uptime_formatted": _format_uptime(uptime)
    }
    
    # Check database health if database is provided
    if db is not None:
        try:
            db_health = check_database_health(db)
            components["database"] = db_health
            
            # Update overall status based on database health
            if db_health.get("status") == "unhealthy":
                overall_status = "unhealthy"
            elif db_health.get("status") == "degraded":
                if overall_status == "healthy":
                    overall_status = "degraded"
        except Exception as e:
            logger.error("Error checking database health", exc_info=True)
            components["database"] = {
                "status": "unhealthy",
                "error": str(e),
                "error_type": type(e).__name__
            }
            overall_status = "unhealthy"
    
    return {
        "status": overall_status,
        "service": "todo-service",
        "timestamp": timestamp,
        "uptime_seconds": uptime,
        "uptime_formatted": _format_uptime(uptime),
        "components": components
    }


def _format_uptime(seconds: float) -> str:
    """Format uptime in human-readable format."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if days > 0:
        return f"{days}d {hours}h {minutes}m {secs}s"
    elif hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"
