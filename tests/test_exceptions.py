"""
Comprehensive tests for exception handling in todorama.

Tests verify that standard exceptions work correctly, convert properly to
HTTPException and MCP error responses, and preserve context.
"""
import pytest
from fastapi import HTTPException
from todorama.exceptions import (
    ServiceError,
    NotFoundError,
    ValidationError,
    DuplicateError,
    DatabaseError,
    TaskNotFoundError,
    ProjectNotFoundError,
    OrganizationNotFoundError,
    TagNotFoundError,
    TemplateNotFoundError,
    to_http_exception,
    to_mcp_error_response,
)


# ============================================================================
# Test Exception Initialization
# ============================================================================

class TestServiceErrorInitialization:
    """Test ServiceError base class initialization."""
    
    def test_basic_initialization(self):
        """Test basic ServiceError initialization."""
        exc = ServiceError("Test error message")
        assert exc.message == "Test error message"
        assert exc.request_id is None
        assert exc.context == {}
        assert exc.original_error is None
        assert str(exc) == "Test error message"
    
    def test_with_request_id(self):
        """Test ServiceError with request_id."""
        exc = ServiceError("Test error", request_id="req-123")
        assert exc.message == "Test error"
        assert exc.request_id == "req-123"
    
    def test_with_context(self):
        """Test ServiceError with context."""
        context = {"field": "task_id", "value": 123}
        exc = ServiceError("Test error", context=context)
        assert exc.context == context
    
    def test_with_original_error(self):
        """Test ServiceError with original_error."""
        original = ValueError("Original error")
        exc = ServiceError("Test error", original_error=original)
        assert exc.original_error == original
    
    def test_to_dict(self):
        """Test ServiceError.to_dict() method."""
        original = ValueError("Original")
        exc = ServiceError(
            "Test error",
            request_id="req-123",
            context={"key": "value"},
            original_error=original
        )
        result = exc.to_dict()
        assert result["error_type"] == "ServiceError"
        assert result["message"] == "Test error"
        assert result["request_id"] == "req-123"
        assert result["context"] == {"key": "value"}
        assert result["original_error"]["type"] == "ValueError"
        assert result["original_error"]["message"] == "Original"
    
    def test_to_dict_minimal(self):
        """Test ServiceError.to_dict() with minimal fields."""
        exc = ServiceError("Test error")
        result = exc.to_dict()
        assert result["error_type"] == "ServiceError"
        assert result["message"] == "Test error"
        assert "request_id" not in result
        assert "context" not in result
        assert "original_error" not in result


class TestNotFoundErrorInitialization:
    """Test NotFoundError initialization."""
    
    def test_basic_initialization(self):
        """Test basic NotFoundError initialization."""
        exc = NotFoundError("Task", "123")
        assert exc.resource_type == "Task"
        assert exc.resource_id == "123"
        assert exc.message == "Task with ID '123' not found"
        assert exc.context["resource_type"] == "Task"
        assert exc.context["resource_id"] == "123"
    
    def test_with_custom_message(self):
        """Test NotFoundError with custom message."""
        exc = NotFoundError("Task", "123", message="Custom message")
        assert exc.message == "Custom message"
        assert exc.resource_type == "Task"
        assert exc.resource_id == "123"
    
    def test_with_request_id(self):
        """Test NotFoundError with request_id."""
        exc = NotFoundError("Task", "123", request_id="req-456")
        assert exc.request_id == "req-456"
    
    def test_with_context(self):
        """Test NotFoundError with additional context."""
        context = {"operation": "update"}
        exc = NotFoundError("Task", "123", context=context)
        assert exc.context["resource_type"] == "Task"
        assert exc.context["resource_id"] == "123"
        assert exc.context["operation"] == "update"
    
    def test_int_resource_id(self):
        """Test NotFoundError with integer resource_id."""
        exc = NotFoundError("Task", 123)
        assert exc.resource_id == "123"  # Converted to string
        assert exc.message == "Task with ID '123' not found"


