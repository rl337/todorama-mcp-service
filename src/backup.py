"""
Backup and restore functionality for TODO service.

Provides snapshot creation, scheduled backups, and restore capabilities.
"""
import os
import shutil
import gzip
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import threading
import time

logger = logging.getLogger(__name__)


class BackupManager:
    """Manages database backups and restores."""
    
    def __init__(self, db_path: str, backups_dir: str = "backups"):
        """Initialize backup manager.
        
        Args:
            db_path: Path to SQLite database
            backups_dir: Directory to store backups
        """
        self.db_path = Path(db_path)
        self.backups_dir = Path(backups_dir)
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        self._backup_lock = threading.Lock()
    
    def create_snapshot(self, snapshot_name: Optional[str] = None) -> str:
        """
        Create a snapshot of the database.
        
        Args:
            snapshot_name: Optional custom name for snapshot (defaults to timestamp)
            
        Returns:
            Path to the snapshot file
        """
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        
        if snapshot_name:
            snapshot_file = self.backups_dir / f"{snapshot_name}.db"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            snapshot_file = self.backups_dir / f"snapshot_{timestamp}.db"
        
        # Use SQLite backup API for safe copying
        logger.info(f"Creating snapshot: {snapshot_file}")
        
        try:
            # Connect to source database
            source_conn = sqlite3.connect(str(self.db_path))
            
            # Create backup database
            backup_conn = sqlite3.connect(str(snapshot_file))
            
            # Use SQLite backup API
            source_conn.backup(backup_conn)
            
            # Close connections
            backup_conn.close()
            source_conn.close()
            
            logger.info(f"Snapshot created: {snapshot_file}")
            return str(snapshot_file)
        except Exception as e:
            logger.error(f"Failed to create snapshot: {e}")
            # Clean up on failure
            if snapshot_file.exists():
                snapshot_file.unlink()
            raise
    
    def create_backup_archive(self, snapshot_name: Optional[str] = None) -> str:
        """
        Create a gzip-compressed backup archive.
        
        Args:
            snapshot_name: Optional custom name for snapshot
            
        Returns:
            Path to the gzip archive
        """
        with self._backup_lock:
            # Create snapshot first
            snapshot_path = self.create_snapshot(snapshot_name)
            
            # Create gzip archive
            if snapshot_name:
                archive_name = f"{snapshot_name}.db.gz"
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_name = f"backup_{timestamp}.db.gz"
            
            archive_path = self.backups_dir / archive_name
            
            logger.info(f"Creating backup archive: {archive_path}")
            
            try:
                with open(snapshot_path, 'rb') as f_in:
                    with gzip.open(archive_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                # Remove uncompressed snapshot
                Path(snapshot_path).unlink()
                
                logger.info(f"Backup archive created: {archive_path}")
                return str(archive_path)
            except Exception as e:
                logger.error(f"Failed to create backup archive: {e}")
                # Clean up on failure
                if archive_path.exists():
                    archive_path.unlink()
                raise
    
    def restore_from_backup(self, backup_path: str, force: bool = False) -> bool:
        """
        Restore database from a backup archive or snapshot.
        
        Args:
            backup_path: Path to backup file (.db.gz, .db, or .gz)
            force: If True, restore even if database exists and has data
            
        Returns:
            True if successful
        """
        backup_path = Path(backup_path)
        
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")
        
        # Check if database exists and has data
        if not force and self.db_path.exists():
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tasks")
            task_count = cursor.fetchone()[0]
            conn.close()
            
            if task_count > 0:
                raise ValueError(
                    f"Database has {task_count} tasks. Use force=True to restore anyway."
                )
        
        logger.info(f"Restoring from backup: {backup_path}")
        
        try:
            # Determine if it's compressed
            if backup_path.suffix == '.gz':
                # Extract gzip archive
                temp_db = self.backups_dir / f"restore_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                with gzip.open(backup_path, 'rb') as f_in:
                    with open(temp_db, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                source_path = temp_db
            elif backup_path.suffix == '.db':
                source_path = backup_path
            else:
                raise ValueError(f"Unsupported backup format: {backup_path.suffix}")
            
            # Create backup of current database if it exists
            if self.db_path.exists():
                old_backup = self.backups_dir / f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                shutil.copy2(self.db_path, old_backup)
                logger.info(f"Created backup of current database: {old_backup}")
            
            # Restore database
            shutil.copy2(source_path, self.db_path)
            
            # Clean up temp file if created
            if source_path != backup_path and source_path.exists():
                source_path.unlink()
            
            # Verify restoration
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM tasks")
            task_count = cursor.fetchone()[0]
            conn.close()
            
            logger.info(f"Database restored successfully. Task count: {task_count}")
            return True
        except Exception as e:
            logger.error(f"Failed to restore database: {e}")
            raise
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """
        List all available backups.
        
        Returns:
            List of backup info dictionaries
        """
        backups = []
        
        for backup_file in sorted(self.backups_dir.glob("*.db.gz"), reverse=True):
            stat = backup_file.stat()
            backups.append({
                "filename": backup_file.name,
                "path": str(backup_file),
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "type": "gzip"
            })
        
        # Also list uncompressed snapshots
        for snapshot_file in sorted(self.backups_dir.glob("snapshot_*.db"), reverse=True):
            stat = snapshot_file.stat()
            backups.append({
                "filename": snapshot_file.name,
                "path": str(snapshot_file),
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "type": "snapshot"
            })
        
        return backups
    
    def cleanup_old_backups(self, keep_days: int = 30) -> int:
        """
        Clean up backups older than specified days.
        
        Args:
            keep_days: Number of days to keep backups
            
        Returns:
            Number of backups deleted
        """
        cutoff_time = time.time() - (keep_days * 24 * 60 * 60)
        deleted_count = 0
        
        for backup_file in self.backups_dir.glob("*.db.gz"):
            if backup_file.stat().st_mtime < cutoff_time:
                try:
                    backup_file.unlink()
                    deleted_count += 1
                    logger.info(f"Deleted old backup: {backup_file.name}")
                except Exception as e:
                    logger.error(f"Failed to delete backup {backup_file.name}: {e}")
        
        return deleted_count


class BackupScheduler:
    """Schedules and manages automatic backups."""
    
    def __init__(self, backup_manager: BackupManager, backup_interval_hours: int = 24):
        """Initialize backup scheduler.
        
        Args:
            backup_manager: BackupManager instance
            backup_interval_hours: Hours between backups (default: 24 for nightly)
        """
        self.backup_manager = backup_manager
        self.backup_interval_hours = backup_interval_hours
        self.running = False
        self._thread: Optional[threading.Thread] = None
    
    def start(self):
        """Start the backup scheduler."""
        if self.running:
            logger.warning("Backup scheduler already running")
            return
        
        self.running = True
        self._thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._thread.start()
        logger.info(f"Backup scheduler started (interval: {self.backup_interval_hours} hours)")
    
    def stop(self):
        """Stop the backup scheduler."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Backup scheduler stopped")
    
    def _run_scheduler(self):
        """Run the backup scheduler loop."""
        while self.running:
            try:
                # Create nightly backup
                self.backup_manager.create_backup_archive()
                
                # Cleanup old backups (keep 30 days)
                self.backup_manager.cleanup_old_backups(keep_days=30)
                
                # Sleep until next backup
                sleep_seconds = self.backup_interval_hours * 3600
                for _ in range(sleep_seconds):
                    if not self.running:
                        break
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error in backup scheduler: {e}")
                # Sleep 1 hour before retrying
                time.sleep(3600)

