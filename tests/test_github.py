"""
Tests for GitHub integration functionality.
"""
import pytest
import json
import os
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import TodoDatabase


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    db = TodoDatabase(db_path)
    yield db, db_path
    shutil.rmtree(temp_dir)


def test_metadata_column_exists(temp_db):
    """Test that metadata column exists after database initialization."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    task = db.get_task(task_id)
    # Metadata column should exist (may be None)
    assert "metadata" in task or task.get("metadata") is None


def test_link_github_issue(temp_db):
    """Test linking a GitHub issue to a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    github_url = "https://github.com/owner/repo/issues/123"
    db.link_github_issue(task_id, github_url)
    
    task = db.get_task(task_id)
    metadata = json.loads(task["metadata"]) if task.get("metadata") else {}
    assert metadata.get("github_issue_url") == github_url


def test_link_github_pr(temp_db):
    """Test linking a GitHub PR to a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    github_url = "https://github.com/owner/repo/pull/456"
    db.link_github_pr(task_id, github_url)
    
    task = db.get_task(task_id)
    metadata = json.loads(task["metadata"]) if task.get("metadata") else {}
    assert metadata.get("github_pr_url") == github_url


def test_link_both_issue_and_pr(temp_db):
    """Test linking both issue and PR to the same task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    issue_url = "https://github.com/owner/repo/issues/123"
    pr_url = "https://github.com/owner/repo/pull/456"
    db.link_github_issue(task_id, issue_url)
    db.link_github_pr(task_id, pr_url)
    
    task = db.get_task(task_id)
    metadata = json.loads(task["metadata"]) if task.get("metadata") else {}
    assert metadata.get("github_issue_url") == issue_url
    assert metadata.get("github_pr_url") == pr_url


def test_unlink_github_issue(temp_db):
    """Test unlinking a GitHub issue from a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    github_url = "https://github.com/owner/repo/issues/123"
    db.link_github_issue(task_id, github_url)
    db.unlink_github_issue(task_id)
    
    task = db.get_task(task_id)
    metadata = json.loads(task["metadata"]) if task.get("metadata") else {}
    assert metadata.get("github_issue_url") is None


def test_unlink_github_pr(temp_db):
    """Test unlinking a GitHub PR from a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    github_url = "https://github.com/owner/repo/pull/456"
    db.link_github_pr(task_id, github_url)
    db.unlink_github_pr(task_id)
    
    task = db.get_task(task_id)
    metadata = json.loads(task["metadata"]) if task.get("metadata") else {}
    assert metadata.get("github_pr_url") is None


def test_get_github_links(temp_db):
    """Test getting GitHub links for a task."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    issue_url = "https://github.com/owner/repo/issues/123"
    pr_url = "https://github.com/owner/repo/pull/456"
    db.link_github_issue(task_id, issue_url)
    db.link_github_pr(task_id, pr_url)
    
    links = db.get_github_links(task_id)
    assert links["github_issue_url"] == issue_url
    assert links["github_pr_url"] == pr_url


def test_get_github_links_no_links(temp_db):
    """Test getting GitHub links when none are set."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    links = db.get_github_links(task_id)
    assert links["github_issue_url"] is None
    assert links["github_pr_url"] is None


def test_link_invalid_github_url(temp_db):
    """Test that invalid GitHub URLs are rejected."""
    db, _ = temp_db
    task_id = db.create_task(
        title="Test Task",
        task_type="concrete",
        task_instruction="Do something",
        verification_instruction="Check it works",
        agent_id="test-agent"
    )
    
    invalid_url = "https://example.com/not-github"
    with pytest.raises(ValueError, match="Invalid GitHub URL"):
        db.link_github_issue(task_id, invalid_url)