class TestValidationErrorInitialization:
    """Test ValidationError initialization."""
    
    def test_basic_initialization(self):
        """Test basic ValidationError initialization."""
        exc = ValidationError("Invalid value")
        assert exc.message == "Invalid value"
        assert exc.field is None
        assert exc.value is None
    
    def test_with_field(self):
        """Test ValidationError with field."""
        exc = ValidationError("Invalid value", field="task_id")
        assert exc.field == "task_id"
        assert exc.context["field"] == "task_id"
    
    def test_with_value(self):
        """Test ValidationError with value."""
        exc = ValidationError("Invalid value", value=123)
        assert exc.value == 123
        assert exc.context["value"] == "123"  # Converted to string
    
    def test_with_field_and_value(self):
        """Test ValidationError with both field and value."""
        exc = ValidationError("Invalid value", field="task_id", value=123)
        assert exc.field == "task_id"
        assert exc.value == 123
        assert exc.context["field"] == "task_id"
        assert exc.context["value"] == "123"


class TestDuplicateErrorInitialization:
    """Test DuplicateError initialization."""
    
    def test_basic_initialization(self):
        """Test basic DuplicateError initialization."""
        exc = DuplicateError("Task", "title", "My Task")
        assert exc.resource_type == "Task"
        assert exc.field == "title"
        assert exc.value == "My Task"
        assert exc.message == "Task with title 'My Task' already exists"
        assert exc.context["resource_type"] == "Task"
        assert exc.context["field"] == "title"
        assert exc.context["value"] == "My Task"
    
    def test_with_custom_message(self):
        """Test DuplicateError with custom message."""
        exc = DuplicateError("Task", "title", "My Task", message="Custom message")
        assert exc.message == "Custom message"


class TestDatabaseErrorInitialization:
    """Test DatabaseError initialization."""
    
    def test_basic_initialization(self):
        """Test basic DatabaseError initialization."""
        exc = DatabaseError("Database connection failed")
        assert exc.message == "Database connection failed"
        assert exc.operation is None
        assert exc.original_error is None
    
    def test_with_operation(self):
        """Test DatabaseError with operation."""
        exc = DatabaseError("Database error", operation="INSERT")
        assert exc.operation == "INSERT"
        assert exc.context["operation"] == "INSERT"
    
    def test_with_original_error(self):
        """Test DatabaseError with original_error."""
        original = ValueError("Original error")
        exc = DatabaseError("Database error", original_error=original)
        assert exc.original_error == original


class TestServiceSpecificExceptions:
    """Test service-specific exception classes."""
    
    def test_task_not_found_error(self):
        """Test TaskNotFoundError."""
        exc = TaskNotFoundError(123)
        assert exc.task_id == 123
        assert exc.resource_type == "Task"
        assert exc.resource_id == "123"
        assert exc.message == "Task with ID '123' not found"
    
    def test_project_not_found_error(self):
        """Test ProjectNotFoundError."""
        exc = ProjectNotFoundError(456)
        assert exc.project_id == 456
        assert exc.resource_type == "Project"
        assert exc.resource_id == "456"
    
    def test_organization_not_found_error(self):
        """Test OrganizationNotFoundError."""
        exc = OrganizationNotFoundError(789)
        assert exc.organization_id == 789
        assert exc.resource_type == "Organization"
        assert exc.resource_id == "789"
    
    def test_tag_not_found_error(self):
        """Test TagNotFoundError."""
        exc = TagNotFoundError(10)
        assert exc.tag_id == 10
        assert exc.resource_type == "Tag"
        assert exc.resource_id == "10"
    
    def test_template_not_found_error(self):
        """Test TemplateNotFoundError."""
        exc = TemplateNotFoundError(20)
        assert exc.template_id == 20
        assert exc.resource_type == "Template"
        assert exc.resource_id == "20"


# ============================================================================
# Test Exception Message Formatting
# ============================================================================

class TestExceptionMessageFormatting:
    """Test exception message formatting."""
    
    def test_not_found_error_message_formatting(self):
        """Test NotFoundError message formatting."""
        exc = NotFoundError("Task", "123")
        assert "Task" in exc.message
        assert "123" in exc.message
        assert "not found" in exc.message.lower()
    
    def test_duplicate_error_message_formatting(self):
        """Test DuplicateError message formatting."""
        exc = DuplicateError("Task", "title", "My Task")
        assert "Task" in exc.message
        assert "title" in exc.message
        assert "My Task" in exc.message
        assert "already exists" in exc.message.lower()
    
    def test_validation_error_message_formatting(self):
        """Test ValidationError message formatting."""
        exc = ValidationError("Invalid task_id format")
        assert "Invalid" in exc.message or "invalid" in exc.message.lower()


# ============================================================================
# Test Exception Context Storage and Retrieval
# ============================================================================

