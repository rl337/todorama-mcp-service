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
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Body, Path, Request, UploadFile, File, Form, Depends
import httpx
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field, field_validator, model_validator
import json
import asyncio

from database import TodoDatabase, TaskType, TaskStatus, VerificationStatus, RelationshipType
from mcp_api import MCPTodoAPI, MCP_FUNCTIONS, set_db
from backup import BackupManager, BackupScheduler
from webhooks import notify_webhooks
from monitoring import MetricsMiddleware, get_metrics, get_health_info, get_request_id
from rate_limiting import RateLimitMiddleware
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
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from strawberry.fastapi import GraphQLRouter
from graphql_schema import schema

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
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Add request ID filter for structured logging
class RequestIDFilter(logging.Filter):
    """Filter to add request ID to log records."""
    def filter(self, record):
        record.request_id = get_request_id() or '-'
        return True

# Apply filter to root logger
logging.getLogger().addFilter(RequestIDFilter())
logger = logging.getLogger(__name__)

# Initialize database
db_path = os.getenv("TODO_DB_PATH", "/app/data/todos.db")
db = TodoDatabase(db_path)

# Initialize MCP API with database
set_db(db)

# Initialize backup manager
backups_dir = os.getenv("TODO_BACKUPS_DIR", "/app/backups")
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

# Initialize NATS queue (if available)
nats_queue = None
nats_workers = []
if NATS_AVAILABLE:
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
    logger.info("NATS queue unavailable (nats-py not installed)")

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
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

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
    
    # Start NATS workers if available
    global nats_workers
    if NATS_AVAILABLE and nats_queue:
        try:
            num_workers = int(os.getenv("NATS_NUM_WORKERS", "1"))
            nats_workers = await start_workers(
                db=db,
                nats_url=nats_queue.nats_url,
                num_workers=num_workers,
                use_jetstream=nats_queue.use_jetstream
            )
            logger.info(f"Started {len(nats_workers)} NATS workers")
        except Exception as e:
            logger.warning(f"Failed to start NATS workers: {e}", exc_info=True)
            nats_workers = []
    
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

# Add monitoring middleware (must be added before routes)
app.add_middleware(MetricsMiddleware)

# Add rate limiting middleware (after metrics, before routes)
app.add_middleware(RateLimitMiddleware)

# Add GraphQL router
graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")

# Authentication security scheme
security = HTTPBearer(auto_error=False)


# Authentication dependency
async def verify_api_key(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = None
) -> Dict[str, Any]:
    """
    Verify API key from request headers.
    Supports both X-API-Key header and Authorization: Bearer token.
    
    Returns:
        Dictionary with 'key_id' and 'project_id' if authenticated
    Raises:
        HTTPException 401 if authentication fails
    """
    api_key = None
    
    # Try X-API-Key header first
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        api_key = api_key_header
    
    # Try Authorization: Bearer token
    if not api_key and authorization:
        api_key = authorization.credentials
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide X-API-Key header or Authorization: Bearer token."
        )
    
    # Hash the key and look it up
    key_hash = db._hash_api_key(api_key)
    key_info = db.get_api_key_by_hash(key_hash)
    
    if not key_info:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
    
    if key_info["enabled"] != 1:
        raise HTTPException(
            status_code=401,
            detail="API key has been revoked"
        )
    
    # Update last used timestamp
    db.update_api_key_last_used(key_info["id"])
    
    # Store in request state for use in endpoints
    request.state.project_id = key_info["project_id"]
    request.state.key_id = key_info["id"]
    
    # Get admin status
    is_admin = db.is_api_key_admin(key_info["id"])
    request.state.is_admin = is_admin
    
    return {
        "key_id": key_info["id"],
        "project_id": key_info["project_id"],
        "is_admin": is_admin
    }


# Admin authentication dependency
async def verify_admin_api_key(
    request: Request,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Verify that the API key has admin privileges.
    
    Returns:
        Same as verify_api_key if admin, else raises 403
    Raises:
        HTTPException 403 if not admin
    """
    if not auth.get("is_admin", False):
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required"
        )
    return auth


async def verify_session_token(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = None
) -> Dict[str, Any]:
    """
    Verify session token from Authorization: Bearer token.
    
    Returns:
        Dictionary with 'user_id', 'session_id', and 'session_token' if authenticated
    Raises:
        HTTPException 401 if authentication fails
    """
    token = None
    
    # Get token from Authorization header
    if authorization:
        token = authorization.credentials
    else:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Session token required. Provide Authorization: Bearer token."
        )
    
    # Look up session
    session = db.get_session_by_token(token)
    
    if not session:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session token"
        )
    
    # Store in request state
    request.state.user_id = session["user_id"]
    request.state.session_id = session["id"]
    request.state.session_token = token
    
    return {
        "user_id": session["user_id"],
        "session_id": session["id"],
        "session_token": token
    }


async def verify_user_auth(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = None
) -> Dict[str, Any]:
    """
    Verify either API key or session token authentication.
    Tries session token first, then API key.
    
    Returns:
        Dictionary with authentication info
    """
    # Try session token first
    token = None
    if authorization:
        token = authorization.credentials
    else:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if token:
        # Try as session token first
        session = db.get_session_by_token(token)
        if session:
            request.state.user_id = session["user_id"]
            request.state.session_id = session["id"]
            return {
                "user_id": session["user_id"],
                "session_id": session["id"],
                "auth_type": "session"
            }
    
    # Try API key if no session token found
    api_key = None
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        api_key = api_key_header
    
    if api_key:
        # Hash the key and look it up
        key_hash = db._hash_api_key(api_key)
        key_info = db.get_api_key_by_hash(key_hash)
        
        if key_info and key_info["enabled"] == 1:
            db.update_api_key_last_used(key_info["id"])
            request.state.project_id = key_info["project_id"]
            request.state.key_id = key_info["id"]
            return {
                "key_id": key_info["id"],
                "project_id": key_info["project_id"],
                "auth_type": "api_key"
            }
    
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide X-API-Key header or Authorization: Bearer token."
    )


# Optional authentication (doesn't raise error if missing)
async def optional_api_key(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = None
) -> Optional[Dict[str, Any]]:
    """
    Optional API key verification.
    Returns None if no key provided, otherwise verifies the key.
    """
    try:
        return await verify_api_key(request, authorization)
    except HTTPException:
        # Check if it's a 401 (missing key is OK for optional auth)
        api_key_header = request.headers.get("X-API-Key")
        if not api_key_header and not authorization:
            return None
        raise  # Re-raise if key was provided but invalid


# Global exception handler for consistent error responses
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


# Pydantic models for request/response
class ProjectCreate(BaseModel):
    name: str = Field(..., description="Project name (unique)", min_length=1)
    local_path: str = Field(..., description="Local path where project is located", min_length=1)
    origin_url: Optional[str] = Field(None, description="Origin URL (GitHub, file://, etc.)")
    description: Optional[str] = Field(None, description="Project description")
    
    @field_validator('name', 'local_path')
    @classmethod
    def validate_not_empty_or_whitespace(cls, v: str) -> str:
        """Validate that string fields are not empty or only whitespace."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or contain only whitespace")
        return v.strip()


class TaskCreate(BaseModel):
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
    task_status: Optional[str] = None
    verification_status: Optional[str] = None
    notes: Optional[str] = None
    
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


class RelationshipCreate(BaseModel):
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


class ProjectResponse(BaseModel):
    """Project response model."""
    id: int
    name: str
    local_path: str
    origin_url: Optional[str]
    description: Optional[str]
    created_at: str
    updated_at: str


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


@app.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(project: ProjectCreate):
    """Create a new project."""
    try:
        project_id = db.create_project(
            name=project.name,
            local_path=project.local_path,
            origin_url=project.origin_url,
            description=project.description
        )
        created_project = db.get_project(project_id)
        if not created_project:
            raise HTTPException(status_code=500, detail="Failed to retrieve created project")
        return ProjectResponse(**created_project)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Project with name '{project.name}' already exists")


@app.get("/projects", response_model=List[ProjectResponse])
async def list_projects(
    request: Request,
    auth: Optional[Dict[str, Any]] = Depends(optional_api_key)
):
    """List all projects."""
    # If authenticated, filter by project scope
    if auth:
        # For now, allow listing all projects even with auth
        # Can be restricted to user's project later
        projects = db.list_projects()
    else:
        # Without auth, return all projects (backward compatibility)
        projects = db.list_projects()
    return [ProjectResponse(**project) for project in projects]


@app.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int = Path(..., gt=0, description="Project ID")):
    """Get a project by ID."""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project {project_id} not found. Please verify the project_id is correct."
        )
    return ProjectResponse(**project)


@app.get("/projects/name/{project_name}", response_model=ProjectResponse)
async def get_project_by_name(project_name: str = Path(..., min_length=1, description="Project name")):
    """Get a project by name."""
    # Validate project_name is not empty or whitespace
    if not project_name or not project_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Project name cannot be empty or contain only whitespace. Please provide a valid project name."
        )
    
    project = db.get_project_by_name(project_name.strip())
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project '{project_name}' not found. Please verify the project name is correct and try again."
        )
    return ProjectResponse(**project)


@app.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    task: TaskCreate,
    request: Request,
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """Create a new task."""
    # Verify project exists if provided (validation already handled by Pydantic)
    if task.project_id is not None:
        project = db.get_project(task.project_id)
        if not project:
            raise HTTPException(
                status_code=404,
                detail=f"Project with ID {task.project_id} not found. Please verify the project_id is correct."
            )
        # Verify API key is for this project
        if request.state.project_id != task.project_id:
            raise HTTPException(
                status_code=403,
                detail="API key is not authorized for this project"
            )
    else:
        # If no project_id, tasks can be created without project (allowed)
        pass
    
    try:
        # Parse due_date if provided with better error handling
        due_date_obj = None
        if task.due_date:
            try:
                from datetime import datetime
                # Try parsing with timezone first
                if task.due_date.endswith('Z'):
                    due_date_obj = datetime.fromisoformat(task.due_date.replace('Z', '+00:00'))
                else:
                    due_date_obj = datetime.fromisoformat(task.due_date)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid due_date format '{task.due_date}'. Must be ISO 8601 format (e.g., '2024-01-01T00:00:00' or '2024-01-01T00:00:00Z'). Error: {str(e)}"
                )
        
        task_id = db.create_task(
            title=task.title,
            task_type=task.task_type,
            task_instruction=task.task_instruction,
            verification_instruction=task.verification_instruction,
            agent_id=task.agent_id,
            project_id=task.project_id,
            notes=task.notes,
            priority=task.priority,
            estimated_hours=task.estimated_hours,
            due_date=due_date_obj if task.due_date else None
        )
    except Exception as e:
        logger.error(f"Failed to create task: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to create task. Please try again or contact support if the issue persists."
        )
    
    created_task = db.get_task(task_id)
    if not created_task:
        logger.error(f"Task {task_id} was created but could not be retrieved")
        raise HTTPException(
            status_code=500,
            detail="Task was created but could not be retrieved. Please check task status."
        )
    
    # Notify webhooks for task.created event
    asyncio.create_task(notify_webhooks(
        db,
        project_id=task.project_id,
        event_type="task.created",
        payload={
            "event": "task.created",
            "task": dict(created_task),
            "timestamp": datetime.utcnow().isoformat()
        }
    ))
    
    # Send Slack notification (async wrapper for sync function)
    project = db.get_project(task.project_id) if task.project_id else None
    async def send_slack_notif():
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            send_task_notification,
            None,  # Use default channel from env
            "task.created",
            dict(created_task),
            dict(project) if project else None
        )
    asyncio.create_task(send_slack_notif())
    
    return TaskResponse(**created_task)


@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int = Path(..., gt=0, description="Task ID")):
    """Get a task by ID."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    return TaskResponse(**task)


@app.get("/tasks", response_model=List[TaskResponse])
async def query_tasks(
    task_type: Optional[str] = Query(None, description="Filter by task type"),
    task_status: Optional[str] = Query(None, description="Filter by task status"),
    assigned_agent: Optional[str] = Query(None, description="Filter by assigned agent"),
    project_id: Optional[int] = Query(None, description="Filter by project ID", gt=0),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    tag_id: Optional[int] = Query(None, description="Filter by tag ID (single tag)", gt=0),
    tag_ids: Optional[str] = Query(None, description="Filter by multiple tag IDs (comma-separated)"),
    order_by: Optional[str] = Query(None, description="Order by: priority, priority_asc, or created_at (default)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    # Advanced filtering: date ranges
    created_after: Optional[str] = Query(None, description="Filter by created_at >= date (ISO format)"),
    created_before: Optional[str] = Query(None, description="Filter by created_at <= date (ISO format)"),
    updated_after: Optional[str] = Query(None, description="Filter by updated_at >= date (ISO format)"),
    updated_before: Optional[str] = Query(None, description="Filter by updated_at <= date (ISO format)"),
    completed_after: Optional[str] = Query(None, description="Filter by completed_at >= date (ISO format)"),
    completed_before: Optional[str] = Query(None, description="Filter by completed_at <= date (ISO format)"),
    # Advanced filtering: text search
    search: Optional[str] = Query(None, description="Search in title and task_instruction (case-insensitive)")
):
    """Query tasks with filters including advanced date range and text search."""
    if task_type and task_type not in ["concrete", "abstract", "epic"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type '{task_type}'. Must be one of: concrete, abstract, epic"
        )
    if task_status and task_status not in ["available", "in_progress", "complete", "blocked", "cancelled"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_status '{task_status}'. Must be one of: available, in_progress, complete, blocked, cancelled"
        )
    if priority and priority not in ["low", "medium", "high", "critical"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority '{priority}'. Must be one of: low, medium, high, critical"
        )
    if order_by and order_by not in ["priority", "priority_asc"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid order_by '{order_by}'. Must be one of: priority, priority_asc"
        )
    
    # Parse tag_ids if provided
    tag_ids_list = None
    if tag_ids:
        try:
            tag_ids_list = [int(tid.strip()) for tid in tag_ids.split(",") if tid.strip()]
            # Validate all tag IDs are positive
            for tid in tag_ids_list:
                if tid <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid tag_id '{tid}' in tag_ids. All tag IDs must be positive integers"
                    )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tag_ids format '{tag_ids}'. Must be comma-separated positive integers (e.g., '1,2,3'). Error: {str(e)}"
            )
    
    # Validate and parse date strings
    from datetime import datetime
    date_filters = {}
    for date_param, date_value in [
        ("created_after", created_after),
        ("created_before", created_before),
        ("updated_after", updated_after),
        ("updated_before", updated_before),
        ("completed_after", completed_after),
        ("completed_before", completed_before),
    ]:
        if date_value:
            try:
                # Parse ISO format datetime
                parsed_date = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                date_filters[date_param] = parsed_date.isoformat()
            except (ValueError, AttributeError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid date format for {date_param}: '{date_value}'. Expected ISO format (e.g., '2025-01-01T00:00:00'). Error: {str(e)}"
                )
    
    tasks = db.query_tasks(
        task_type=task_type,
        task_status=task_status,
        assigned_agent=assigned_agent,
        project_id=project_id,
        priority=priority,
        tag_id=tag_id,
        tag_ids=tag_ids_list,
        order_by=order_by,
        limit=limit,
        created_after=date_filters.get("created_after"),
        created_before=date_filters.get("created_before"),
        updated_after=date_filters.get("updated_after"),
        updated_before=date_filters.get("updated_before"),
        completed_after=date_filters.get("completed_after"),
        completed_before=date_filters.get("completed_before"),
        search=search
    )
    return [TaskResponse(**task) for task in tasks]


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


@app.post("/tasks/{task_id}/lock")
async def lock_task(task_id: int = Path(..., gt=0), request: LockTaskRequest = Body(..., embed=True)):
    """Lock a task for an agent (set to in_progress)."""
    agent_id = request.agent_id
    
    # Check if agent is blocked
    if db.is_agent_blocked(agent_id):
        raise HTTPException(
            status_code=403,
            detail=f"Agent {agent_id} is blocked and cannot reserve tasks"
        )
    
    # Check if task exists first
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    success = db.lock_task(task_id, agent_id)
    if not success:
        current_status = task.get("task_status", "unknown")
        assigned_to = task.get("assigned_agent", "none")
        raise HTTPException(
            status_code=409,
            detail=f"Task {task_id} cannot be locked. Current status: {current_status}, assigned to: {assigned_to}. Only tasks with status 'available' can be locked."
        )
    
    # Notify webhooks for task.status_changed event
    updated_task = db.get_task(task_id)
    asyncio.create_task(notify_webhooks(
        db,
        project_id=task.get("project_id"),
        event_type="task.status_changed",
        payload={
            "event": "task.status_changed",
            "task": dict(updated_task),
            "old_status": current_status,
            "new_status": "in_progress",
            "agent_id": agent_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    ))
    
    return {"message": f"Task {task_id} locked by agent {agent_id}", "task_id": task_id}


@app.post("/tasks/{task_id}/unlock")
async def unlock_task(task_id: int = Path(..., gt=0), request: LockTaskRequest = Body(..., embed=True)):
    """Unlock a task (set back to available)."""
    agent_id = request.agent_id
    
    # Get task before unlocking to capture old status
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    old_status = task.get("task_status", "unknown")
    
    # Check if task is actually locked
    if old_status != "in_progress":
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} is not currently locked (status: '{old_status}'). Only tasks with status 'in_progress' can be unlocked."
        )
    
    # Check if task is assigned to this agent
    if task.get("assigned_agent") != agent_id:
        raise HTTPException(
            status_code=403,
            detail=f"Task {task_id} is assigned to agent '{task.get('assigned_agent', 'none')}', not '{agent_id}'. Only the assigned agent can unlock this task."
        )
    
    db.unlock_task(task_id, agent_id)
    
    # Notify webhooks for task.status_changed event
    updated_task = db.get_task(task_id)
    asyncio.create_task(notify_webhooks(
        db,
        project_id=task.get("project_id"),
        event_type="task.status_changed",
        payload={
            "event": "task.status_changed",
            "task": dict(updated_task),
            "old_status": old_status,
            "new_status": "available",
            "agent_id": agent_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    ))
    
    return {"message": f"Task {task_id} unlocked by agent {agent_id}", "task_id": task_id}


@app.get("/monitoring/stale-tasks")
async def get_stale_tasks(hours: Optional[int] = Query(None, description="Hours threshold for stale tasks (defaults to TASK_TIMEOUT_HOURS env var or 24)", ge=1)):
    """Get stale tasks (tasks in_progress longer than timeout)."""
    stale_tasks = db.get_stale_tasks(hours=hours)
    timeout_hours = hours if hours is not None else int(os.getenv("TASK_TIMEOUT_HOURS", "24"))
    
    return {
        "stale_tasks": [dict(task) for task in stale_tasks],
        "count": len(stale_tasks),
        "timeout_hours": timeout_hours
    }


@app.get("/monitoring/nats")
async def get_nats_status():
    """Get NATS queue status and worker information."""
    if not NATS_AVAILABLE or not nats_queue:
        return {
            "available": False,
            "status": "not_configured",
            "message": "NATS queue is not available or not configured"
        }
    
    try:
        # Check connection status
        connected = nats_queue.connected if hasattr(nats_queue, 'connected') else False
        
        # Get worker statistics
        workers_info = []
        if nats_workers:
            for worker in nats_workers:
                workers_info.append({
                    "worker_id": worker.worker_id,
                    "processed_count": worker.processed_count,
                    "error_count": worker.error_count,
                    "running": worker.running
                })
        
        return {
            "available": True,
            "status": "connected" if connected else "disconnected",
            "nats_url": nats_queue.nats_url,
            "use_jetstream": nats_queue.use_jetstream,
            "connected": connected,
            "workers": {
                "count": len(nats_workers),
                "details": workers_info
            }
        }
    except Exception as e:
        logger.error(f"Error getting NATS status: {e}", exc_info=True)
        return {
            "available": True,
            "status": "error",
            "error": str(e)
        }


@app.post("/tasks/{task_id}/unlock-stale")
async def unlock_stale_task(task_id: int = Path(..., gt=0)):
    """Manually unlock a stale task (bypasses normal unlock restrictions)."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    # Only allow unlocking tasks that are in_progress
    if task.get("task_status") != "in_progress":
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} is not in_progress (status: '{task.get('task_status', 'unknown')}'). Only in_progress tasks can be unlocked via this endpoint."
        )
    
    # Check if task is stale
    timeout_hours = int(os.getenv("TASK_TIMEOUT_HOURS", "24"))
    stale_tasks = db.get_stale_tasks(hours=timeout_hours)
    stale_task_ids = [t["id"] for t in stale_tasks]
    
    if task_id not in stale_task_ids:
        # Still allow unlock but warn
        logger.warning(f"Unlock-stale called for task {task_id} which is not yet stale (timeout: {timeout_hours} hours)")
    
    # Unlock the task using system agent
    old_agent = task.get("assigned_agent", "unknown")
    db.unlock_task(task_id, "system")
    
    # Add finding update
    stale_message = f"Task manually unlocked as stale via API. Previously assigned to agent '{old_agent}'."
    db.add_task_update(
        task_id=task_id,
        agent_id="system",
        content=stale_message,
        update_type="finding",
        metadata={"manual_unlock": True, "previous_agent": old_agent}
    )
    
    # Notify webhooks
    updated_task = db.get_task(task_id)
    asyncio.create_task(notify_webhooks(
        db,
        project_id=task.get("project_id"),
        event_type="task.status_changed",
        payload={
            "event": "task.status_changed",
            "task": dict(updated_task),
            "old_status": "in_progress",
            "new_status": "available",
            "agent_id": "system",
            "timestamp": datetime.utcnow().isoformat(),
            "reason": "stale_unlock"
        }
    ))
    
    return {
        "unlocked": True,
        "task_id": task_id,
        "message": f"Stale task {task_id} unlocked successfully"
    }


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


@app.post("/tasks/{task_id}/complete")
async def complete_task(task_id: int = Path(..., gt=0), request: CompleteTaskRequest = Body(..., embed=True)):
    """Mark a task as complete."""
    agent_id = request.agent_id
    notes = request.notes
    actual_hours = request.actual_hours
    
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    # Check if task can be completed
    if task.get("task_status") == "complete":
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} is already complete. No action needed."
        )
    
    db.complete_task(task_id, agent_id, notes=notes, actual_hours=actual_hours)
    
    # Get updated task data
    updated_task = db.get_task(task_id)
    
    # Notify webhooks for task.completed event
    asyncio.create_task(notify_webhooks(
        db,
        project_id=task.get("project_id"),
        event_type="task.completed",
        payload={
            "event": "task.completed",
            "task": dict(updated_task),
            "agent_id": agent_id,
            "notes": notes,
            "actual_hours": actual_hours,
            "timestamp": datetime.utcnow().isoformat()
        }
    ))
    
    # Send Slack notification (async wrapper for sync function)
    project = db.get_project(task.get("project_id")) if task.get("project_id") else None
    async def send_slack_notif():
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            send_task_notification,
            None,  # Use default channel from env
            "task.completed",
            dict(updated_task),
            dict(project) if project else None
        )
    asyncio.create_task(send_slack_notif())
    
    return {"message": f"Task {task_id} marked as complete by agent {agent_id}", "task_id": task_id}


