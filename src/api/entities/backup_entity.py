"""
Backup entity for backup and restore operations.
"""
from typing import Dict, Any, Optional
from fastapi import HTTPException
from api.entities.base_entity import BaseEntity
import logging

logger = logging.getLogger(__name__)


class BackupEntity(BaseEntity):
    """Entity class for backup-related operations."""
    
    def __init__(self, db, backup_manager, auth_info: Optional[Dict[str, Any]] = None):
        """
        Initialize backup entity.
        
        Args:
            db: Database instance
            backup_manager: BackupManager instance
            auth_info: Authentication information (optional for backups)
        """
        super().__init__(db, auth_info)
        self.backup_manager = backup_manager
    
    def create(self, snapshot_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a backup archive.
        
        POST /api/Backup/create
        Body: {"snapshot_name": "optional_name"} (optional)
        """
        try:
            backup_path = self.backup_manager.create_backup_archive(snapshot_name=snapshot_name)
            return {
                "success": True,
                "backup_path": backup_path
            }
        except Exception as e:
            self._handle_error(e, "Failed to create backup")
    
    def list(self) -> Dict[str, Any]:
        """
        List all available backups.
        
        GET /api/Backup/list
        """
        try:
            backups = self.backup_manager.list_backups()
            return {
                "backups": backups,
                "count": len(backups)
            }
        except Exception as e:
            self._handle_error(e, "Failed to list backups")
    
    def restore(self, backup_path: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """
        Restore from a backup.
        
        POST /api/Backup/restore
        Body: {"backup_path": "path/to/backup.db.gz", "force": false} (optional)
        """
        try:
            if backup_path:
                # Restore from specific backup
                success = self.backup_manager.restore_from_backup(backup_path, force=force)
            else:
                # Restore from most recent backup
                backups = self.backup_manager.list_backups()
                if not backups:
                    raise ValueError("No backups available to restore")
                # Get most recent backup
                most_recent = backups[0]["path"]
                success = self.backup_manager.restore_from_backup(most_recent, force=force)
            
            if not success:
                raise ValueError("Restore operation failed")
            
            return {
                "success": True,
                "message": "Backup restored successfully"
            }
        except Exception as e:
            self._handle_error(e, "Failed to restore backup")