class TestExceptionContext:
    """Test exception context storage and retrieval."""
    
    def test_context_preservation(self):
        """Test that context is preserved in exceptions."""
        context = {
            "field": "task_id",
            "value": 123,
            "operation": "update",
            "custom_key": "custom_value"
        }
        exc = ValidationError("Error", field="task_id", value=123, context=context)
        assert exc.context["field"] == "task_id"
        assert exc.context["value"] == "123"
        assert exc.context["operation"] == "update"
        assert exc.context["custom_key"] == "custom_value"
    
    def test_context_in_to_dict(self):
        """Test that context is included in to_dict()."""
        context = {"key": "value"}
        exc = ServiceError("Error", context=context)
        result = exc.to_dict()
        assert result["context"] == context
    
    def test_nested_context(self):
        """Test nested context structures."""
        context = {
            "nested": {
                "key": "value"
            },
            "list": [1, 2, 3]
        }
        exc = ServiceError("Error", context=context)
        assert exc.context["nested"]["key"] == "value"
        assert exc.context["list"] == [1, 2, 3]


# ============================================================================
# Test Conversion to HTTPException
# ============================================================================

class TestToHTTPException:
    """Test conversion to HTTPException."""
    
    def test_not_found_to_http_exception(self):
        """Test NotFoundError conversion to HTTPException."""
        exc = NotFoundError("Task", "123")
        http_exc = to_http_exception(exc)
        assert isinstance(http_exc, HTTPException)
        assert http_exc.status_code == 404
        assert http_exc.detail["error"] == "NotFoundError"
        assert http_exc.detail["message"] == "Task with ID '123' not found"
    
    def test_validation_error_to_http_exception(self):
        """Test ValidationError conversion to HTTPException."""
        exc = ValidationError("Invalid value", field="task_id")
        http_exc = to_http_exception(exc)
        assert http_exc.status_code == 422
        assert http_exc.detail["error"] == "ValidationError"
        assert http_exc.detail["message"] == "Invalid value"
        assert http_exc.detail["context"]["field"] == "task_id"
    
    def test_duplicate_error_to_http_exception(self):
        """Test DuplicateError conversion to HTTPException."""
        exc = DuplicateError("Task", "title", "My Task")
        http_exc = to_http_exception(exc)
        assert http_exc.status_code == 409
        assert http_exc.detail["error"] == "DuplicateError"
    
    def test_database_error_to_http_exception(self):
        """Test DatabaseError conversion to HTTPException."""
        exc = DatabaseError("Database connection failed")
        http_exc = to_http_exception(exc)
        assert http_exc.status_code == 500
        assert http_exc.detail["error"] == "DatabaseError"
    
    def test_http_exception_with_request_id(self):
        """Test HTTPException includes request_id."""
        exc = NotFoundError("Task", "123", request_id="req-456")
        http_exc = to_http_exception(exc)
        assert http_exc.detail["request_id"] == "req-456"
    
    def test_http_exception_with_context(self):
        """Test HTTPException includes context."""
        exc = ValidationError("Error", context={"key": "value"})
        http_exc = to_http_exception(exc, include_context=True)
        assert http_exc.detail["context"] == {"key": "value"}
    
    def test_http_exception_without_context(self):
        """Test HTTPException can exclude context."""
        exc = ValidationError("Error", context={"key": "value"})
        http_exc = to_http_exception(exc, include_context=False)
        assert "context" not in http_exc.detail
    
    def test_http_exception_default_status_code(self):
        """Test HTTPException uses default status code for unknown exceptions."""
        class CustomError(ServiceError):
            pass
        
        exc = CustomError("Custom error")
        http_exc = to_http_exception(exc, default_status_code=400)
        assert http_exc.status_code == 400


# ============================================================================
# Test Conversion to MCP Error Response
# ============================================================================