@app.post("/tasks/{task_id}/verify")
async def verify_task(task_id: int = Path(..., gt=0), request: LockTaskRequest = Body(..., embed=True)):
    """Mark a task as verified (verification check passed)."""
    agent_id = request.agent_id
    
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    if task["task_status"] != "complete":
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} must be complete before verification. Current status: '{task['task_status']}'. Please complete the task first."
        )
    
    if task.get("verification_status") == "verified":
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} is already verified. No action needed."
        )
    
    db.verify_task(task_id, agent_id)
    return {"message": f"Task {task_id} verified by agent {agent_id}", "task_id": task_id}


# Bulk operations endpoints
@app.post("/tasks/bulk/complete")
async def bulk_complete_tasks(request: BulkCompleteRequest):
    """Bulk complete multiple tasks."""
    try:
        result = db.bulk_complete_tasks(
            task_ids=request.task_ids,
            agent_id=request.agent_id,
            notes=request.notes,
            actual_hours=request.actual_hours,
            require_all=request.require_all
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Bulk complete failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Bulk complete operation failed: {str(e)}")


@app.post("/tasks/bulk/assign")
async def bulk_assign_tasks(request: BulkAssignRequest):
    """Bulk assign multiple tasks to an agent."""
    try:
        result = db.bulk_assign_tasks(
            task_ids=request.task_ids,
            agent_id=request.agent_id,
            require_all=request.require_all
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Bulk assign failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Bulk assign operation failed: {str(e)}")


@app.post("/tasks/bulk/update-status")
async def bulk_update_status(request: BulkUpdateStatusRequest):
    """Bulk update status of multiple tasks."""
    try:
        result = db.bulk_update_status(
            task_ids=request.task_ids,
            task_status=request.task_status,
            agent_id=request.agent_id,
            require_all=request.require_all
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Bulk update status failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Bulk update status operation failed: {str(e)}")


@app.post("/tasks/bulk/delete")
async def bulk_delete_tasks(request: BulkDeleteRequest):
    """Bulk delete multiple tasks. Requires confirmation."""
    if not request.confirm:
        raise HTTPException(
            status_code=400,
            detail="Bulk delete requires confirmation. Set 'confirm' to true to proceed."
        )
    
    try:
        result = db.bulk_delete_tasks(
            task_ids=request.task_ids,
            require_all=request.require_all
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Bulk delete failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Bulk delete operation failed: {str(e)}")


# File attachment endpoints
@app.post("/tasks/{task_id}/attachments")
async def upload_attachment(
    task_id: int = Path(..., gt=0),
    file: UploadFile = File(...),
    agent_id: str = Form(...),
    description: Optional[str] = Form(None)
):
    """Upload a file attachment to a task."""
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    if not agent_id or not agent_id.strip():
        raise HTTPException(
            status_code=400,
            detail="agent_id is required and cannot be empty"
        )
    
    # Validate file type
    content_type = file.content_type or "application/octet-stream"
    if not validate_file_type(content_type):
        raise HTTPException(
            status_code=415,
            detail=f"File type '{content_type}' is not allowed. Please upload a supported file type."
        )
    
    # Read file content
    try:
        file_content = await file.read()
    except Exception as e:
        logger.error(f"Failed to read uploaded file: {e}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read uploaded file: {str(e)}"
        )
    
    # Validate file size
    file_size = len(file_content)
    max_size = int(os.getenv("TODO_MAX_ATTACHMENT_SIZE", DEFAULT_MAX_FILE_SIZE))
    if not validate_file_size(file_size, max_size):
        raise HTTPException(
            status_code=413,
            detail=f"File size ({file_size} bytes) exceeds maximum allowed size ({max_size} bytes)"
        )
    
    # Sanitize and generate unique filename
    original_filename = file.filename or "unnamed_file"
    storage_filename, file_path = generate_unique_filename(original_filename, task_id)
    
    # Save file to disk
    try:
        save_file(file_content, file_path)
    except Exception as e:
        logger.error(f"Failed to save file: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save file: {str(e)}"
        )
    
    # Create attachment record
    try:
        attachment_id = db.create_attachment(
            task_id=task_id,
            filename=storage_filename,
            original_filename=sanitize_filename(original_filename),
            file_path=file_path,
            file_size=file_size,
            content_type=content_type,
            uploaded_by=agent_id,
            description=description
        )
    except Exception as e:
        # Clean up file if database insert fails
        delete_file(file_path)
        logger.error(f"Failed to create attachment record: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create attachment record: {str(e)}"
        )
    
    # Get created attachment
    attachment = db.get_attachment(attachment_id)
    if not attachment:
        raise HTTPException(status_code=500, detail="Failed to retrieve created attachment")
    
    logger.info(f"Attachment {attachment_id} uploaded to task {task_id} by {agent_id}")
    return {
        "success": True,
        "attachment_id": attachment_id,
        "filename": attachment["original_filename"],
        "file_size": attachment["file_size"],
        "content_type": attachment["content_type"],
        "description": attachment.get("description"),
        "created_at": attachment["created_at"]
    }


@app.get("/tasks/{task_id}/attachments")
async def list_task_attachments(task_id: int = Path(..., gt=0)):
    """List all attachments for a task."""
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    attachments = db.get_task_attachments(task_id)
    return {
        "success": True,
        "task_id": task_id,
        "attachments": [
            {
                "id": att["id"],
                "filename": att["original_filename"],
                "file_size": att["file_size"],
                "content_type": att["content_type"],
                "description": att.get("description"),
                "uploaded_by": att["uploaded_by"],
                "created_at": att["created_at"]
            }
            for att in attachments
        ],
        "count": len(attachments)
    }


@app.get("/tasks/{task_id}/attachments/{attachment_id}")
async def get_attachment_metadata(
    task_id: int = Path(..., gt=0),
    attachment_id: int = Path(..., gt=0)
):
    """Get attachment metadata."""
    attachment = db.get_attachment_by_task_and_id(task_id, attachment_id)
    if not attachment:
        raise HTTPException(
            status_code=404,
            detail=f"Attachment {attachment_id} not found for task {task_id}. Please verify the IDs are correct."
        )
    
    return {
        "success": True,
        "id": attachment["id"],
        "task_id": attachment["task_id"],
        "filename": attachment["original_filename"],
        "file_size": attachment["file_size"],
        "content_type": attachment["content_type"],
        "description": attachment.get("description"),
        "uploaded_by": attachment["uploaded_by"],
        "created_at": attachment["created_at"]
    }


@app.get("/tasks/{task_id}/attachments/{attachment_id}/download")
async def download_attachment(
    task_id: int = Path(..., gt=0),
    attachment_id: int = Path(..., gt=0)
):
    """Download a file attachment."""
    attachment = db.get_attachment_by_task_and_id(task_id, attachment_id)
    if not attachment:
        raise HTTPException(
            status_code=404,
            detail=f"Attachment {attachment_id} not found for task {task_id}. Please verify the IDs are correct."
        )
    
    # Read file from disk
    try:
        file_content = read_file(attachment["file_path"])
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Attachment file not found on disk. The file may have been deleted."
        )
    except Exception as e:
        logger.error(f"Failed to read attachment file: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read attachment file: {str(e)}"
        )
    
    # Return file as streaming response
    return Response(
        content=file_content,
        media_type=attachment["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{attachment["original_filename"]}"'
        }
    )


@app.delete("/tasks/{task_id}/attachments/{attachment_id}")
async def delete_attachment(
    task_id: int = Path(..., gt=0),
    attachment_id: int = Path(..., gt=0)
):
    """Delete a file attachment."""
    attachment = db.get_attachment_by_task_and_id(task_id, attachment_id)
    if not attachment:
        raise HTTPException(
            status_code=404,
            detail=f"Attachment {attachment_id} not found for task {task_id}. Please verify the IDs are correct."
        )
    
    # Delete from database (this will also delete the file via database method)
    success = db.delete_attachment(attachment_id)
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to delete attachment"
        )
    
    logger.info(f"Attachment {attachment_id} deleted from task {task_id}")
    return {
        "success": True,
        "message": f"Attachment {attachment_id} deleted successfully",
        "attachment_id": attachment_id,
        "task_id": task_id
    }


# Task comments endpoints
@app.post("/tasks/{task_id}/comments", response_model=CommentResponse, status_code=201)
async def create_comment(
    task_id: int = Path(..., gt=0, description="Task ID"),
    comment: CommentCreate = Body(...)
):
    """Create a comment on a task."""
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    try:
        comment_id = db.create_comment(
            task_id=task_id,
            agent_id=comment.agent_id,
            content=comment.content,
            parent_comment_id=comment.parent_comment_id,
            mentions=comment.mentions
        )
        
        created_comment = db.get_comment(comment_id)
        if not created_comment:
            raise HTTPException(status_code=500, detail="Failed to retrieve created comment")
        
        # Notify webhooks
        asyncio.create_task(notify_webhooks(
            db,
            project_id=task.get("project_id"),
            event_type="comment.created",
            payload={
                "event": "comment.created",
                "comment": dict(created_comment),
                "task_id": task_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        ))
        
        return CommentResponse(**created_comment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create comment: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to create comment. Please try again or contact support if the issue persists."
        )


@app.get("/tasks/{task_id}/comments", response_model=List[CommentResponse])
async def list_task_comments(
    task_id: int = Path(..., gt=0, description="Task ID"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of comments to return")
):
    """List all top-level comments for a task."""
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    comments = db.get_task_comments(task_id, limit=limit)
    return [CommentResponse(**comment) for comment in comments]


@app.get("/tasks/{task_id}/comments/{comment_id}", response_model=CommentResponse)
async def get_comment(
    task_id: int = Path(..., gt=0, description="Task ID"),
    comment_id: int = Path(..., gt=0, description="Comment ID")
):
    """Get a comment by ID."""
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    comment = db.get_comment(comment_id)
    if not comment:
        raise HTTPException(
            status_code=404,
            detail=f"Comment {comment_id} not found. Please verify the comment_id is correct."
        )
    
    # Verify comment belongs to task
    if comment["task_id"] != task_id:
        raise HTTPException(
            status_code=400,
            detail=f"Comment {comment_id} does not belong to task {task_id}."
        )
    
    return CommentResponse(**comment)


@app.get("/comments/{comment_id}/thread", response_model=List[CommentResponse])
async def get_comment_thread(
    comment_id: int = Path(..., gt=0, description="Parent comment ID")
):
    """Get a comment thread (parent and all replies)."""
    comment = db.get_comment(comment_id)
    if not comment:
        raise HTTPException(
            status_code=404,
            detail=f"Comment {comment_id} not found. Please verify the comment_id is correct."
        )
    
    thread = db.get_comment_thread(comment_id)
    return [CommentResponse(**c) for c in thread]


@app.put("/tasks/{task_id}/comments/{comment_id}", response_model=CommentResponse)
async def update_comment(
    task_id: int = Path(..., gt=0, description="Task ID"),
    comment_id: int = Path(..., gt=0, description="Comment ID"),
    update: CommentUpdate = Body(...),
    agent_id: str = Body(..., embed=True, description="Agent ID of comment owner")
):
    """Update a comment."""
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    # Verify comment exists and belongs to task
    comment = db.get_comment(comment_id)
    if not comment:
        raise HTTPException(
            status_code=404,
            detail=f"Comment {comment_id} not found. Please verify the comment_id is correct."
        )
    
    if comment["task_id"] != task_id:
        raise HTTPException(
            status_code=400,
            detail=f"Comment {comment_id} does not belong to task {task_id}."
        )
    
    try:
        success = db.update_comment(comment_id, agent_id, update.content)
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to update comment"
            )
        
        updated_comment = db.get_comment(comment_id)
        return CommentResponse(**updated_comment)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update comment: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to update comment. Please try again or contact support if the issue persists."
        )


@app.delete("/tasks/{task_id}/comments/{comment_id}")
async def delete_comment(
    task_id: int = Path(..., gt=0, description="Task ID"),
    comment_id: int = Path(..., gt=0, description="Comment ID"),
    agent_id: str = Body(..., embed=True, description="Agent ID of comment owner")
):
    """Delete a comment (cascades to replies)."""
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    # Verify comment exists and belongs to task
    comment = db.get_comment(comment_id)
    if not comment:
        raise HTTPException(
            status_code=404,
            detail=f"Comment {comment_id} not found. Please verify the comment_id is correct."
        )
    
    if comment["task_id"] != task_id:
        raise HTTPException(
            status_code=400,
            detail=f"Comment {comment_id} does not belong to task {task_id}."
        )
    
    try:
        success = db.delete_comment(comment_id, agent_id)
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to delete comment"
            )
        
        logger.info(f"Comment {comment_id} deleted from task {task_id}")
        return {
            "success": True,
            "message": f"Comment {comment_id} deleted successfully",
            "comment_id": comment_id,
            "task_id": task_id
        }
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete comment: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete comment. Please try again or contact support if the issue persists."
        )


@app.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int = Path(..., gt=0, description="Task ID"),
    update: TaskUpdate = Body(...)
):
    """Update a task (partial update)."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    # Validate at least one field is being updated
    if not any([update.task_status, update.verification_status, update.notes]):
        raise HTTPException(
            status_code=400,
            detail="At least one field (task_status, verification_status, or notes) must be provided for update."
        )
    
    # Update fields if provided (validation already handled by Pydantic)
    if update.task_status:
        # Use database methods for status changes
        if update.task_status == "complete":
            db.complete_task(task_id, notes=update.notes)
        elif update.task_status == "available":
            db.unlock_task(task_id)
        else:
            # Direct update for other statuses
            conn = db._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE tasks 
                    SET task_status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (update.task_status, task_id))
                conn.commit()
            finally:
                conn.close()
    
    if update.verification_status:
        # Validation already handled by Pydantic
        if update.verification_status == "verified":
            db.verify_task(task_id)
        else:
            conn = db._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE tasks 
                    SET verification_status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (update.verification_status, task_id))
                conn.commit()
            finally:
                conn.close()
    
    if update.notes:
        conn = db._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tasks 
                SET notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (update.notes, task_id))
            conn.commit()
        finally:
            conn.close()
    
    # Create a new version after any update
    # Use agent_id from update if provided, otherwise use system
    agent_id = getattr(update, 'agent_id', 'system')
    try:
        db._create_task_version(task_id, agent_id)
    except Exception as e:
        # Log error but don't fail the update
        import logging
        logging.getLogger(__name__).warning(f"Failed to create version for task {task_id}: {e}")
    
    updated_task = db.get_task(task_id)
    return TaskResponse(**updated_task)


class RelationshipCreateWithAgent(BaseModel):
    parent_task_id: int = Field(..., description="Parent task ID", gt=0)
    child_task_id: int = Field(..., description="Child task ID", gt=0)
    relationship_type: str = Field(..., description="Relationship type: subtask, blocking, blocked_by, followup, related")
    agent_id: str = Field(..., description="Agent ID creating this relationship", min_length=1)
    
    @field_validator('relationship_type')
    @classmethod
    def validate_relationship_type(cls, v: str) -> str:
        """Validate relationship_type enum."""
        valid_types = ["subtask", "blocking", "blocked_by", "followup", "related"]
        if v not in valid_types:
            raise ValueError(f"Invalid relationship_type '{v}'. Must be one of: {', '.join(valid_types)}")
        return v
    
    @field_validator('agent_id')
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        """Validate agent_id is not empty."""
        if not v or not v.strip():
            raise ValueError("agent_id cannot be empty or contain only whitespace")
        return v.strip()
    
    @model_validator(mode='after')
    def validate_different_tasks(self):
        """Validate parent and child are different tasks."""
        if self.parent_task_id == self.child_task_id:
            raise ValueError("parent_task_id and child_task_id cannot be the same")
        return self


@app.post("/relationships")
async def create_relationship(relationship: RelationshipCreateWithAgent):
    """Create a relationship between two tasks."""
    # Validation already handled by Pydantic (relationship_type, agent_id, task IDs)
    
    # Verify both tasks exist
    parent = db.get_task(relationship.parent_task_id)
    child = db.get_task(relationship.child_task_id)
    if not parent:
        raise HTTPException(
            status_code=404,
            detail=f"Parent task {relationship.parent_task_id} not found. Please verify the parent_task_id is correct."
        )
    if not child:
        raise HTTPException(
            status_code=404,
            detail=f"Child task {relationship.child_task_id} not found. Please verify the child_task_id is correct."
        )
    
    try:
        rel_id = db.create_relationship(
            parent_task_id=relationship.parent_task_id,
            child_task_id=relationship.child_task_id,
            relationship_type=relationship.relationship_type,
            agent_id=relationship.agent_id
        )
        return {"message": "Relationship created", "relationship_id": rel_id}
    except ValueError as e:
        # Handle circular dependency and other validation errors
        raise HTTPException(status_code=400, detail=str(e))
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=409, detail=f"Relationship already exists: {str(e)}")


@app.get("/tasks/{task_id}/relationships")
async def get_task_relationships(
    task_id: int = Path(..., gt=0, description="Task ID"),
    relationship_type: Optional[str] = Query(None, description="Filter by relationship type")
):
    """Get relationships for a task."""
    # Validate task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    # Validate relationship_type if provided
    if relationship_type is not None:
        valid_types = ["subtask", "blocking", "blocked_by", "followup", "related"]
        if relationship_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid relationship_type '{relationship_type}'. Must be one of: {', '.join(valid_types)}"
            )
    
    relationships = db.get_related_tasks(task_id, relationship_type)
    return {"task_id": task_id, "relationships": relationships}


@app.get("/tasks/{task_id}/blocking")
async def get_blocking_tasks(task_id: int = Path(..., gt=0, description="Task ID")):
    """Get tasks that are blocking the given task."""
    # Validate task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    blocking = db.get_blocking_tasks(task_id)
    return {"task_id": task_id, "blocking_tasks": blocking}


@app.get("/tasks/overdue")
async def get_overdue_tasks(limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")):
    """Get tasks that are overdue (past due date and not complete)."""
    overdue = db.get_overdue_tasks(limit=limit)
    return {"tasks": [TaskResponse(**task) for task in overdue]}


@app.get("/tasks/approaching-deadline")
async def get_tasks_approaching_deadline(
    days_ahead: int = Query(3, ge=1, le=365, description="Number of days ahead to look for approaching deadlines"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")
):
    """Get tasks that are approaching their deadline."""
    approaching = db.get_tasks_approaching_deadline(days_ahead=days_ahead, limit=limit)
    return {"tasks": [TaskResponse(**task) for task in approaching]}


# ===== Recurring Tasks Models =====
class RecurringTaskCreate(BaseModel):
    """Model for creating a recurring task."""
    task_id: int = Field(..., description="ID of the base task to recur", gt=0)
    recurrence_type: str = Field(..., description="Recurrence type: daily, weekly, or monthly")
    recurrence_config: Dict[str, Any] = Field(default_factory=dict, description="Recurrence configuration (day_of_week for weekly, day_of_month for monthly)")
    next_occurrence: str = Field(..., description="When to create the next instance (ISO format timestamp)")
    
    @field_validator('recurrence_type')
    @classmethod
    def validate_recurrence_type(cls, v: str) -> str:
        """Validate recurrence_type enum."""
        valid_types = ["daily", "weekly", "monthly"]
        if v not in valid_types:
            raise ValueError(f"Invalid recurrence_type '{v}'. Must be one of: {', '.join(valid_types)}")
        return v


class RecurringTaskUpdate(BaseModel):
    """Model for updating a recurring task."""
    recurrence_type: Optional[str] = Field(None, description="New recurrence type")
    recurrence_config: Optional[Dict[str, Any]] = Field(None, description="New recurrence configuration")
    next_occurrence: Optional[str] = Field(None, description="New next occurrence date (ISO format timestamp)")
    
    @field_validator('recurrence_type')
    @classmethod
    def validate_recurrence_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate recurrence_type enum."""
        if v is None:
            return v
        valid_types = ["daily", "weekly", "monthly"]
        if v not in valid_types:
            raise ValueError(f"Invalid recurrence_type '{v}'. Must be one of: {', '.join(valid_types)}")
        return v


class RecurringTaskResponse(BaseModel):
    """Recurring task response model."""
    id: int
    task_id: int
    recurrence_type: str
    recurrence_config: Dict[str, Any]
    next_occurrence: str
    last_occurrence_created: Optional[str]
    is_active: int
    created_at: str
    updated_at: str


