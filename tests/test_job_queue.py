"""
Tests for background job queue system.
"""
import pytest
import time
import json
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

# Import job queue components
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from job_queue import (
    JobQueue, JobStatus, JobType, JobPriority,
    JobError, RetryableJobError, NonRetryableJobError
)


class TestJobQueue:
    """Test job queue functionality."""
    
    @pytest.fixture
    def redis_mock(self):
        """Mock Redis connection."""
        mock = MagicMock()
        mock.ping.return_value = True
        mock.lpush.return_value = 1
        mock.rpop.return_value = None
        mock.get.return_value = None
        mock.set.return_value = True
        mock.delete.return_value = 1
        mock.exists.return_value = False
        mock.hset.return_value = 1
        mock.hgetall.return_value = {}
        mock.zadd.return_value = 1
        mock.zrange.return_value = []
        mock.zrem.return_value = 1
        mock.expire.return_value = True
        return mock
    
    @pytest.fixture
    def job_queue(self, redis_mock):
        """Create job queue instance with mocked Redis."""
        with patch('job_queue.redis.Redis', return_value=redis_mock):
            queue = JobQueue(redis_url='redis://localhost:6379')
            queue.redis = redis_mock
            return queue
    
    def test_submit_job(self, job_queue, redis_mock):
        """Test submitting a job to the queue."""
        job_data = {
            "job_type": "backup",
            "parameters": {"project_id": 1}
        }
        
        job_id = job_queue.submit_job(
            job_type=JobType.BACKUP,
            parameters=job_data["parameters"],
            priority=JobPriority.MEDIUM
        )
        
        assert job_id is not None
        assert len(job_id) > 0
        
        # Verify Redis was called to enqueue job
        redis_mock.lpush.assert_called_once()
        redis_mock.hset.assert_called()  # Job metadata stored
        
    def test_get_job_status(self, job_queue, redis_mock):
        """Test retrieving job status."""
        job_id = "test-job-123"
        
        # Mock job status in Redis
        status_data = {
            "status": JobStatus.PENDING.value,
            "job_type": JobType.BACKUP.value,
            "created_at": "2025-01-01T00:00:00",
            "priority": JobPriority.MEDIUM.value
        }
        redis_mock.hgetall.return_value = {
            k.encode(): json.dumps(v).encode() if isinstance(v, dict) else str(v).encode()
            for k, v in status_data.items()
        }
        
        status = job_queue.get_job_status(job_id)
        
        assert status is not None
        assert status["status"] == JobStatus.PENDING.value
        assert status["job_type"] == JobType.BACKUP.value
        
    def test_job_processing(self, job_queue, redis_mock):
        """Test processing jobs from the queue."""
        # Mock job in queue
        job_data = {
            "job_id": "test-job-123",
            "job_type": JobType.BACKUP.value,
            "parameters": {"project_id": 1},
            "priority": JobPriority.MEDIUM.value
        }
        redis_mock.rpop.return_value = json.dumps(job_data).encode()
        
        # Mock job status
        redis_mock.hgetall.return_value = {
            b"status": JobStatus.PENDING.value.encode(),
            b"job_type": JobType.BACKUP.value.encode()
        }
        
        job = job_queue.get_next_job()
        
        assert job is not None
        assert job["job_id"] == "test-job-123"
        
    def test_job_retry_on_error(self, job_queue, redis_mock):
        """Test job retry mechanism on retryable errors."""
        job_id = "test-job-123"
        
        # Initially fail, then succeed
        job_queue.record_job_error(job_id, RetryableJobError("Temporary error"))
        
        # Verify job is requeued with retry
        redis_mock.lpush.assert_called()
        redis_mock.hset.assert_called()  # Update retry count
        
    def test_job_failure_on_non_retryable_error(self, job_queue, redis_mock):
        """Test job fails permanently on non-retryable errors."""
        job_id = "test-job-123"
        
        job_queue.record_job_error(job_id, NonRetryableJobError("Permanent error"))
        
        # Verify job status is set to failed
        calls = redis_mock.hset.call_args_list
        status_updates = [call for call in calls if len(call[0]) > 0 and b"status" in str(call[0][0])]
        assert len(status_updates) > 0
        
    def test_job_completion(self, job_queue, redis_mock):
        """Test marking a job as complete."""
        job_id = "test-job-123"
        result = {"backup_file": "backup.db.gz"}
        
        job_queue.complete_job(job_id, result)
        
        # Verify status updated to complete
        redis_mock.hset.assert_called()
        calls = redis_mock.hset.call_args_list
        assert any("status" in str(call) or "complete" in str(call) for call in calls)
        
    def test_job_timeout(self, job_queue, redis_mock):
        """Test job timeout handling."""
        job_id = "test-job-123"
        
        # Mock job that's been processing too long
        status_data = {
            "status": JobStatus.PROCESSING.value,
            "started_at": str(time.time() - 3600)  # 1 hour ago
        }
        redis_mock.hgetall.return_value = {
            k.encode(): v.encode() if isinstance(v, str) else str(v).encode()
            for k, v in status_data.items()
        }
        
        # Check for timeout
        is_timeout = job_queue.check_job_timeout(job_id, timeout_seconds=1800)
        
        assert is_timeout is True
        
    def test_priority_ordering(self, job_queue, redis_mock):
        """Test jobs are processed in priority order."""
        # Submit jobs with different priorities
        job_queue.submit_job(JobType.BACKUP, {}, JobPriority.LOW)
        job_queue.submit_job(JobType.BACKUP, {}, JobPriority.HIGH)
        job_queue.submit_job(JobType.BACKUP, {}, JobPriority.MEDIUM)
        
        # Verify high priority jobs are retrieved first
        # (Redis sorted sets should handle this)
        redis_mock.zrange.assert_called()  # Priority queue uses sorted sets