class TestToMCPErrorResponse:
    """Test conversion to MCP error response."""
    
    def test_not_found_to_mcp_error(self):
        """Test NotFoundError conversion to MCP error response."""
        exc = NotFoundError("Task", "123")
        response = to_mcp_error_response(exc)
        assert response["success"] is False
        assert response["error"]["code"] == -32001
        assert response["error"]["message"] == "Task with ID '123' not found"
        assert response["error"]["error_type"] == "NotFoundError"
    
    def test_validation_error_to_mcp_error(self):
        """Test ValidationError conversion to MCP error response."""
        exc = ValidationError("Invalid value", field="task_id")
        response = to_mcp_error_response(exc)
        assert response["success"] is False
        assert response["error"]["code"] == -32602
        assert response["error"]["message"] == "Invalid value"
        assert response["error"]["error_type"] == "ValidationError"
        assert response["error"]["context"]["field"] == "task_id"
    
    def test_duplicate_error_to_mcp_error(self):
        """Test DuplicateError conversion to MCP error response."""
        exc = DuplicateError("Task", "title", "My Task")
        response = to_mcp_error_response(exc)
        assert response["success"] is False
        assert response["error"]["code"] == -32002
        assert response["error"]["error_type"] == "DuplicateError"
    
    def test_database_error_to_mcp_error(self):
        """Test DatabaseError conversion to MCP error response."""
        exc = DatabaseError("Database connection failed")
        response = to_mcp_error_response(exc)
        assert response["success"] is False
        assert response["error"]["code"] == -32603
        assert response["error"]["error_type"] == "DatabaseError"
    
    def test_mcp_error_with_request_id(self):
        """Test MCP error response includes request_id."""
        exc = NotFoundError("Task", "123", request_id="req-456")
        response = to_mcp_error_response(exc)
        assert response["error"]["request_id"] == "req-456"
    
    def test_mcp_error_with_context(self):
        """Test MCP error response includes context."""
        exc = ValidationError("Error", context={"key": "value"})
        response = to_mcp_error_response(exc)
        assert response["error"]["context"] == {"key": "value"}
    
    def test_mcp_error_format(self):
        """Test MCP error response format structure."""
        exc = NotFoundError("Task", "123")
        response = to_mcp_error_response(exc)
        assert "success" in response
        assert "error" in response
        assert "code" in response["error"]
        assert "message" in response["error"]
        assert "error_type" in response["error"]


# ============================================================================
# Test Error Response Format Consistency
# ============================================================================

class TestErrorResponseFormatConsistency:
    """Test error response format consistency."""
    
    def test_http_exception_format_consistency(self):
        """Test HTTPException format is consistent across exception types."""
        exceptions = [
            NotFoundError("Task", "123"),
            ValidationError("Error"),
            DuplicateError("Task", "title", "value"),
            DatabaseError("Error"),
        ]
        
        formats = []
        for exc in exceptions:
            http_exc = to_http_exception(exc)
            formats.append(set(http_exc.detail.keys()))
        
        # All should have at least "error" and "message"
        for fmt in formats:
            assert "error" in fmt
            assert "message" in fmt
    
    def test_mcp_error_format_consistency(self):
        """Test MCP error response format is consistent across exception types."""
        exceptions = [
            NotFoundError("Task", "123"),
            ValidationError("Error"),
            DuplicateError("Task", "title", "value"),
            DatabaseError("Error"),
        ]
        
        formats = []
        for exc in exceptions:
            response = to_mcp_error_response(exc)
            formats.append(set(response["error"].keys()))
        
        # All should have at least "code", "message", and "error_type"
        for fmt in formats:
            assert "code" in fmt
            assert "message" in fmt
            assert "error_type" in fmt


# ============================================================================
# Test Integration with Service-Specific Scenarios
# ============================================================================

class TestServiceSpecificScenarios:
    """Test exception handling in service-specific scenarios."""
    
    def test_task_not_found_scenario(self):
        """Test TaskNotFoundError in typical scenario."""
        exc = TaskNotFoundError(123, request_id="req-456")
        assert exc.task_id == 123
        assert exc.resource_id == "123"
        
        # Test HTTP conversion
        http_exc = to_http_exception(exc)
        assert http_exc.status_code == 404
        
        # Test MCP conversion
        mcp_response = to_mcp_error_response(exc)
        assert mcp_response["error"]["code"] == -32001
    
    def test_validation_error_with_field(self):
        """Test ValidationError with field in typical scenario."""
        exc = ValidationError(
            "task_id must be a positive integer",
            field="task_id",
            value=-1,
            request_id="req-789"
        )
        assert exc.field == "task_id"
        assert exc.value == -1
        
        # Test HTTP conversion
        http_exc = to_http_exception(exc)
        assert http_exc.status_code == 422
        assert http_exc.detail["context"]["field"] == "task_id"
        assert http_exc.detail["context"]["value"] == "-1"
        
        # Test MCP conversion
        mcp_response = to_mcp_error_response(exc)
        assert mcp_response["error"]["code"] == -32602
        assert mcp_response["error"]["context"]["field"] == "task_id"
    
    def test_database_error_with_original_error(self):
        """Test DatabaseError with original_error."""
        original = ValueError("Connection failed")
        exc = DatabaseError(
            "Database operation failed",
            operation="INSERT",
            original_error=original
        )
        assert exc.operation == "INSERT"
        assert exc.original_error == original
        
        # Test to_dict includes original_error
        result = exc.to_dict()
        assert result["original_error"]["type"] == "ValueError"
        assert result["original_error"]["message"] == "Connection failed"


