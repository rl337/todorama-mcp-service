"""
Tests for backup and restore functionality.
"""
import pytest
import os
import tempfile
import shutil
import sqlite3
import gzip
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import TodoDatabase
from backup import BackupManager


@pytest.fixture
def temp_setup():
    """Create temporary database and backup directory."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    backups_dir = os.path.join(temp_dir, "backups")
    
    # Create database with some data
    db = TodoDatabase(db_path)
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Verify it",
        agent_id="test-agent"
    )
    db.complete_task(task_id, "test-agent")
    
    backup_manager = BackupManager(db_path, backups_dir)
    
    yield db, db_path, backups_dir, backup_manager
    
    shutil.rmtree(temp_dir)


def test_create_snapshot(temp_setup):
    """Test creating a database snapshot."""
    _, db_path, backups_dir, backup_manager = temp_setup
    
    snapshot_path = backup_manager.create_snapshot()
    
    assert os.path.exists(snapshot_path)
    assert snapshot_path.endswith(".db")
    
    # Verify snapshot is valid SQLite database
    conn = sqlite3.connect(snapshot_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tasks")
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count == 1


def test_create_backup_archive(temp_setup):
    """Test creating gzip backup archive."""
    _, db_path, backups_dir, backup_manager = temp_setup
    
    archive_path = backup_manager.create_backup_archive()
    
    assert os.path.exists(archive_path)
    assert archive_path.endswith(".db.gz")
    
    # Verify archive is valid gzip
    with gzip.open(archive_path, 'rb') as f:
        data = f.read()
        assert len(data) > 0
    
    # Extract and verify database
    temp_db = os.path.join(backups_dir, "test_extract.db")
    with gzip.open(archive_path, 'rb') as f_in:
        with open(temp_db, 'wb') as f_out:
            f_out.write(f_in.read())
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tasks")
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count == 1
    os.unlink(temp_db)


def test_restore_from_backup(temp_setup):
    """Test restoring from backup archive."""
    db, db_path, backups_dir, backup_manager = temp_setup
    
    # Create backup
    archive_path = backup_manager.create_backup_archive()
    
    # Add more data to original database
    task_id2 = db.create_task(
        title="Task 2",
        task_type="concrete",
        task_instruction="Do something else",
        verification_instruction="Verify it",
        agent_id="test-agent"
    )
    
    # Verify we have 2 tasks now
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tasks")
    count_before = cursor.fetchone()[0]
    conn.close()
    assert count_before == 2
    
    # Restore from backup (should have 1 task)
    backup_manager.restore_from_backup(archive_path, force=True)
    
    # Verify restoration
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tasks")
    count_after = cursor.fetchone()[0]
    conn.close()
    
    assert count_after == 1


def test_restore_requires_force(temp_setup):
    """Test that restore requires force if database has data."""
    _, db_path, backups_dir, backup_manager = temp_setup
    
    # Create backup
    archive_path = backup_manager.create_backup_archive()
    
    # Try to restore without force (should fail)
    with pytest.raises(ValueError, match="Database has"):
        backup_manager.restore_from_backup(archive_path, force=False)
    
    # Restore with force (should succeed)
    backup_manager.restore_from_backup(archive_path, force=True)


def test_list_backups(temp_setup):
    """Test listing backups."""
    _, db_path, backups_dir, backup_manager = temp_setup
    
    # Create multiple backups
    backup1 = backup_manager.create_backup_archive()
    backup2 = backup_manager.create_backup_archive()
    
    # List backups
    backups = backup_manager.list_backups()
    
    assert len(backups) >= 2
    assert all("filename" in b for b in backups)
    assert all("path" in b for b in backups)
    assert all("size_bytes" in b for b in backups)
    assert all("created_at" in b for b in backups)


def test_cleanup_old_backups(temp_setup, monkeypatch):
    """Test cleaning up old backups."""
    _, db_path, backups_dir, backup_manager = temp_setup
    
    # Create backup
    backup_path = backup_manager.create_backup_archive()
    
    # Make backup file old (31 days)
    import time
    old_time = time.time() - (31 * 24 * 60 * 60)
    os.utime(backup_path, (old_time, old_time))
    
    # Cleanup (keep 30 days)
    deleted = backup_manager.cleanup_old_backups(keep_days=30)
    
    assert deleted == 1
    assert not os.path.exists(backup_path)

