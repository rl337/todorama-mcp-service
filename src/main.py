"""
TODO Service - REST API for task management.

Provides endpoints for agents to:
- Query tasks (by type, status, etc.)
- Lock tasks (mark in_progress)
- Update tasks (complete, verify, etc.)
- Create tasks and relationships
"""
import os
import sqlite3
import logging
import signal
import sys
import threading
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from datetime import datetime, UTC

# Third-party imports
from fastapi import FastAPI, HTTPException, Query, Body, Path, Request, UploadFile, File, Form, Depends
import httpx
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field, field_validator, model_validator
import json
import asyncio
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from strawberry.fastapi import GraphQLRouter

# Internal service imports
from database import TodoDatabase, TaskType, TaskStatus, VerificationStatus, RelationshipType
from mcp_api import MCPTodoAPI, MCP_FUNCTIONS, set_db
from backup import BackupManager, BackupScheduler
from webhooks import notify_webhooks
from monitoring import MetricsMiddleware, get_metrics, get_health_info, get_request_id
from rate_limiting import RateLimitMiddleware
from security_headers import SecurityHeadersMiddleware
from tracing import (
    setup_tracing, instrument_fastapi, instrument_database, instrument_httpx
)
from slack import send_task_notification, verify_slack_signature, get_slack_notifier
from file_storage import (
    validate_file_type, validate_file_size, save_file, read_file, delete_file,
    generate_unique_filename, sanitize_filename, DEFAULT_MAX_FILE_SIZE
)
from conversation_storage import ConversationStorage
from conversation_backup import ConversationBackupManager, BackupScheduler as ConversationBackupScheduler
from graphql_schema import schema

# Import extracted modules
from models import (
    ProjectCreate, ProjectResponse,
    TaskCreate, TaskUpdate, TaskResponse,
    LockTaskRequest, CompleteTaskRequest, BulkCompleteRequest,
    BulkAssignRequest, BulkUpdateStatusRequest, BulkDeleteRequest,
    RelationshipCreate,
    CommentCreate, CommentUpdate, CommentResponse
)
from auth.dependencies import verify_api_key, verify_admin_api_key, verify_session_token, verify_user_auth, optional_api_key
from exceptions.handlers import setup_exception_handlers
from middleware.setup import setup_middleware

# Routes are now consolidated in api/routes.py
# Import only for factory usage (not needed here in main.py)

# Try to import cost tracking
try:
    from cost_tracking import CostTracker, ServiceType
    COST_TRACKING_AVAILABLE = True
except ImportError:
    COST_TRACKING_AVAILABLE = False
    CostTracker = None
    ServiceType = None

# Try to import job queue
try:
    from job_queue import JobQueue, JobType, JobPriority, JobStatus
    JOB_QUEUE_AVAILABLE = True
except ImportError:
    JOB_QUEUE_AVAILABLE = False
    JobQueue = None
    JobType = None
    JobPriority = None
    JobStatus = None

# Try to import NATS queue
try:
    from nats_queue import NATSQueue
    from nats_worker import start_workers, stop_workers, TaskWorker
    NATS_AVAILABLE = True
except ImportError:
    NATS_AVAILABLE = False
    NATSQueue = None
    start_workers = None
    stop_workers = None
    TaskWorker = None

# Try to import voice commands module
try:
    from voice_commands import VoiceCommandRecognizer, VoiceCommandError, CommandType
    VOICE_COMMANDS_AVAILABLE = True
except ImportError:
    VOICE_COMMANDS_AVAILABLE = False
    VoiceCommandRecognizer = None
    VoiceCommandError = Exception
    CommandType = None

# Try to import voice quality scorer
try:
    from voice_quality import VoiceQualityScorer, VoiceQualityError
    VOICE_QUALITY_AVAILABLE = True
except ImportError:
    VOICE_QUALITY_AVAILABLE = False
    VoiceQualityScorer = None
    VoiceQualityError = Exception

# Setup structured logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()

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