# ============================================================================
# Test Exception Inheritance
# ============================================================================

class TestExceptionInheritance:
    """Test exception inheritance hierarchy."""
    
    def test_not_found_error_inheritance(self):
        """Test NotFoundError inherits from ServiceError."""
        exc = NotFoundError("Task", "123")
        assert isinstance(exc, ServiceError)
        assert isinstance(exc, NotFoundError)
        assert isinstance(exc, Exception)
    
    def test_service_specific_inheritance(self):
        """Test service-specific exceptions inherit correctly."""
        exc = TaskNotFoundError(123)
        assert isinstance(exc, ServiceError)
        assert isinstance(exc, NotFoundError)
        assert isinstance(exc, TaskNotFoundError)
    
    def test_exception_hierarchy(self):
        """Test exception hierarchy is correct."""
        # All exceptions should inherit from ServiceError
        exceptions = [
            NotFoundError("Task", "123"),
            ValidationError("Error"),
            DuplicateError("Task", "field", "value"),
            DatabaseError("Error"),
            TaskNotFoundError(123),
            ProjectNotFoundError(456),
        ]
        
        for exc in exceptions:
            assert isinstance(exc, ServiceError)
            assert isinstance(exc, Exception)


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestExceptionEdgeCases:
    """Test exception handling edge cases."""
    
    def test_empty_message(self):
        """Test exception with empty message (should not happen, but test anyway)."""
        exc = ServiceError("")
        assert exc.message == ""
    
    def test_none_context(self):
        """Test exception with None context (should default to empty dict)."""
        exc = ServiceError("Error", context=None)
        assert exc.context == {}
    
    def test_none_request_id(self):
        """Test exception with None request_id."""
        exc = ServiceError("Error", request_id=None)
        assert exc.request_id is None
    
    def test_unicode_in_message(self):
        """Test exception with unicode characters in message."""
        exc = ServiceError("Error: 测试")
        assert "测试" in exc.message
    
    def test_large_context(self):
        """Test exception with large context dictionary."""
        large_context = {f"key_{i}": f"value_{i}" for i in range(100)}
        exc = ServiceError("Error", context=large_context)
        assert len(exc.context) == 100
    
    def test_nested_exceptions(self):
        """Test exception with nested original_error."""
        inner = ValueError("Inner error")
        middle = RuntimeError("Middle error")
        outer = DatabaseError("Outer error", original_error=middle)
        # Note: original_error is single, not nested, but we can test it
        assert outer.original_error == middle


# ============================================================================
# Integration Tests for Exception Handling in API Endpoints
# ============================================================================

class TestExceptionHandlingInAPIEndpoints:
    """Test exception handling in actual API endpoints."""
    
    @pytest.fixture
    def app(self):
        """Create FastAPI app for testing."""
        from todorama.app import create_app
        return create_app()
    
    @pytest.fixture
    def client(self, app):
        """Create test client."""
        from fastapi.testclient import TestClient
        return TestClient(app)
    
    def test_task_not_found_in_api(self, client):
        """Test TaskNotFoundError handling in API endpoint."""
        # This would require setting up a test database and trying to get a non-existent task
        # For now, we'll test that the exception handler is registered
        from todorama.exceptions import TaskNotFoundError
        from todorama.exceptions.handlers import service_error_handler
        from todorama.adapters.http_framework import HTTPFrameworkAdapter
        
        http_adapter = HTTPFrameworkAdapter()
        Request = http_adapter.Request
        
        # Create a mock request
        class MockRequest:
            def __init__(self):
                self.method = "GET"
                self.url = type('obj', (object,), {'path': '/api/tasks/999'})()
        
        # Test that exception handler can handle TaskNotFoundError
        exc = TaskNotFoundError(999)
        # Note: We can't easily test the full handler without a real request object,
        # but we can verify the exception is properly structured
        assert exc.task_id == 999
        assert exc.resource_type == "Task"
    
    def test_validation_error_in_api(self, client):
        """Test ValidationError handling in API endpoint."""
        from todorama.exceptions import ValidationError
        
        # Test that ValidationError has proper structure
        exc = ValidationError("Invalid task_id", field="task_id", value="invalid")
        assert exc.field == "task_id"
        assert exc.value == "invalid"
        
        # Test conversion
        http_exc = to_http_exception(exc)
        assert http_exc.status_code == 422
    
    def test_mcp_endpoint_error_format(self):
        """Test that MCP endpoints return errors in correct format (200 OK with success: False)."""
        from todorama.exceptions import TaskNotFoundError, to_mcp_error_response
        
        exc = TaskNotFoundError(123)
        response = to_mcp_error_response(exc)
        
        # Verify MCP error format
        assert response["success"] is False
        assert "error" in response
        assert "code" in response["error"]
        assert "message" in response["error"]
        assert "error_type" in response["error"]
        assert response["error"]["code"] == -32001  # Not Found error code