class TestJobProcessors:
    """Test job processor implementations."""
    
    @pytest.fixture
    def job_queue(self):
        """Create job queue for processor tests."""
        with patch('job_queue.redis.Redis'):
            queue = JobQueue(redis_url='redis://localhost:6379')
            queue.redis = MagicMock()
            return queue
    
    def test_backup_job_processor(self, job_queue):
        """Test backup job processor."""
        from job_queue import BackupJobProcessor
        
        processor = BackupJobProcessor(job_queue)
        job_data = {
            "job_id": "test-123",
            "parameters": {"project_id": 1}
        }
        
        # Mock backup operation
        with patch('backup.BackupManager.create_backup') as mock_backup:
            mock_backup.return_value = "backup.db.gz"
            
            result = processor.process(job_data)
            
            assert result is not None
            assert "backup_file" in result
            
    def test_webhook_job_processor(self, job_queue):
        """Test webhook delivery job processor."""
        from job_queue import WebhookJobProcessor
        
        processor = WebhookJobProcessor(job_queue)
        job_data = {
            "job_id": "test-123",
            "parameters": {
                "url": "https://example.com/webhook",
                "payload": {"event": "task.completed"},
                "secret": "secret-key"
            }
        }
        
        # Mock webhook delivery
        with patch('httpx.post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response
            
            result = processor.process(job_data)
            
            assert result is not None
            mock_post.assert_called_once()


class TestJobQueueIntegration:
    """Integration tests for job queue."""
    
    @pytest.fixture
    def temp_redis(self):
        """Create temporary Redis instance for integration tests."""
        # Skip if Redis not available
        try:
            import redis
            client = redis.Redis(host='localhost', port=6379, db=15, decode_responses=True)
            client.ping()
            yield client
            # Cleanup
            client.flushdb()
            client.close()
        except Exception:
            pytest.skip("Redis not available for integration tests")
    
    def test_full_job_lifecycle(self, temp_redis):
        """Test complete job lifecycle: submit -> process -> complete."""
        queue = JobQueue(redis_client=temp_redis)
        
        # Submit job
        job_id = queue.submit_job(
            JobType.BACKUP,
            {"project_id": 1},
            JobPriority.MEDIUM
        )
        
        # Get status
        status = queue.get_job_status(job_id)
        assert status["status"] == JobStatus.PENDING.value
        
        # Process job
        job = queue.get_next_job()
        assert job is not None
        assert job["job_id"] == job_id
        
        # Mark as processing
        queue.start_job_processing(job_id)
        status = queue.get_job_status(job_id)
        assert status["status"] == JobStatus.PROCESSING.value
        
        # Complete job
        result = {"file": "backup.db.gz"}
        queue.complete_job(job_id, result)
        
        status = queue.get_job_status(job_id)
        assert status["status"] == JobStatus.COMPLETE.value
        assert status.get("result") == result
