"""
Tests for security headers middleware.
"""
import pytest
import os
import tempfile
import shutil
from fastapi.testclient import TestClient
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from security_headers import SecurityHeadersMiddleware


@pytest.fixture
def app_with_security_headers():
    """Create FastAPI app with security headers middleware."""
    app = FastAPI()
    
    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"message": "test"}
    
    app.add_middleware(SecurityHeadersMiddleware)
    return app


@pytest.fixture
def client(app_with_security_headers):
    """Create test client."""
    return TestClient(app_with_security_headers)


def test_security_headers_present(client):
    """Test that security headers are present in responses."""
    response = client.get("/test")
    
    assert response.status_code == 200
    
    # Check for essential security headers
    assert "X-Content-Type-Options" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    
    assert "X-Frame-Options" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    
    assert "X-XSS-Protection" in response.headers
    assert response.headers["X-XSS-Protection"] == "1; mode=block"
    
    assert "Referrer-Policy" in response.headers
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    
    assert "Cross-Origin-Opener-Policy" in response.headers
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    
    assert "Cross-Origin-Resource-Policy" in response.headers
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"


def test_content_security_policy_header(client):
    """Test that Content-Security-Policy header is present."""
    response = client.get("/test")
    
    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_permissions_policy_header(client):
    """Test that Permissions-Policy header is present."""
    response = client.get("/test")
    
    assert response.status_code == 200
    assert "Permissions-Policy" in response.headers
    
    # Should have restrictive permissions
    permissions_policy = response.headers["Permissions-Policy"]
    assert "geolocation=()" in permissions_policy
    assert "microphone=()" in permissions_policy
    assert "camera=()" in permissions_policy


def test_hsts_not_set_on_http(client):
    """Test that HSTS header is NOT set on HTTP requests."""
    response = client.get("/test")
    
    assert response.status_code == 200
    
    # HSTS should not be set on HTTP (default test client uses HTTP)
    # Note: We can't easily test HTTPS in TestClient, but we verify HTTP doesn't get HSTS
    # HSTS will be set only when SECURITY_HSTS_ENABLED=true AND request is HTTPS
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_configuration():
    """Test HSTS configuration via environment variables."""
    import os
    
    # Temporarily set environment variables
    original_hsts_enabled = os.environ.get("SECURITY_HSTS_ENABLED")
    original_hsts_max_age = os.environ.get("SECURITY_HSTS_MAX_AGE")
    original_hsts_include_subdomains = os.environ.get("SECURITY_HSTS_INCLUDE_SUBDOMAINS")
    
    try:
        os.environ["SECURITY_HSTS_ENABLED"] = "true"
        os.environ["SECURITY_HSTS_MAX_AGE"] = "86400"
        os.environ["SECURITY_HSTS_INCLUDE_SUBDOMAINS"] = "true"
        
        # Create new middleware instance to pick up env vars
        app = FastAPI()
        
        @app.get("/test")
        async def test_endpoint():
            return {"message": "test"}
        
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)
        
        # HSTS should still not be set on HTTP
        response = client.get("/test")
        assert response.status_code == 200
        # Still no HSTS on HTTP even when enabled
        assert "Strict-Transport-Security" not in response.headers
        
    finally:
        # Restore original environment
        if original_hsts_enabled is None:
            os.environ.pop("SECURITY_HSTS_ENABLED", None)
        else:
            os.environ["SECURITY_HSTS_ENABLED"] = original_hsts_enabled
        
        if original_hsts_max_age is None:
            os.environ.pop("SECURITY_HSTS_MAX_AGE", None)
        else:
            os.environ["SECURITY_HSTS_MAX_AGE"] = original_hsts_max_age
        
        if original_hsts_include_subdomains is None:
            os.environ.pop("SECURITY_HSTS_INCLUDE_SUBDOMAINS", None)
        else:
            os.environ["SECURITY_HSTS_INCLUDE_SUBDOMAINS"] = original_hsts_include_subdomains


