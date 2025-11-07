"""
TODO Service - REST API for task management.

Main entry point for the TODO MCP Service.
All initialization logic is in app/factory.py.
"""
import os
import uvicorn
import logging

from app import create_app

# Get logger (logging is configured in app/factory.py)
logger = logging.getLogger(__name__)

# Create app instance for testing and running
# This allows tests to import 'app' from main
app = create_app()

if __name__ == "__main__":
    # Get port from environment or use default
    port = int(os.getenv("TODO_SERVICE_PORT", "8004"))
    
    # Configure uvicorn for production
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level=os.getenv("LOG_LEVEL", "INFO").lower(),
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
        # Cleanup is handled by lifespan context manager in app/factory.py
        logger.info("Service stopped")
else:
    # When imported (e.g., by tests), use the app instance created above
    pass
