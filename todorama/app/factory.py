"""
Application factory - creates and configures the FastAPI application.
This isolates all initialization logic from main.py.
"""
import os
import signal
import logging
import asyncio
import threading
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from todorama.adapters.http_framework import HTTPFrameworkAdapter
from prometheus_client import CONTENT_TYPE_LATEST
from strawberry.fastapi import GraphQLRouter

# Import middleware and handlers
from todorama.middleware.setup import setup_middleware
from todorama.exceptions.handlers import setup_exception_handlers
from todorama.graphql_schema import schema
from todorama.monitoring import get_metrics, get_health_info, get_request_id

# Import routes
from todorama.api.command_router import router as command_router
from todorama.api.routes.mcp import router as mcp_router
from todorama.api.all_routes import router as all_routes_router
from todorama.models import RelationshipCreate

# Import service container (handles all initialization)
from todorama.dependencies.services import get_services

# Initialize HTTP framework adapter
http_adapter = HTTPFrameworkAdapter()
FastAPI = http_adapter.FastAPI
HTTPException = http_adapter.HTTPException
Request = http_adapter.Request
Body = http_adapter.Body
StaticFiles = http_adapter.StaticFiles
HTMLResponse = http_adapter.HTMLResponse
JSONResponse = http_adapter.JSONResponse
Response = http_adapter.Response
RequestValidationError = http_adapter.RequestValidationError


def setup_logging():
    """Setup structured logging with request ID support."""
    # Add request ID filter for structured logging (must be before basicConfig)
    class RequestIDFilter(logging.Filter):
        """Filter to add request ID to log records."""
        def filter(self, record):
            # Always set request_id to avoid KeyError in format string
            try:
                req_id = get_request_id() if callable(get_request_id) else (get_request_id or '-')
            except:
                req_id = '-'
            record.request_id = req_id
            return True

    # Apply filter FIRST, then configure logging
    logging.getLogger().addFilter(RequestIDFilter())

    # Use a custom formatter that safely handles request_id
    class SafeFormatter(logging.Formatter):
        def format(self, record):
            if not hasattr(record, 'request_id'):
                record.request_id = '-'
            return super().format(record)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter('%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logging.basicConfig(
        level=getattr(logging, log_level),
        handlers=[handler],
        force=True
    )


def create_signal_handler(shutdown_event: asyncio.Event):
    """Create a signal handler function that uses the provided shutdown event."""
    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        logger = logging.getLogger(__name__)
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        shutdown_event.set()
        # Stop backup schedulers
        services = get_services()
        services.backup_scheduler.stop()
        if services.conversation_backup_scheduler:
            services.conversation_backup_scheduler.stop()
        logger.info("Graceful shutdown complete")
    return signal_handler


@asynccontextmanager
async def lifespan(app):
    """Manage application lifespan with graceful shutdown."""
    # FastAPI passes the app instance directly, not the adapter
    # Startup
    logger = logging.getLogger(__name__)
    logger.info("Application starting up...")
    
    # Initialize services (database, backup, etc.)
    # This happens automatically when get_services() is first called
    services = get_services()
    logger.info("Services initialized")
    
    # Initialize and enable distributed tracing
    try:
        from tracing import setup_tracing, instrument_fastapi, instrument_database, instrument_httpx
        setup_tracing()
        instrument_fastapi(app)
        instrument_database()
        instrument_httpx()
        logger.info("Distributed tracing enabled")
    except Exception as e:
        logger.warning("Failed to initialize tracing, continuing without it", exc_info=True)
    
    # Start NATS workers if available (non-blocking - don't wait if it fails)
    nats_workers = []
    if hasattr(services, 'nats_queue') and services.nats_queue:
        # Start NATS workers in background - don't block HTTP server startup
        async def start_nats_workers_background():
            try:
                from nats_worker import start_workers
                num_workers = int(os.getenv("NATS_NUM_WORKERS", "1"))
                workers = await start_workers(
                    db=services.db,
                    nats_url=services.nats_queue.nats_url,
                    num_workers=num_workers,
                    use_jetstream=services.nats_queue.use_jetstream
                )
                nats_workers.extend(workers)
                logger.info(f"Started {len(workers)} NATS workers")
            except Exception as e:
                logger.warning(f"Failed to start NATS workers (service will continue without NATS): {e}")
                nats_workers.clear()
        
        # Don't await - let it run in background, HTTP server should start immediately
        asyncio.create_task(start_nats_workers_background())
        logger.info("NATS workers will start in background (if available)")
    
    yield
    
    # Shutdown
    logger.info("Application shutting down...")
    services.backup_scheduler.stop()
    if services.conversation_backup_scheduler:
        services.conversation_backup_scheduler.stop()
    
    # Stop NATS workers
    if nats_workers:
        try:
            from nats_worker import stop_workers
            await stop_workers(nats_workers)
            logger.info("Stopped NATS workers")
        except Exception as e:
            logger.warning(f"Error stopping NATS workers: {e}", exc_info=True)
    
    logger.info("Shutdown complete")


