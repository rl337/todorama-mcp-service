"""
Adapter for job queue implementations.
Isolates job queue library imports to make replacement easier.
"""
import os
import logging

logger = logging.getLogger(__name__)

try:
    from job_queue import JobQueue, JobType, JobPriority, JobStatus
    JOB_QUEUE_AVAILABLE = True
except ImportError:
    JOB_QUEUE_AVAILABLE = False
    JobQueue = None
    JobType = None
    JobPriority = None
    JobStatus = None


class JobQueueAdapter:
    """Adapter for job queue implementations."""
    
    def __init__(self):
        self.available = JOB_QUEUE_AVAILABLE
        self._queue = None
        if JOB_QUEUE_AVAILABLE:
            try:
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                self._queue = JobQueue(redis_url=redis_url)
                logger.info("Job queue initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize job queue: {e}. Job queue features will be unavailable.")
                self._queue = None
    
    def get_queue(self):
        """Get the job queue instance, or None if unavailable."""
        return self._queue
    
    def is_available(self):
        """Check if job queue is available."""
        return self.available and self._queue is not None

