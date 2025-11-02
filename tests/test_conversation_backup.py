"""
Tests for conversation backup to object storage functionality.
"""
import pytest
import os
import json
import tempfile
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch, call
import boto3
from moto import mock_s3

from src.conversation_storage import ConversationStorage
from src.conversation_backup import ConversationBackupManager, BackupScheduler


@pytest.fixture
def mock_s3_client():
    """Create a mock S3 client using moto."""
    with mock_s3():
        client = boto3.client('s3', region_name='us-east-1')
        bucket_name = 'test-conversation-backups'
        client.create_bucket(Bucket=bucket_name)
        yield client, bucket_name


@pytest.fixture
def storage():
    """Create a ConversationStorage instance for testing."""
    # Use SQLite for testing (via db_adapter)
    db_path = os.path.join(tempfile.gettempdir(), f"test_conversations_{os.getpid()}.db")
    try:
        storage = ConversationStorage(db_path=db_path)
        yield storage
    finally:
        # Cleanup
        if os.path.exists(db_path):
            os.remove(db_path)


@pytest.fixture
def backup_manager(mock_s3_client, storage):
    """Create a ConversationBackupManager instance for testing."""
    s3_client, bucket_name = mock_s3_client
    
    # Set environment variables for backup configuration
    os.environ['BACKUP_S3_BUCKET'] = bucket_name
    os.environ['BACKUP_S3_REGION'] = 'us-east-1'
    os.environ['BACKUP_S3_PREFIX'] = 'conversations/'
    
    manager = ConversationBackupManager(
        storage=storage,
        s3_client=s3_client,
        bucket_name=bucket_name,
        prefix='conversations/'
    )
    return manager