handler = logging.StreamHandler()
handler.setFormatter(SafeFormatter('%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logging.basicConfig(
    level=getattr(logging, log_level),
    handlers=[handler],
    force=True
)
logger = logging.getLogger(__name__)

# Initialize database
# Use a safe default path that works in both production and test environments
default_db_path = os.getenv("TODO_DB_PATH")
if not default_db_path:
    # Try to use a writable location based on environment
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        default_db_path = "/app/data/todos.db"
    else:
        # Fallback to a temp location for testing/development
        import tempfile
        temp_dir = tempfile.gettempdir()
        default_db_path = os.path.join(temp_dir, "todo_test_default.db")
        # Ensure directory exists
        os.makedirs(os.path.dirname(default_db_path), exist_ok=True)

db_path = default_db_path
db = TodoDatabase(db_path)

# Initialize MCP API with database
set_db(db)

# Initialize backup manager
# Use a safe default path that works in both production and test environments
default_backups_dir = os.getenv("TODO_BACKUPS_DIR")
if not default_backups_dir:
    # Try to use a writable location based on environment
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        default_backups_dir = "/app/backups"
    else:
        # Fallback to a temp location for testing/development
        import tempfile
        temp_dir = tempfile.gettempdir()
        default_backups_dir = os.path.join(temp_dir, "todo_test_backups")
        # Ensure directory exists
        os.makedirs(default_backups_dir, exist_ok=True)

backups_dir = default_backups_dir
backup_manager = BackupManager(db_path, backups_dir)

# Initialize and start backup scheduler (nightly backups)
backup_interval_hours = int(os.getenv("TODO_BACKUP_INTERVAL_HOURS", "24"))
backup_scheduler = BackupScheduler(backup_manager, backup_interval_hours)
backup_scheduler.start()

# Initialize conversation storage
conversation_storage = ConversationStorage()

# Initialize conversation backup manager (if S3 is configured)
conversation_backup_manager = None
conversation_backup_scheduler = None

backup_s3_bucket = os.getenv("BACKUP_S3_BUCKET")

# Initialize job queue (if Redis is available)
job_queue = None
if JOB_QUEUE_AVAILABLE:
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        job_queue = JobQueue(redis_url=redis_url)
        logger.info("Job queue initialized successfully")
    except Exception as e:
        logger.warning(f"Failed to initialize job queue: {e}. Job queue features will be unavailable.")
        job_queue = None

# Initialize NATS queue (if available and explicitly enabled)
# NATS is optional - service works fine without it
nats_queue = None
nats_workers = []
if NATS_AVAILABLE and os.getenv("NATS_ENABLED", "false").lower() == "true":
    try:
        nats_url = os.getenv("NATS_URL", "nats://localhost:4222")
        use_jetstream = os.getenv("NATS_USE_JETSTREAM", "false").lower() == "true"
        num_workers = int(os.getenv("NATS_NUM_WORKERS", "1"))
        nats_queue = NATSQueue(nats_url=nats_url, use_jetstream=use_jetstream)
        logger.info(f"NATS queue initialized (URL: {nats_url}, JetStream: {use_jetstream})")
    except Exception as e:
        logger.warning(f"Failed to initialize NATS queue: {e}. NATS features will be unavailable.")
        nats_queue = None
else:
    if not NATS_AVAILABLE:
        logger.info("NATS queue unavailable (nats-py not installed)")
    else:
        logger.info("NATS disabled (set NATS_ENABLED=true to enable)")

backup_s3_bucket = os.getenv("BACKUP_S3_BUCKET")
if backup_s3_bucket:
    try:
        conversation_backup_manager = ConversationBackupManager(
            storage=conversation_storage,
            bucket_name=backup_s3_bucket
        )
        
        # Initialize and start conversation backup scheduler
        conversation_backup_interval = int(os.getenv("CONVERSATION_BACKUP_INTERVAL_HOURS", "24"))
        conversation_retention_days = int(os.getenv("CONVERSATION_BACKUP_RETENTION_DAYS", "30")) if os.getenv("CONVERSATION_BACKUP_RETENTION_DAYS") else None
        max_backups_per_conv = int(os.getenv("CONVERSATION_BACKUP_MAX_PER_CONVERSATION", "10"))
        
        conversation_backup_scheduler = ConversationBackupScheduler(
            backup_manager=conversation_backup_manager,
            interval_hours=conversation_backup_interval,
            enabled=True,
            retention_days=conversation_retention_days,
            max_backups_per_conversation=max_backups_per_conv
        )
        
        logger.info("Conversation backup to S3 enabled")
    except Exception as e:
        logger.warning(f"Failed to initialize conversation backup manager: {e}. Backups disabled.")
        conversation_backup_manager = None
else:
    logger.info("Conversation backup disabled (BACKUP_S3_BUCKET not set)")

# Graceful shutdown handler
shutdown_event = asyncio.Event()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_event.set()
    # Stop backup schedulers
    backup_scheduler.stop()
    if conversation_backup_scheduler:
        conversation_backup_scheduler.stop()
    logger.info("Graceful shutdown complete")


# Register signal handlers for graceful shutdown
# Only register in main thread (signal.signal only works in main thread)
if threading.current_thread() is threading.main_thread():
    try:
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    except ValueError:
        # Signal handlers may not be available in all contexts (e.g., tests)
        pass

# FastAPI lifespan events for graceful shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan with graceful shutdown."""
    # Startup
    logger.info("Application starting up...")
    
    # Initialize and enable distributed tracing
    try:
        setup_tracing()
        instrument_fastapi(app)
        instrument_database()
        instrument_httpx()
        logger.info("Distributed tracing enabled")
    except Exception as e:
        logger.warning("Failed to initialize tracing, continuing without it", exc_info=True)
    
    # Start NATS workers if available (non-blocking - don't wait if it fails)
    global nats_workers
    nats_workers = []
    if NATS_AVAILABLE and nats_queue:
        # Start NATS workers in background - don't block HTTP server startup
        async def start_nats_workers_background():
            try:
                num_workers = int(os.getenv("NATS_NUM_WORKERS", "1"))
                workers = await start_workers(
                    db=db,
                    nats_url=nats_queue.nats_url,
                    num_workers=num_workers,
                    use_jetstream=nats_queue.use_jetstream
                )
                nats_workers.extend(workers)
                logger.info(f"Started {len(workers)} NATS workers")
            except Exception as e:
                logger.warning(f"Failed to start NATS workers (service will continue without NATS): {e}")
                nats_workers = []
        
        # Don't await - let it run in background, HTTP server should start immediately
        asyncio.create_task(start_nats_workers_background())
        logger.info("NATS workers will start in background (if available)")
    
    yield
    # Shutdown
    logger.info("Application shutting down...")
    backup_scheduler.stop()
    if conversation_backup_scheduler:
        conversation_backup_scheduler.stop()
    
    # Stop NATS workers
    if nats_workers:
        try:
            await stop_workers(nats_workers)
            logger.info("Stopped NATS workers")
        except Exception as e:
            logger.warning(f"Error stopping NATS workers: {e}", exc_info=True)
    
    logger.info("Shutdown complete")


# Create FastAPI app with lifespan
app = FastAPI(
    title="TODO Service",
    description="Task management service for AI agents",
    version="0.1.0",
    lifespan=lifespan
)

# Setup middleware (includes MetricsMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware)
setup_middleware(app)

# Setup exception handlers
setup_exception_handlers(app)

# IMPORTANT: Define specific routes BEFORE including the router
# FastAPI matches routes in order, so specific routes like /tasks/activity-feed
# must come before parameterized routes like /tasks/{task_id} to avoid conflicts
# The activity-feed route is defined later in this file, but we need to ensure
# route ordering is correct. Routes defined here will be matched before router routes.

# Register command pattern router (minimal FastAPI usage)
# All API routes are now under /api/<Entity>/<action>
from api.command_router import router as command_router
from api.routes.mcp import router as mcp_router
app.include_router(command_router)
app.include_router(mcp_router)

# Add GraphQL router
graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")

# Relationships endpoint
@app.post("/relationships", status_code=201)
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
        
        # Validate using RelationshipCreate model (this will catch invalid relationship_type and parent==child)
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
            # Pydantic field_validator or model_validator errors (from RelationshipCreate validators)
            raise HTTPException(status_code=422, detail=str(e))
        except KeyError as e:
            raise HTTPException(status_code=422, detail=f"Missing required field: {e}")
        
        # RelationshipCreate model already validates relationship_type and parent != child
        # The model_validator will raise ValueError if parent == child
        rel_id = db.create_relationship(
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
    except HTTPException:
        raise
    except ValueError as e:
        # Handle validation errors from database (circular dependencies, etc.)
        # But RelationshipCreate model validation should catch most issues
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create relationship: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create relationship")

# Mount static files directory for web interface
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Root endpoint - serve web interface
@app.get("/", response_class=HTMLResponse)
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

# Authentication security scheme
security = HTTPBearer(auto_error=False)

# Authentication dependencies are now imported from auth.dependencies above
# Old definitions removed - see auth/dependencies.py

# Exception handlers are now set up via setup_exception_handlers() above
# Keeping old handlers for now during migration - they will be removed
# once setup_exception_handlers() is confirmed working
@app.exception_handler(Exception)
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


@app.exception_handler(sqlite3.Error)
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


@app.exception_handler(RequestValidationError)
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


# Pydantic models are now imported from models module above


@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint with component status (database, service)."""
    health_info = get_health_info(db)
    
    # Return appropriate HTTP status based on overall health
    if health_info.get("status") == "unhealthy":
        from fastapi import status as http_status
        return JSONResponse(
            content=health_info,
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    return health_info


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=get_metrics(),
        media_type=CONTENT_TYPE_LATEST
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("TODO_SERVICE_PORT", "8004"))
    
    # Configure uvicorn for production
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level=log_level.lower(),
        access_log=True,
        # Graceful shutdown settings
        timeout_keep_alive=30,
        timeout_graceful_shutdown=30,
    )
    server = uvicorn.Server(config)
    
    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    finally:
        # Ensure cleanup
        backup_scheduler.stop()
        logger.info("Service stopped")


