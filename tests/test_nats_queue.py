"""
Tests for NATS message queue functionality.
"""
import pytest
import asyncio
import os
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Skip tests if nats-py is not available
try:
    import nats
    NATS_AVAILABLE = True
except ImportError:
    NATS_AVAILABLE = False


@pytest.mark.skipif(not NATS_AVAILABLE, reason="nats-py not available")
class TestNATSQueue:
    """Test NATS queue implementation."""
    
    @pytest.mark.asyncio
    async def test_queue_initialization(self):
        """Test queue initialization."""
        from nats_queue import NATSQueue
        
        # Test without connection (mocked)
        with patch('nats_queue.nats.connect', new_callable=AsyncMock) as mock_connect:
            mock_nc = AsyncMock()
            mock_connect.return_value = mock_nc
            mock_nc.jetstream.return_value = MagicMock()
            
            queue = NATSQueue(nats_url="nats://localhost:4222", use_jetstream=False)
            assert queue.nats_url == "nats://localhost:4222"
            assert queue.use_jetstream is False
            assert not queue.connected
    
    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        """Test connection and disconnection."""
        from nats_queue import NATSQueue
        
        with patch('nats_queue.nats.connect', new_callable=AsyncMock) as mock_connect:
            mock_nc = AsyncMock()
            mock_connect.return_value = mock_nc
            
            queue = NATSQueue(nats_url="nats://localhost:4222")
            await queue.connect()
            
            assert queue.connected
            assert queue.nc == mock_nc
            
            await queue.disconnect()
            mock_nc.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_publish_message(self):
        """Test publishing messages."""
        from nats_queue import NATSQueue
        
        with patch('nats_queue.nats.connect', new_callable=AsyncMock) as mock_connect:
            mock_nc = AsyncMock()
            mock_connect.return_value = mock_nc
            
            queue = NATSQueue(nats_url="nats://localhost:4222")
            await queue.connect()
            
            test_data = {
                "type": "test.message",
                "data": {"key": "value"}
            }
            
            await queue.publish("test.subject", test_data)
            
            # Verify publish was called
            assert mock_nc.publish.called
    
    @pytest.mark.asyncio
    async def test_subscribe_to_messages(self):
        """Test subscribing to messages."""
        from nats_queue import NATSQueue
        
        with patch('nats_queue.nats.connect', new_callable=AsyncMock) as mock_connect:
            mock_nc = AsyncMock()
            mock_connect.return_value = mock_nc
            
            queue = NATSQueue(nats_url="nats://localhost:4222")
            await queue.connect()
            
            handler_called = asyncio.Event()
            
            async def test_handler(data, msg):
                handler_called.set()
            
            await queue.subscribe("test.subject", test_handler, queue_group="test-group")
            
            # Verify subscribe was called
            mock_nc.subscribe.assert_called()


@pytest.mark.skipif(not NATS_AVAILABLE, reason="nats-py not available")
class TestNATSWorker:
    """Test NATS worker implementation."""
    
    @pytest.mark.asyncio
    async def test_worker_initialization(self):
        """Test worker initialization."""
        from nats_queue import NATSQueue
        from nats_worker import TaskWorker
        
        mock_db = Mock()
        
        with patch('nats_queue.nats.connect', new_callable=AsyncMock) as mock_connect:
            mock_nc = AsyncMock()
            mock_connect.return_value = mock_nc
            
            queue = NATSQueue(nats_url="nats://localhost:4222")
            worker = TaskWorker(queue=queue, db=mock_db, worker_id="test-worker")
            
            assert worker.worker_id == "test-worker"
            assert worker.db == mock_db
            assert worker.processed_count == 0
            assert worker.error_count == 0
    
    @pytest.mark.asyncio
    async def test_worker_start_stop(self):
        """Test worker start and stop."""
        from nats_queue import NATSQueue
        from nats_worker import TaskWorker
        
        mock_db = Mock()
        
        with patch('nats_queue.nats.connect', new_callable=AsyncMock) as mock_connect:
            mock_nc = AsyncMock()
            mock_connect.return_value = mock_nc
            
            queue = NATSQueue(nats_url="nats://localhost:4222")
            worker = TaskWorker(queue=queue, db=mock_db, worker_id="test-worker")
            
            subjects = ["test.subject"]
            await worker.start(subjects)
            
            assert worker.running
            
            await worker.stop()
            
            assert not worker.running


@pytest.mark.skipif(not NATS_AVAILABLE, reason="nats-py not available")
class TestNATSIntegration:
    """Integration tests for NATS queue with database."""
    
    @pytest.mark.asyncio
    async def test_task_complete_via_queue(self):
        """Test completing a task via NATS queue."""
        from nats_queue import NATSQueue, MessageType
        from nats_worker import TaskWorker
        from database import TodoDatabase
        import tempfile
        
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            db = TodoDatabase(db_path)
            
            # Create a test task
            task_id = db.create_task(
                title="Test Task",
                task_type="concrete",
                task_instruction="Test instruction",
                verification_instruction="Test verification",
                agent_id="test-agent"
            )
            
            mock_queue = Mock(spec=NATSQueue)
            mock_queue.nats_url = "nats://localhost:4222"
            mock_queue.use_jetstream = False
            mock_queue.connected = True
            
            worker = TaskWorker(queue=mock_queue, db=db, worker_id="test-worker")
            
            # Simulate message handling
            message_data = {
                "type": MessageType.TASK_COMPLETE.value,
                "task_id": task_id,
                "agent_id": "test-agent",
                "notes": "Completed via queue"
            }
            
            mock_msg = Mock()
            await worker._handle_task_complete(message_data)
            
            # Verify task was completed
            task = db.get_task(task_id)
            assert task["task_status"] == "complete"
            
        finally:
            # Cleanup
            if os.path.exists(db_path):
                os.unlink(db_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