# ===== Recurring Tasks Endpoints =====
@app.post("/recurring-tasks", response_model=RecurringTaskResponse, status_code=201)
async def create_recurring_task(
    recurring_task: RecurringTaskCreate,
    request: Request,
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """Create a recurring task pattern."""
    # Verify task exists
    task = db.get_task(recurring_task.task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {recurring_task.task_id} not found. Please verify the task_id is correct."
        )
    
    # Parse next_occurrence
    try:
        next_occurrence = datetime.fromisoformat(recurring_task.next_occurrence.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid next_occurrence format. Must be ISO format timestamp."
        )
    
    try:
        recurring_id = db.create_recurring_task(
            task_id=recurring_task.task_id,
            recurrence_type=recurring_task.recurrence_type,
            recurrence_config=recurring_task.recurrence_config,
            next_occurrence=next_occurrence
        )
        recurring = db.get_recurring_task(recurring_id)
        return RecurringTaskResponse(**recurring)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/recurring-tasks", response_model=List[RecurringTaskResponse])
async def list_recurring_tasks(
    active_only: bool = Query(False, description="Only return active recurring tasks"),
    request: Request = None,
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """List all recurring tasks."""
    recurring_tasks = db.list_recurring_tasks(active_only=active_only)
    return [RecurringTaskResponse(**rt) for rt in recurring_tasks]


@app.get("/recurring-tasks/{recurring_id}", response_model=RecurringTaskResponse)
async def get_recurring_task(
    recurring_id: int = Path(..., gt=0, description="Recurring task ID"),
    request: Request = None,
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """Get a recurring task by ID."""
    recurring = db.get_recurring_task(recurring_id)
    if not recurring:
        raise HTTPException(
            status_code=404,
            detail=f"Recurring task {recurring_id} not found. Please verify the recurring_id is correct."
        )
    return RecurringTaskResponse(**recurring)


@app.put("/recurring-tasks/{recurring_id}", response_model=RecurringTaskResponse)
async def update_recurring_task(
    recurring_id: int = Path(..., gt=0, description="Recurring task ID"),
    update: RecurringTaskUpdate = Body(...),
    request: Request = None,
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """Update a recurring task."""
    # Parse next_occurrence if provided
    next_occurrence_obj = None
    if update.next_occurrence:
        try:
            next_occurrence_obj = datetime.fromisoformat(update.next_occurrence.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid next_occurrence format. Must be ISO format timestamp."
            )
    
    try:
        db.update_recurring_task(
            recurring_id=recurring_id,
            recurrence_type=update.recurrence_type,
            recurrence_config=update.recurrence_config,
            next_occurrence=next_occurrence_obj
        )
        recurring = db.get_recurring_task(recurring_id)
        if not recurring:
            raise HTTPException(status_code=404, detail=f"Recurring task {recurring_id} not found")
        return RecurringTaskResponse(**recurring)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/recurring-tasks/{recurring_id}")
async def deactivate_recurring_task(
    recurring_id: int = Path(..., gt=0, description="Recurring task ID"),
    request: Request = None,
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """Deactivate a recurring task (stop creating new instances)."""
    recurring = db.get_recurring_task(recurring_id)
    if not recurring:
        raise HTTPException(
            status_code=404,
            detail=f"Recurring task {recurring_id} not found. Please verify the recurring_id is correct."
        )
    
    db.deactivate_recurring_task(recurring_id)
    return {"message": f"Recurring task {recurring_id} deactivated successfully"}


@app.post("/recurring-tasks/{recurring_id}/create-instance")
async def create_recurring_instance(
    recurring_id: int = Path(..., gt=0, description="Recurring task ID"),
    request: Request = None,
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """Manually create the next instance from a recurring task."""
    try:
        instance_id = db.create_recurring_instance(recurring_id)
        instance = db.get_task(instance_id)
        return {
            "message": f"Instance created successfully",
            "instance_id": instance_id,
            "task": TaskResponse(**instance)
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/recurring-tasks/process")
async def process_recurring_tasks(
    request: Request = None,
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """
    Process all due recurring tasks and create instances.
    This endpoint should be called periodically (e.g., via cron job).
    """
    created_task_ids = db.process_recurring_tasks()
    return {
        "message": f"Processed {len(created_task_ids)} recurring task(s)",
        "created_task_ids": created_task_ids
    }


@app.get("/agents/{agent_type}/available-tasks")
async def get_available_tasks_for_agent(
    agent_type: str,
    project_id: Optional[int] = Query(None, description="Filter by project ID"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of results")
):
    """
    Get available tasks for an agent type.
    
    - 'breakdown': Returns abstract/epic tasks that need to be broken down
    - 'implementation': Returns concrete tasks ready for implementation
    """
    if agent_type not in ["breakdown", "implementation"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid agent_type. Must be: breakdown or implementation"
        )
    
    tasks = db.get_available_tasks_for_agent(agent_type, project_id=project_id, limit=limit)
    return {"agent_type": agent_type, "project_id": project_id, "tasks": [TaskResponse(**task) for task in tasks]}


@app.post("/tasks/{task_id}/add-followup")
async def add_followup_task(task_id: int, followup: TaskCreate):
    """Complete a task and add a followup task."""
    # Verify parent task exists
    parent = db.get_task(task_id)
    if not parent:
        raise HTTPException(status_code=404, detail=f"Parent task {task_id} not found")
    
    # Create followup task
    followup_id = db.create_task(
        title=followup.title,
        task_type=followup.task_type,
        task_instruction=followup.task_instruction,
        verification_instruction=followup.verification_instruction,
        agent_id=followup.agent_id,
        notes=followup.notes
    )
    
    # Create followup relationship
    db.create_relationship(
        parent_task_id=task_id,
        child_task_id=followup_id,
        relationship_type="followup",
        agent_id=followup.agent_id
    )
    
    return {
        "message": f"Followup task created and linked to task {task_id}",
        "parent_task_id": task_id,
        "followup_task_id": followup_id
    }


@app.get("/tasks/{task_id}/versions", response_model=List[Dict[str, Any]])
async def get_task_versions(
    task_id: int = Path(..., gt=0, description="Task ID")
):
    """Get all versions for a task."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    versions = db.get_task_versions(task_id)
    return versions


@app.get("/tasks/{task_id}/versions/{version_number}", response_model=Dict[str, Any])
async def get_task_version(
    task_id: int = Path(..., gt=0, description="Task ID"),
    version_number: int = Path(..., gt=0, description="Version number")
):
    """Get a specific version of a task."""
    version = db.get_task_version(task_id, version_number)
    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version_number} for task {task_id} not found. Please verify the version_number is correct."
        )
    return version


@app.get("/tasks/{task_id}/versions/latest", response_model=Dict[str, Any])
async def get_latest_task_version(
    task_id: int = Path(..., gt=0, description="Task ID")
):
    """Get the latest version of a task."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    version = db.get_latest_task_version(task_id)
    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"No versions found for task {task_id}."
        )
    return version


@app.get("/tasks/{task_id}/versions/diff")
async def diff_task_versions(
    task_id: int = Path(..., gt=0, description="Task ID"),
    version_number_1: int = Query(..., gt=0, description="First version number"),
    version_number_2: int = Query(..., gt=0, description="Second version number")
):
    """Diff two task versions and return changed fields."""
    try:
        diff = db.diff_task_versions(task_id, version_number_1, version_number_2)
        return {
            "task_id": task_id,
            "version_1": version_number_1,
            "version_2": version_number_2,
            "diff": diff,
            "changed_fields": list(diff.keys())
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/change-history")
async def get_change_history(
    task_id: Optional[int] = Query(None, description="Filter by task ID"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")
):
    """Get change history with optional filters."""
    history = db.get_change_history(task_id=task_id, agent_id=agent_id, limit=limit)
    return {"history": history}


@app.get("/agents/{agent_id}/stats")
async def get_agent_stats(
    agent_id: str,
    task_type: Optional[str] = Query(None, description="Filter by task type")
):
    """Get statistics for an agent's performance."""
    stats = db.get_agent_stats(agent_id, task_type)
    return stats


# Analytics and Reporting endpoints
@app.get("/analytics/metrics")
async def get_analytics_metrics(
    project_id: Optional[int] = Query(None, description="Filter by project ID"),
    task_type: Optional[str] = Query(None, description="Filter by task type")
):
    """
    Get analytics metrics including completion rates and average time to complete.
    
    Returns:
    - completion_rates: Total tasks, completed tasks, completion percentage, status breakdown, tasks by type
    - average_time_to_complete: Average, min, max hours to complete tasks
    """
    try:
        completion_rates = db.get_completion_rates(project_id=project_id, task_type=task_type)
        average_time = db.get_average_time_to_complete(project_id=project_id, task_type=task_type)
        
        return {
            "completion_rates": completion_rates,
            "average_time_to_complete": average_time,
            "filters": {
                "project_id": project_id,
                "task_type": task_type
            }
        }
    except Exception as e:
        logger.error(f"Error getting analytics metrics: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get analytics metrics: {str(e)}")


@app.get("/analytics/bottlenecks")
async def get_analytics_bottlenecks(
    long_running_hours: float = Query(24.0, description="Hours threshold for long-running tasks"),
    limit: int = Query(50, description="Maximum number of results")
):
    """
    Identify bottlenecks in task completion.
    
    Returns:
    - long_running_tasks: Tasks in_progress for longer than threshold
    - blocking_tasks: Tasks that block other tasks
    - blocked_tasks: Tasks blocked by incomplete tasks
    """
    try:
        bottlenecks = db.get_bottlenecks(long_running_hours=long_running_hours, limit=limit)
        return bottlenecks
    except Exception as e:
        logger.error(f"Error getting bottlenecks: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get bottlenecks: {str(e)}")


@app.get("/analytics/agents")
async def get_analytics_agents(
    task_type: Optional[str] = Query(None, description="Filter by task type"),
    limit: int = Query(100, description="Maximum number of agents to return")
):
    """
    Get agent performance comparisons.
    
    Returns:
    - agents: List of agents with performance metrics (tasks_completed, tasks_verified, 
              avg_time_delta, avg_actual_hours, avg_estimated_hours, success_rate)
    - total_agents: Number of agents returned
    """
    try:
        comparisons = db.get_agent_comparisons(task_type=task_type, limit=limit)
        return comparisons
    except Exception as e:
        logger.error(f"Error getting agent comparisons: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get agent comparisons: {str(e)}")


# GitHub Integration Models
class GitHubLinkRequest(BaseModel):
    """Request model for linking GitHub issue/PR."""
    github_url: str = Field(..., description="GitHub issue or PR URL", min_length=1)
    
    @field_validator('github_url')
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        """Validate GitHub URL."""
        if not v or not v.strip():
            raise ValueError("GitHub URL cannot be empty")
        url = v.strip()
        if "github.com" not in url.lower():
            raise ValueError("Invalid GitHub URL: must be a GitHub.com URL")
        return url


# GitHub Integration Endpoints
@app.post("/tasks/{task_id}/github/link-issue")
async def link_github_issue(
    task_id: int = Path(..., gt=0, description="Task ID"),
    request: GitHubLinkRequest = Body(...)
):
    """Link a GitHub issue to a task."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    try:
        db.link_github_issue(task_id, request.github_url)
        links = db.get_github_links(task_id)
        return {
            "message": f"GitHub issue linked to task {task_id}",
            "task_id": task_id,
            "github_issue_url": links.get("github_issue_url")
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to link GitHub issue: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to link GitHub issue: {str(e)}")


@app.post("/tasks/{task_id}/github/link-pr")
async def link_github_pr(
    task_id: int = Path(..., gt=0, description="Task ID"),
    request: GitHubLinkRequest = Body(...)
):
    """Link a GitHub PR to a task."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    try:
        db.link_github_pr(task_id, request.github_url)
        links = db.get_github_links(task_id)
        return {
            "message": f"GitHub PR linked to task {task_id}",
            "task_id": task_id,
            "github_pr_url": links.get("github_pr_url")
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to link GitHub PR: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to link GitHub PR: {str(e)}")


@app.delete("/tasks/{task_id}/github/unlink-issue")
async def unlink_github_issue(
    task_id: int = Path(..., gt=0, description="Task ID")
):
    """Unlink a GitHub issue from a task."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    try:
        db.unlink_github_issue(task_id)
        return {
            "message": f"GitHub issue unlinked from task {task_id}",
            "task_id": task_id
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to unlink GitHub issue: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to unlink GitHub issue: {str(e)}")


@app.delete("/tasks/{task_id}/github/unlink-pr")
async def unlink_github_pr(
    task_id: int = Path(..., gt=0, description="Task ID")
):
    """Unlink a GitHub PR from a task."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    try:
        db.unlink_github_pr(task_id)
        return {
            "message": f"GitHub PR unlinked from task {task_id}",
            "task_id": task_id
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to unlink GitHub PR: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to unlink GitHub PR: {str(e)}")


@app.get("/tasks/{task_id}/github/links")
async def get_github_links_endpoint(
    task_id: int = Path(..., gt=0, description="Task ID")
):
    """Get GitHub issue and PR links for a task."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    try:
        links = db.get_github_links(task_id)
        return {
            "task_id": task_id,
            "github_issue_url": links.get("github_issue_url"),
            "github_pr_url": links.get("github_pr_url")
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get GitHub links: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get GitHub links: {str(e)}")


@app.post("/tasks/{task_id}/github/sync")
async def sync_github_status(
    task_id: int = Path(..., gt=0, description="Task ID"),
    github_token: Optional[str] = Body(None, embed=True, description="GitHub token for API access (optional, can use GITHUB_TOKEN env var)")
):
    """
    Sync task status with GitHub issue status.
    
    This endpoint:
    - Fetches the GitHub issue status (open/closed)
    - Updates the task status accordingly (available/in_progress -> complete if issue is closed)
    - Supports bidirectional syncing (can update GitHub issue based on task status)
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    links = db.get_github_links(task_id)
    github_issue_url = links.get("github_issue_url")
    
    if not github_issue_url:
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} does not have a linked GitHub issue"
        )
    
    # Get GitHub token from parameter or environment
    token = github_token or os.getenv("GITHUB_TOKEN")
    if not token:
        raise HTTPException(
            status_code=401,
            detail="GitHub token required. Provide github_token in request body or set GITHUB_TOKEN environment variable."
        )
    
    try:
        # Parse GitHub URL to extract owner/repo/issue_number
        # Format: https://github.com/owner/repo/issues/123
        parts = github_issue_url.replace("https://github.com/", "").replace("http://github.com/", "").split("/")
        if len(parts) < 3:
            raise ValueError("Invalid GitHub issue URL format")
        
        owner = parts[0]
        repo = parts[1]
        issue_number = parts[-1].split("#")[0]  # Handle fragments
        
        # Fetch issue status from GitHub API
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json"
            }
            response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}",
                headers=headers,
                timeout=10.0
            )
            
            if response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"GitHub issue {github_issue_url} not found"
                )
            elif response.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="GitHub token is invalid or expired"
                )
            elif response.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail=f"GitHub API error: {response.status_code}"
                )
            
            issue_data = response.json()
            issue_state = issue_data.get("state")  # "open" or "closed"
            
            # Sync task status based on GitHub issue state
            current_task_status = task.get("task_status")
            updates = []
            
            if issue_state == "closed" and current_task_status in ["available", "in_progress"]:
                # Issue is closed, mark task as complete
                db.complete_task(task_id, agent_id="github-sync", notes="Task completed via GitHub issue sync")
                updates.append("Task marked as complete (GitHub issue is closed)")
            elif issue_state == "open" and current_task_status == "complete":
                # Issue is open, but task is complete - could reopen or leave as is
                # For now, we'll log this but not auto-change
                updates.append("Note: Task is complete but GitHub issue is open")
            
            return {
                "message": "GitHub sync completed",
                "task_id": task_id,
                "github_issue_url": github_issue_url,
                "github_issue_state": issue_state,
                "task_status_before": current_task_status,
                "task_status_after": db.get_task(task_id).get("task_status"),
                "updates": updates
            }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="GitHub API request timed out")
    except httpx.RequestError as e:
        logger.error(f"GitHub API request error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to connect to GitHub API: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to sync GitHub status: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to sync GitHub status: {str(e)}")


@app.get("/analytics/visualization")
async def get_analytics_visualization(
    project_id: Optional[int] = Query(None, description="Filter by project ID"),
    start_date: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)")
):
    """
    Get data formatted for visualization/charts.
    
    Returns:
    - status_distribution: Count of tasks by status
    - type_distribution: Count of tasks by type
    - priority_distribution: Count of tasks by priority
    - completion_timeline: Daily completion counts over time
    """
    try:
        viz_data = db.get_visualization_data(
            project_id=project_id,
            start_date=start_date,
            end_date=end_date
        )
        return viz_data
    except Exception as e:
        logger.error(f"Error getting visualization data: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get visualization data: {str(e)}")


@app.get("/mcp/functions")
async def get_mcp_functions():
    """Get MCP function definitions."""
    return {"functions": MCP_FUNCTIONS}


def build_tools_list():
    """Helper to build tools list for MCP."""
    tools_list = []
    for func in MCP_FUNCTIONS:
        tool_def = {
            "name": func["name"],
            "description": func["description"],
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
        if "parameters" in func:
            for param_name, param_info in func["parameters"].items():
                param_type = param_info.get("type", "string")
                prop_schema = {"type": param_type}
                
                # Include description if present
                if "description" in param_info:
                    prop_schema["description"] = param_info["description"]
                
                # Handle enum with descriptions if available
                if "enum" in param_info:
                    prop_schema["enum"] = param_info["enum"]
                    # Add enum descriptions if available
                    if "enumDescriptions" in param_info:
                        prop_schema["enumDescriptions"] = param_info["enumDescriptions"]
                
                # Include example values if available
                if "example" in param_info:
                    prop_schema["example"] = param_info["example"]
                elif "examples" in param_info:
                    prop_schema["examples"] = param_info["examples"]
                
                # Include default value if present
                if "default" in param_info:
                    prop_schema["default"] = param_info["default"]
                
                # Include constraints/validation rules
                constraints = {}
                if "minimum" in param_info:
                    constraints["minimum"] = param_info["minimum"]
                if "maximum" in param_info:
                    constraints["maximum"] = param_info["maximum"]
                if "minLength" in param_info:
                    constraints["minLength"] = param_info["minLength"]
                if "maxLength" in param_info:
                    constraints["maxLength"] = param_info["maxLength"]
                if "pattern" in param_info:
                    constraints["pattern"] = param_info["pattern"]
                if constraints:
                    prop_schema.update(constraints)
                
                # Mark required vs optional clearly
                is_optional = param_info.get("optional", False)
                if not is_optional:
                    tool_def["inputSchema"]["required"].append(param_name)
                # Include optional flag in description if not already clear
                if is_optional and "description" in prop_schema:
                    if not prop_schema["description"].startswith("Optional"):
                        prop_schema["description"] = f"[Optional] {prop_schema['description']}"
                
                tool_def["inputSchema"]["properties"][param_name] = prop_schema
        tools_list.append(tool_def)
    return tools_list


@app.post("/mcp/sse")
async def mcp_sse_post(request: Request):
    """MCP POST endpoint for /mcp/sse (streamableHttp transport)."""
    try:
        body = await request.json()
        # Handle initialize request
        if body.get("method") == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {
                            "listChanged": True
                        }
                    },
                    "serverInfo": {
                        "name": "todo-mcp-service",
                        "version": "1.0.0"
                    }
                }
            }
        # Handle tools/list request
        elif body.get("method") == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {
                    "tools": build_tools_list()
                }
            }
        # Handle tools/call request (for executing tools)
        elif body.get("method") == "tools/call":
            tool_name = body.get("params", {}).get("name")
            tool_args = body.get("params", {}).get("arguments", {})
            
            # Route to appropriate MCP function
            if tool_name == "list_available_tasks":
                result = MCPTodoAPI.list_available_tasks(
                    tool_args.get("agent_type"),
                    project_id=tool_args.get("project_id"),
                    limit=tool_args.get("limit", 10)
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "reserve_task":
                result = MCPTodoAPI.reserve_task(
                    tool_args.get("task_id"),
                    tool_args.get("agent_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "complete_task":
                result = MCPTodoAPI.complete_task(
                    tool_args.get("task_id"),
                    tool_args.get("agent_id"),
                    notes=tool_args.get("notes"),
                    actual_hours=tool_args.get("actual_hours"),
                    followup_title=tool_args.get("followup_title"),
                    followup_task_type=tool_args.get("followup_task_type"),
                    followup_instruction=tool_args.get("followup_instruction"),
                    followup_verification=tool_args.get("followup_verification")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "create_task":
                result = MCPTodoAPI.create_task(
                    tool_args.get("title"),
                    tool_args.get("task_type"),
                    tool_args.get("task_instruction"),
                    tool_args.get("verification_instruction"),
                    tool_args.get("agent_id"),
                    project_id=tool_args.get("project_id"),
                    parent_task_id=tool_args.get("parent_task_id"),
                    relationship_type=tool_args.get("relationship_type"),
                    notes=tool_args.get("notes"),
                    priority=tool_args.get("priority"),
                    estimated_hours=tool_args.get("estimated_hours"),
                    due_date=tool_args.get("due_date")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_agent_performance":
                result = MCPTodoAPI.get_agent_performance(
                    tool_args.get("agent_id"),
                    task_type=tool_args.get("task_type")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "unlock_task":
                result = MCPTodoAPI.unlock_task(
                    tool_args.get("task_id"),
                    tool_args.get("agent_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "query_tasks":
                result = MCPTodoAPI.query_tasks(
                    project_id=tool_args.get("project_id"),
                    task_type=tool_args.get("task_type"),
                    task_status=tool_args.get("task_status"),
                    agent_id=tool_args.get("agent_id"),
                    priority=tool_args.get("priority"),
                    tag_id=tool_args.get("tag_id"),
                    tag_ids=tool_args.get("tag_ids"),
                    order_by=tool_args.get("order_by"),
                    limit=tool_args.get("limit", 100)
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "query_stale_tasks":
                result = MCPTodoAPI.query_stale_tasks(
                    hours=tool_args.get("hours")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "add_task_update":
                result = MCPTodoAPI.add_task_update(
                    tool_args.get("task_id"),
                    tool_args.get("agent_id"),
                    tool_args.get("content"),
                    tool_args.get("update_type"),
                    metadata=tool_args.get("metadata")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_task_context":
                result = MCPTodoAPI.get_task_context(
                    tool_args.get("task_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "search_tasks":
                result = MCPTodoAPI.search_tasks(
                    tool_args.get("query"),
                    limit=tool_args.get("limit", 100)
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_tasks_approaching_deadline":
                result = MCPTodoAPI.get_tasks_approaching_deadline(
                    days_ahead=tool_args.get("days_ahead", 3),
                    limit=tool_args.get("limit", 100)
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "create_tag":
                result = MCPTodoAPI.create_tag(
                    tool_args.get("name")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "list_tags":
                result = MCPTodoAPI.list_tags()
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "assign_tag_to_task":
                result = MCPTodoAPI.assign_tag_to_task(
                    tool_args.get("task_id"),
                    tool_args.get("tag_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "remove_tag_from_task":
                result = MCPTodoAPI.remove_tag_from_task(
                    tool_args.get("task_id"),
                    tool_args.get("tag_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_task_tags":
                result = MCPTodoAPI.get_task_tags(
                    tool_args.get("task_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "create_template":
                result = MCPTodoAPI.create_template(
                    tool_args.get("name"),
                    tool_args.get("task_type"),
                    tool_args.get("task_instruction"),
                    tool_args.get("verification_instruction"),
                    description=tool_args.get("description"),
                    priority=tool_args.get("priority"),
                    estimated_hours=tool_args.get("estimated_hours"),
                    notes=tool_args.get("notes")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "list_templates":
                result = MCPTodoAPI.list_templates(
                    task_type=tool_args.get("task_type")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_template":
                result = MCPTodoAPI.get_template(
                    tool_args.get("template_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "create_task_from_template":
                result = MCPTodoAPI.create_task_from_template(
                    tool_args.get("template_id"),
                    tool_args.get("agent_id"),
                    title=tool_args.get("title"),
                    project_id=tool_args.get("project_id"),
                    notes=tool_args.get("notes"),
                    priority=tool_args.get("priority"),
                    estimated_hours=tool_args.get("estimated_hours"),
                    due_date=tool_args.get("due_date")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_activity_feed":
                result = MCPTodoAPI.get_activity_feed(
                    task_id=tool_args.get("task_id"),
                    agent_id=tool_args.get("agent_id"),
                    start_date=tool_args.get("start_date"),
                    end_date=tool_args.get("end_date"),
                    limit=tool_args.get("limit", 1000)
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "create_comment":
                result = MCPTodoAPI.create_comment(
                    tool_args.get("task_id"),
                    tool_args.get("agent_id"),
                    tool_args.get("content"),
                    parent_comment_id=tool_args.get("parent_comment_id"),
                    mentions=tool_args.get("mentions")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_task_comments":
                result = MCPTodoAPI.get_task_comments(
                    tool_args.get("task_id"),
                    limit=tool_args.get("limit", 100)
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_comment_thread":
                result = MCPTodoAPI.get_comment_thread(
                    tool_args.get("comment_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "update_comment":
                result = MCPTodoAPI.update_comment(
                    tool_args.get("comment_id"),
                    tool_args.get("agent_id"),
                    tool_args.get("content")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "delete_comment":
                result = MCPTodoAPI.delete_comment(
                    tool_args.get("comment_id"),
                    tool_args.get("agent_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "create_recurring_task":
                result = MCPTodoAPI.create_recurring_task(
                    tool_args.get("task_id"),
                    tool_args.get("recurrence_type"),
                    tool_args.get("next_occurrence"),
                    recurrence_config=tool_args.get("recurrence_config")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "list_recurring_tasks":
                result = MCPTodoAPI.list_recurring_tasks(
                    active_only=tool_args.get("active_only", False)
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_recurring_task":
                result = MCPTodoAPI.get_recurring_task(
                    tool_args.get("recurring_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "update_recurring_task":
                result = MCPTodoAPI.update_recurring_task(
                    tool_args.get("recurring_id"),
                    recurrence_type=tool_args.get("recurrence_type"),
                    recurrence_config=tool_args.get("recurrence_config"),
                    next_occurrence=tool_args.get("next_occurrence")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "deactivate_recurring_task":
                result = MCPTodoAPI.deactivate_recurring_task(
                    tool_args.get("recurring_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "create_recurring_instance":
                result = MCPTodoAPI.create_recurring_instance(
                    tool_args.get("recurring_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_task_versions":
                result = MCPTodoAPI.get_task_versions(
                    tool_args.get("task_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_task_version":
                result = MCPTodoAPI.get_task_version(
                    tool_args.get("task_id"),
                    tool_args.get("version_number")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_latest_task_version":
                result = MCPTodoAPI.get_latest_task_version(
                    tool_args.get("task_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "diff_task_versions":
                result = MCPTodoAPI.diff_task_versions(
                    tool_args.get("task_id"),
                    tool_args.get("version_number_1"),
                    tool_args.get("version_number_2")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "link_github_issue":
                result = MCPTodoAPI.link_github_issue(
                    tool_args.get("task_id"),
                    tool_args.get("github_url")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "link_github_pr":
                result = MCPTodoAPI.link_github_pr(
                    tool_args.get("task_id"),
                    tool_args.get("github_url")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            elif tool_name == "get_github_links":
                result = MCPTodoAPI.get_github_links(
                    tool_args.get("task_id")
                )
                return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "error": {
                        "code": -32601,
                        "message": f"Tool not found: {tool_name}"
                    }
                }
        else:
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {
                    "code": -32601,
                    "message": "Method not found"
                }
            }
    except ValueError as e:
        logger.warning(f"MCP POST validation error: {str(e)}")
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {
                "code": -32602,
                "message": f"Invalid parameters: {str(e)}"
            }
        }
    except KeyError as e:
        logger.warning(f"MCP POST missing parameter: {str(e)}")
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {
                "code": -32602,
                "message": f"Missing required parameter: {str(e)}"
            }
        }
    except Exception as e:
        logger.error(f"MCP POST error in {request.url.path}: {str(e)}", exc_info=True)
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {
                "code": -32603,
                "message": f"Internal error: An unexpected error occurred processing your request"
            }
        }


@app.get("/mcp/sse")
async def mcp_sse():
    """MCP Server-Sent Events endpoint for JSON-RPC over SSE."""
    async def event_generator():
        # Build tools list using helper
        tools_list = build_tools_list()
        
        # Send server info notification (proper JSON-RPC notification - no id)
        server_info = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": True
                    }
                },
                "serverInfo": {
                    "name": "todo-mcp-service",
                    "version": "1.0.0"
                }
            }
        }
        yield f"event: message\ndata: {json.dumps(server_info)}\n\n"
        
        # Send tools list notification
        tools_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed",
            "params": {
                "tools": tools_list
            }
        }
        yield f"event: message\ndata: {json.dumps(tools_notification)}\n\n"
        
        # Keep connection alive
        while True:
            await asyncio.sleep(30)
            yield f": keepalive\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/mcp")
async def mcp_post(request: Request):
    """MCP HTTP POST endpoint for /mcp (legacy/fallback)."""
    # Redirect to /mcp/sse handler
    return await mcp_sse_post(request)


# MCP-compatible endpoints
@app.post("/mcp/list_available_tasks")
async def mcp_list_available_tasks(
    agent_type: str = Body(..., embed=True),
    project_id: Optional[int] = Body(None, embed=True),
    limit: int = Body(10, embed=True)
):
    """MCP: List available tasks for an agent type."""
    tasks = MCPTodoAPI.list_available_tasks(agent_type, project_id=project_id, limit=limit)
    return {"tasks": tasks}


@app.post("/mcp/reserve_task")
async def mcp_reserve_task(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True)
):
    """MCP: Reserve (lock) a task for an agent."""
    result = MCPTodoAPI.reserve_task(task_id, agent_id)
    return result


@app.post("/mcp/complete_task")
async def mcp_complete_task(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    notes: Optional[str] = Body(None, embed=True),
    actual_hours: Optional[float] = Body(None, embed=True),
    followup_title: Optional[str] = Body(None, embed=True),
    followup_task_type: Optional[str] = Body(None, embed=True),
    followup_instruction: Optional[str] = Body(None, embed=True),
    followup_verification: Optional[str] = Body(None, embed=True)
):
    """MCP: Complete a task and optionally create followup."""
    result = MCPTodoAPI.complete_task(
        task_id, agent_id, notes, actual_hours,
        followup_title, followup_task_type, followup_instruction, followup_verification
    )
    return result


@app.post("/mcp/create_task")
async def mcp_create_task(
    title: str = Body(..., embed=True),
    task_type: str = Body(..., embed=True),
    task_instruction: str = Body(..., embed=True),
    verification_instruction: str = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    project_id: Optional[int] = Body(None, embed=True),
    parent_task_id: Optional[int] = Body(None, embed=True),
    relationship_type: Optional[str] = Body(None, embed=True),
    notes: Optional[str] = Body(None, embed=True),
    priority: Optional[str] = Body(None, embed=True),
    estimated_hours: Optional[float] = Body(None, embed=True),
    due_date: Optional[str] = Body(None, embed=True)
):
    """MCP: Create a new task."""
    result = MCPTodoAPI.create_task(
        title, task_type, task_instruction, verification_instruction, agent_id,
        project_id=project_id, parent_task_id=parent_task_id, relationship_type=relationship_type, notes=notes, priority=priority, estimated_hours=estimated_hours, due_date=due_date
    )
    return result


@app.post("/mcp/get_agent_performance")
async def mcp_get_agent_performance(
    agent_id: str = Body(..., embed=True),
    task_type: Optional[str] = Body(None, embed=True)
):
    """MCP: Get agent performance statistics."""
    stats = MCPTodoAPI.get_agent_performance(agent_id, task_type)
    return stats


@app.post("/mcp/unlock_task")
async def mcp_unlock_task(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True)
):
    """MCP: Unlock (release) a reserved task."""
    result = MCPTodoAPI.unlock_task(task_id, agent_id)
    return result


@app.post("/mcp/query_tasks")
async def mcp_query_tasks(
    project_id: Optional[int] = Body(None, embed=True),
    task_type: Optional[str] = Body(None, embed=True),
    task_status: Optional[str] = Body(None, embed=True),
    agent_id: Optional[str] = Body(None, embed=True),
    priority: Optional[str] = Body(None, embed=True),
    tag_id: Optional[int] = Body(None, embed=True),
    tag_ids: Optional[List[int]] = Body(None, embed=True),
    order_by: Optional[str] = Body(None, embed=True),
    limit: int = Body(100, embed=True)
):
    """MCP: Query tasks by various criteria."""
    tasks = MCPTodoAPI.query_tasks(
        project_id=project_id,
        task_type=task_type,
        task_status=task_status,
        agent_id=agent_id,
        priority=priority,
        tag_id=tag_id,
        tag_ids=tag_ids,
        order_by=order_by,
        limit=limit
    )
    return {"tasks": tasks}


@app.post("/mcp/add_task_update")
async def mcp_add_task_update(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
    update_type: str = Body(..., embed=True),
    metadata: Optional[Dict[str, Any]] = Body(None, embed=True)
):
    """MCP: Add a task update (progress, note, blocker, question, finding)."""
    result = MCPTodoAPI.add_task_update(task_id, agent_id, content, update_type, metadata)
    return result


@app.post("/mcp/get_task_context")
async def mcp_get_task_context(
    task_id: int = Body(..., embed=True)
):
    """MCP: Get full context for a task (project, ancestry, updates)."""
    result = MCPTodoAPI.get_task_context(task_id)
    return result


@app.post("/mcp/search_tasks")
async def mcp_search_tasks(
    query: str = Body(..., embed=True),
    limit: int = Body(100, embed=True)
):
    """MCP: Search tasks using full-text search."""
    tasks = MCPTodoAPI.search_tasks(query, limit)
    return {"tasks": tasks}


@app.post("/mcp/link_github_issue")
async def mcp_link_github_issue(
    task_id: int = Body(..., embed=True),
    github_url: str = Body(..., embed=True)
):
    """MCP: Link a GitHub issue to a task."""
    result = MCPTodoAPI.link_github_issue(task_id, github_url)
    return result


@app.post("/mcp/link_github_pr")
async def mcp_link_github_pr(
    task_id: int = Body(..., embed=True),
    github_url: str = Body(..., embed=True)
):
    """MCP: Link a GitHub PR to a task."""
    result = MCPTodoAPI.link_github_pr(task_id, github_url)
    return result


@app.post("/mcp/get_github_links")
async def mcp_get_github_links(
    task_id: int = Body(..., embed=True)
):
    """MCP: Get GitHub issue and PR links for a task."""
    result = MCPTodoAPI.get_github_links(task_id)
    return result


@app.post("/mcp/create_comment")
async def mcp_create_comment(
    task_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
    parent_comment_id: Optional[int] = Body(None, embed=True),
    mentions: Optional[List[str]] = Body(None, embed=True)
):
    """MCP: Create a comment on a task."""
    result = MCPTodoAPI.create_comment(task_id, agent_id, content, parent_comment_id, mentions)
    return result


@app.post("/mcp/get_task_comments")
async def mcp_get_task_comments(
    task_id: int = Body(..., embed=True),
    limit: int = Body(100, embed=True)
):
    """MCP: Get all comments for a task."""
    result = MCPTodoAPI.get_task_comments(task_id, limit)
    return result


@app.post("/mcp/get_comment_thread")
async def mcp_get_comment_thread(
    comment_id: int = Body(..., embed=True)
):
    """MCP: Get a comment thread (parent and all replies)."""
    result = MCPTodoAPI.get_comment_thread(comment_id)
    return result


@app.post("/mcp/update_comment")
async def mcp_update_comment(
    comment_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    content: str = Body(..., embed=True)
):
    """MCP: Update a comment."""
    result = MCPTodoAPI.update_comment(comment_id, agent_id, content)
    return result


@app.post("/mcp/delete_comment")
async def mcp_delete_comment(
    comment_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True)
):
    """MCP: Delete a comment."""
    result = MCPTodoAPI.delete_comment(comment_id, agent_id)
    return result


@app.post("/mcp/get_tasks_approaching_deadline")
async def mcp_get_tasks_approaching_deadline(
    days_ahead: int = Body(3, embed=True),
    limit: int = Body(100, embed=True)
):
    """MCP: Get tasks that are approaching their deadline."""
    result = MCPTodoAPI.get_tasks_approaching_deadline(days_ahead=days_ahead, limit=limit)
    return result


# MCP Tag endpoints
@app.post("/mcp/create_tag")
async def mcp_create_tag(name: str = Body(..., embed=True)):
    """MCP: Create a tag (or return existing tag ID if name already exists)."""
    result = MCPTodoAPI.create_tag(name)
    return result


@app.post("/mcp/list_tags")
async def mcp_list_tags():
    """MCP: List all tags."""
    result = MCPTodoAPI.list_tags()
    return result


@app.post("/mcp/assign_tag_to_task")
async def mcp_assign_tag_to_task(
    task_id: int = Body(..., embed=True),
    tag_id: int = Body(..., embed=True)
):
    """MCP: Assign a tag to a task."""
    result = MCPTodoAPI.assign_tag_to_task(task_id, tag_id)
    return result


@app.post("/mcp/remove_tag_from_task")
async def mcp_remove_tag_from_task(
    task_id: int = Body(..., embed=True),
    tag_id: int = Body(..., embed=True)
):
    """MCP: Remove a tag from a task."""
    result = MCPTodoAPI.remove_tag_from_task(task_id, tag_id)
    return result


@app.post("/mcp/get_task_tags")
async def mcp_get_task_tags(task_id: int = Body(..., embed=True)):
    """MCP: Get all tags assigned to a task."""
    result = MCPTodoAPI.get_task_tags(task_id)
    return result


# MCP Template endpoints
@app.post("/mcp/create_template")
async def mcp_create_template(
    name: str = Body(..., embed=True),
    task_type: str = Body(..., embed=True),
    task_instruction: str = Body(..., embed=True),
    verification_instruction: str = Body(..., embed=True),
    description: Optional[str] = Body(None, embed=True),
    priority: Optional[str] = Body(None, embed=True),
    estimated_hours: Optional[float] = Body(None, embed=True),
    notes: Optional[str] = Body(None, embed=True)
):
    """MCP: Create a task template."""
    result = MCPTodoAPI.create_template(
        name, task_type, task_instruction, verification_instruction,
        description=description, priority=priority, estimated_hours=estimated_hours, notes=notes
    )
    return result


@app.post("/mcp/list_templates")
async def mcp_list_templates(task_type: Optional[str] = Body(None, embed=True)):
    """MCP: List all templates, optionally filtered by task type."""
    result = MCPTodoAPI.list_templates(task_type=task_type)
    return result


@app.post("/mcp/get_template")
async def mcp_get_template(template_id: int = Body(..., embed=True)):
    """MCP: Get a template by ID."""
    result = MCPTodoAPI.get_template(template_id)
    return result


@app.post("/mcp/create_task_from_template")
async def mcp_create_task_from_template(
    template_id: int = Body(..., embed=True),
    agent_id: str = Body(..., embed=True),
    title: Optional[str] = Body(None, embed=True),
    project_id: Optional[int] = Body(None, embed=True),
    notes: Optional[str] = Body(None, embed=True),
    priority: Optional[str] = Body(None, embed=True),
    estimated_hours: Optional[float] = Body(None, embed=True),
    due_date: Optional[str] = Body(None, embed=True)
):
    """MCP: Create a task from a template."""
    result = MCPTodoAPI.create_task_from_template(
        template_id, agent_id,
        title=title, project_id=project_id, notes=notes, priority=priority,
        estimated_hours=estimated_hours, due_date=due_date
    )
    return result


# Tag endpoints
class TagCreate(BaseModel):
    name: str = Field(..., description="Tag name", min_length=1)
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate tag name is not empty or only whitespace."""
        if not v or not v.strip():
            raise ValueError("Tag name cannot be empty or contain only whitespace")
        return v.strip()


class TagResponse(BaseModel):
    """Tag response model."""
    id: int
    name: str
    created_at: str


@app.post("/tags", response_model=TagResponse, status_code=201)
async def create_tag(tag: TagCreate):
    """Create a tag (or return existing if name already exists)."""
    if not tag.name or not tag.name.strip():
        raise HTTPException(status_code=400, detail="Tag name is required and cannot be empty")
    
    tag_id = db.create_tag(name=tag.name.strip())
    created_tag = db.get_tag(tag_id)
    if not created_tag:
        raise HTTPException(status_code=500, detail="Failed to retrieve created tag")
    return TagResponse(**created_tag)


@app.get("/tags", response_model=List[TagResponse])
async def list_tags():
    """List all tags."""
    tags = db.list_tags()
    return [TagResponse(**tag) for tag in tags]


@app.get("/tags/{tag_id}", response_model=TagResponse)
async def get_tag(tag_id: int = Path(..., gt=0, description="Tag ID")):
    """Get a tag by ID."""
    tag = db.get_tag(tag_id)
    if not tag:
        raise HTTPException(
            status_code=404,
            detail=f"Tag {tag_id} not found. Please verify the tag_id is correct."
        )
    return TagResponse(**tag)


@app.get("/tags/name/{tag_name}", response_model=TagResponse)
async def get_tag_by_name(tag_name: str = Path(..., min_length=1, description="Tag name")):
    """Get a tag by name."""
    # Validate tag_name is not empty or whitespace
    if not tag_name or not tag_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Tag name cannot be empty or contain only whitespace. Please provide a valid tag name."
        )
    
    tag = db.get_tag_by_name(tag_name.strip())
    if not tag:
        raise HTTPException(
            status_code=404,
            detail=f"Tag '{tag_name}' not found. Please verify the tag name is correct and try again."
        )
    return TagResponse(**tag)


@app.post("/tasks/{task_id}/tags/{tag_id}")
async def assign_tag_to_task(task_id: int = Path(..., gt=0), tag_id: int = Path(..., gt=0)):
    """Assign a tag to a task."""
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    # Verify tag exists
    tag = db.get_tag(tag_id)
    if not tag:
        raise HTTPException(
            status_code=404,
            detail=f"Tag {tag_id} not found. Please verify the tag_id is correct."
        )
    
    db.assign_tag_to_task(task_id, tag_id)
    return {"message": f"Tag {tag_id} assigned to task {task_id}", "task_id": task_id, "tag_id": tag_id}


@app.delete("/tasks/{task_id}/tags/{tag_id}")
async def remove_tag_from_task(task_id: int = Path(..., gt=0), tag_id: int = Path(..., gt=0)):
    """Remove a tag from a task."""
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    # Verify tag exists
    tag = db.get_tag(tag_id)
    if not tag:
        raise HTTPException(
            status_code=404,
            detail=f"Tag {tag_id} not found. Please verify the tag_id is correct."
        )
    
    db.remove_tag_from_task(task_id, tag_id)
    return {"message": f"Tag {tag_id} removed from task {task_id}", "task_id": task_id, "tag_id": tag_id}


@app.get("/tasks/{task_id}/tags", response_model=List[TagResponse])
async def get_task_tags(task_id: int = Path(..., gt=0)):
    """Get all tags assigned to a task."""
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    tags = db.get_task_tags(task_id)
    return [TagResponse(**tag) for tag in tags]


@app.get("/tasks/search", response_model=List[TaskResponse])
async def search_tasks(
    q: str = Query(..., description="Search query"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")
):
    """Search tasks using full-text search across titles, instructions, and notes."""
    if not q or not q.strip():
        raise HTTPException(
            status_code=400,
            detail="Search query cannot be empty or contain only whitespace. Please provide a valid search term."
        )
    
    tasks = db.search_tasks(q, limit=limit)
    return [TaskResponse(**task) for task in tasks]


@app.get("/tasks/activity-feed")
async def get_activity_feed(
    task_id: Optional[int] = Query(None, description="Filter by task ID", gt=0),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum number of results")
):
    """
    Get activity feed showing all task updates, completions, and relationship changes
    in chronological order. Supports filtering by task, agent, or date range.
    """
    # Validate date formats if provided
    if start_date:
        try:
            if start_date.endswith('Z'):
                datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            else:
                datetime.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid start_date format '{start_date}'. Must be ISO 8601 format."
            )
    
    if end_date:
        try:
            if end_date.endswith('Z'):
                datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            else:
                datetime.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid end_date format '{end_date}'. Must be ISO 8601 format."
            )
    
    try:
        feed = db.get_activity_feed(
            task_id=task_id,
            agent_id=agent_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        return {
            "feed": feed,
            "count": len(feed),
            "filters": {
                "task_id": task_id,
                "agent_id": agent_id,
                "start_date": start_date,
                "end_date": end_date
            }
        }
    except Exception as e:
        logger.error(f"Failed to get activity feed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to get activity feed. Please check the logs for details."
        )


@app.get("/tasks/export/json")
async def export_tasks_json(
    task_type: Optional[str] = Query(None, description="Filter by task type"),
    task_status: Optional[str] = Query(None, description="Filter by task status"),
    project_id: Optional[int] = Query(None, description="Filter by project ID", gt=0),
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
    limit: int = Query(10000, ge=1, le=50000, description="Maximum number of tasks to export")
):
    """Export tasks as JSON with all fields, relationships, and tags."""
    # Validate task_type if provided
    if task_type and task_type not in ["concrete", "abstract", "epic"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type '{task_type}'. Must be one of: concrete, abstract, epic"
        )
    
    # Validate task_status if provided
    if task_status and task_status not in ["available", "in_progress", "complete", "blocked", "cancelled"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_status '{task_status}'. Must be one of: available, in_progress, complete, blocked, cancelled"
        )
    
    # Validate date formats
    if start_date:
        try:
            if start_date.endswith('Z'):
                datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            else:
                datetime.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid start_date format '{start_date}'. Must be ISO 8601 format."
            )
    
    if end_date:
        try:
            if end_date.endswith('Z'):
                datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            else:
                datetime.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid end_date format '{end_date}'. Must be ISO 8601 format."
            )
    
    try:
        tasks = db.export_tasks(
            task_type=task_type,
            task_status=task_status,
            project_id=project_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        
        return JSONResponse(
            content={"tasks": tasks, "count": len(tasks)},
            media_type="application/json"
        )
    except Exception as e:
        logger.error(f"Failed to export tasks: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to export tasks. Please check the logs for details."
        )


@app.get("/tasks/export/csv")
async def export_tasks_csv(
    task_type: Optional[str] = Query(None, description="Filter by task type"),
    task_status: Optional[str] = Query(None, description="Filter by task status"),
    project_id: Optional[int] = Query(None, description="Filter by project ID", gt=0),
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
    limit: int = Query(10000, ge=1, le=50000, description="Maximum number of tasks to export")
):
    """Export tasks as CSV with all fields."""
    import csv
    from io import StringIO
    
    # Validate task_type if provided
    if task_type and task_type not in ["concrete", "abstract", "epic"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type '{task_type}'. Must be one of: concrete, abstract, epic"
        )
    
    # Validate task_status if provided
    if task_status and task_status not in ["available", "in_progress", "complete", "blocked", "cancelled"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_status '{task_status}'. Must be one of: available, in_progress, complete, blocked, cancelled"
        )
    
    # Validate date formats
    if start_date:
        try:
            if start_date.endswith('Z'):
                datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            else:
                datetime.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid start_date format '{start_date}'. Must be ISO 8601 format."
            )
    
    if end_date:
        try:
            if end_date.endswith('Z'):
                datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            else:
                datetime.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid end_date format '{end_date}'. Must be ISO 8601 format."
            )
    
    try:
        tasks = db.export_tasks(
            task_type=task_type,
            task_status=task_status,
            project_id=project_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        
        if not tasks:
            # Return empty CSV with headers
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(["id", "title", "task_type", "task_status", "priority", "project_id", "assigned_agent", 
                           "created_at", "updated_at", "completed_at", "relationships", "tags"])
            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=tasks_export.csv"}
            )
        
        # Define CSV columns
        fieldnames = [
            "id", "project_id", "title", "task_type", "task_instruction", "verification_instruction",
            "task_status", "verification_status", "priority", "assigned_agent", "created_at", "updated_at",
            "completed_at", "notes", "estimated_hours", "actual_hours", "started_at", "time_delta_hours",
            "due_date", "relationships", "tags"
        ]
        
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        
        for task in tasks:
            # Format relationships and tags as JSON strings for CSV
            row = task.copy()
            if row.get("relationships"):
                row["relationships"] = json.dumps(row["relationships"])
            else:
                row["relationships"] = ""
            
            if row.get("tags"):
                row["tags"] = json.dumps(row["tags"])
            else:
                row["tags"] = ""
            
            writer.writerow(row)
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=tasks_export.csv"}
        )
    except Exception as e:
        logger.error(f"Failed to export tasks as CSV: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to export tasks as CSV. Please check the logs for details."
        )


class TaskImportRequest(BaseModel):
    """Request model for task import."""
    tasks: List[Dict[str, Any]] = Field(..., description="List of tasks to import")
    agent_id: str = Field(..., description="Agent ID for import")
    handle_duplicates: str = Field("skip", description="How to handle duplicates: skip, error, or update")


@app.post("/tasks/import/json")
async def import_tasks_json(
    request: TaskImportRequest = Body(...)
):
    """Import tasks from JSON format."""
    tasks_data = {"tasks": request.tasks}
    agent_id = request.agent_id
    handle_duplicates = request.handle_duplicates
    
    if handle_duplicates not in ["skip", "error", "update"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid handle_duplicates value '{handle_duplicates}'. Must be: skip, error, or update"
        )
    
    created_count = 0
    skipped_count = 0
    error_count = 0
    created_task_ids = []
    skipped_tasks = []
    errors = []
    import_id_to_task_id = {}  # Map import_id to actual task_id for relationships
    
    # First pass: create all tasks and build import_id mapping
    for idx, task_data in enumerate(tasks_data["tasks"]):
        try:
            # Check for duplicates (by title if no import_id provided)
            title = task_data.get("title", "").strip()
            if not title:
                errors.append({
                    "index": idx,
                    "task": task_data,
                    "error": "Title is required and cannot be empty"
                })
                error_count += 1
                continue
            
            # Check for duplicate by title
            existing_tasks = db.query_tasks(limit=1000)  # Get all tasks to check for duplicates
            duplicate_found = False
            for existing_task in existing_tasks:
                if existing_task.get("title", "").strip() == title:
                    duplicate_found = True
                    if handle_duplicates == "skip":
                        skipped_tasks.append({
                            "index": idx,
                            "task": task_data,
                            "reason": f"Duplicate task with title '{title}'"
                        })
                        skipped_count += 1
                        break
                    elif handle_duplicates == "error":
                        errors.append({
                            "index": idx,
                            "task": task_data,
                            "error": f"Duplicate task with title '{title}'"
                        })
                        error_count += 1
                        break
                    # For "update", we'd need to implement update logic - skip for now
                    break
            
            if duplicate_found:
                continue
            
            # Validate required fields
            if "task_type" not in task_data:
                errors.append({
                    "index": idx,
                    "task": task_data,
                    "error": "task_type is required"
                })
                error_count += 1
                continue
            
            if task_data["task_type"] not in ["concrete", "abstract", "epic"]:
                errors.append({
                    "index": idx,
                    "task": task_data,
                    "error": f"Invalid task_type '{task_data['task_type']}'. Must be one of: concrete, abstract, epic"
                })
                error_count += 1
                continue
            
            if "task_instruction" not in task_data or not task_data["task_instruction"].strip():
                errors.append({
                    "index": idx,
                    "task": task_data,
                    "error": "task_instruction is required and cannot be empty"
                })
                error_count += 1
                continue
            
            if "verification_instruction" not in task_data or not task_data["verification_instruction"].strip():
                errors.append({
                    "index": idx,
                    "task": task_data,
                    "error": "verification_instruction is required and cannot be empty"
                })
                error_count += 1
                continue
            
            # Validate project_id if provided
            project_id = task_data.get("project_id")
            if project_id is not None:
                project = db.get_project(project_id)
                if not project:
                    errors.append({
                        "index": idx,
                        "task": task_data,
                        "error": f"Project ID {project_id} not found"
                    })
                    error_count += 1
                    continue
            
            # Parse due_date if provided
            due_date_obj = None
            if task_data.get("due_date"):
                try:
                    due_date_str = task_data["due_date"]
                    if due_date_str.endswith('Z'):
                        due_date_obj = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                    else:
                        due_date_obj = datetime.fromisoformat(due_date_str)
                except ValueError as e:
                    errors.append({
                        "index": idx,
                        "task": task_data,
                        "error": f"Invalid due_date format: {str(e)}"
                    })
                    error_count += 1
                    continue
            
            # Create task
            task_id = db.create_task(
                title=title,
                task_type=task_data["task_type"],
                task_instruction=task_data["task_instruction"].strip(),
                verification_instruction=task_data["verification_instruction"].strip(),
                agent_id=agent_id,
                project_id=project_id,
                notes=task_data.get("notes"),
                priority=task_data.get("priority", "medium"),
                estimated_hours=task_data.get("estimated_hours"),
                due_date=due_date_obj
            )
            
            created_task_ids.append(task_id)
            created_count += 1
            
            # Store import_id mapping for relationship creation
            import_id = task_data.get("import_id")
            if import_id:
                import_id_to_task_id[str(import_id)] = task_id
            
        except Exception as e:
            logger.error(f"Error importing task at index {idx}: {str(e)}", exc_info=True)
            errors.append({
                "index": idx,
                "task": task_data,
                "error": f"Unexpected error: {str(e)}"
            })
            error_count += 1
    
    # Second pass: create relationships
    relationships_created = 0
    for idx, task_data in enumerate(tasks_data["tasks"]):
        import_id = task_data.get("import_id")
        parent_import_id = task_data.get("parent_import_id")
        relationship_type = task_data.get("relationship_type")
        
        if parent_import_id and import_id and relationship_type:
            parent_task_id = import_id_to_task_id.get(str(parent_import_id))
            child_task_id = import_id_to_task_id.get(str(import_id))
            
            if parent_task_id and child_task_id:
                try:
                    db.create_relationship(
                        parent_task_id=parent_task_id,
                        child_task_id=child_task_id,
                        relationship_type=relationship_type,
                        agent_id=agent_id
                    )
                    relationships_created += 1
                except Exception as e:
                    logger.warning(f"Failed to create relationship: {str(e)}")
    
    return {
        "success": True,
        "created": created_count,
        "skipped": skipped_count,
        "error_count": error_count,
        "task_ids": created_task_ids,
        "skipped_tasks": skipped_tasks if skipped_tasks else [],
        "errors": errors if errors else [],
        "relationships_created": relationships_created
    }


@app.post("/tasks/import/csv")
async def import_tasks_csv(
    file: UploadFile = File(..., description="CSV file to import"),
    agent_id: str = Form(..., description="Agent ID for import"),
    handle_duplicates: str = Form("skip", description="How to handle duplicates: skip, error, or update"),
    field_mapping: Optional[str] = Form(None, description="JSON object mapping CSV columns to task fields")
):
    """Import tasks from CSV format."""
    import csv
    from io import StringIO
    
    if handle_duplicates not in ["skip", "error", "update"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid handle_duplicates value '{handle_duplicates}'. Must be: skip, error, or update"
        )
    
    # Parse field mapping if provided
    mapping = {}
    if field_mapping:
        try:
            mapping = json.loads(field_mapping)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON format for field_mapping parameter"
            )
    
    # Read CSV file
    try:
        content = await file.read()
        csv_content = content.decode('utf-8')
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read CSV file: {str(e)}"
        )
    
    # Parse CSV
    try:
        csv_reader = csv.DictReader(StringIO(csv_content))
        rows = list(csv_reader)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse CSV file: {str(e)}"
        )
    
    if not rows:
        return {
            "success": True,
            "created": 0,
            "skipped": 0,
            "error_count": 0,
            "task_ids": [],
            "skipped_tasks": [],
            "errors": [],
            "relationships_created": 0
        }
    
    # Map CSV columns to task fields
    def map_field(csv_field):
        """Map CSV field name to task field name using mapping or direct match."""
        if csv_field in mapping:
            return mapping[csv_field]
        # Direct match (normalize field names)
        field_lower = csv_field.lower().replace(" ", "_").replace("-", "_")
        # Common mappings
        if field_lower in ["task_title", "title", "name"]:
            return "title"
        if field_lower in ["task_type", "type"]:
            return "task_type"
        if field_lower in ["task_instruction", "instruction", "description"]:
            return "task_instruction"
        if field_lower in ["verification_instruction", "verification", "verification_step"]:
            return "verification_instruction"
        if field_lower in ["priority", "pri"]:
            return "priority"
        if field_lower in ["estimated_hours", "hours", "estimate"]:
            return "estimated_hours"
        if field_lower in ["notes", "note", "comments"]:
            return "notes"
        if field_lower in ["project_id", "project"]:
            return "project_id"
        if field_lower in ["due_date", "due", "deadline"]:
            return "due_date"
        return csv_field
    
    created_count = 0
    skipped_count = 0
    error_count = 0
    created_task_ids = []
    skipped_tasks = []
    errors = []
    import_id_to_task_id = {}
    
    # Process each row
    for idx, row in enumerate(rows):
        try:
            # Map CSV fields to task fields
            task_data = {}
            for csv_field, value in row.items():
                if value and value.strip():  # Skip empty values
                    mapped_field = map_field(csv_field)
                    task_data[mapped_field] = value.strip() if isinstance(value, str) else value
            
            # Check required fields
            title = task_data.get("title", "").strip()
            if not title:
                errors.append({
                    "index": idx,
                    "row": row,
                    "error": "Title is required and cannot be empty"
                })
                error_count += 1
                continue
            
            # Check for duplicates
            existing_tasks = db.query_tasks(limit=1000)
            duplicate_found = False
            for existing_task in existing_tasks:
                if existing_task.get("title", "").strip() == title:
                    duplicate_found = True
                    if handle_duplicates == "skip":
                        skipped_tasks.append({
                            "index": idx,
                            "row": row,
                            "reason": f"Duplicate task with title '{title}'"
                        })
                        skipped_count += 1
                        break
                    elif handle_duplicates == "error":
                        errors.append({
                            "index": idx,
                            "row": row,
                            "error": f"Duplicate task with title '{title}'"
                        })
                        error_count += 1
                        break
                    break
            
            if duplicate_found:
                continue
            
            # Set defaults and validate
            task_type = task_data.get("task_type", "concrete")
            if task_type not in ["concrete", "abstract", "epic"]:
                errors.append({
                    "index": idx,
                    "row": row,
                    "error": f"Invalid task_type '{task_type}'. Must be one of: concrete, abstract, epic"
                })
                error_count += 1
                continue
            
            task_instruction = task_data.get("task_instruction", "").strip()
            if not task_instruction:
                errors.append({
                    "index": idx,
                    "row": row,
                    "error": "task_instruction is required and cannot be empty"
                })
                error_count += 1
                continue
            
            verification_instruction = task_data.get("verification_instruction", "").strip()
            if not verification_instruction:
                errors.append({
                    "index": idx,
                    "row": row,
                    "error": "verification_instruction is required and cannot be empty"
                })
                error_count += 1
                continue
            
            # Validate project_id if provided
            project_id = task_data.get("project_id")
            if project_id:
                try:
                    project_id = int(project_id)
                    project = db.get_project(project_id)
                    if not project:
                        errors.append({
                            "index": idx,
                            "row": row,
                            "error": f"Project ID {project_id} not found"
                        })
                        error_count += 1
                        continue
                except ValueError:
                    errors.append({
                        "index": idx,
                        "row": row,
                        "error": f"Invalid project_id format: {task_data.get('project_id')}"
                    })
                    error_count += 1
                    continue
            else:
                project_id = None
            
            # Parse estimated_hours if provided
            estimated_hours = None
            if task_data.get("estimated_hours"):
                try:
                    estimated_hours = float(task_data["estimated_hours"])
                    if estimated_hours <= 0:
                        raise ValueError("estimated_hours must be positive")
                except (ValueError, TypeError):
                    errors.append({
                        "index": idx,
                        "row": row,
                        "error": f"Invalid estimated_hours format: {task_data.get('estimated_hours')}"
                    })
                    error_count += 1
                    continue
            
            # Parse due_date if provided
            due_date_obj = None
            if task_data.get("due_date"):
                try:
                    due_date_str = task_data["due_date"]
                    if due_date_str.endswith('Z'):
                        due_date_obj = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                    else:
                        due_date_obj = datetime.fromisoformat(due_date_str)
                except ValueError as e:
                    errors.append({
                        "index": idx,
                        "row": row,
                        "error": f"Invalid due_date format: {str(e)}"
                    })
                    error_count += 1
                    continue
            
            # Create task
            task_id = db.create_task(
                title=title,
                task_type=task_type,
                task_instruction=task_instruction,
                verification_instruction=verification_instruction,
                agent_id=agent_id,
                project_id=project_id,
                notes=task_data.get("notes"),
                priority=task_data.get("priority", "medium"),
                estimated_hours=estimated_hours,
                due_date=due_date_obj
            )
            
            created_task_ids.append(task_id)
            created_count += 1
            
            # Store import_id mapping for relationships
            import_id = task_data.get("import_id")
            if import_id:
                import_id_to_task_id[str(import_id)] = task_id
            
        except Exception as e:
            logger.error(f"Error importing CSV row {idx}: {str(e)}", exc_info=True)
            errors.append({
                "index": idx,
                "row": row,
                "error": f"Unexpected error: {str(e)}"
            })
            error_count += 1
    
    # Create relationships if import_id and parent_import_id are present
    relationships_created = 0
    for idx, row in enumerate(rows):
        try:
            task_data = {}
            for csv_field, value in row.items():
                if value and value.strip():
                    mapped_field = map_field(csv_field)
                    task_data[mapped_field] = value.strip() if isinstance(value, str) else value
            
            import_id = task_data.get("import_id")
            parent_import_id = task_data.get("parent_import_id")
            relationship_type = task_data.get("relationship_type", "subtask")
            
            if parent_import_id and import_id:
                parent_task_id = import_id_to_task_id.get(str(parent_import_id))
                child_task_id = import_id_to_task_id.get(str(import_id))
                
                if parent_task_id and child_task_id:
                    try:
                        db.create_relationship(
                            parent_task_id=parent_task_id,
                            child_task_id=child_task_id,
                            relationship_type=relationship_type,
                            agent_id=agent_id
                        )
                        relationships_created += 1
                    except Exception as e:
                        logger.warning(f"Failed to create relationship: {str(e)}")
        except Exception:
            pass  # Skip relationship creation for rows that failed
    
    return {
        "success": True,
        "created": created_count,
        "skipped": skipped_count,
        "error_count": error_count,
        "task_ids": created_task_ids,
        "skipped_tasks": skipped_tasks if skipped_tasks else [],
        "errors": errors if errors else [],
        "relationships_created": relationships_created
    }


@app.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int = Path(..., gt=0)):
    """Delete a tag (removes from all tasks)."""
    tag = db.get_tag(tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail=f"Tag {tag_id} not found")
    
    db.delete_tag(tag_id)
    return {"message": f"Tag {tag_id} deleted", "tag_id": tag_id}


# Template endpoints
class TemplateCreate(BaseModel):
    name: str = Field(..., description="Template name (unique)", min_length=1)
    task_type: str = Field(..., description="Task type: concrete, abstract, or epic")
    task_instruction: str = Field(..., description="What to do", min_length=1)
    verification_instruction: str = Field(..., description="How to verify completion", min_length=1)
    description: Optional[str] = Field(None, description="Optional template description")
    priority: Optional[str] = Field("medium", description="Task priority: low, medium, high, or critical")
    estimated_hours: Optional[float] = Field(None, description="Optional estimated hours", gt=0)
    notes: Optional[str] = Field(None, description="Optional notes")
    
    @field_validator('name', 'task_instruction', 'verification_instruction')
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


class CreateTaskFromTemplateRequest(BaseModel):
    agent_id: str = Field(..., description="Agent ID creating this task", min_length=1)
    title: Optional[str] = Field(None, description="Optional task title (defaults to template name)")
    project_id: Optional[int] = Field(None, description="Optional project ID", gt=0)
    notes: Optional[str] = Field(None, description="Optional notes (combined with template notes)")
    priority: Optional[str] = Field(None, description="Optional priority override")
    estimated_hours: Optional[float] = Field(None, description="Optional estimated hours override", gt=0)
    due_date: Optional[str] = Field(None, description="Optional due date (ISO format timestamp)")
    
    @field_validator('agent_id')
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        """Validate agent_id is not empty."""
        if not v or not v.strip():
            raise ValueError("agent_id cannot be empty or contain only whitespace")
        return v.strip()


class TemplateResponse(BaseModel):
    """Template response model."""
    id: int
    name: str
    description: Optional[str]
    task_type: str
    task_instruction: str
    verification_instruction: str
    priority: str
    estimated_hours: Optional[float]
    notes: Optional[str]
    created_at: str
    updated_at: str


@app.post("/templates", response_model=TemplateResponse, status_code=201)
async def create_template(template: TemplateCreate):
    """Create a new task template."""
    try:
        template_id = db.create_template(
            name=template.name,
            description=template.description,
            task_type=template.task_type,
            task_instruction=template.task_instruction,
            verification_instruction=template.verification_instruction,
            priority=template.priority,
            estimated_hours=template.estimated_hours,
            notes=template.notes
        )
        created_template = db.get_template(template_id)
        if not created_template:
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve created template. The template may have been created but could not be retrieved. Please try again or contact support."
            )
        return TemplateResponse(**created_template)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"Template with name '{template.name}' already exists. Please use a different name or update the existing template."
        )


@app.get("/templates", response_model=List[TemplateResponse])
async def list_templates(task_type: Optional[str] = Query(None, description="Filter by task type")):
    """List all templates, optionally filtered by task type."""
    if task_type and task_type not in ["concrete", "abstract", "epic"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type '{task_type}'. Must be one of: concrete, abstract, epic"
        )
    templates = db.list_templates(task_type=task_type)
    return [TemplateResponse(**template) for template in templates]


@app.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: int = Path(..., gt=0, description="Template ID")):
    """Get a template by ID."""
    template = db.get_template(template_id)
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template {template_id} not found. Please verify the template_id is correct."
        )
    return TemplateResponse(**template)


@app.post("/templates/{template_id}/create-task", response_model=TaskResponse, status_code=201)
async def create_task_from_template(
    template_id: int = Path(..., gt=0, description="Template ID"),
    request: CreateTaskFromTemplateRequest = Body(...)
):
    """Create a task from a template."""
    # Verify template exists
    template = db.get_template(template_id)
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template {template_id} not found. Please verify the template_id is correct."
        )
    
    # Verify project exists if provided
    if request.project_id is not None:
        project = db.get_project(request.project_id)
        if not project:
            raise HTTPException(
                status_code=404,
                detail=f"Project with ID {request.project_id} not found. Please verify the project_id is correct."
            )
    
    try:
        # Parse due_date if provided
        due_date_obj = None
        if request.due_date:
            try:
                if request.due_date.endswith('Z'):
                    due_date_obj = datetime.fromisoformat(request.due_date.replace('Z', '+00:00'))
                else:
                    due_date_obj = datetime.fromisoformat(request.due_date)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid due_date format '{request.due_date}'. Must be ISO 8601 format. Error: {str(e)}"
                )
        
        task_id = db.create_task_from_template(
            template_id=template_id,
            agent_id=request.agent_id,
            title=request.title,
            project_id=request.project_id,
            notes=request.notes,
            priority=request.priority,
            estimated_hours=request.estimated_hours,
            due_date=due_date_obj if request.due_date else None
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create task from template: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to create task from template. Please try again or contact support if the issue persists."
        )
    
    created_task = db.get_task(task_id)
    if not created_task:
        logger.error(f"Task {task_id} was created but could not be retrieved")
        raise HTTPException(
            status_code=500,
            detail="Task was created but could not be retrieved. Please check task status."
        )
    
    return TaskResponse(**created_task)


@app.post("/backup/create")
async def create_backup():
    """Create a manual backup snapshot (gzip archive)."""
    try:
        archive_path = backup_manager.create_backup_archive()
        logger.info(f"Backup created successfully: {archive_path}")
        return {
            "success": True,
            "backup_path": archive_path,
            "message": "Backup created successfully"
        }
    except FileNotFoundError as e:
        logger.error(f"Backup failed - database not found: {str(e)}")
        raise HTTPException(
            status_code=404,
            detail=f"Backup failed: Database file not found. Please verify the database path is correct."
        )
    except Exception as e:
        logger.error(f"Backup failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Backup creation failed. Please check the logs for details and try again."
        )


@app.get("/backup/list")
async def list_backups():
    """List all available backups."""
    backups = backup_manager.list_backups()
    return {"backups": backups, "count": len(backups)}


@app.post("/backup/restore")
async def restore_backup(
    backup_path: str = Body(..., embed=True),
    force: bool = Body(False, embed=True)
):
    """Restore database from a backup."""
    if not backup_path or not backup_path.strip():
        raise HTTPException(
            status_code=400,
            detail="backup_path is required and cannot be empty"
        )
    
    try:
        success = backup_manager.restore_from_backup(backup_path, force=force)
        if success:
            logger.info(f"Database restored successfully from {backup_path}")
            return {
                "success": True,
                "message": f"Database restored successfully from backup: {backup_path}"
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Restore operation returned unsuccessful. Please check the logs for details."
            )
    except ValueError as e:
        logger.warning(f"Backup restore validation error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid restore request: {str(e)}"
        )
    except FileNotFoundError as e:
        logger.warning(f"Backup restore - file not found: {str(e)}")
        raise HTTPException(
            status_code=404,
            detail=f"Backup file not found: {backup_path}. Please verify the backup path is correct."
        )
    except Exception as e:
        logger.error(f"Backup restore failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Restore operation failed. Please check the logs for details and try again."
        )


@app.post("/backup/cleanup")
async def cleanup_backups(keep_days: int = Body(30, embed=True)):
    """Clean up old backups (keep only recent N days)."""
    try:
        deleted_count = backup_manager.cleanup_old_backups(keep_days=keep_days)
        return {"success": True, "deleted_count": deleted_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")


# ===== Conversation Management Endpoints =====

class MessageAdd(BaseModel):
    """Model for adding a message to a conversation."""
    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str = Field(..., description="Message content", min_length=1)
    tokens: Optional[int] = Field(None, description="Token count for this message", ge=0)
    
    @field_validator('role')
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Validate message role."""
        if v not in ['user', 'assistant', 'system']:
            raise ValueError(f"Invalid role '{v}'. Must be one of: user, assistant, system")
        return v


class ConversationResponse(BaseModel):
    """Response model for conversation data."""
    id: int
    user_id: str
    chat_id: str
    created_at: str
    updated_at: str
    last_message_at: Optional[str]
    message_count: int
    total_tokens: int
    metadata: Dict[str, Any]
    messages: List[Dict[str, Any]]


class ConversationResetRequest(BaseModel):
    """Request model for resetting a conversation."""
    pass  # No additional fields needed


class ShareCreateRequest(BaseModel):
    """Request model for creating a conversation share."""
    shared_with_user_id: Optional[str] = Field(None, description="User ID to share with (optional)")
    permission: str = Field("read_only", description="Share permission: 'read_only' or 'editable'")
    share_token: Optional[str] = Field(None, description="Custom share token (auto-generated if not provided)")
    
    @field_validator('permission')
    @classmethod
    def validate_permission(cls, v: str) -> str:
        """Validate permission."""
        if v not in ['read_only', 'editable']:
            raise ValueError(f"Invalid permission '{v}'. Must be 'read_only' or 'editable'")
        return v


class ShareResponse(BaseModel):
    """Response model for conversation share data."""
    id: int
    conversation_id: int
    owner_user_id: str
    shared_with_user_id: Optional[str]
    share_token: str
    permission: str
    created_at: str


@app.post("/conversations/{user_id}/{chat_id}", response_model=ConversationResponse, status_code=200)
async def get_or_create_conversation_endpoint(
    user_id: str = Path(..., description="User identifier"),
    chat_id: str = Path(..., description="Chat/conversation identifier")
):
    """
    Get an existing conversation or create a new one.
    Returns the conversation with all messages.
    """
    try:
        conversation_id = conversation_storage.get_or_create_conversation(user_id, chat_id)
        conversation = conversation_storage.get_conversation(user_id, chat_id)
        if not conversation:
            raise HTTPException(status_code=500, detail="Failed to retrieve conversation after creation")
        
        # Convert datetime objects to ISO format strings
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return ConversationResponse(
            id=conversation['id'],
            user_id=conversation['user_id'],
            chat_id=conversation['chat_id'],
            created_at=format_datetime(conversation['created_at']),
            updated_at=format_datetime(conversation['updated_at']),
            last_message_at=format_datetime(conversation['last_message_at']),
            message_count=conversation['message_count'],
            total_tokens=conversation['total_tokens'],
            metadata=conversation.get('metadata', {}),
            messages=[
                {
                    'id': msg['id'],
                    'role': msg['role'],
                    'content': msg['content'],
                    'tokens': msg.get('tokens'),
                    'created_at': format_datetime(msg['created_at'])
                }
                for msg in conversation.get('messages', [])
            ]
        )
    except Exception as e:
        logger.error(f"Error in get_or_create_conversation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get or create conversation: {str(e)}")


@app.get("/conversations/{user_id}/{chat_id}", response_model=ConversationResponse)
async def get_conversation_endpoint(
    user_id: str = Path(..., description="User identifier"),
    chat_id: str = Path(..., description="Chat/conversation identifier"),
    limit: Optional[int] = Query(None, description="Maximum number of messages to return", ge=1),
    max_tokens: Optional[int] = Query(None, description="Maximum tokens (oldest messages pruned first)", ge=0)
):
    """
    Get conversation history for a user/chat.
    Supports limiting by message count or token count.
    """
    try:
        conversation = conversation_storage.get_conversation(user_id, chat_id, limit=limit, max_tokens=max_tokens)
        if not conversation:
            raise HTTPException(status_code=404, detail=f"Conversation not found for user {user_id}, chat {chat_id}")
        
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return ConversationResponse(
            id=conversation['id'],
            user_id=conversation['user_id'],
            chat_id=conversation['chat_id'],
            created_at=format_datetime(conversation['created_at']),
            updated_at=format_datetime(conversation['updated_at']),
            last_message_at=format_datetime(conversation['last_message_at']),
            message_count=conversation['message_count'],
            total_tokens=conversation['total_tokens'],
            metadata=conversation.get('metadata', {}),
            messages=[
                {
                    'id': msg['id'],
                    'role': msg['role'],
                    'content': msg['content'],
                    'tokens': msg.get('tokens'),
                    'created_at': format_datetime(msg['created_at'])
                }
                for msg in conversation.get('messages', [])
            ]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_conversation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get conversation: {str(e)}")


@app.post("/conversations/{user_id}/{chat_id}/messages", status_code=201)
async def add_message_endpoint(
    user_id: str = Path(..., description="User identifier (owner)"),
    chat_id: str = Path(..., description="Chat/conversation identifier"),
    message: MessageAdd = Body(...),
    accessed_by_user_id: Optional[str] = Query(None, description="User ID requesting access (for access control)")
):
    """
    Add a message to a conversation.
    Creates the conversation if it doesn't exist.
    Checks write permissions if accessed_by_user_id is provided.
    """
    try:
        # Check write access if accessed_by_user_id is provided and different from owner
        requesting_user = accessed_by_user_id or user_id
        if requesting_user != user_id:
            access = conversation_storage.check_conversation_access(user_id, chat_id, requesting_user)
            if not access['can_write']:
                raise HTTPException(
                    status_code=403,
                    detail="Write permission denied. Only owners and users with editable shares can add messages."
                )
        
        conversation_id = conversation_storage.get_or_create_conversation(user_id, chat_id)
        message_id = conversation_storage.add_message(
            conversation_id=conversation_id,
            role=message.role,
            content=message.content,
            tokens=message.tokens
        )
        return {"message_id": message_id, "conversation_id": conversation_id}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in add_message: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add message: {str(e)}")


@app.post("/conversations/{user_id}/{chat_id}/reset")
async def reset_conversation_endpoint(
    user_id: str = Path(..., description="User identifier"),
    chat_id: str = Path(..., description="Chat/conversation identifier")
):
    """
    Reset a conversation by clearing all messages but keeping the conversation record.
    This starts a new conversation context while preserving metadata.
    """
    try:
        reset = conversation_storage.reset_conversation(user_id, chat_id)
        if not reset:
            raise HTTPException(status_code=404, detail=f"Conversation not found for user {user_id}, chat {chat_id}")
        return {"success": True, "message": "Conversation reset successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in reset_conversation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to reset conversation: {str(e)}")


@app.delete("/conversations/{user_id}/{chat_id}")
async def delete_conversation_endpoint(
    user_id: str = Path(..., description="User identifier"),
    chat_id: str = Path(..., description="Chat/conversation identifier")
):
    """
    Delete a conversation and all its messages.
    """
    try:
        deleted = conversation_storage.delete_conversation(user_id, chat_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Conversation not found for user {user_id}, chat {chat_id}")
        return {"success": True, "message": "Conversation deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_conversation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation: {str(e)}")


@app.post("/conversations/{user_id}/{chat_id}/prune")
async def prune_conversation_endpoint(
    user_id: str = Path(..., description="User identifier"),
    chat_id: str = Path(..., description="Chat/conversation identifier"),
    max_tokens: int = Body(..., embed=True, description="Maximum tokens to keep", ge=1),
    keep_recent: int = Body(5, embed=True, description="Minimum number of recent messages to always keep", ge=1)
):
    """
    Prune old messages from a conversation to stay within token limit.
    Keeps the most recent messages.
    """
    try:
        pruned_count = conversation_storage.prune_old_contexts(user_id, chat_id, max_tokens, keep_recent)
        return {"success": True, "pruned_count": pruned_count}
    except Exception as e:
        logger.error(f"Error in prune_conversation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to prune conversation: {str(e)}")


@app.get("/conversations")
async def list_conversations_endpoint(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    limit: int = Query(100, description="Maximum number of conversations to return", ge=1, le=1000)
):
    """
    List conversations, optionally filtered by user.
    """
    try:
        conversations = conversation_storage.list_conversations(user_id=user_id, limit=limit)
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return [
            {
                'id': conv['id'],
                'user_id': conv['user_id'],
                'chat_id': conv['chat_id'],
                'created_at': format_datetime(conv['created_at']),
                'updated_at': format_datetime(conv['updated_at']),
                'last_message_at': format_datetime(conv['last_message_at']),
                'message_count': conv['message_count'],
                'total_tokens': conv['total_tokens']
            }
            for conv in conversations
        ]
    except Exception as e:
        logger.error(f"Error in list_conversations: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list conversations: {str(e)}")


@app.get("/conversations/{user_id}/{chat_id}/export")
async def export_conversation_endpoint(
    user_id: str = Path(..., description="User identifier"),
    chat_id: str = Path(..., description="Chat/conversation identifier"),
    format: str = Query("json", description="Export format (json, txt, pdf)", pattern="^(json|txt|pdf)$"),
    start_date: Optional[str] = Query(None, description="Start date for filtering messages (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date for filtering messages (ISO format)")
):
    """
    Export conversation to JSON, TXT, or PDF format.
    Supports date range filtering for messages.
    """
    try:
        # Parse date strings if provided
        start_date_obj = None
        end_date_obj = None
        
        if start_date:
            try:
                from datetime import datetime
                start_date_obj = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid start_date format: {str(e)}")
        
        if end_date:
            try:
                from datetime import datetime
                end_date_obj = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid end_date format: {str(e)}")
        
        # Export conversation
        export_result = conversation_storage.export_conversation(
            user_id=user_id,
            chat_id=chat_id,
            format=format,
            start_date=start_date_obj,
            end_date=end_date_obj
        )
        
        # Return appropriate response based on format
        if format == "json":
            from fastapi.responses import JSONResponse
            return JSONResponse(content=export_result)
        elif format == "txt":
            from fastapi.responses import Response
            return Response(
                content=export_result,
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f"attachment; filename=conversation_{user_id}_{chat_id}.txt"}
            )
        elif format == "pdf":
            from fastapi.responses import Response
            return Response(
                content=export_result,
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=conversation_{user_id}_{chat_id}.pdf"}
            )
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        logger.error(f"Error exporting conversation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to export conversation: {str(e)}")


# Conversation Backup Endpoints

@app.post("/conversations/{user_id}/{chat_id}/backup")
async def create_conversation_backup_endpoint(
    user_id: str = Path(..., description="User identifier"),
    chat_id: str = Path(..., description="Chat/conversation identifier"),
    metadata: Optional[Dict[str, Any]] = Body(None, description="Optional metadata for backup")
):
    """
    Create a backup of a conversation to object storage.
    Requires BACKUP_S3_BUCKET to be configured.
    """
    if not conversation_backup_manager:
        raise HTTPException(
            status_code=503,
            detail="Conversation backup not configured. Set BACKUP_S3_BUCKET environment variable."
        )
    
    try:
        backup_key = conversation_backup_manager.create_backup(
            user_id=user_id,
            chat_id=chat_id,
            metadata=metadata
        )
        return {
            "success": True,
            "backup_key": backup_key,
            "message": f"Backup created successfully: {backup_key}"
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating backup: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create backup: {str(e)}")


@app.get("/conversations/backups")
async def list_conversation_backups_endpoint(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    chat_id: Optional[str] = Query(None, description="Filter by chat ID"),
    limit: int = Query(100, description="Maximum number of backups to return", ge=1, le=1000)
):
    """
    List available conversation backups.
    Requires BACKUP_S3_BUCKET to be configured.
    """
    if not conversation_backup_manager:
        raise HTTPException(
            status_code=503,
            detail="Conversation backup not configured. Set BACKUP_S3_BUCKET environment variable."
        )
    
    try:
        backups = conversation_backup_manager.list_backups(
            user_id=user_id,
            chat_id=chat_id,
            limit=limit
        )
        return {
            "backups": backups,
            "count": len(backups)
        }
    except Exception as e:
        logger.error(f"Error listing backups: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list backups: {str(e)}")


@app.post("/conversations/{user_id}/{chat_id}/share", response_model=ShareResponse, status_code=201)
async def create_share_endpoint(
    user_id: str = Path(..., description="User identifier (owner)"),
    chat_id: str = Path(..., description="Chat/conversation identifier"),
    share_request: ShareCreateRequest = Body(...)
):
    """
    Create a share for a conversation.
    Supports read-only and editable sharing modes.
    """
    try:
        share_id = conversation_storage.create_share(
            user_id=user_id,
            chat_id=chat_id,
            shared_with_user_id=share_request.shared_with_user_id,
            permission=share_request.permission,
            share_token=share_request.share_token
        )
        
        share = conversation_storage.get_share(share_id)
        if not share:
            raise HTTPException(status_code=500, detail="Failed to retrieve created share")
        
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return ShareResponse(
            id=share['id'],
            conversation_id=share['conversation_id'],
            owner_user_id=share['owner_user_id'],
            shared_with_user_id=share['shared_with_user_id'],
            share_token=share['share_token'],
            permission=share['permission'],
            created_at=format_datetime(share['created_at'])
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in create_share: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create share: {str(e)}")


@app.get("/conversations/{user_id}/{chat_id}/shares", response_model=List[ShareResponse])
async def list_shares_endpoint(
    user_id: str = Path(..., description="User identifier (owner)"),
    chat_id: str = Path(..., description="Chat/conversation identifier")
):
    """
    List all shares for a conversation.
    """
    try:
        shares = conversation_storage.list_shares_for_conversation(user_id, chat_id)
        
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return [
            ShareResponse(
                id=s['id'],
                conversation_id=s['conversation_id'],
                owner_user_id=s['owner_user_id'],
                shared_with_user_id=s.get('shared_with_user_id'),
                share_token=s['share_token'],
                permission=s['permission'],
                created_at=format_datetime(s['created_at'])
            )
            for s in shares
        ]
    except Exception as e:
        logger.error(f"Error in list_shares: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list shares: {str(e)}")


@app.get("/conversations/shares/user/{user_id}", response_model=List[ShareResponse])
async def list_shares_for_user_endpoint(
    user_id: str = Path(..., description="User identifier")
):
    """
    List all shares where a user is the recipient.
    """
    try:
        shares = conversation_storage.list_shares_for_user(user_id)
        
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return [
            ShareResponse(
                id=s['id'],
                conversation_id=s['conversation_id'],
                owner_user_id=s['owner_user_id'],
                shared_with_user_id=s.get('shared_with_user_id'),
                share_token=s['share_token'],
                permission=s['permission'],
                created_at=format_datetime(s['created_at'])
            )
            for s in shares
        ]
    except Exception as e:
        logger.error(f"Error in list_shares_for_user: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list shares: {str(e)}")


@app.get("/conversations/shared/{share_token}", response_model=ConversationResponse)
async def get_conversation_by_share_token_endpoint(
    share_token: str = Path(..., description="Share token"),
    limit: Optional[int] = Query(None, description="Maximum number of messages to return", ge=1),
    max_tokens: Optional[int] = Query(None, description="Maximum tokens (oldest messages pruned first)", ge=0)
):
    """
    Get a conversation using a share token.
    """
    try:
        conversation = conversation_storage.get_conversation_by_share_token(
            share_token, limit=limit, max_tokens=max_tokens
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Invalid share token")
        
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return ConversationResponse(
            id=conversation['id'],
            user_id=conversation['user_id'],
            chat_id=conversation['chat_id'],
            created_at=format_datetime(conversation['created_at']),
            updated_at=format_datetime(conversation['updated_at']),
            last_message_at=format_datetime(conversation['last_message_at']),
            message_count=conversation['message_count'],
            total_tokens=conversation['total_tokens'],
            metadata=conversation.get('metadata', {}),
            messages=[
                {
                    'id': msg['id'],
                    'role': msg['role'],
                    'content': msg['content'],
                    'tokens': msg.get('tokens'),
                    'created_at': format_datetime(msg['created_at'])
                }
                for msg in conversation.get('messages', [])
            ]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_conversation_by_share_token: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get conversation: {str(e)}")


@app.get("/conversations/shares/{share_id}", response_model=ShareResponse)
async def get_share_endpoint(
    share_id: int = Path(..., description="Share ID")
):
    """
    Get a share by ID.
    """
    try:
        share = conversation_storage.get_share(share_id)
        if not share:
            raise HTTPException(status_code=404, detail=f"Share {share_id} not found")
        
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return ShareResponse(
            id=share['id'],
            conversation_id=share['conversation_id'],
            owner_user_id=share['owner_user_id'],
            shared_with_user_id=share.get('shared_with_user_id'),
            share_token=share['share_token'],
            permission=share['permission'],
            created_at=format_datetime(share['created_at'])
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_share: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get share: {str(e)}")


@app.delete("/conversations/shares/{share_id}")
async def delete_share_endpoint(
    share_id: int = Path(..., description="Share ID")
):
    """
    Delete a share.
    """
    try:
        deleted = conversation_storage.delete_share(share_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Share {share_id} not found")
        return {"success": True, "message": "Share deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_share: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete share: {str(e)}")


@app.post("/conversations/backups/{backup_key:path}/restore")
async def restore_conversation_backup_endpoint(
    backup_key: str = Path(..., description="S3 key of backup to restore")
):
    """
    Restore a conversation from backup.
    Requires BACKUP_S3_BUCKET to be configured.
    """
    if not conversation_backup_manager:
        raise HTTPException(
            status_code=503,
            detail="Conversation backup not configured. Set BACKUP_S3_BUCKET environment variable."
        )
    
    try:
        conversation_id = conversation_backup_manager.restore_backup(backup_key)
        return {
            "success": True,
            "conversation_id": conversation_id,
            "message": f"Conversation restored successfully from backup: {backup_key}"
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error restoring backup: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to restore backup: {str(e)}")


@app.post("/conversations/backups/retention")
async def apply_retention_policy_endpoint(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    chat_id: Optional[str] = Query(None, description="Filter by chat ID"),
    keep_latest: int = Query(10, description="Number of most recent backups to keep", ge=1),
    retention_days: Optional[int] = Query(None, description="Delete backups older than this many days", ge=1)
):
    """
    Apply retention policy to delete old backups.
    Requires BACKUP_S3_BUCKET to be configured.
    """
    if not conversation_backup_manager:
        raise HTTPException(
            status_code=503,
            detail="Conversation backup not configured. Set BACKUP_S3_BUCKET environment variable."
        )
    
    try:
        deleted_count = conversation_backup_manager.apply_retention_policy(
            user_id=user_id,
            chat_id=chat_id,
            keep_latest=keep_latest,
            retention_days=retention_days
        )
        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": f"Retention policy applied. Deleted {deleted_count} old backups."
        }
    except Exception as e:
        logger.error(f"Error applying retention policy: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to apply retention policy: {str(e)}")


# A/B Testing Models and Endpoints

class ABTestCreate(BaseModel):
    """Model for creating an A/B test."""
    name: str = Field(..., description="Test name")
    description: Optional[str] = Field(None, description="Test description")
    control: Dict[str, Any] = Field(..., description="Control configuration (model, temperature, system_prompt, etc.)")
    variant: Dict[str, Any] = Field(..., description="Variant configuration")
    traffic_split: float = Field(0.5, description="Fraction of traffic to send to variant (0.0-1.0)", ge=0.0, le=1.0)
    active: bool = Field(True, description="Whether test is active")


class ABTestUpdate(BaseModel):
    """Model for updating an A/B test."""
    name: Optional[str] = None
    description: Optional[str] = None
    control: Optional[Dict[str, Any]] = None
    variant: Optional[Dict[str, Any]] = None
    traffic_split: Optional[float] = Field(None, ge=0.0, le=1.0)
    active: Optional[bool] = None


@app.post("/ab-tests", status_code=201)
async def create_ab_test_endpoint(test: ABTestCreate = Body(...)):
    """
    Create a new A/B test configuration.
    """
    try:
        test_id = conversation_storage.create_ab_test(
            name=test.name,
            description=test.description,
            control=test.control,
            variant=test.variant,
            traffic_split=test.traffic_split,
            active=test.active
        )
        return {
            "success": True,
            "test_id": test_id,
            "message": f"A/B test created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating A/B test: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create A/B test: {str(e)}")


@app.get("/ab-tests")
async def list_ab_tests_endpoint(
    active_only: bool = Query(False, description="Only return active tests")
):
    """
    List A/B tests.
    """
    try:
        tests = conversation_storage.list_ab_tests(active_only=active_only)
        # Parse JSON configs for response
        for test in tests:
            test['control'] = json.loads(test['control_config'])
            test['variant'] = json.loads(test['variant_config'])
            del test['control_config']
            del test['variant_config']
        return {
            "tests": tests,
            "count": len(tests)
        }
    except Exception as e:
        logger.error(f"Error listing A/B tests: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list A/B tests: {str(e)}")


@app.get("/ab-tests/{test_id}")
async def get_ab_test_endpoint(
    test_id: int = Path(..., description="A/B test ID")
):
    """
    Get an A/B test configuration.
    """
    try:
        test = conversation_storage.get_ab_test(test_id)
        if not test:
            raise HTTPException(status_code=404, detail=f"A/B test {test_id} not found")
        
        # Parse JSON configs for response
        test['control'] = json.loads(test['control_config'])
        test['variant'] = json.loads(test['variant_config'])
        del test['control_config']
        del test['variant_config']
        return test
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting A/B test: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get A/B test: {str(e)}")


@app.put("/ab-tests/{test_id}")
async def update_ab_test_endpoint(
    test_id: int = Path(..., description="A/B test ID"),
    update: ABTestUpdate = Body(...)
):
    """
    Update an A/B test configuration.
    """
    try:
        updated = conversation_storage.update_ab_test(
            test_id=test_id,
            name=update.name,
            description=update.description,
            control=update.control,
            variant=update.variant,
            traffic_split=update.traffic_split,
            active=update.active
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"A/B test {test_id} not found")
        return {
            "success": True,
            "message": f"A/B test {test_id} updated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating A/B test: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update A/B test: {str(e)}")


@app.post("/ab-tests/{test_id}/deactivate")
async def deactivate_ab_test_endpoint(
    test_id: int = Path(..., description="A/B test ID")
):
    """
    Deactivate an A/B test.
    """
    try:
        deactivated = conversation_storage.deactivate_ab_test(test_id)
        if not deactivated:
            raise HTTPException(status_code=404, detail=f"A/B test {test_id} not found")
        return {
            "success": True,
            "message": f"A/B test {test_id} deactivated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating A/B test: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to deactivate A/B test: {str(e)}")


@app.get("/ab-tests/{test_id}/metrics")
async def get_ab_test_metrics_endpoint(
    test_id: int = Path(..., description="A/B test ID"),
    variant: Optional[str] = Query(None, description="Filter by variant (control or variant)", pattern="^(control|variant)$")
):
    """
    Get metrics for an A/B test.
    """
    try:
        metrics = conversation_storage.get_ab_metrics(test_id, variant=variant)
        return {
            "metrics": metrics,
            "count": len(metrics)
        }
    except Exception as e:
        logger.error(f"Error getting A/B test metrics: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get A/B test metrics: {str(e)}")


@app.get("/ab-tests/{test_id}/statistics")
async def get_ab_test_statistics_endpoint(
    test_id: int = Path(..., description="A/B test ID")
):
    """
    Get statistical analysis of A/B test results.
    """
    try:
        stats = conversation_storage.get_ab_statistics(test_id)
        return stats
    except Exception as e:
        logger.error(f"Error getting A/B test statistics: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get A/B test statistics: {str(e)}")


# Conversation Template Models and Endpoints

class TemplateCreate(BaseModel):
    """Model for creating a conversation template."""
    user_id: str = Field(..., description="User identifier who owns the template")
    name: str = Field(..., description="Template name", min_length=1)
    description: str = Field("", description="Template description")
    initial_messages: List[Dict[str, str]] = Field(default_factory=list, description="Initial messages to include")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")


class TemplateUpdate(BaseModel):
    """Model for updating a conversation template."""
    name: Optional[str] = Field(None, description="Template name", min_length=1)
    description: Optional[str] = Field(None, description="Template description")
    initial_messages: Optional[List[Dict[str, str]]] = Field(None, description="Initial messages")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Metadata")


class QuickReplyCreate(BaseModel):
    """Model for creating a quick reply."""
    label: str = Field(..., description="Button label text", min_length=1)
    action: str = Field(..., description="Action identifier/command", min_length=1)
    order_index: int = Field(0, description="Display order (lower numbers appear first)")


class QuickReplyUpdate(BaseModel):
    """Model for updating a quick reply."""
    label: Optional[str] = Field(None, description="Button label text", min_length=1)
    action: Optional[str] = Field(None, description="Action identifier/command", min_length=1)
    order_index: Optional[int] = Field(None, description="Display order")


class TemplateApply(BaseModel):
    """Model for applying a template to a conversation."""
    user_id: str = Field(..., description="User identifier")
    chat_id: str = Field(..., description="Chat identifier")
    template_id: int = Field(..., description="Template ID to apply", gt=0)


@app.post("/templates", status_code=201)
async def create_template_endpoint(template: TemplateCreate = Body(...)):
    """Create a conversation template."""
    try:
        template_id = conversation_storage.create_template(
            user_id=template.user_id,
            name=template.name,
            description=template.description,
            initial_messages=template.initial_messages,
            metadata=template.metadata
        )
        return {"template_id": template_id, "success": True}
    except Exception as e:
        logger.error(f"Error creating template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create template: {str(e)}")


@app.get("/templates/{template_id}")
async def get_template_endpoint(template_id: int = Path(..., gt=0)):
    """Get a template by ID, including quick replies."""
    try:
        template = conversation_storage.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return {
            'id': template['id'],
            'user_id': template['user_id'],
            'name': template['name'],
            'description': template['description'],
            'initial_messages': template['initial_messages'],
            'metadata': template['metadata'],
            'created_at': format_datetime(template['created_at']),
            'updated_at': format_datetime(template['updated_at']),
            'quick_replies': [
                {
                    'id': reply['id'],
                    'label': reply['label'],
                    'action': reply['action'],
                    'order_index': reply['order_index'],
                    'created_at': format_datetime(reply['created_at'])
                }
                for reply in template.get('quick_replies', [])
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get template: {str(e)}")


@app.get("/templates")
async def list_templates_endpoint(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    limit: int = Query(100, description="Maximum number of templates", ge=1, le=1000)
):
    """List conversation templates, optionally filtered by user."""
    try:
        templates = conversation_storage.list_templates(user_id=user_id, limit=limit)
        
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return [
            {
                'id': t['id'],
                'user_id': t['user_id'],
                'name': t['name'],
                'description': t['description'],
                'initial_messages': t['initial_messages'],
                'metadata': t['metadata'],
                'created_at': format_datetime(t['created_at']),
                'updated_at': format_datetime(t['updated_at'])
            }
            for t in templates
        ]
    except Exception as e:
        logger.error(f"Error listing templates: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list templates: {str(e)}")


@app.put("/templates/{template_id}")
async def update_template_endpoint(
    template_id: int = Path(..., gt=0),
    template: TemplateUpdate = Body(...)
):
    """Update a conversation template."""
    try:
        updated = conversation_storage.update_template(
            template_id=template_id,
            name=template.name,
            description=template.description,
            initial_messages=template.initial_messages,
            metadata=template.metadata
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        return {"success": True, "message": f"Template {template_id} updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update template: {str(e)}")


@app.delete("/templates/{template_id}")
async def delete_template_endpoint(template_id: int = Path(..., gt=0)):
    """Delete a conversation template (and its quick replies)."""
    try:
        deleted = conversation_storage.delete_template(template_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        return {"success": True, "message": f"Template {template_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete template: {str(e)}")


@app.post("/templates/{template_id}/quick-replies", status_code=201)
async def add_quick_reply_endpoint(
    template_id: int = Path(..., gt=0),
    reply: QuickReplyCreate = Body(...)
):
    """Add a quick reply button to a template."""
    try:
        # Verify template exists
        template = conversation_storage.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        
        reply_id = conversation_storage.add_quick_reply(
            template_id=template_id,
            label=reply.label,
            action=reply.action,
            order_index=reply.order_index
        )
        return {"reply_id": reply_id, "success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding quick reply: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add quick reply: {str(e)}")


@app.put("/quick-replies/{reply_id}")
async def update_quick_reply_endpoint(
    reply_id: int = Path(..., gt=0),
    reply: QuickReplyUpdate = Body(...)
):
    """Update a quick reply."""
    try:
        updated = conversation_storage.update_quick_reply(
            reply_id=reply_id,
            label=reply.label,
            action=reply.action,
            order_index=reply.order_index
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Quick reply {reply_id} not found")
        return {"success": True, "message": f"Quick reply {reply_id} updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating quick reply: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update quick reply: {str(e)}")


@app.delete("/quick-replies/{reply_id}")
async def delete_quick_reply_endpoint(reply_id: int = Path(..., gt=0)):
    """Delete a quick reply."""
    try:
        deleted = conversation_storage.delete_quick_reply(reply_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Quick reply {reply_id} not found")
        return {"success": True, "message": f"Quick reply {reply_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting quick reply: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete quick reply: {str(e)}")


@app.post("/conversations/apply-template")
async def apply_template_endpoint(apply_data: TemplateApply = Body(...)):
    """Apply a template to start a conversation."""
    try:
        conversation_id = conversation_storage.apply_template(
            user_id=apply_data.user_id,
            chat_id=apply_data.chat_id,
            template_id=apply_data.template_id
        )
        return {"conversation_id": conversation_id, "success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error applying template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to apply template: {str(e)}")


# ===== Prompt Template Endpoints =====

class PromptTemplateCreate(BaseModel):
    user_id: str = Field(..., description="User identifier")
    template_name: str = Field(..., description="Template name")
    template_content: str = Field(..., description="Template content")
    template_type: str = Field("summarization", description="Template type (default: summarization)")
    conversation_id: Optional[int] = Field(None, description="Optional conversation ID for per-conversation templates")


class PromptTemplateUpdate(BaseModel):
    template_name: Optional[str] = Field(None, description="New template name")
    template_content: Optional[str] = Field(None, description="New template content")


@app.post("/prompt-templates", status_code=201)
async def create_prompt_template_endpoint(template_data: PromptTemplateCreate = Body(...)):
    """
    Create a new prompt template.
    
    Supports per-user and per-conversation templates.
    Templates are validated for syntax before creation.
    """
    try:
        template_id = conversation_storage.create_prompt_template(
            user_id=template_data.user_id,
            template_name=template_data.template_name,
            template_content=template_data.template_content,
            template_type=template_data.template_type,
            conversation_id=template_data.conversation_id
        )
        return {
            "template_id": template_id,
            "success": True,
            "message": "Prompt template created successfully"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating prompt template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create prompt template: {str(e)}")


@app.get("/prompt-templates/{template_id}")
async def get_prompt_template_endpoint(
    template_id: int = Path(..., description="Template ID")
):
    """Get a prompt template by ID."""
    try:
        template = conversation_storage.get_prompt_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        return template
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting prompt template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get prompt template: {str(e)}")


@app.get("/prompt-templates")
async def list_prompt_templates_endpoint(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    template_type: Optional[str] = Query(None, description="Filter by template type")
):
    """List prompt templates."""
    try:
        templates = conversation_storage.list_prompt_templates(
            user_id=user_id,
            template_type=template_type
        )
        return {
            "templates": templates,
            "count": len(templates)
        }
    except Exception as e:
        logger.error(f"Error listing prompt templates: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list prompt templates: {str(e)}")


@app.get("/prompt-templates/user/{user_id}")
async def get_user_prompt_template_endpoint(
    user_id: str = Path(..., description="User ID"),
    template_type: str = Query("summarization", description="Template type")
):
    """Get prompt template for a user."""
    try:
        template = conversation_storage.get_prompt_template_for_user(user_id, template_type)
        if not template:
            raise HTTPException(
                status_code=404,
                detail=f"No prompt template found for user {user_id} with type {template_type}"
            )
        return template
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user prompt template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get user prompt template: {str(e)}")


@app.get("/prompt-templates/conversation/{user_id}/{chat_id}")
async def get_conversation_prompt_template_endpoint(
    user_id: str = Path(..., description="User ID"),
    chat_id: str = Path(..., description="Chat ID"),
    template_type: str = Query("summarization", description="Template type")
):
    """Get prompt template for a conversation. Falls back to user template if no conversation-specific template exists."""
    try:
        template = conversation_storage.get_prompt_template_for_conversation(
            user_id, chat_id, template_type
        )
        if not template:
            raise HTTPException(
                status_code=404,
                detail=f"No prompt template found for conversation {user_id}/{chat_id} with type {template_type}"
            )
        return template
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation prompt template: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get conversation prompt template: {str(e)}"
        )


@app.put("/prompt-templates/{template_id}")
async def update_prompt_template_endpoint(
    template_id: int = Path(..., description="Template ID"),
    update_data: PromptTemplateUpdate = Body(...)
):
    """Update a prompt template."""
    try:
        updated = conversation_storage.update_prompt_template(
            template_id,
            template_name=update_data.template_name,
            template_content=update_data.template_content
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        return {
            "success": True,
            "message": "Prompt template updated successfully"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating prompt template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update prompt template: {str(e)}")


@app.delete("/prompt-templates/{template_id}")
async def delete_prompt_template_endpoint(
    template_id: int = Path(..., description="Template ID")
):
    """Delete a prompt template."""
    try:
        deleted = conversation_storage.delete_prompt_template(template_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        return {
            "success": True,
            "message": "Prompt template deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting prompt template: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete prompt template: {str(e)}")


# ===== Conversation Analytics Endpoints =====

@app.get("/conversations/analytics/metrics")
async def get_conversation_analytics_metrics(
    user_id: Optional[str] = Query(None, description="User ID"),
    chat_id: Optional[str] = Query(None, description="Chat ID")
):
    """
    Get analytics metrics for a conversation.
    
    Returns:
    - message_count: Total number of messages
    - total_tokens: Total tokens used
    - average_response_time_seconds: Average response time
    - user_engagement_score: Engagement score
    - conversation_duration_seconds: Total conversation duration
    """
    try:
        if not user_id or not chat_id:
            raise HTTPException(
                status_code=400,
                detail="Both user_id and chat_id are required"
            )
        
        analytics = conversation_storage.get_conversation_analytics(user_id, chat_id)
        if not analytics:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation not found for user {user_id}, chat {chat_id}"
            )
        
        return analytics
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation analytics: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get conversation analytics: {str(e)}"
        )


@app.get("/conversations/analytics/dashboard")
async def get_conversation_analytics_dashboard(
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
    user_id: Optional[str] = Query(None, description="Filter by user ID")
):
    """
    Get dashboard analytics aggregating data across conversations.
    
    Returns:
    - total_conversations: Total number of conversations
    - active_users: Number of unique users
    - total_messages: Total messages across all conversations
    - average_response_time: Average response time
    - engagement_metrics: User engagement statistics
    """
    try:
        # Parse dates if provided
        parsed_start_date = None
        parsed_end_date = None
        
        if start_date:
            try:
                parsed_start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except:
                try:
                    from dateutil.parser import parse
                    parsed_start_date = parse(start_date)
                except:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid start_date format. Use ISO format (e.g., 2024-01-01T00:00:00)"
                    )
        
        if end_date:
            try:
                parsed_end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except:
                try:
                    from dateutil.parser import parse
                    parsed_end_date = parse(end_date)
                except:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid end_date format. Use ISO format (e.g., 2024-01-01T00:00:00)"
                    )
        
        dashboard = conversation_storage.get_dashboard_analytics(
            start_date=parsed_start_date,
            end_date=parsed_end_date,
            user_id=user_id
        )
        
        return dashboard
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting dashboard analytics: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get dashboard analytics: {str(e)}"
        )


@app.get("/conversations/analytics/report")
async def generate_conversation_analytics_report(
    format: str = Query("json", description="Report format: json or csv"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
    user_id: Optional[str] = Query(None, description="Filter by user ID")
):
    """
    Generate analytics report in JSON or CSV format.
    
    Returns comprehensive analytics report with dashboard summary and conversation details.
    """
    try:
        if format not in ["json", "csv"]:
            raise HTTPException(
                status_code=400,
                detail="Format must be 'json' or 'csv'"
            )
        
        # Parse dates if provided
        parsed_start_date = None
        parsed_end_date = None
        
        if start_date:
            try:
                parsed_start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except:
                try:
                    from dateutil.parser import parse
                    parsed_start_date = parse(start_date)
                except:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid start_date format. Use ISO format"
                    )
        
        if end_date:
            try:
                parsed_end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except:
                try:
                    from dateutil.parser import parse
                    parsed_end_date = parse(end_date)
                except:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid end_date format. Use ISO format"
                    )
        
        report = conversation_storage.generate_analytics_report(
            format=format,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
            user_id=user_id
        )
        
        if format == "csv":
            from fastapi.responses import Response
            return Response(
                content=report,
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": "attachment; filename=conversation_analytics_report.csv"}
            )
        else:
            return report
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating analytics report: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate analytics report: {str(e)}"
        )


# Webhook endpoints
class WebhookCreate(BaseModel):
    """Webhook creation model."""
    url: str = Field(..., description="Webhook URL", min_length=1)
    events: List[str] = Field(..., description="List of events to subscribe to")
    secret: Optional[str] = Field(None, description="Optional secret for HMAC signature")
    enabled: Optional[bool] = Field(True, description="Whether webhook is enabled")
    retry_count: Optional[int] = Field(3, description="Number of retry attempts", ge=1, le=10)
    timeout_seconds: Optional[int] = Field(10, description="Request timeout in seconds", ge=1, le=60)
    
    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format."""
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")
        v = v.strip()
        if not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError("URL must start with http:// or https://")
        return v
    
    @field_validator('events')
    @classmethod
    def validate_events(cls, v: List[str]) -> List[str]:
        """Validate event types."""
        valid_events = ["task.created", "task.completed", "task.status_changed"]
        if not v:
            raise ValueError("At least one event must be specified")
        for event in v:
            if event not in valid_events:
                raise ValueError(f"Invalid event '{event}'. Must be one of: {', '.join(valid_events)}")
        return v


class WebhookResponse(BaseModel):
    """Webhook response model."""
    id: int


# API Key Models

class APIKeyCreate(BaseModel):
    """API key creation request model."""
    name: str = Field(..., min_length=1, description="User-friendly name for the API key")


class APIKeyResponse(BaseModel):
    """API key response model."""
    key_id: int
    project_id: int
    name: str
    key_prefix: str
    api_key: Optional[str] = None  # Only present when creating
    enabled: int
    created_at: str
    updated_at: str
    last_used_at: Optional[str] = None


@app.post("/projects/{project_id}/webhooks", response_model=WebhookResponse, status_code=201)
async def create_webhook(project_id: int = Path(..., gt=0), webhook: WebhookCreate = Body(...)):
    """Create a webhook for a project."""
    # Verify project exists
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    try:
        webhook_id = db.create_webhook(
            project_id=project_id,
            url=webhook.url,
            events=webhook.events,
            secret=webhook.secret,
            enabled=webhook.enabled if webhook.enabled is not None else True,
            retry_count=webhook.retry_count if webhook.retry_count is not None else 3,
            timeout_seconds=webhook.timeout_seconds if webhook.timeout_seconds is not None else 10
        )
        
        created_webhook = db.get_webhook(webhook_id)
        if not created_webhook:
            raise HTTPException(status_code=500, detail="Failed to retrieve created webhook")
        
        return WebhookResponse(**created_webhook)
    except Exception as e:
        logger.error(f"Failed to create webhook: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create webhook: {str(e)}")


@app.get("/projects/{project_id}/webhooks")
async def list_webhooks(project_id: int = Path(..., gt=0)):
    """List webhooks for a project."""
    # Verify project exists
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    webhooks = db.list_webhooks(project_id=project_id)
    return {"project_id": project_id, "webhooks": [WebhookResponse(**w) for w in webhooks]}


@app.get("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(webhook_id: int = Path(..., gt=0)):
    """Get a webhook by ID."""
    webhook = db.get_webhook(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail=f"Webhook {webhook_id} not found")
    return WebhookResponse(**webhook)


@app.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: int = Path(..., gt=0)):
    """Delete a webhook."""
    webhook = db.get_webhook(webhook_id)
    if not webhook:
        raise HTTPException(status_code=404, detail=f"Webhook {webhook_id} not found")
    
    db.delete_webhook(webhook_id)
    return {"message": f"Webhook {webhook_id} deleted", "webhook_id": webhook_id}


# User Authentication and Management Models

class UserRegister(BaseModel):
    """User registration model."""
    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    email: str = Field(..., description="Unique email address")
    password: str = Field(..., min_length=8, description="Password (minimum 8 characters)")


class UserLogin(BaseModel):
    """User login model."""
    username: str = Field(..., description="Username or email")
    password: str = Field(..., description="Password")


class UserResponse(BaseModel):
    """User response model."""
    id: int
    username: str
    email: str
    created_at: str
    updated_at: str
    last_login_at: Optional[str] = None


class LoginResponse(BaseModel):
    """Login response model."""
    session_token: str
    user_id: int
    username: str
    expires_at: str


class UserUpdate(BaseModel):
    """User update model."""
    username: Optional[str] = Field(None, min_length=3, max_length=50, description="New username")
    email: Optional[str] = Field(None, description="New email address")


# User Authentication and Management Endpoints

@app.post("/users/register", response_model=UserResponse, status_code=201)
async def register_user(user_data: UserRegister = Body(...)):
    """Register a new user account."""
    try:
        user_id = db.create_user(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password
        )
        user = db.get_user_by_id(user_id)
        
        return UserResponse(
            id=user["id"],
            username=user["username"],
            email=user["email"],
            created_at=user["created_at"],
            updated_at=user["updated_at"],
            last_login_at=user.get("last_login_at")
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Error registering user: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to register user")


@app.post("/users/login", response_model=LoginResponse)
async def login_user(login_data: UserLogin = Body(...)):
    """Login user and create session."""
    user = db.authenticate_user(login_data.username, login_data.password)
    
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid username/email or password"
        )
    
    # Create session (24 hour expiration)
    session_token, expires_at = db.create_session(user["id"], expires_hours=24)
    
    return LoginResponse(
        session_token=session_token,
        user_id=user["id"],
        username=user["username"],
        expires_at=expires_at.isoformat()
    )


@app.post("/users/logout")
async def logout_user(auth: Dict[str, Any] = Depends(verify_session_token)):
    """Logout user (delete session)."""
    session_token = auth.get("session_token")
    if session_token:
        db.delete_session(session_token)
    return {"message": "Logged out successfully"}


@app.get("/users/me", response_model=UserResponse)
async def get_current_user(auth: Dict[str, Any] = Depends(verify_session_token)):
    """Get current authenticated user."""
    user = db.get_user_by_id(auth["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return UserResponse(
        id=user["id"],
        username=user["username"],
        email=user["email"],
        created_at=user["created_at"],
        updated_at=user["updated_at"],
        last_login_at=user.get("last_login_at")
    )


@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int = Path(..., gt=0)):
    """Get user by ID."""
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    
    return UserResponse(
        id=user["id"],
        username=user["username"],
        email=user["email"],
        created_at=user["created_at"],
        updated_at=user["updated_at"],
        last_login_at=user.get("last_login_at")
    )


@app.get("/users", response_model=List[UserResponse])
async def list_users(
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of users"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """List all users."""
    users = db.list_users(limit=limit, offset=offset)
    return [
        UserResponse(
            id=user["id"],
            username=user["username"],
            email=user["email"],
            created_at=user["created_at"],
            updated_at=user["updated_at"],
            last_login_at=user.get("last_login_at")
        )
        for user in users
    ]


@app.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int = Path(..., gt=0),
    user_data: UserUpdate = Body(...),
    auth: Dict[str, Any] = Depends(verify_session_token)
):
    """Update user information (requires authentication as that user)."""
    # Verify user is updating their own account
    if auth["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Can only update your own account")
    
    try:
        db.update_user(
            user_id=user_id,
            username=user_data.username,
            email=user_data.email
        )
        
        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        
        return UserResponse(
            id=user["id"],
            username=user["username"],
            email=user["email"],
            created_at=user["created_at"],
            updated_at=user["updated_at"],
            last_login_at=user.get("last_login_at")
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.delete("/users/{user_id}")
async def delete_user(
    user_id: int = Path(..., gt=0),
    auth: Dict[str, Any] = Depends(verify_session_token)
):
    """Delete user account (requires authentication as that user)."""
    # Verify user is deleting their own account
    if auth["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Can only delete your own account")
    
    if not db.delete_user(user_id):
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    
    return {"message": f"User {user_id} deleted successfully"}


# API Key Management Endpoints

@app.post("/projects/{project_id}/api-keys", response_model=APIKeyResponse, status_code=201)
async def create_api_key(
    project_id: int = Path(..., gt=0, description="Project ID"),
    key_data: APIKeyCreate = Body(...)
):
    """Create a new API key for a project."""
    # Verify project exists
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    try:
        key_id, full_key = db.create_api_key(project_id, key_data.name)
        key_info = db.get_api_key_by_hash(db._hash_api_key(full_key))
        
        return APIKeyResponse(
            key_id=key_id,
            project_id=key_info["project_id"],
            name=key_info["name"],
            key_prefix=key_info["key_prefix"],
            api_key=full_key,  # Only returned on creation
            enabled=key_info["enabled"],
            created_at=key_info["created_at"],
            updated_at=key_info["updated_at"],
            last_used_at=key_info["last_used_at"]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/projects/{project_id}/api-keys", response_model=List[APIKeyResponse])
async def list_api_keys(project_id: int = Path(..., gt=0, description="Project ID")):
    """List all API keys for a project."""
    # Verify project exists
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    keys = db.list_api_keys(project_id)
    return [APIKeyResponse(**key) for key in keys]


@app.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: int = Path(..., gt=0, description="API key ID")):
    """Revoke (disable) an API key."""
    success = db.revoke_api_key(key_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"API key {key_id} not found")
    return {"success": True, "message": f"API key {key_id} revoked"}


@app.post("/api-keys/{key_id}/rotate", response_model=APIKeyResponse)
async def rotate_api_key(key_id: int = Path(..., gt=0, description="API key ID")):
    """Rotate an API key (creates new key, revokes old)."""
    try:
        new_key_id, new_key = db.rotate_api_key(key_id)
        key_info = db.get_api_key_by_hash(db._hash_api_key(new_key))
        
        return APIKeyResponse(
            key_id=new_key_id,
            project_id=key_info["project_id"],
            name=key_info["name"],
            key_prefix=key_info["key_prefix"],
            api_key=new_key,  # Only returned on creation
            enabled=key_info["enabled"],
            created_at=key_info["created_at"],
            updated_at=key_info["updated_at"],
            last_used_at=key_info["last_used_at"]
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# Admin Endpoints

def get_client_ip(request: Request) -> Optional[str]:
    """Get client IP address from request."""
    # Check X-Forwarded-For header (for proxies/load balancers)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one
        return forwarded_for.split(",")[0].strip()
    
    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fall back to direct client IP
    if request.client:
        return request.client.host
    
    return None


@app.post("/admin/agents/block")
async def block_agent(
    request: Request,
    agent_block: dict = Body(...),
    auth: Dict[str, Any] = Depends(verify_admin_api_key)
):
    """
    Block an agent from using the service.
    
    Requires admin API key.
    """
    agent_id = agent_block.get("agent_id")
    reason = agent_block.get("reason")
    
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    
    # Get API key name for audit log
    key_info = db.get_api_key_by_hash(db._hash_api_key(request.headers.get("X-API-Key", "")))
    actor_name = key_info.get("name", "unknown") if key_info else "unknown"
    
    # Block the agent
    success = db.block_agent(agent_id, reason, actor_name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to block agent")
    
    # Log audit event
    client_ip = get_client_ip(request)
    db.add_audit_log(
        action="agent.blocked",
        actor=actor_name,
        actor_type="api_key",
        target_type="agent",
        target_id=agent_id,
        details=json.dumps({"reason": reason}) if reason else None,
        ip_address=client_ip
    )
    
    return {
        "blocked": True,
        "agent_id": agent_id,
        "message": f"Agent {agent_id} has been blocked"
    }


@app.post("/admin/agents/unblock")
async def unblock_agent(
    request: Request,
    agent_unblock: dict = Body(...),
    auth: Dict[str, Any] = Depends(verify_admin_api_key)
):
    """
    Unblock an agent.
    
    Requires admin API key.
    """
    agent_id = agent_unblock.get("agent_id")
    
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    
    # Get API key name for audit log
    key_info = db.get_api_key_by_hash(db._hash_api_key(request.headers.get("X-API-Key", "")))
    actor_name = key_info.get("name", "unknown") if key_info else "unknown"
    
    # Unblock the agent
    success = db.unblock_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} is not blocked")
    
    # Log audit event
    client_ip = get_client_ip(request)
    db.add_audit_log(
        action="agent.unblocked",
        actor=actor_name,
        actor_type="api_key",
        target_type="agent",
        target_id=agent_id,
        ip_address=client_ip
    )
    
    return {
        "blocked": False,
        "agent_id": agent_id,
        "message": f"Agent {agent_id} has been unblocked"
    }


@app.get("/admin/agents/{agent_id}")
async def get_agent_status(
    agent_id: str = Path(...),
    auth: Dict[str, Any] = Depends(verify_admin_api_key)
):
    """
    Get agent block status.
    
    Requires admin API key.
    """
    status = db.get_agent_block_status(agent_id)
    if status:
        return status
    return {
        "agent_id": agent_id,
        "blocked": False
    }


@app.get("/admin/agents/blocked")
async def list_blocked_agents(
    auth: Dict[str, Any] = Depends(verify_admin_api_key)
):
    """
    List all currently blocked agents.
    
    Requires admin API key.
    """
    agents = db.list_blocked_agents()
    return agents


@app.post("/admin/conversations/clear")
async def clear_conversation(
    request: Request,
    conversation_data: dict = Body(...),
    auth: Dict[str, Any] = Depends(verify_admin_api_key)
):
    """
    Clear a conversation for a user/chat.
    
    Requires admin API key.
    """
    user_id = conversation_data.get("user_id")
    chat_id = conversation_data.get("chat_id")
    
    if not user_id or not chat_id:
        raise HTTPException(status_code=400, detail="user_id and chat_id are required")
    
    # Get API key name for audit log
    key_info = db.get_api_key_by_hash(db._hash_api_key(request.headers.get("X-API-Key", "")))
    actor_name = key_info.get("name", "unknown") if key_info else "unknown"
    
    # Clear conversation if conversation_storage is available
    try:
        if conversation_storage and hasattr(conversation_storage, 'clear_conversation'):
            success = conversation_storage.clear_conversation(user_id, chat_id)
            if not success:
                raise HTTPException(status_code=404, detail=f"Conversation {user_id}/{chat_id} not found")
        else:
            raise HTTPException(status_code=503, detail="Conversation storage not available")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clear conversation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to clear conversation: {str(e)}")
    
    # Log audit event
    client_ip = get_client_ip(request)
    db.add_audit_log(
        action="conversation.cleared",
        actor=actor_name,
        actor_type="api_key",
        target_type="conversation",
        target_id=f"{user_id}/{chat_id}",
        ip_address=client_ip
    )
    
    return {
        "cleared": True,
        "user_id": user_id,
        "chat_id": chat_id,
        "message": f"Conversation {user_id}/{chat_id} has been cleared"
    }


@app.get("/admin/status")
async def get_admin_status(
    auth: Dict[str, Any] = Depends(verify_admin_api_key)
):
    """
    Get system status information.
    
    Requires admin API key.
    """
    status = db.get_system_status()
    return status


@app.get("/admin/audit-logs")
async def get_audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    action: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    auth: Dict[str, Any] = Depends(verify_admin_api_key)
):
    """
    Get audit logs for admin actions.
    
    Requires admin API key.
    """
    logs = db.get_audit_logs(limit=limit, action=action, actor=actor)
    return logs


# Slack Integration Endpoints

@app.post("/slack/events")
async def slack_events(request: Request):
    """
    Handle Slack Events API.
    Supports URL verification challenge and event callbacks.
    """
    signing_secret = os.getenv("SLACK_SIGNING_SECRET")
    if not signing_secret:
        raise HTTPException(
            status_code=500,
            detail="SLACK_SIGNING_SECRET not configured"
        )
    
    # Get request body
    body_bytes = await request.body()
    body_str = body_bytes.decode('utf-8')
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    
    # Verify signature
    if not verify_slack_signature(signing_secret, timestamp, signature, body_str):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")
    
    # Parse JSON body
    try:
        event_data = json.loads(body_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    # Handle URL verification challenge
    if event_data.get("type") == "url_verification":
        challenge = event_data.get("challenge")
        if challenge:
            return {"challenge": challenge}
        raise HTTPException(status_code=400, detail="Missing challenge in verification request")
    
    # Handle event callbacks
    if event_data.get("type") == "event_callback":
        event = event_data.get("event", {})
        event_type = event.get("type")
        
        # Log event (can be extended to handle specific events)
        logger.info(f"Received Slack event: {event_type}")
        
        # Return 200 OK immediately (Slack requires response within 3 seconds)
        return {"ok": True}
    
    return {"ok": True}


@app.post("/slack/commands")
async def slack_commands(request: Request):
    """
    Handle Slack slash commands.
    Commands:
    - /todo list - List available tasks
    - /todo reserve <task_id> - Reserve a task
    - /todo complete <task_id> [notes] - Complete a task
    - /todo help - Show help
    """
    signing_secret = os.getenv("SLACK_SIGNING_SECRET")
    if not signing_secret:
        raise HTTPException(
            status_code=500,
            detail="SLACK_SIGNING_SECRET not configured"
        )
    
    # Get form data
    form_data = await request.form()
    body_dict = dict(form_data)
    
    # Reconstruct body string for signature verification
    body_str = "&".join([f"{k}={v}" for k, v in body_dict.items()])
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    
    # Verify signature
    if not verify_slack_signature(signing_secret, timestamp, signature, body_str):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")
    
    command = body_dict.get("command", "")
    text = body_dict.get("text", "").strip()
    user_id = body_dict.get("user_id", "")
    channel_id = body_dict.get("channel_id", "")
    response_url = body_dict.get("response_url", "")
    
    # Map Slack user_id to agent_id
    agent_id = f"slack-{user_id}"
    
    try:
        if command == "/todo":
            parts = text.split(None, 1) if text else []
            action = parts[0].lower() if parts else "help"
            
            if action == "list" or action == "ls":
                # List available tasks
                tasks = db.query_tasks(
                    task_status="available",
                    limit=10
                )
                
                if not tasks:
                    return {
                        "response_type": "ephemeral",
                        "text": "No available tasks found."
                    }
                
                blocks = [{
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"?? Available Tasks ({len(tasks)})"
                    }
                }]
                
                for task in tasks:
                    task_id = task.get("id")
                    title = task.get("title", "Untitled")
                    task_type = task.get("task_type", "concrete")
                    
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{title}* (ID: {task_id}, Type: {task_type})"
                        },
                        "accessory": {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Reserve"
                            },
                            "style": "primary",
                            "action_id": "reserve_task",
                            "value": str(task_id)
                        }
                    })
                
                return {
                    "response_type": "in_channel",
                    "blocks": blocks
                }
            
            elif action == "reserve":
                if len(parts) < 2:
                    return {
                        "response_type": "ephemeral",
                        "text": "Usage: /todo reserve <task_id>"
                    }
                
                try:
                    task_id = int(parts[1])
                except ValueError:
                    return {
                        "response_type": "ephemeral",
                        "text": f"Invalid task ID: {parts[1]}"
                    }
                
                # Lock/reserve task
                task = db.get_task(task_id)
                if not task:
                    return {
                        "response_type": "ephemeral",
                        "text": f"Task {task_id} not found"
                    }
                
                if task.get("task_status") != "available":
                    return {
                        "response_type": "ephemeral",
                        "text": f"Task {task_id} is not available (status: {task.get('task_status')})"
                    }
                
                db.lock_task(task_id, agent_id)
                updated_task = db.get_task(task_id)
                
                return {
                    "response_type": "in_channel",
                    "text": f"? Task {task_id} reserved by <@{user_id}>",
                    "blocks": [{
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"? *Task Reserved*\n*{updated_task.get('title')}* (ID: {task_id})\nReserved by: <@{user_id}>"
                        }
                    }]
                }
            
            elif action == "complete":
                if len(parts) < 2:
                    return {
                        "response_type": "ephemeral",
                        "text": "Usage: /todo complete <task_id> [notes]"
                    }
                
                try:
                    task_id = int(parts[1])
                except ValueError:
                    return {
                        "response_type": "ephemeral",
                        "text": f"Invalid task ID: {parts[1]}"
                    }
                
                notes = parts[2] if len(parts) > 2 else None
                
                # Complete task
                task = db.get_task(task_id)
                if not task:
                    return {
                        "response_type": "ephemeral",
                        "text": f"Task {task_id} not found"
                    }
                
                if task.get("task_status") == "complete":
                    return {
                        "response_type": "ephemeral",
                        "text": f"Task {task_id} is already complete"
                    }
                
                db.complete_task(task_id, agent_id, notes=notes)
                updated_task = db.get_task(task_id)
                
                return {
                    "response_type": "in_channel",
                    "text": f"? Task {task_id} completed by <@{user_id}>",
                    "blocks": [{
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"? *Task Completed*\n*{updated_task.get('title')}* (ID: {task_id})\nCompleted by: <@{user_id}>\n" + (f"Notes: {notes}" if notes else "")
                        }
                    }]
                }
            
            else:
                # Show help
                return {
                    "response_type": "ephemeral",
                    "text": "TODO Service Slack Commands",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "*Available Commands:*\n\n? `/todo list` - List available tasks\n? `/todo reserve <task_id>` - Reserve a task\n? `/todo complete <task_id> [notes]` - Complete a task\n? `/todo help` - Show this help"
                            }
                        }
                    ]
                }
        else:
            return {
                "response_type": "ephemeral",
                "text": f"Unknown command: {command}"
            }
    
    except Exception as e:
        logger.error(f"Error handling Slack command: {str(e)}", exc_info=True)
        return {
            "response_type": "ephemeral",
            "text": f"Error: {str(e)}"
        }


@app.post("/slack/interactive")
async def slack_interactive(request: Request):
    """
    Handle Slack interactive components (buttons, etc.).
    """
    signing_secret = os.getenv("SLACK_SIGNING_SECRET")
    if not signing_secret:
        raise HTTPException(
            status_code=500,
            detail="SLACK_SIGNING_SECRET not configured"
        )
    
    # Get form data
    form_data = await request.form()
    payload_str = form_data.get("payload", "{}")
    
    # Reconstruct body string for signature verification
    body_str = f"payload={payload_str}"
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    
    # Verify signature
    if not verify_slack_signature(signing_secret, timestamp, signature, body_str):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")
    
    # Parse payload
    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid payload JSON")
    
    payload_type = payload.get("type")
    user_id = payload.get("user", {}).get("id", "")
    agent_id = f"slack-{user_id}"
    
    try:
        if payload_type == "block_actions":
            actions = payload.get("actions", [])
            response_url = payload.get("response_url", "")
            
            for action in actions:
                action_id = action.get("action_id")
                action_value = action.get("value")
                
                if action_id == "reserve_task":
                    try:
                        task_id = int(action_value)
                    except ValueError:
                        return {
                            "response_type": "ephemeral",
                            "text": f"Invalid task ID: {action_value}"
                        }
                    
                    task = db.get_task(task_id)
                    if not task:
                        return {
                            "response_type": "ephemeral",
                            "text": f"Task {task_id} not found"
                        }
                    
                    if task.get("task_status") != "available":
                        return {
                            "response_type": "ephemeral",
                            "text": f"Task {task_id} is not available"
                        }
                    
                    db.lock_task(task_id, agent_id)
                    updated_task = db.get_task(task_id)
                    
                    return {
                        "response_type": "in_channel",
                        "replace_original": True,
                        "text": f"? Task {task_id} reserved by <@{user_id}>",
                        "blocks": [{
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"? *Task Reserved*\n*{updated_task.get('title')}* (ID: {task_id})\nReserved by: <@{user_id}>"
                            }
                        }]
                    }
        
        return {"ok": True}
    
    except Exception as e:
        logger.error(f"Error handling Slack interactive: {str(e)}", exc_info=True)
        return {
            "response_type": "ephemeral",
            "text": f"Error: {str(e)}"
        }


# Job Queue Endpoints

class JobSubmitRequest(BaseModel):
    """Request model for job submission."""
    job_type: str = Field(..., description="Job type (backup, webhook, bulk_import, etc.)")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Job parameters")
    priority: str = Field(default="medium", description="Job priority (low, medium, high, critical)")
    timeout: Optional[int] = Field(default=None, description="Job timeout in seconds")
    delay: int = Field(default=0, description="Delay before processing (seconds)")


class JobSubmitResponse(BaseModel):
    """Response model for job submission."""
    job_id: str = Field(..., description="Job identifier")
    status: str = Field(..., description="Initial job status")


class JobStatusResponse(BaseModel):
    """Response model for job status."""
    job_id: str = Field(..., description="Job identifier")
    status: str = Field(..., description="Current job status")
    job_type: str = Field(..., description="Job type")
    created_at: str = Field(..., description="Job creation timestamp")
    started_at: Optional[str] = Field(default=None, description="Job start timestamp")
    completed_at: Optional[str] = Field(default=None, description="Job completion timestamp")
    result: Optional[Dict[str, Any]] = Field(default=None, description="Job result (if complete)")
    error: Optional[str] = Field(default=None, description="Error message (if failed)")
    retry_count: int = Field(default=0, description="Number of retry attempts")


@app.post("/jobs", response_model=JobSubmitResponse, status_code=201)
async def submit_job(
    request: JobSubmitRequest,
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """
    Submit a job to the background job queue.
    
    Supported job types:
    - backup: Create a database backup
    - webhook: Deliver a webhook
    - bulk_import: Bulk import tasks
    - bulk_export: Bulk export tasks
    - cleanup: Cleanup old data
    - notification: Send notification
    """
    if not job_queue:
        raise HTTPException(
            status_code=503,
            detail="Job queue not available. Redis connection required."
        )
    
    try:
        # Map string job type to enum
        job_type_map = {
            "backup": JobType.BACKUP,
            "webhook": JobType.WEBHOOK,
            "bulk_import": JobType.BULK_IMPORT,
            "bulk_export": JobType.BULK_EXPORT,
            "cleanup": JobType.CLEANUP,
            "notification": JobType.NOTIFICATION
        }
        
        if request.job_type not in job_type_map:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid job type: {request.job_type}. Valid types: {list(job_type_map.keys())}"
            )
        
        # Map priority string to enum
        priority_map = {
            "low": JobPriority.LOW,
            "medium": JobPriority.MEDIUM,
            "high": JobPriority.HIGH,
            "critical": JobPriority.CRITICAL
        }
        
        priority = priority_map.get(request.priority, JobPriority.MEDIUM)
        
        # Submit job
        job_id = job_queue.submit_job(
            job_type=job_type_map[request.job_type],
            parameters=request.parameters,
            priority=priority,
            timeout=request.timeout,
            delay=request.delay
        )
        
        logger.info(f"Job submitted: {job_id} (type={request.job_type}, priority={request.priority})")
        
        return JobSubmitResponse(
            job_id=job_id,
            status=JobStatus.PENDING.value
        )
    except Exception as e:
        logger.error(f"Failed to submit job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str = Path(..., description="Job identifier"),
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """Get status of a job."""
    if not job_queue:
        raise HTTPException(
            status_code=503,
            detail="Job queue not available. Redis connection required."
        )
    
    try:
        status = job_queue.get_job_status(job_id)
        
        if not status:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        return JobStatusResponse(
            job_id=job_id,
            status=status.get("status", "unknown"),
            job_type=status.get("job_type", "unknown"),
            created_at=status.get("created_at", ""),
            started_at=status.get("started_at"),
            completed_at=status.get("completed_at"),
            result=status.get("result"),
            error=status.get("error"),
            retry_count=int(status.get("retry_count", "0"))
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")


@app.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: str = Path(..., description="Job identifier"),
    auth: Dict[str, Any] = Depends(verify_api_key)
):
    """Cancel a pending or processing job."""
    if not job_queue:
        raise HTTPException(
            status_code=503,
            detail="Job queue not available. Redis connection required."
        )
    
    try:
        cancelled = job_queue.cancel_job(job_id)
        
        if not cancelled:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found or cannot be cancelled")
        
        return {"success": True, "message": f"Job {job_id} cancelled"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")


# Cost Tracking Endpoints

@app.get("/costs/user/{user_id}")
async def get_user_costs(
    user_id: str = Path(..., description="User identifier"),
    service_type: Optional[str] = Query(None, description="Filter by service type (stt, tts, llm)"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)")
):
    """
    Get cost entries for a user.
    
    Returns list of cost entries with service type, cost, tokens, and metadata.
    """
    if not COST_TRACKING_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Cost tracking not available"
        )
    
    try:
        cost_tracker = CostTracker()
        
        # Parse service type
        service_type_enum = None
        if service_type:
            try:
                service_type_enum = ServiceType(service_type.lower())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid service_type: {service_type}. Must be one of: stt, tts, llm"
                )
        
        # Parse dates
        start_date_obj = None
        end_date_obj = None
        if start_date:
            try:
                from datetime import date as date_class
                start_date_obj = date_class.fromisoformat(start_date)
            except (ValueError, AttributeError):
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use ISO format.")
        
        if end_date:
            try:
                from datetime import date as date_class
                end_date_obj = date_class.fromisoformat(end_date)
            except (ValueError, AttributeError):
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use ISO format.")
        
        costs = cost_tracker.get_costs_for_user(
            user_id=user_id,
            service_type=service_type_enum,
            start_date=start_date_obj,
            end_date=end_date_obj
        )
        
        # Format datetime objects
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return {
            "user_id": user_id,
            "total_cost": sum(c['cost'] for c in costs),
            "count": len(costs),
            "costs": [
                {
                    "id": c['id'],
                    "service_type": c['service_type'],
                    "cost": c['cost'],
                    "tokens": c.get('tokens'),
                    "duration_seconds": c.get('duration_seconds'),
                    "metadata": c.get('metadata', {}),
                    "created_at": format_datetime(c.get('created_at'))
                }
                for c in costs
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user costs: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get user costs: {str(e)}")


@app.get("/costs/conversation/{conversation_id}")
async def get_conversation_costs(
    conversation_id: int = Path(..., description="Conversation ID"),
    service_type: Optional[str] = Query(None, description="Filter by service type (stt, tts, llm)")
):
    """
    Get cost entries for a conversation.
    
    Returns list of cost entries for the specified conversation.
    """
    if not COST_TRACKING_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Cost tracking not available"
        )
    
    try:
        cost_tracker = CostTracker()
        
        # Parse service type
        service_type_enum = None
        if service_type:
            try:
                service_type_enum = ServiceType(service_type.lower())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid service_type: {service_type}. Must be one of: stt, tts, llm"
                )
        
        costs = cost_tracker.get_costs_for_conversation(
            conversation_id=conversation_id,
            service_type=service_type_enum
        )
        
        # Format datetime objects
        def format_datetime(dt):
            if dt is None:
                return None
            if isinstance(dt, datetime):
                return dt.isoformat()
            return str(dt)
        
        return {
            "conversation_id": conversation_id,
            "total_cost": sum(c['cost'] for c in costs),
            "count": len(costs),
            "costs": [
                {
                    "id": c['id'],
                    "service_type": c['service_type'],
                    "cost": c['cost'],
                    "tokens": c.get('tokens'),
                    "duration_seconds": c.get('duration_seconds'),
                    "metadata": c.get('metadata', {}),
                    "created_at": format_datetime(c.get('created_at'))
                }
                for c in costs
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation costs: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get conversation costs: {str(e)}")


@app.get("/costs/user/{user_id}/report")
async def get_billing_report(
    user_id: str = Path(..., description="User identifier"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)")
):
    """
    Generate billing report for a user.
    
    Returns detailed billing report with cost breakdown by service type.
    """
    if not COST_TRACKING_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Cost tracking not available"
        )
    
    try:
        cost_tracker = CostTracker()
        
        # Parse dates
        start_date_obj = None
        end_date_obj = None
        if start_date:
            try:
                from datetime import date as date_class
                start_date_obj = date_class.fromisoformat(start_date)
            except (ValueError, AttributeError):
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use ISO format.")
        
        if end_date:
            try:
                from datetime import date as date_class
                end_date_obj = date_class.fromisoformat(end_date)
            except (ValueError, AttributeError):
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use ISO format.")
        
        report = cost_tracker.generate_billing_report(
            user_id=user_id,
            start_date=start_date_obj,
            end_date=end_date_obj
        )
        
        return report
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating billing report: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate billing report: {str(e)}")


# Voice Command Recognition Endpoints

class VoiceCommandResponse(BaseModel):
    """Response model for voice command recognition."""
    command_type: str = Field(..., description="Type of recognized command")
    text: str = Field(..., description="Transcribed text")
    confidence: float = Field(..., description="Recognition confidence (0.0 to 1.0)")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Command parameters")


@app.post("/voice/recognize", response_model=VoiceCommandResponse)
async def recognize_voice_command(
    audio: UploadFile = File(..., description="Audio file (WAV, FLAC, etc.)")
):
    """
    Recognize voice command from audio file.
    
    Supports commands:
    - "new conversation" / "start new conversation" - Start a new conversation
    - "clear history" / "delete history" - Clear conversation history
    - "change language to [language]" / "switch to [language]" - Change language
    
    Returns recognized command type and parameters.
    """
    if not VOICE_COMMANDS_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Voice command recognition not available. Install SpeechRecognition package."
        )
    
    try:
        # Save uploaded file temporarily
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{audio.filename.split('.')[-1] if audio.filename else 'wav'}") as temp_file:
            content = await audio.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            # Recognize command
            recognizer = VoiceCommandRecognizer()
            command = recognizer.recognize_command(temp_file_path)
            
            return VoiceCommandResponse(
                command_type=command.command_type.value,
                text=command.text,
                confidence=command.confidence,
                parameters=command.parameters
            )
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(f"Failed to delete temporary file {temp_file_path}: {str(e)}")
                
    except VoiceCommandError as e:
        logger.error(f"Voice command recognition error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in voice command recognition: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to recognize command: {str(e)}")


# Voice Quality Scoring Endpoints

class VoiceQualityResponse(BaseModel):
    """Response model for voice quality scoring."""
    overall_score: int = Field(..., description="Overall quality score (0-100)")
    volume_score: int = Field(..., description="Volume level score (0-100)")
    clarity_score: int = Field(..., description="Speech clarity score (0-100)")
    noise_score: int = Field(..., description="Noise level score (0-100, higher = less noise)")
    feedback: str = Field(..., description="Textual feedback about quality")
    suggestions: List[str] = Field(..., description="List of improvement suggestions")


@app.post("/voice/quality", response_model=VoiceQualityResponse)
async def score_voice_quality(
    audio: UploadFile = File(..., description="Audio file (WAV, FLAC, OGG, etc.)")
):
    """
    Score voice message quality and provide feedback.
    
    Analyzes audio for:
    - Volume level (too quiet or too loud)
    - Background noise detection
    - Speech clarity and intelligibility
    - Overall quality assessment
    
    Returns quality scores (0-100) and improvement suggestions.
    """
    if not VOICE_QUALITY_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Voice quality scoring not available. Install numpy package: pip install numpy"
        )
    
    try:
        # Save uploaded file temporarily
        import tempfile
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f".{audio.filename.split('.')[-1] if audio.filename else 'wav'}"
        ) as temp_file:
            content = await audio.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            # Score voice quality
            scorer = VoiceQualityScorer()
            score_result = scorer.score_voice_message(temp_file_path)
            
            return VoiceQualityResponse(
                overall_score=score_result["overall_score"],
                volume_score=score_result["volume_score"],
                clarity_score=score_result["clarity_score"],
                noise_score=score_result["noise_score"],
                feedback=score_result["feedback"],
                suggestions=score_result["suggestions"]
            )
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(f"Failed to delete temporary file {temp_file_path}: {str(e)}")
                
    except VoiceQualityError as e:
        logger.error(f"Voice quality scoring error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in voice quality scoring: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to score voice quality: {str(e)}")


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

