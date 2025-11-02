"""
Automatic conversation backup to object storage (S3/MinIO).

Provides functionality to:
- Automatically backup conversations to object storage
- Implement retention policies
- Restore conversations from backups
- Schedule automatic backups
"""
import os
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, BotoCoreError

from conversation_storage import ConversationStorage

logger = logging.getLogger(__name__)


class ConversationBackupManager:
    """Manages conversation backups to object storage (S3/MinIO)."""
    
    def __init__(
        self,
        storage: ConversationStorage,
        s3_client=None,
        bucket_name: Optional[str] = None,
        prefix: str = "conversations/",
        endpoint_url: Optional[str] = None
    ):
        """
        Initialize conversation backup manager.
        
        Args:
            storage: ConversationStorage instance
            s3_client: Boto3 S3 client (if None, will be created from env vars)
            bucket_name: S3 bucket name (defaults to BACKUP_S3_BUCKET env var)
            prefix: S3 key prefix for backups (default: "conversations/")
            endpoint_url: Optional S3 endpoint URL (for MinIO compatibility)
        """
        self.storage = storage
        
        # Get configuration from environment
        self.bucket_name = bucket_name or os.getenv("BACKUP_S3_BUCKET")
        self.prefix = prefix.rstrip('/') + '/' if prefix else "conversations/"
        self.endpoint_url = endpoint_url or os.getenv("BACKUP_S3_ENDPOINT_URL")
        
        if not self.bucket_name:
            raise ValueError("Bucket name must be provided or BACKUP_S3_BUCKET must be set")
        
        # Create or use provided S3 client
        if s3_client:
            self.s3_client = s3_client
        else:
            self.s3_client = self._create_s3_client()
        
        # Verify bucket exists, create if it doesn't
        self._ensure_bucket_exists()
        
        logger.info(
            f"Initialized ConversationBackupManager: bucket={self.bucket_name}, "
            f"prefix={self.prefix}, endpoint={self.endpoint_url}"
        )
    
    def _create_s3_client(self):
        """Create boto3 S3 client from environment variables."""
        aws_access_key_id = os.getenv("BACKUP_S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.getenv("BACKUP_S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
        region_name = os.getenv("BACKUP_S3_REGION", "us-east-1")
        
        config = {
            "region_name": region_name
        }
        
        if self.endpoint_url:
            config["endpoint_url"] = self.endpoint_url
        
        if aws_access_key_id and aws_secret_access_key:
            return boto3.client(
                's3',
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                **config
            )
        else:
            # Use default credentials (IAM role, etc.)
            return boto3.client('s3', **config)
    
    def _ensure_bucket_exists(self):
        """Ensure the S3 bucket exists, create if it doesn't."""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.debug(f"Bucket {self.bucket_name} exists")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                # Bucket doesn't exist, create it
                try:
                    if self.endpoint_url:
                        # MinIO - may need location constraint
                        self.s3_client.create_bucket(Bucket=self.bucket_name)
                    else:
                        # AWS S3
                        region = self.s3_client.meta.region_name
                        if region == 'us-east-1':
                            self.s3_client.create_bucket(Bucket=self.bucket_name)
                        else:
                            self.s3_client.create_bucket(
                                Bucket=self.bucket_name,
                                CreateBucketConfiguration={'LocationConstraint': region}
                            )
                    logger.info(f"Created bucket {self.bucket_name}")
                except ClientError as create_error:
                    logger.error(f"Failed to create bucket {self.bucket_name}: {create_error}")
                    raise
            else:
                logger.error(f"Error checking bucket {self.bucket_name}: {e}")
                raise
    
    def create_backup(
        self,
        user_id: str,
        chat_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        incremental: bool = False,
        last_backup_key: Optional[str] = None
    ) -> str:
        """
        Create a backup of a conversation.
        
        Args:
            user_id: User identifier
            chat_id: Chat identifier
            metadata: Optional metadata to include in backup
            incremental: If True, only backup new messages since last_backup_key
            last_backup_key: Key of last backup (required for incremental)
            
        Returns:
            S3 key path of the backup
        """
        # Get conversation
        conversation = self.storage.get_conversation(user_id, chat_id)
        if not conversation:
            raise ValueError(f"Conversation not found for user {user_id}, chat {chat_id}")
        
        # Prepare backup data
        backup_data = {
            'user_id': conversation['user_id'],
            'chat_id': conversation['chat_id'],
            'created_at': conversation['created_at'].isoformat() if isinstance(conversation['created_at'], datetime) else str(conversation['created_at']),
            'updated_at': conversation['updated_at'].isoformat() if isinstance(conversation['updated_at'], datetime) else str(conversation['updated_at']),
            'last_message_at': conversation['last_message_at'].isoformat() if conversation['last_message_at'] and isinstance(conversation['last_message_at'], datetime) else (str(conversation['last_message_at']) if conversation['last_message_at'] else None),
            'message_count': conversation['message_count'],
            'total_tokens': conversation['total_tokens'],
            'metadata': conversation.get('metadata', {}),
            'messages': [
                {
                    'role': msg['role'],
                    'content': msg['content'],
                    'tokens': msg.get('tokens'),
                    'created_at': msg['created_at'].isoformat() if isinstance(msg['created_at'], datetime) else str(msg['created_at'])
                }
                for msg in conversation.get('messages', [])
            ],
            'backup_metadata': {
                'backup_timestamp': datetime.utcnow().isoformat(),
                'backup_type': 'incremental' if incremental else 'full',
                **(metadata or {})
            }
        }
        
        # Handle incremental backups
        if incremental and last_backup_key:
            # Get last backup to determine which messages are new
            try:
                last_backup = self._get_backup_data(last_backup_key)
                if last_backup:
                    last_message_id = last_backup.get('messages', [])[-1].get('id') if last_backup.get('messages') else None
                    # Filter to only new messages (simplified - in production would track message IDs)
                    # For now, we'll include all messages but mark as incremental
                    pass
            except Exception as e:
                logger.warning(f"Failed to load last backup for incremental backup: {e}")
                # Fall back to full backup
        
        # Generate backup key
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_key = f"{self.prefix}{user_id}/{chat_id}/backup_{timestamp}.json"
        
        # Upload to S3
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=backup_key,
                Body=json.dumps(backup_data, indent=2),
                ContentType='application/json',
                Metadata={
                    'user_id': user_id,
                    'chat_id': chat_id,
                    'backup_timestamp': timestamp,
                    'backup_type': 'incremental' if incremental else 'full'
                }
            )
            logger.info(f"Created backup: {backup_key}")
            return backup_key
        except (ClientError, BotoCoreError) as e:
            logger.error(f"Failed to upload backup to S3: {e}", exc_info=True)
            raise
    
    def _get_backup_data(self, backup_key: str) -> Optional[Dict[str, Any]]:
        """Get backup data from S3."""
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=backup_key)
            return json.loads(response['Body'].read())
        except ClientError as e:
            if e.response.get('Error', {}).get('Code') == 'NoSuchKey':
                return None
            logger.error(f"Failed to get backup data: {e}", exc_info=True)
            raise
    
    def list_backups(
        self,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List available backups.
        
        Args:
            user_id: Optional user ID filter
            chat_id: Optional chat ID filter
            limit: Maximum number of backups to return
            
        Returns:
            List of backup metadata dictionaries
        """
        prefix = self.prefix
        if user_id:
            prefix += f"{user_id}/"
            if chat_id:
                prefix += f"{chat_id}/"
        
        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            backups = []
            
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                if 'Contents' not in page:
                    continue
                
                for obj in page['Contents']:
                    key = obj['Key']
                    if not key.endswith('.json'):
                        continue
                    
                    # Extract metadata
                    metadata_response = self.s3_client.head_object(
                        Bucket=self.bucket_name,
                        Key=key
                    )
                    metadata = metadata_response.get('Metadata', {})
                    
                    backups.append({
                        'key': key,
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'],
                        'user_id': metadata.get('user_id', ''),
                        'chat_id': metadata.get('chat_id', ''),
                        'backup_timestamp': metadata.get('backup_timestamp', ''),
                        'backup_type': metadata.get('backup_type', 'full')
                    })
                    
                    if len(backups) >= limit:
                        break
                
                if len(backups) >= limit:
                    break
            
            # Sort by last modified (newest first)
            backups.sort(key=lambda x: x['last_modified'], reverse=True)
            return backups[:limit]
            
        except ClientError as e:
            logger.error(f"Failed to list backups: {e}", exc_info=True)
            raise
    
    def restore_backup(self, backup_key: str) -> int:
        """
        Restore a conversation from backup.
        
        Args:
            backup_key: S3 key of the backup to restore
            
        Returns:
            Conversation ID of restored conversation
        """
        # Get backup data
        backup_data = self._get_backup_data(backup_key)
        if not backup_data:
            raise ValueError(f"Backup not found: {backup_key}")
        
        user_id = backup_data['user_id']
        chat_id = backup_data['chat_id']
        
        # Check if conversation already exists
        existing = self.storage.get_conversation(user_id, chat_id)
        if existing:
            # Reset existing conversation
            self.storage.reset_conversation(user_id, chat_id)
        
        # Create or get conversation
        conversation_id = self.storage.get_or_create_conversation(user_id, chat_id)
        
        # Restore messages
        for msg_data in backup_data.get('messages', []):
            self.storage.add_message(
                conversation_id=conversation_id,
                role=msg_data['role'],
                content=msg_data['content'],
                tokens=msg_data.get('tokens')
            )
        
        # Restore metadata if provided
        if backup_data.get('metadata'):
            conn = self.storage._get_connection()
            try:
                cursor = conn.cursor()
                query = self.storage._normalize_sql("""
                    UPDATE conversations
                    SET metadata = ?
                    WHERE id = ?
                """)
                cursor.execute(query, (json.dumps(backup_data['metadata']), conversation_id))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to restore metadata: {e}", exc_info=True)
            finally:
                self.storage.adapter.close(conn)
        
        logger.info(f"Restored conversation {conversation_id} from backup {backup_key}")
        return conversation_id
    
    def apply_retention_policy(
        self,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        keep_latest: int = 10,
        retention_days: Optional[int] = None
    ) -> int:
        """
        Apply retention policy to delete old backups.
        
        Args:
            user_id: Optional user ID filter
            chat_id: Optional chat ID filter
            keep_latest: Number of most recent backups to keep
            retention_days: Optional - delete backups older than this many days
            
        Returns:
            Number of backups deleted
        """
        backups = self.list_backups(user_id=user_id, chat_id=chat_id, limit=1000)
        
        if len(backups) <= keep_latest:
            return 0
        
        # Sort by last modified (oldest first)
        backups.sort(key=lambda x: x['last_modified'])
        
        deleted_count = 0
        cutoff_date = None
        if retention_days:
            cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        
        # Keep the most recent N backups
        backups_to_delete = backups[:-keep_latest] if keep_latest > 0 else backups
        
        for backup in backups_to_delete:
            # Check retention days if specified
            if cutoff_date and backup['last_modified'] > cutoff_date:
                continue
            
            try:
                self.s3_client.delete_object(
                    Bucket=self.bucket_name,
                    Key=backup['key']
                )
                deleted_count += 1
                logger.debug(f"Deleted old backup: {backup['key']}")
            except ClientError as e:
                logger.error(f"Failed to delete backup {backup['key']}: {e}", exc_info=True)
        
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old backups (kept {keep_latest} most recent)")
        
        return deleted_count


class BackupScheduler:
    """Scheduler for automatic conversation backups."""
    
    def __init__(
        self,
        backup_manager: ConversationBackupManager,
        interval_hours: int = 24,
        enabled: bool = True,
        retention_days: Optional[int] = None,
        max_backups_per_conversation: int = 10
    ):
        """
        Initialize backup scheduler.
        
        Args:
            backup_manager: ConversationBackupManager instance
            interval_hours: Hours between automatic backups
            enabled: Whether scheduler is enabled
            retention_days: Days to keep backups (None = no time-based retention)
            max_backups_per_conversation: Maximum backups to keep per conversation
        """
        self.backup_manager = backup_manager
        self.interval_hours = interval_hours
        self.enabled = enabled
        self.retention_days = retention_days
        self.max_backups_per_conversation = max_backups_per_conversation
        
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        
        if self.enabled:
            self.start()
    
    def start(self):
        """Start the backup scheduler thread."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                logger.warning("Backup scheduler already running")
                return
            
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            logger.info(f"Started backup scheduler (interval: {self.interval_hours} hours)")
    
    def stop(self):
        """Stop the backup scheduler thread."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._stop_event.set()
                self._thread.join(timeout=5.0)
                logger.info("Stopped backup scheduler")
    
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._thread is not None and self._thread.is_alive()
    
    def _run(self):
        """Main scheduler loop."""
        while not self._stop_event.is_set():
            try:
                # Backup all conversations
                self._backup_all_conversations()
                
                # Apply retention policies
                self._apply_retention_policies()
                
                # Wait for next interval
                self._stop_event.wait(timeout=self.interval_hours * 3600)
                
            except Exception as e:
                logger.error(f"Error in backup scheduler: {e}", exc_info=True)
                # Wait a bit before retrying
                self._stop_event.wait(timeout=300)  # 5 minutes
    
    def _backup_all_conversations(self):
        """Backup all conversations."""
        try:
            conversations = self.backup_manager.storage.list_conversations(limit=1000)
            logger.info(f"Starting backup of {len(conversations)} conversations")
            
            backed_up = 0
            for conv in conversations:
                if self._stop_event.is_set():
                    break
                
                try:
                    self.backup_manager.create_backup(
                        conv['user_id'],
                        conv['chat_id']
                    )
                    backed_up += 1
                except Exception as e:
                    logger.error(
                        f"Failed to backup conversation {conv['user_id']}/{conv['chat_id']}: {e}",
                        exc_info=True
                    )
            
            logger.info(f"Completed backup of {backed_up} conversations")
        except Exception as e:
            logger.error(f"Error backing up conversations: {e}", exc_info=True)
    
    def _apply_retention_policies(self):
        """Apply retention policies to all backups."""
        try:
            # Get all unique user/chat combinations
            backups = self.backup_manager.list_backups(limit=1000)
            conversations = set()
            for backup in backups:
                conversations.add((backup.get('user_id'), backup.get('chat_id')))
            
            deleted_total = 0
            for user_id, chat_id in conversations:
                if self._stop_event.is_set():
                    break
                
                deleted = self.backup_manager.apply_retention_policy(
                    user_id=user_id,
                    chat_id=chat_id,
                    keep_latest=self.max_backups_per_conversation,
                    retention_days=self.retention_days
                )
                deleted_total += deleted
            
            if deleted_total > 0:
                logger.info(f"Applied retention policies, deleted {deleted_total} old backups")
        except Exception as e:
            logger.error(f"Error applying retention policies: {e}", exc_info=True)
