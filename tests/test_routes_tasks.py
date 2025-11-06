"""
Isolated tests for task routes to diagnose routing issues.
Tests the router in isolation without full app context.
"""
import pytest
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import Mock, MagicMock, patch
from api.routes import tasks
from models.task_models import TaskCreate, TaskResponse


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = Mock()
    db.get_project.return_value = {"id": 1, "name": "Test Project"}
    db.get_task.return_value = {"id": 1, "title": "Test Task", "task_type": "concrete"}
    db.create_task.return_value = 1
    return db


@pytest.fixture
def mock_task_service(mock_db):
    """Create a mock task service."""
    service = Mock()
    service.create_task.return_value = {"id": 1, "title": "Test Task", "task_type": "concrete"}
    service.get_task.return_value = {"id": 1, "title": "Test Task", "task_type": "concrete"}
    return service


@pytest.fixture
def app_with_tasks_router():
    """Create a minimal FastAPI app with only the tasks router."""
    app = FastAPI()
    app.include_router(tasks.router)
    return app


@pytest.fixture
def client(app_with_tasks_router):
    """Create a test client for the isolated app."""
    return TestClient(app_with_tasks_router)


def test_tasks_router_registered(app_with_tasks_router):
    """Test that the tasks router is registered."""
    # Get all routes
    routes = []
    for route in app_with_tasks_router.routes:
        if hasattr(route, 'path'):
            routes.append(route.path)
    
    print(f"\nRegistered routes: {routes}")
    
    # Check that task routes exist
    assert any('/tasks' in r for r in routes), f"No /tasks route found. Routes: {routes}"
    assert any('/tasks/{' in r or r == '/tasks' for r in routes), f"No /tasks endpoint found. Routes: {routes}"


def test_create_task_route_exists(client):
    """Test that POST /tasks route exists."""
    # Try to get route info
    with patch('dependencies.services.get_db') as mock_get_db, \
         patch('services.task_service.TaskService') as mock_service_class:
            
            mock_db = Mock()
            mock_get_db.return_value = mock_db
            
            mock_service = Mock()
            mock_service.create_task.return_value = {
                "id": 1,
                "title": "Test Task",
                "task_type": "concrete",
                "task_instruction": "Do something",
                "verification_instruction": "Verify it",
                "agent_id": "test-agent",
                "project_id": 1
            }
            mock_service_class.return_value = mock_service
            
            # Check if route exists by trying to access it
            # This will fail with 422 (validation) or 401 (auth) but not 404 if route exists
            response = client.post("/tasks", json={
            "task": {
                "title": "Test Task",
                "task_type": "concrete",
                "task_instruction": "Do something",
                "verification_instruction": "Verify it",
                "agent_id": "test-agent",
                "project_id": 1
            }
            })
            
            print(f"\nPOST /tasks response status: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            
            # Route exists if we get validation/auth error, not 404
            assert response.status_code != 404, f"Route not found (404). Available routes: {[r.path for r in client.app.routes if hasattr(r, 'path')]}"


def test_get_task_route_exists(client):
    """Test that GET /tasks/{task_id} route exists."""
    with patch('dependencies.services.get_db') as mock_get_db, \
         patch('services.task_service.TaskService') as mock_service_class:
            
            mock_db = Mock()
            mock_get_db.return_value = mock_db
            
            mock_service = Mock()
            mock_service.get_task.return_value = {
                "id": 1,
                "title": "Test Task",
                "task_type": "concrete"
            }
            mock_service_class.return_value = mock_service
            
            response = client.get("/tasks/1")
            
            print(f"\nGET /tasks/1 response status: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            
            # Route exists if we get auth/validation error, not 404
            assert response.status_code != 404, f"Route not found (404). Available routes: {[r.path for r in client.app.routes if hasattr(r, 'path')]}"


def test_list_all_routes(client):
    """List all routes in the app for debugging."""
    routes_info = []
    for route in client.app.routes:
        if hasattr(route, 'path'):
            methods = getattr(route, 'methods', set())
            routes_info.append({
                'path': route.path,
                'methods': list(methods) if methods else None,
                'name': getattr(route, 'name', None)
            })
    
    print(f"\n=== All Routes in App ===")
    for route in routes_info:
        print(f"  {route['methods']} {route['path']} (name: {route['name']})")
    
    # This test always passes - it's just for debugging
    assert True