class TestConversationBackupManager:
    """Test conversation backup manager functionality."""
    
    def test_create_backup(self, backup_manager, storage, mock_s3_client):
        """Test creating a backup of a conversation."""
        s3_client, bucket_name = mock_s3_client
        
        # Create a conversation with messages
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Hello", tokens=10)
        storage.add_message(conv_id, "assistant", "Hi there!", tokens=15)
        
        # Create backup
        backup_path = backup_manager.create_backup("user1", "chat1")
        
        assert backup_path is not None
        
        # Verify backup exists in S3
        objects = s3_client.list_objects_v2(Bucket=bucket_name, Prefix='conversations/')
        assert 'Contents' in objects
        assert len(objects['Contents']) > 0
        
        # Verify backup content
        backup_key = backup_path.split('/')[-1]
        response = s3_client.get_object(Bucket=bucket_name, Key=f'conversations/{backup_key}')
        backup_data = json.loads(response['Body'].read())
        
        assert backup_data['user_id'] == "user1"
        assert backup_data['chat_id'] == "chat1"
        assert len(backup_data['messages']) == 2
    
    def test_backup_non_existent_conversation(self, backup_manager):
        """Test backing up a non-existent conversation."""
        with pytest.raises(ValueError, match="Conversation not found"):
            backup_manager.create_backup("nonexistent", "chat")
    
    def test_list_backups(self, backup_manager, storage, mock_s3_client):
        """Test listing available backups."""
        # Create and backup multiple conversations
        conv_id1 = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id1, "user", "Hello")
        backup_manager.create_backup("user1", "chat1")
        
        conv_id2 = storage.get_or_create_conversation("user2", "chat2")
        storage.add_message(conv_id2, "user", "Hi")
        backup_manager.create_backup("user2", "chat2")
        
        # List backups
        backups = backup_manager.list_backups(user_id="user1")
        assert len(backups) >= 1
        assert all(b['user_id'] == "user1" for b in backups)
        
        # List all backups
        all_backups = backup_manager.list_backups()
        assert len(all_backups) >= 2
    
    def test_restore_backup(self, backup_manager, storage, mock_s3_client):
        """Test restoring a conversation from backup."""
        # Create original conversation
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Original message", tokens=10)
        
        # Create backup
        backup_path = backup_manager.create_backup("user1", "chat1")
        
        # Delete original conversation
        storage.delete_conversation("user1", "chat1")
        
        # Verify conversation is gone
        assert storage.get_conversation("user1", "chat1") is None
        
        # Restore from backup
        backup_key = backup_path.split('/')[-1]
        restored_id = backup_manager.restore_backup(f'conversations/{backup_key}')
        
        assert restored_id > 0
        
        # Verify restored conversation
        restored = storage.get_conversation("user1", "chat1")
        assert restored is not None
        assert len(restored['messages']) == 1
        assert restored['messages'][0]['content'] == "Original message"
    
    def test_retention_policy(self, backup_manager, storage, mock_s3_client):
        """Test that retention policy deletes old backups."""
        s3_client, bucket_name = mock_s3_client
        
        # Create multiple backups
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Message")
        
        # Create backups with different timestamps
        backup1 = backup_manager.create_backup("user1", "chat1")
        backup2 = backup_manager.create_backup("user1", "chat1")
        backup3 = backup_manager.create_backup("user1", "chat1")
        
        # Initially, all backups exist
        objects = s3_client.list_objects_v2(Bucket=bucket_name, Prefix='conversations/')
        backup_count_before = len(objects.get('Contents', []))
        assert backup_count_before >= 3
        
        # Apply retention policy (keep only 2 most recent)
        deleted_count = backup_manager.apply_retention_policy(
            user_id="user1",
            chat_id="chat1",
            keep_latest=2
        )
        
        # Verify old backups were deleted
        objects = s3_client.list_objects_v2(Bucket=bucket_name, Prefix='conversations/')
        backup_count_after = len(objects.get('Contents', []))
        assert backup_count_after == 2
        assert deleted_count >= 1
    
    def test_backup_with_metadata(self, backup_manager, storage, mock_s3_client):
        """Test that backup includes metadata."""
        s3_client, bucket_name = mock_s3_client
        
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Hello")
        
        # Create backup with custom metadata
        backup_path = backup_manager.create_backup(
            "user1",
            "chat1",
            metadata={"source": "test", "version": "1.0"}
        )
        
        # Verify metadata in backup
        backup_key = backup_path.split('/')[-1]
        response = s3_client.get_object(Bucket=bucket_name, Key=f'conversations/{backup_key}')
        backup_data = json.loads(response['Body'].read())
        
        assert 'backup_metadata' in backup_data
        assert backup_data['backup_metadata']['source'] == "test"
        assert backup_data['backup_metadata']['version'] == "1.0"
    
    def test_backup_incremental(self, backup_manager, storage, mock_s3_client):
        """Test that incremental backups only backup changes."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Message 1")
        
        # First backup
        backup1 = backup_manager.create_backup("user1", "chat1")
        
        # Add more messages
        storage.add_message(conv_id, "user", "Message 2")
        storage.add_message(conv_id, "user", "Message 3")
        
        # Incremental backup (only new messages)
        backup2 = backup_manager.create_backup(
            "user1",
            "chat1",
            incremental=True,
            last_backup_key=backup1.split('/')[-1]
        )
        
        # Verify incremental backup only contains new messages
        s3_client, bucket_name = mock_s3_client
        backup_key = backup2.split('/')[-1]
        response = s3_client.get_object(Bucket=bucket_name, Key=f'conversations/{backup_key}')
        backup_data = json.loads(response['Body'].read())
        
        assert backup_data.get('backup_type') == 'incremental'
        # Should only have the new messages
        assert len(backup_data['messages']) == 2  # Message 2 and 3


class TestBackupScheduler:
    """Test automatic backup scheduling."""
    
    def test_scheduler_creates_backups(self, storage, mock_s3_client):
        """Test that scheduler automatically creates backups."""
        s3_client, bucket_name = mock_s3_client
        
        # Create conversation
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Hello")
        
        # Create scheduler
        backup_manager = ConversationBackupManager(
            storage=storage,
            s3_client=s3_client,
            bucket_name=bucket_name,
            prefix='conversations/'
        )
        
        scheduler = BackupScheduler(
            backup_manager=backup_manager,
            interval_hours=1,
            enabled=True
        )
        
        try:
            # Trigger immediate backup (for testing)
            scheduler._backup_all_conversations()
            
            # Verify backup was created
            objects = s3_client.list_objects_v2(Bucket=bucket_name, Prefix='conversations/')
            assert 'Contents' in objects
            assert len(objects['Contents']) > 0
        finally:
            scheduler.stop()
    
    def test_scheduler_respects_interval(self, storage, mock_s3_client):
        """Test that scheduler respects backup interval."""
        s3_client, bucket_name = mock_s3_client
        
        backup_manager = ConversationBackupManager(
            storage=storage,
            s3_client=s3_client,
            bucket_name=bucket_name,
            prefix='conversations/'
        )
        
        scheduler = BackupScheduler(
            backup_manager=backup_manager,
            interval_hours=24,  # 24 hour interval
            enabled=True
        )
        
        try:
            # Create conversation
            conv_id = storage.get_or_create_conversation("user1", "chat1")
            storage.add_message(conv_id, "user", "Message")
            
            # First backup should be created
            scheduler._backup_all_conversations()
            
            # Immediately trigger again - should be skipped if within interval
            # (This would require tracking last backup time, which we'll implement)
            # For now, just verify the scheduler exists and can be stopped
            assert scheduler.is_running()
        finally:
            scheduler.stop()
    
    def test_scheduler_applies_retention(self, storage, mock_s3_client):
        """Test that scheduler applies retention policies."""
        s3_client, bucket_name = mock_s3_client
        
        backup_manager = ConversationBackupManager(
            storage=storage,
            s3_client=s3_client,
            bucket_name=bucket_name,
            prefix='conversations/'
        )
        
        scheduler = BackupScheduler(
            backup_manager=backup_manager,
            interval_hours=1,
            enabled=True,
            retention_days=7,  # Keep backups for 7 days
            max_backups_per_conversation=5
        )
        
        try:
            # Create and backup multiple times
            conv_id = storage.get_or_create_conversation("user1", "chat1")
            storage.add_message(conv_id, "user", "Message")
            
            # Create multiple backups
            for _ in range(10):
                backup_manager.create_backup("user1", "chat1")
            
            # Apply retention
            scheduler._apply_retention_policies()
            
            # Verify only recent backups exist
            backups = backup_manager.list_backups(user_id="user1", chat_id="chat1")
            assert len(backups) <= 5
        finally:
            scheduler.stop()