def create_app():
    """
    Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI app instance ready to run (wrapped in adapter).
    """
    # Setup logging first (must be done before creating logger)
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Create shutdown event for signal handling
    shutdown_event = asyncio.Event()
    
    # Register signal handlers for graceful shutdown
    # Only register in main thread (signal.signal only works in main thread)
    if threading.current_thread() is threading.main_thread():
        try:
            signal_handler_func = create_signal_handler(shutdown_event)
            signal.signal(signal.SIGTERM, signal_handler_func)
            signal.signal(signal.SIGINT, signal_handler_func)
        except ValueError:
            # Signal handlers may not be available in all contexts (e.g., tests)
            pass
    
    # Create FastAPI app with lifespan using adapter
    app_adapter = http_adapter.create_app(
        title="TODO Service",
        description="Task management service for AI agents",
        version="0.1.0",
        lifespan=lifespan
    )
    app = app_adapter.app  # Get underlying FastAPI app for middleware/setup
    
    # Setup middleware (includes MetricsMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware)
    setup_middleware(app)
    
    # Setup exception handlers
    setup_exception_handlers(app)
    
    # Register command pattern router (minimal FastAPI usage)
    # All API routes are now under /api/<Entity>/<action>
    # Include all_routes FIRST so specific routes like /api/Task/import/json are handled before command router
    # Use adapter's include_router to handle adapter-wrapped routers
    app_adapter.include_router(all_routes_router)
    app_adapter.include_router(command_router)
    app_adapter.include_router(mcp_router)
    
    # Add GraphQL router
    graphql_app = GraphQLRouter(schema)
    app.include_router(graphql_app, prefix="/graphql")
    
    # Relationships endpoint
    @app_adapter.post("/relationships", status_code=201)
    async def create_relationship(
        relationship_data: Dict[str, Any] = Body(...),
        request: Request = None
    ):
        """
        Create a relationship between two tasks.
        
        POST /relationships
        Body: {
            "parent_task_id": 100,
            "child_task_id": 123,
            "relationship_type": "subtask",
            "agent_id": "agent-123" (optional, defaults to "system" for validation tests)
        }
        """
        try:
            # Extract agent_id from body or use default
            agent_id = relationship_data.get("agent_id", "system")
            
            # Validate using RelationshipCreate model
            from pydantic import ValidationError
            try:
                relationship = RelationshipCreate(
                    parent_task_id=relationship_data["parent_task_id"],
                    child_task_id=relationship_data["child_task_id"],
                    relationship_type=relationship_data["relationship_type"]
                )
            except ValidationError as e:
                # Pydantic validation errors - convert to FastAPI format
                errors = []
                for error in e.errors():
                    errors.append({
                        "loc": list(error.get("loc", [])),
                        "msg": error.get("msg", str(e)),
                        "type": error.get("type", "validation_error")
                    })
                raise HTTPException(status_code=422, detail=errors)
            except ValueError as e:
                # Pydantic field_validator or model_validator errors
                raise HTTPException(status_code=422, detail=str(e))
            except KeyError as e:
                raise HTTPException(status_code=422, detail=f"Missing required field: {e}")
            
            # RelationshipCreate model already validates relationship_type and parent != child
            services = get_services()
            try:
                rel_id = services.db.create_relationship(
                    parent_task_id=relationship.parent_task_id,
                    child_task_id=relationship.child_task_id,
                    relationship_type=relationship.relationship_type,
                    agent_id=agent_id
                )
                return {
                    "relationship_id": rel_id,
                    "parent_task_id": relationship.parent_task_id,
                    "child_task_id": relationship.child_task_id,
                    "relationship_type": relationship.relationship_type
                }
            except ValueError as e:
                # Handle circular dependency and other validation errors
                error_msg = str(e)
                if "circular" in error_msg.lower() or "dependency" in error_msg.lower():
                    raise HTTPException(status_code=400, detail=error_msg)
                else:
                    raise HTTPException(status_code=400, detail=error_msg)
        except HTTPException:
            raise
        except ValueError as e:
            # Handle validation errors from database
            error_msg = str(e).lower()
            # Circular dependencies should return 400 (bad request), not 422 (validation error)
            if "circular" in error_msg or "dependency" in error_msg:
                raise HTTPException(status_code=400, detail=str(e))
            # Other validation errors return 422
            raise HTTPException(status_code=422, detail=str(e))
        except sqlite3.IntegrityError as e:
            # Handle other integrity errors (shouldn't happen for relationships now since we check first)
            error_msg = str(e).lower()
            if "unique constraint" in error_msg and "task_relationships" in error_msg:
                # This shouldn't happen now since we check first, but handle gracefully
                # Try to get existing relationship ID
                try:
                    services = get_services()
                    cursor = services.db._get_connection().cursor()
                    cursor.execute("""
                        SELECT id FROM task_relationships
                        WHERE parent_task_id = ? AND child_task_id = ? AND relationship_type = ?
                    """, (relationship.parent_task_id, relationship.child_task_id, relationship.relationship_type))
                    existing = cursor.fetchone()
                    if existing:
                        return {
                            "relationship_id": existing[0],
                            "parent_task_id": relationship.parent_task_id,
                            "child_task_id": relationship.child_task_id,
                            "relationship_type": relationship.relationship_type
                        }
                except Exception:
                    pass
                raise HTTPException(
                    status_code=409,  # Conflict - relationship already exists
                    detail=f"Relationship already exists between task {relationship.parent_task_id} and task {relationship.child_task_id} with type {relationship.relationship_type}"
                )
            logger.error(f"Database integrity error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to create relationship")
        except Exception as e:
            logger.error(f"Failed to create relationship: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to create relationship")
    
    # Mount static files directory for web interface
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    if os.path.exists(static_dir):
        app_adapter.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    # Root endpoint - serve web interface
    @app_adapter.get("/", response_class=HTMLResponse)
    async def root():
        """Serve the web-based task management interface."""
        static_dir_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        index_file = os.path.join(static_dir_path, "index.html")
        
        if os.path.exists(index_file):
            with open(index_file, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        else:
            return HTMLResponse(
                content="<h1>TODO Service</h1><p>Web interface not found. Please ensure static files are deployed.</p>",
                status_code=404
            )
    
    # Health check endpoint
    @app_adapter.get("/health")
    async def health_check():
        """Comprehensive health check endpoint with component status (database, service)."""
        services = get_services()
        health_info = get_health_info(services.db)
        
        # Return appropriate HTTP status based on overall health
        if health_info.get("status") == "unhealthy":
            # Use 503 status code directly (standard HTTP status)
            return JSONResponse(
                content=health_info,
                status_code=503  # HTTP_503_SERVICE_UNAVAILABLE
            )
        
        return health_info
    
    # Metrics endpoint
    @app_adapter.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint."""
        return Response(
            content=get_metrics(),
            media_type=CONTENT_TYPE_LATEST
        )
    
    # Additional exception handlers (beyond setup_exception_handlers)
    @app_adapter.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle all unhandled exceptions with consistent error format."""
        request_id = get_request_id() or '-'
        logger.error(
            f"Unhandled exception in {request.method} {request.url.path}: {str(exc)}",
            exc_info=True,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "exception_type": type(exc).__name__,
            }
        )
        response = JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": "An unexpected error occurred. Please check the logs for details.",
                "path": request.url.path,
                "method": request.method,
                "request_id": request_id
            }
        )
        # Add request ID to headers if available
        if request_id != '-':
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Trace-ID"] = request_id
        return response
    
    @app_adapter.exception_handler(sqlite3.Error)
    async def sqlite_exception_handler(request: Request, exc: sqlite3.Error):
        """Handle SQLite-specific errors."""
        request_id = get_request_id() or '-'
        logger.error(
            f"Database error in {request.method} {request.url.path}: {str(exc)}",
            exc_info=True,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "exception_type": type(exc).__name__,
            }
        )
        
        # For MCP endpoints, return error in MCP format so agents can see it
        if request.url.path.startswith("/mcp/"):
            error_detail = str(exc)
            if isinstance(exc, sqlite3.IntegrityError) and "CHECK constraint" in error_detail:
                error_detail += ". This may indicate a schema mismatch - please check database migration status."
            
            response = JSONResponse(
                status_code=200,  # MCP endpoints return 200 even on error
                content={
                    "success": False,
                    "error": f"Database error in {request.url.path}: {error_detail}",
                    "error_type": type(exc).__name__,
                    "error_details": error_detail,
                    "path": request.url.path,
                    "request_id": request_id
                }
            )
        else:
            # For non-MCP endpoints, use standard error format
            response = JSONResponse(
                status_code=500,
                content={
                    "error": "Database error",
                    "detail": "A database operation failed. Please try again or contact support if the issue persists.",
                    "path": request.url.path,
                    "method": request.method,
                    "request_id": request_id
                }
            )
        
        # Add request ID to headers if available
        if request_id != '-':
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Trace-ID"] = request_id
        return response
    
    @app_adapter.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handle request validation errors with clear messages."""
        request_id = get_request_id() or '-'
        errors = []
        for error in exc.errors():
            field = " -> ".join(str(loc) for loc in error["loc"])
            msg = error["msg"]
            errors.append(f"{field}: {msg}")
        
        logger.warning(
            f"Validation error in {request.method} {request.url.path}: {', '.join(errors)}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "errors": errors,
            }
        )
        response = JSONResponse(
            status_code=422,
            content={
                "error": "Validation error",
                "detail": "One or more fields failed validation",
                "errors": errors,
                "path": request.url.path,
                "method": request.method,
                "request_id": request_id
            }
        )
        # Add request ID to headers if available
        if request_id != '-':
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Trace-ID"] = request_id
        return response
    
    logger.info("FastAPI app created and configured")
    
    # Return the underlying FastAPI app for compatibility with uvicorn and tests
    # The adapter is used internally, but external code expects FastAPI instance
    return app