def test_custom_headers_configuration():
    """Test custom security header configuration via environment variables."""
    import os
    
    # Temporarily set environment variables
    original_frame_options = os.environ.get("SECURITY_HEADER_X_FRAME_OPTIONS")
    original_referrer_policy = os.environ.get("SECURITY_HEADER_REFERRER_POLICY")
    
    try:
        os.environ["SECURITY_HEADER_X_FRAME_OPTIONS"] = "SAMEORIGIN"
        os.environ["SECURITY_HEADER_REFERRER_POLICY"] = "no-referrer"
        
        # Create new middleware instance to pick up env vars
        app = FastAPI()
        
        @app.get("/test")
        async def test_endpoint():
            return {"message": "test"}
        
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)
        
        response = client.get("/test")
        assert response.status_code == 200
        
        # Check custom values
        assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        
    finally:
        # Restore original environment
        if original_frame_options is None:
            os.environ.pop("SECURITY_HEADER_X_FRAME_OPTIONS", None)
        else:
            os.environ["SECURITY_HEADER_X_FRAME_OPTIONS"] = original_frame_options
        
        if original_referrer_policy is None:
            os.environ.pop("SECURITY_HEADER_REFERRER_POLICY", None)
        else:
            os.environ["SECURITY_HEADER_REFERRER_POLICY"] = original_referrer_policy


def test_coep_disabled_by_default(client):
    """Test that Cross-Origin-Embedder-Policy is disabled by default."""
    response = client.get("/test")
    
    assert response.status_code == 200
    
    # COEP should not be set by default
    assert "Cross-Origin-Embedder-Policy" not in response.headers


def test_coep_enabled_via_config():
    """Test that COEP can be enabled via environment variable."""
    import os
    
    original_coep_enabled = os.environ.get("SECURITY_HEADER_COEP_ENABLED")
    
    try:
        os.environ["SECURITY_HEADER_COEP_ENABLED"] = "true"
        
        # Create new middleware instance
        app = FastAPI()
        
        @app.get("/test")
        async def test_endpoint():
            return {"message": "test"}
        
        app.add_middleware(SecurityHeadersMiddleware)
        client = TestClient(app)
        
        response = client.get("/test")
        assert response.status_code == 200
        
        # COEP should now be set
        assert "Cross-Origin-Embedder-Policy" in response.headers
        assert response.headers["Cross-Origin-Embedder-Policy"] == "require-corp"
        
    finally:
        if original_coep_enabled is None:
            os.environ.pop("SECURITY_HEADER_COEP_ENABLED", None)
        else:
            os.environ["SECURITY_HEADER_COEP_ENABLED"] = original_coep_enabled


def test_all_endpoints_get_headers(client):
    """Test that all endpoints receive security headers."""
    # Create app with multiple endpoints
    from fastapi import FastAPI
    app = FastAPI()
    
    @app.get("/endpoint1")
    async def endpoint1():
        return {"message": "1"}
    
    @app.post("/endpoint2")
    async def endpoint2():
        return {"message": "2"}
    
    @app.put("/endpoint3/{id}")
    async def endpoint3(id: int):
        return {"message": "3", "id": id}
    
    app.add_middleware(SecurityHeadersMiddleware)
    test_client = TestClient(app)
    
    # Test all endpoints get security headers
    for endpoint, method in [
        ("/endpoint1", "GET"),
        ("/endpoint2", "POST"),
        ("/endpoint3/123", "PUT"),
    ]:
        if method == "GET":
            response = test_client.get(endpoint)
        elif method == "POST":
            response = test_client.post(endpoint)
        elif method == "PUT":
            response = test_client.put(endpoint)
        
        assert response.status_code in [200, 201]
        assert "X-Content-Type-Options" in response.headers
        assert "X-Frame-Options" in response.headers
        assert "Referrer-Policy" in response.headers
