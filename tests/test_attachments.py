"""
Tests for file attachment functionality.
"""
import pytest
import os
import tempfile
import shutil
from io import BytesIO
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from main import app
from database import TodoDatabase
from backup import BackupManager


@pytest.fixture
def temp_db():
    """Create temporary database and file storage for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    backups_dir = os.path.join(temp_dir, "backups")
    attachments_dir = os.path.join(temp_dir, "attachments")
    os.makedirs(attachments_dir, exist_ok=True)
    
    # Create database
    db = TodoDatabase(db_path)
    backup_manager = BackupManager(db_path, backups_dir)
    
    # Override the database and backup manager in the app
    import main
    main.db = db
    main.backup_manager = backup_manager
    
    # Set attachments directory
    os.environ["TODO_ATTACHMENTS_DIR"] = attachments_dir
    
    yield db, db_path, backups_dir, attachments_dir
    
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def task_id(client):
    """Create a test task and return its ID."""
    response = client.post("/tasks", json={
        "title": "Test Task",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    return response.json()["id"]


def test_upload_attachment_to_task(client, task_id):
    """Test uploading a file attachment to a task."""
    # Create a test file
    file_content = b"Test file content"
    file_data = {"file": ("test.txt", BytesIO(file_content), "text/plain")}
    
    response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert "attachment_id" in data
    assert data["filename"] == "test.txt"
    assert data["file_size"] == len(file_content)
    assert data["content_type"] == "text/plain"


def test_upload_attachment_with_description(client, task_id):
    """Test uploading an attachment with a description."""
    file_content = b"Test file"
    file_data = {"file": ("test.txt", BytesIO(file_content), "text/plain")}
    
    response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent", "description": "Test attachment"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["description"] == "Test attachment"


def test_upload_attachment_to_nonexistent_task(client):
    """Test uploading to a nonexistent task."""
    file_content = b"Test file"
    file_data = {"file": ("test.txt", BytesIO(file_content), "text/plain")}
    
    response = client.post(
        "/tasks/99999/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    assert response.status_code == 404


def test_upload_attachment_file_size_limit(client, task_id):
    """Test that file size limits are enforced."""
    # Create a file larger than limit (assuming 10MB default)
    large_content = b"x" * (11 * 1024 * 1024)  # 11MB
    file_data = {"file": ("large.txt", BytesIO(large_content), "text/plain")}
    
    response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    assert response.status_code == 413  # Payload Too Large


def test_upload_attachment_invalid_file_type(client, task_id):
    """Test that invalid file types are rejected."""
    file_content = b"executable content"
    file_data = {"file": ("script.exe", BytesIO(file_content), "application/x-msdownload")}
    
    response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    # Should reject executable files
    assert response.status_code in [400, 415]  # Bad Request or Unsupported Media Type


def test_list_task_attachments(client, task_id):
    """Test listing attachments for a task."""
    # Upload multiple attachments
    for i in range(3):
        file_content = f"File {i}".encode()
        file_data = {"file": (f"test_{i}.txt", BytesIO(file_content), "text/plain")}
        client.post(
            f"/tasks/{task_id}/attachments",
            files=file_data,
            data={"agent_id": "test-agent"}
        )
    
    # List attachments
    response = client.get(f"/tasks/{task_id}/attachments")
    assert response.status_code == 200
    data = response.json()
    assert "attachments" in data
    assert len(data["attachments"]) == 3


def test_download_attachment(client, task_id):
    """Test downloading a file attachment."""
    # Upload attachment
    file_content = b"Download test content"
    file_data = {"file": ("download_test.txt", BytesIO(file_content), "text/plain")}
    upload_response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    attachment_id = upload_response.json()["attachment_id"]
    
    # Download attachment
    response = client.get(f"/tasks/{task_id}/attachments/{attachment_id}/download")
    assert response.status_code == 200
    assert response.content == file_content
    assert "Content-Disposition" in response.headers
    assert "download_test.txt" in response.headers["Content-Disposition"]


def test_download_attachment_nonexistent(client, task_id):
    """Test downloading a nonexistent attachment."""
    response = client.get(f"/tasks/{task_id}/attachments/99999/download")
    assert response.status_code == 404


def test_download_attachment_wrong_task(client, task_id):
    """Test downloading attachment from wrong task."""
    # Create another task
    response2 = client.post("/tasks", json={
        "title": "Task 2",
        "task_type": "concrete",
        "task_instruction": "Test",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
    task2_id = response2.json()["id"]
    
    # Upload to task 1
    file_data = {"file": ("test.txt", BytesIO(b"content"), "text/plain")}
    upload_response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    attachment_id = upload_response.json()["attachment_id"]
    
    # Try to download from task 2
    response = client.get(f"/tasks/{task2_id}/attachments/{attachment_id}/download")
    assert response.status_code == 404


def test_delete_attachment(client, task_id):
    """Test deleting a file attachment."""
    # Upload attachment
    file_data = {"file": ("delete_test.txt", BytesIO(b"content"), "text/plain")}
    upload_response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    attachment_id = upload_response.json()["attachment_id"]
    
    # Delete attachment
    response = client.delete(f"/tasks/{task_id}/attachments/{attachment_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Verify deleted (list should be empty)
    list_response = client.get(f"/tasks/{task_id}/attachments")
    assert len(list_response.json()["attachments"]) == 0
    
    # Verify file deleted from disk
    response = client.get(f"/tasks/{task_id}/attachments/{attachment_id}/download")
    assert response.status_code == 404


def test_delete_attachment_nonexistent(client, task_id):
    """Test deleting a nonexistent attachment."""
    response = client.delete(f"/tasks/{task_id}/attachments/99999")
    assert response.status_code == 404


def test_get_attachment_metadata(client, task_id):
    """Test getting attachment metadata."""
    # Upload attachment
    file_data = {"file": ("metadata_test.txt", BytesIO(b"content"), "text/plain")}
    upload_response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent", "description": "Test metadata"}
    )
    attachment_id = upload_response.json()["attachment_id"]
    
    # Get metadata
    response = client.get(f"/tasks/{task_id}/attachments/{attachment_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == attachment_id
    assert data["filename"] == "metadata_test.txt"
    assert data["description"] == "Test metadata"
    assert "file_size" in data
    assert "content_type" in data
    assert "created_at" in data


def test_upload_multiple_file_types(client, task_id):
    """Test uploading various file types."""
    file_types = [
        ("test.txt", b"text content", "text/plain"),
        ("test.json", b'{"key": "value"}', "application/json"),
        ("test.pdf", b"%PDF-1.4 fake pdf", "application/pdf"),
        ("test.png", b"\x89PNG fake image", "image/png"),
    ]
    
    for filename, content, content_type in file_types:
        file_data = {"file": (filename, BytesIO(content), content_type)}
        response = client.post(
            f"/tasks/{task_id}/attachments",
            files=file_data,
            data={"agent_id": "test-agent"}
        )
        assert response.status_code == 201, f"Failed to upload {filename}"
    
    # Verify all uploaded
    response = client.get(f"/tasks/{task_id}/attachments")
    assert len(response.json()["attachments"]) == 4


def test_attachment_association_with_task_update(client, task_id):
    """Test that attachments can be associated with task updates."""
    # Upload attachment
    file_data = {"file": ("update_file.txt", BytesIO(b"update content"), "text/plain")}
    upload_response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    attachment_id = upload_response.json()["attachment_id"]
    
    # Add task update with attachment reference
    response = client.post("/mcp/add_task_update", json={
        "task_id": task_id,
        "agent_id": "test-agent",
        "content": "Progress update with attachment",
        "update_type": "progress",
        "metadata": {"attachment_id": attachment_id}
    })
    assert response.status_code == 200


def test_attachment_preserved_on_task_completion(client, task_id):
    """Test that attachments are preserved when task is completed."""
    # Upload attachment
    file_content = b"persistent content"
    file_data = {"file": ("persistent.txt", BytesIO(file_content), "text/plain")}
    upload_response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    attachment_id = upload_response.json()["attachment_id"]
    
    # Complete task
    client.post(f"/tasks/{task_id}/lock", json={"agent_id": "test-agent"})
    client.post(f"/tasks/{task_id}/complete", json={"agent_id": "test-agent"})
    
    # Verify attachment still accessible
    response = client.get(f"/tasks/{task_id}/attachments")
    assert len(response.json()["attachments"]) == 1
    
    download_response = client.get(f"/tasks/{task_id}/attachments/{attachment_id}/download")
    assert download_response.content == file_content


def test_attachment_file_path_security(client, task_id):
    """Test that file paths are secure (no directory traversal)."""
    # Try to upload with malicious filename
    file_data = {"file": ("../../../etc/passwd", BytesIO(b"malicious"), "text/plain")}
    response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    
    # Should sanitize filename
    if response.status_code == 201:
        data = response.json()
        assert "../../../etc/passwd" not in data["filename"]
        assert "passwd" not in data.get("file_path", "")


def test_attachment_unique_filenames(client, task_id):
    """Test that duplicate filenames are handled."""
    # Upload same filename twice
    file_content = b"first"
    file_data = {"file": ("duplicate.txt", BytesIO(file_content), "text/plain")}
    response1 = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    assert response1.status_code == 201
    
    file_content2 = b"second"
    file_data2 = {"file": ("duplicate.txt", BytesIO(file_content2), "text/plain")}
    response2 = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data2,
        data={"agent_id": "test-agent"}
    )
    assert response2.status_code == 201
    
    # Both should be stored with unique identifiers
    attachments = client.get(f"/tasks/{task_id}/attachments").json()["attachments"]
    assert len(attachments) == 2
    # Filenames might be the same but IDs should differ
    assert attachments[0]["id"] != attachments[1]["id"]


def test_empty_file_upload(client, task_id):
    """Test uploading an empty file."""
    file_data = {"file": ("empty.txt", BytesIO(b""), "text/plain")}
    response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["file_size"] == 0


def test_attachment_with_special_characters_in_filename(client, task_id):
    """Test uploading file with special characters in filename."""
    file_data = {"file": ("test file (1).txt", BytesIO(b"content"), "text/plain")}
    response = client.post(
        f"/tasks/{task_id}/attachments",
        files=file_data,
        data={"agent_id": "test-agent"}
    )
    # Should handle or sanitize special characters
    assert response.status_code in [201, 400]

