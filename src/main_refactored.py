"""
TODO Service - Refactored main entry point.

This is a minimal orchestration file that:
- Creates the FastAPI app
- Registers routers
- Sets up middleware
- Configures exception handlers
- Initializes services
"""
import os
import logging
import signal
import asyncio
from contextlib import asynccontextmanager

# Third-party imports
from adapters.http_framework import HTTPFrameworkAdapter
from adapters.metrics import MetricsAdapter
from strawberry.fastapi import GraphQLRouter

# Internal imports
from dependencies.services import ServiceContainer, get_services
from middleware.setup import setup_middleware
from exceptions.handlers import setup_exception_handlers
from monitoring import setup_logging, get_request_id
from tracing import setup_tracing, instrument_fastapi, instrument_database, instrument_httpx

# Route imports
from api.routes import projects, comments, mcp, health
from graphql_schema import schema

# Note: Tasks routes still need to be extracted from main.py
# For now, we'll keep main.py working but this refactored version is incomplete

# Setup logging first
logger = logging.getLogger(__name__)
setup_logging()

# Initialize adapters
http_adapter = HTTPFrameworkAdapter()
FastAPI = http_adapter.FastAPI
StaticFiles = http_adapter.StaticFiles
HTMLResponse = http_adapter.HTMLResponse

# Graceful shutdown handler
shutdown_event = asyncio.Event()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_event.set()
    
    # Stop backup schedulers
    services = get_services()
    services.backup_scheduler.stop()
    if services.conversation_backup_scheduler:
        services.conversation_backup_scheduler.stop()


# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


@asynccontextmanager
async def lifespan(app):
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
    services = get_services()
    if services.nats_queue:
        try:
            from nats_worker import start_workers
            num_workers = int(os.getenv("NATS_NUM_WORKERS", "1"))
            nats_workers = await start_workers(
                db=services.db,
                nats_url=services.nats_queue.nats_url,
                num_workers=num_workers,
                use_jetstream=services.nats_queue.use_jetstream
            )
            logger.info(f"Started {len(nats_workers)} NATS workers")
        except Exception as e:
            logger.warning(f"Failed to start NATS workers: {e}", exc_info=True)
            nats_workers = []
    
    yield
    
    # Shutdown
    logger.info("Application shutting down...")
    services.backup_scheduler.stop()
    if services.conversation_backup_scheduler:
        services.conversation_backup_scheduler.stop()
    
    # Stop NATS workers
    if services.nats_queue:
        try:
            from nats_worker import stop_workers
            if hasattr(services, 'nats_workers') and services.nats_workers:
                await stop_workers(services.nats_workers)
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

# Setup middleware
setup_middleware(app)

# Setup exception handlers
setup_exception_handlers(app)

# Add GraphQL router
graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")

# Mount static files directory for web interface
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Root endpoint - serve web interface
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the web-based task management interface."""
    static_dir_path = os.path.join(os.path.dirname(__file__), "..", "static")
    index_file = os.path.join(static_dir_path, "index.html")
    
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    else:
        return HTMLResponse(
            content="<h1>TODO Service</h1><p>Web interface not found. Please ensure static files are deployed.</p>",
            status_code=404
        )

# Register routers
app.include_router(projects.router)
app.include_router(comments.router)
app.include_router(comments.comment_router)  # For /comments/{comment_id}/thread
app.include_router(mcp.router)
app.include_router(health.router)

# Initialize services (must happen after app creation for lifespan)
# This is done by get_services() when first called
_ = get_services()

