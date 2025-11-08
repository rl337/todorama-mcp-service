"""
Mock-based unit tests for MCP route handlers.
Tests the HTTP layer in isolation without real database or HTTP connections.
"""
import pytest
import sys
import os

# Add src to path BEFORE importing FastAPI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from unittest.mock import Mock, MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import mcp


@pytest.fixture
def app():
    """Create a FastAPI app with MCP router."""
    app = FastAPI()
    app.include_router(mcp.router)
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestCreateTask:
    """Test POST /mcp/create_task endpoint."""
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_create_task_success(self, mock_mcp_api, client):
        """Test successful task creation."""
        mock_mcp_api.create_task.return_value = {
            "success": True,
            "task_id": 1,
            "relationship_id": None
        }
        
        response = client.post(
            "/mcp/create_task",
            json={
                "title": "Test Task",
                "task_type": "concrete",
                "task_instruction": "Do something",
                "verification_instruction": "Verify it",
                "agent_id": "test-agent",
                "project_id": 1
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["task_id"] == 1
        mock_mcp_api.create_task.assert_called_once()
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_create_task_validation_error(self, mock_mcp_api_class, client):
        """Test task creation with validation error."""
        # Missing required fields
        response = client.post("/mcp/create_task", json={})
        
        assert response.status_code == 422  # Validation error


class TestGetAgentPerformance:
    """Test POST /mcp/get_agent_performance endpoint."""
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_get_agent_performance_success(self, mock_mcp_api, client):
        """Test successful agent performance retrieval."""
        mock_mcp_api.get_agent_performance.return_value = {
            "agent_id": "test-agent",
            "tasks_completed": 10,
            "average_hours": 2.5,
            "success_rate": 0.95
        }
        
        response = client.post(
            "/mcp/get_agent_performance",
            json={
                "agent_id": "test-agent",
                "task_type": "concrete"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test-agent"
        assert data["tasks_completed"] == 10
        mock_mcp_api.get_agent_performance.assert_called_once_with("test-agent", "concrete")
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_get_agent_performance_validation_error(self, mock_mcp_api, client):
        """Test agent performance retrieval with validation error."""
        # Missing required agent_id
        response = client.post("/mcp/get_agent_performance", json={})
        
        assert response.status_code == 422  # Validation error


class TestUnlockTask:
    """Test POST /mcp/unlock_task endpoint."""
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_unlock_task_success(self, mock_mcp_api, client):
        """Test successful task unlock."""
        mock_mcp_api.unlock_task.return_value = {
            "success": True,
            "message": "Task unlocked successfully"
        }
        
        response = client.post(
            "/mcp/unlock_task",
            json={
                "task_id": 1,
                "agent_id": "test-agent"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_mcp_api.unlock_task.assert_called_once_with(1, "test-agent")
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_unlock_task_validation_error(self, mock_mcp_api, client):
        """Test task unlock with validation error."""
        # Missing required fields
        response = client.post("/mcp/unlock_task", json={})
        
        assert response.status_code == 422  # Validation error


class TestQueryTasks:
    """Test POST /mcp/query_tasks endpoint."""
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_query_tasks_success(self, mock_mcp_api, client):
        """Test successful task query."""
        mock_mcp_api.query_tasks.return_value = [
            {"id": 1, "title": "Task 1"},
            {"id": 2, "title": "Task 2"}
        ]
        
        response = client.post(
            "/mcp/query_tasks",
            json={
                "project_id": 1,
                "task_type": "concrete",
                "limit": 10
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert len(data["tasks"]) == 2
        mock_mcp_api.query_tasks.assert_called_once()
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_query_tasks_empty(self, mock_mcp_api, client):
        """Test task query with no results."""
        mock_mcp_api.query_tasks.return_value = []
        
        response = client.post(
            "/mcp/query_tasks",
            json={
                "limit": 10
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert len(data["tasks"]) == 0


class TestAddTaskUpdate:
    """Test POST /mcp/add_task_update endpoint."""
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_add_task_update_success(self, mock_mcp_api, client):
        """Test successful task update addition."""
        mock_mcp_api.add_task_update.return_value = {
            "success": True,
            "update_id": 1
        }
        
        response = client.post(
            "/mcp/add_task_update",
            json={
                "task_id": 1,
                "agent_id": "test-agent",
                "content": "Progress update",
                "update_type": "progress"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["update_id"] == 1
        mock_mcp_api.add_task_update.assert_called_once()
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_add_task_update_validation_error(self, mock_mcp_api, client):
        """Test task update addition with validation error."""
        # Missing required fields
        response = client.post("/mcp/add_task_update", json={})
        
        assert response.status_code == 422  # Validation error


class TestGetTaskContext:
    """Test POST /mcp/get_task_context endpoint."""
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_get_task_context_success(self, mock_mcp_api, client):
        """Test successful task context retrieval."""
        mock_mcp_api.get_task_context.return_value = {
            "success": True,
            "task": {"id": 1, "title": "Test Task"},
            "project": {"id": 1, "name": "Test Project"},
            "updates": [],
            "ancestry": []
        }
        
        response = client.post(
            "/mcp/get_task_context",
            json={
                "task_id": 1
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "task" in data
        assert data["task"]["id"] == 1
        mock_mcp_api.get_task_context.assert_called_once_with(1)
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_get_task_context_validation_error(self, mock_mcp_api, client):
        """Test task context retrieval with validation error."""
        # Missing required task_id
        response = client.post("/mcp/get_task_context", json={})
        
        assert response.status_code == 422  # Validation error


class TestSearchTasks:
    """Test POST /mcp/search_tasks endpoint."""
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_search_tasks_success(self, mock_mcp_api, client):
        """Test successful task search."""
        mock_mcp_api.search_tasks.return_value = [
            {"id": 1, "title": "Test Task 1"},
            {"id": 2, "title": "Test Task 2"}
        ]
        
        response = client.post(
            "/mcp/search_tasks",
            json={
                "query": "test",
                "limit": 10
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert len(data["tasks"]) == 2
        mock_mcp_api.search_tasks.assert_called_once_with("test", 10)
    
    @patch('api.routes.mcp.MCPTodoAPI')
    def test_search_tasks_validation_error(self, mock_mcp_api, client):
        """Test task search with validation error."""
        # Missing required query
        response = client.post("/mcp/search_tasks", json={})
        
        assert response.status_code == 422  # Validation error
