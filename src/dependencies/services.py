"""
Service container for dependency injection.
Centralizes service initialization and provides access to all services.
"""
import os
import logging
from typing import Optional

from database import TodoDatabase
from backup import BackupManager, BackupScheduler
from conversation_storage import ConversationStorage
from conversation_backup import ConversationBackupManager, BackupScheduler as ConversationBackupScheduler
from adapters.job_queue_adapter import JobQueueAdapter
from mcp_api import set_db

logger = logging.getLogger(__name__)

# Global service instance
_service_instance: Optional['ServiceContainer'] = None


class ServiceContainer:
    """Container for all application services."""
    
    def __init__(self):
        # Initialize database
        db_path = os.getenv("TODO_DB_PATH", "/app/data/todos.db")
        self.db = TodoDatabase(db_path)
        
        # Initialize MCP API with database
        set_db(self.db)
        
        # Initialize backup manager
        backups_dir = os.getenv("TODO_BACKUPS_DIR", "/app/backups")
        self.backup_manager = BackupManager(db_path, backups_dir)
        
        # Initialize and start backup scheduler (nightly backups)
        backup_interval_hours = int(os.getenv("TODO_BACKUP_INTERVAL_HOURS", "24"))
        self.backup_scheduler = BackupScheduler(self.backup_manager, backup_interval_hours)
        self.backup_scheduler.start()
        
        # Initialize conversation storage
        self.conversation_storage = ConversationStorage()
        
        # Initialize conversation backup manager (if S3 is configured)
        self.conversation_backup_manager = None
        self.conversation_backup_scheduler = None
        
        backup_s3_bucket = os.getenv("BACKUP_S3_BUCKET")
        if backup_s3_bucket:
            try:
                self.conversation_backup_manager = ConversationBackupManager(
                    storage=self.conversation_storage,
                    bucket_name=backup_s3_bucket
                )
                
                # Initialize and start conversation backup scheduler
                conversation_backup_interval = int(os.getenv("CONVERSATION_BACKUP_INTERVAL_HOURS", "24"))
                conversation_retention_days = int(os.getenv("CONVERSATION_BACKUP_RETENTION_DAYS", "30")) if os.getenv("CONVERSATION_BACKUP_RETENTION_DAYS") else None
                max_backups_per_conv = int(os.getenv("CONVERSATION_BACKUP_MAX_PER_CONVERSATION", "10"))
                
                self.conversation_backup_scheduler = ConversationBackupScheduler(
                    backup_manager=self.conversation_backup_manager,
                    interval_hours=conversation_backup_interval,
                    retention_days=conversation_retention_days,
                    max_backups_per_conversation=max_backups_per_conv
                )
                self.conversation_backup_scheduler.start()
                logger.info("Conversation backup scheduler started")
            except Exception as e:
                logger.warning(f"Failed to initialize conversation backup manager: {e}")
        
        # Initialize job queue adapter
        self.job_queue_adapter = JobQueueAdapter()
        self.job_queue = self.job_queue_adapter.get_queue()
        
        # Initialize NATS queue (if available)
        self.nats_queue = None
        self.nats_workers = []
        try:
            from nats_queue import NATSQueue
            from nats_worker import start_workers, stop_workers, TaskWorker
            nats_url = os.getenv("NATS_URL", "nats://localhost:4222")
            use_jetstream = os.getenv("NATS_USE_JETSTREAM", "false").lower() == "true"
            num_workers = int(os.getenv("NATS_NUM_WORKERS", "1"))
            self.nats_queue = NATSQueue(nats_url=nats_url, use_jetstream=use_jetstream)
            logger.info(f"NATS queue initialized (URL: {nats_url}, JetStream: {use_jetstream})")
        except ImportError:
            logger.info("NATS queue unavailable (nats-py not installed)")
        except Exception as e:
            logger.warning(f"Failed to initialize NATS queue: {e}. NATS features will be unavailable.")
            self.nats_queue = None


def get_services() -> ServiceContainer:
    """Get the global service container instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = ServiceContainer()
    return _service_instance


def get_db() -> TodoDatabase:
    """Get the database instance from the service container."""
    return get_services().db