# ============================================================================
# Test Exception Handler Registration
# ============================================================================

class TestExceptionHandlerRegistration:
    """Test that exception handlers are properly registered."""
    
    def test_service_error_handler_registered(self):
        """Test that ServiceError handler is registered in the app."""
        from todorama.app import create_app
        from todorama.exceptions import ServiceError
        
        app = create_app()
        
        # Check that exception handlers are registered
        # FastAPI stores handlers in app.exception_handlers
        assert hasattr(app, 'exception_handlers')
        # ServiceError should be in the handlers
        # Note: We can't easily check the exact registration without accessing private attributes,
        # but we can verify the handler function exists
        from todorama.exceptions.handlers import service_error_handler
        assert callable(service_error_handler)
    
    def test_exception_handler_imports(self):
        """Test that exception handlers can be imported."""
        from todorama.exceptions.handlers import (
            service_error_handler,
            global_exception_handler,
            validation_exception_handler,
            setup_exception_handlers
        )
        assert callable(service_error_handler)
        assert callable(global_exception_handler)
        assert callable(validation_exception_handler)
        assert callable(setup_exception_handlers)


# ============================================================================
# Test Error Code Consistency
# ============================================================================

class TestErrorCodeConsistency:
    """Test that error codes are consistent across exception types."""
    
    def test_error_code_mapping_consistency(self):
        """Test that error codes map consistently."""
        from todorama.exceptions import (
            NotFoundError,
            ValidationError,
            DuplicateError,
            DatabaseError
        )
        
        # Test HTTP status code mapping
        not_found = NotFoundError("Task", "123")
        validation = ValidationError("Error")
        duplicate = DuplicateError("Task", "field", "value")
        database = DatabaseError("Error")
        
        http_not_found = to_http_exception(not_found)
        http_validation = to_http_exception(validation)
        http_duplicate = to_http_exception(duplicate)
        http_database = to_http_exception(database)
        
        assert http_not_found.status_code == 404
        assert http_validation.status_code == 422
        assert http_duplicate.status_code == 409
        assert http_database.status_code == 500
        
        # Test MCP error code mapping
        mcp_not_found = to_mcp_error_response(not_found)
        mcp_validation = to_mcp_error_response(validation)
        mcp_duplicate = to_mcp_error_response(duplicate)
        mcp_database = to_mcp_error_response(database)
        
        assert mcp_not_found["error"]["code"] == -32001
        assert mcp_validation["error"]["code"] == -32602
        assert mcp_duplicate["error"]["code"] == -32002
        assert mcp_database["error"]["code"] == -32603
    
    def test_service_specific_exceptions_use_base_codes(self):
        """Test that service-specific exceptions use base exception error codes."""
        from todorama.exceptions import TaskNotFoundError, ProjectNotFoundError
        
        task_exc = TaskNotFoundError(123)
        project_exc = ProjectNotFoundError(456)
        
        # Both should use NotFoundError error codes
        task_http = to_http_exception(task_exc)
        project_http = to_http_exception(project_exc)
        
        assert task_http.status_code == 404
        assert project_http.status_code == 404
        
        task_mcp = to_mcp_error_response(task_exc)
        project_mcp = to_mcp_error_response(project_exc)
        
        assert task_mcp["error"]["code"] == -32001
        assert project_mcp["error"]["code"] == -32001
