"""
Application factory - creates and configures the FastAPI application.
This isolates all initialization logic from main.py.
"""
import os
import signal
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from strawberry.fastapi import GraphQLRouter

# Import middleware and handlers
from middleware.setup import setup_middleware
from exceptions.handlers import setup_exception_handlers
from graphql_schema import schema

# Import route module (single file with all routes)
from api.all_routes import router as api_router

# Import service container (handles all initialization)
from dependencies.services import get_services

logger = logging.getLogger(__name__)


# Global shutdown event
shutdown_event = asyncio.Event()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_event.set()
    
    # Stop services
    services = get_services()
    services.backup_scheduler.stop()
    if services.conversation_backup_scheduler:
        services.conversation_backup_scheduler.stop()
    
    logger.info("Graceful shutdown complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan with graceful shutdown.
    """
    # Startup
    logger.info("Application starting up...")
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
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
    
    # Start NATS workers if available (non-blocking)
    if hasattr(services, 'nats_queue') and services.nats_queue:
        try:
            from nats_worker import start_workers
            async def start_nats_workers_background():
                try:
                    num_workers = int(os.getenv("NATS_NUM_WORKERS", "1"))
                    workers = await start_workers(
                        db=services.db,
                        nats_url=services.nats_queue.nats_url,
                        num_workers=num_workers,
                        use_jetstream=services.nats_queue.use_jetstream
                    )
                    logger.info(f"Started {len(workers)} NATS workers")
                except Exception as e:
                    logger.warning(f"Failed to start NATS workers: {e}")
            
            asyncio.create_task(start_nats_workers_background())
        except ImportError:
            logger.info("NATS workers not available")
    
    yield
    
    # Shutdown
    logger.info("Application shutting down...")
    
    # Stop backup schedulers
    services.backup_scheduler.stop()
    if services.conversation_backup_scheduler:
        services.conversation_backup_scheduler.stop()
    
    # Stop NATS workers if they exist
    if hasattr(services, 'nats_workers') and services.nats_workers:
        try:
            from nats_worker import stop_workers
            await stop_workers(services.nats_workers)
            logger.info("Stopped NATS workers")
        except Exception as e:
            logger.warning(f"Error stopping NATS workers: {e}", exc_info=True)
    
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI app instance ready to run.
    """
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
    
    # Register API routes (single router with all routes)
    app.include_router(api_router)
    
    # Add GraphQL router
    graphql_app = GraphQLRouter(schema)
    app.include_router(graphql_app, prefix="/graphql")
    
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
    
    logger.info("FastAPI app created and configured")
    
    return app

