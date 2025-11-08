"""
Mock-based unit tests for health route handlers.
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

from api.routes import health


@pytest.fixture
def mock_services():
    """Create mock services."""
    services = Mock()
    services.db = Mock()
    return services


@pytest.fixture
def app():
    """Create a FastAPI app with health router."""
    app = FastAPI()
    app.include_router(health.router)
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestHealthCheck:
    """Test GET /health endpoint."""
    
    @patch('api.routes.health.get_services')
    @patch('api.routes.health.get_health_info')
    def test_health_check_healthy(
        self, mock_get_health_info, mock_get_services, client, mock_services
    ):
        """Test health check when service is healthy."""
        mock_get_services.return_value = mock_services
        mock_get_health_info.return_value = {
            "status": "healthy",
            "database": "connected",
            "uptime_seconds": 100
        }
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        mock_get_health_info.assert_called_once_with(mock_services.db)
    
    @patch('api.routes.health.get_services')
    @patch('api.routes.health.get_health_info')
    def test_health_check_unhealthy(
        self, mock_get_health_info, mock_get_services, client, mock_services
    ):
        """Test health check when service is unhealthy."""
        mock_get_services.return_value = mock_services
        mock_get_health_info.return_value = {
            "status": "unhealthy",
            "database": "disconnected",
            "uptime_seconds": 100
        }
        
        response = client.get("/health")
        
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["database"] == "disconnected"
        mock_get_health_info.assert_called_once_with(mock_services.db)


class TestMetrics:
    """Test GET /metrics endpoint."""
    
    @patch('api.routes.health.get_metrics')
    @patch('api.routes.health.MetricsAdapter')
    def test_metrics_success(self, mock_metrics_adapter_class, mock_get_metrics, client):
        """Test successful metrics retrieval."""
        mock_get_metrics.return_value = "test_metric 1.0\n"
        mock_metrics_adapter = Mock()
        mock_metrics_adapter.get_content_type.return_value = "text/plain"
        mock_metrics_adapter_class.return_value = mock_metrics_adapter
        
        response = client.get("/metrics")
        
        assert response.status_code == 200
        assert response.text == "test_metric 1.0\n"
        assert response.headers["content-type"] == "text/plain"
        mock_get_metrics.assert_called_once()
