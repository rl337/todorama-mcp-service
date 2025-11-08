"""
YAML-driven test runner for API endpoint tests.
Allows test cases to be defined in YAML files instead of Python functions.
"""
import yaml
import pytest
from typing import Dict, Any, List, Optional
from fastapi.testclient import TestClient


class YAMLTestRunner:
    """Runs test cases defined in YAML files."""
    
    def __init__(self, client: TestClient, auth_client: Any = None):
        self.client = client
        self.auth_client = auth_client
        self.variables = {}  # Store variables from setup steps
    
    def run_test_case(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run a single test case from YAML.
        
        Args:
            test_case: Test case dictionary from YAML
            
        Returns:
            Dict with test results
        """
        name = test_case.get("name", "unnamed_test")
        endpoint = test_case.get("endpoint")
        method = test_case.get("method", "GET").upper()
        requires_auth = test_case.get("auth", False)
        request_data = test_case.get("request", {})
        expected = test_case.get("expected", {})
        setup = test_case.get("setup", [])
        
        # Run setup steps
        for setup_step in setup:
            self._run_setup_step(setup_step)
        
        # Substitute variables in request
        request_data = self._substitute_variables(request_data)
        
        # Get the appropriate client
        client = self.auth_client if requires_auth and self.auth_client else self.client
        
        # Make request
        if method == "GET":
            # For GET, request_data goes to query params
            response = client.get(endpoint, params=request_data)
        elif method == "POST":
            # Add project_id if using auth_client and not present
            # But exclude endpoints that don't accept project_id (lock, unlock, complete, etc.)
            if self.auth_client and requires_auth and isinstance(request_data, dict):
                # Endpoints that don't accept project_id in the body
                excluded_endpoints = ["/api/Task/lock", "/api/Task/unlock", "/api/Task/complete"]
                if "project_id" not in request_data and endpoint.startswith("/api/Task"):
                    if endpoint not in excluded_endpoints:
                        request_data["project_id"] = self.auth_client.project_id
            response = client.post(endpoint, json=request_data)
        elif method == "PATCH":
            # For PATCH, endpoint might have query params
            if "task_id" in request_data:
                params = {"task_id": request_data.pop("task_id")}
            else:
                params = {}
            # Add project_id if needed
            if self.auth_client and requires_auth and isinstance(request_data, dict):
                if "project_id" not in request_data and endpoint.startswith("/api/Task"):
                    request_data["project_id"] = self.auth_client.project_id
            response = client.patch(endpoint, params=params, json=request_data)
        elif method == "DELETE":
            response = client.delete(endpoint, json=request_data)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        # Validate response
        results = {
            "name": name,
            "status_code": response.status_code,
            "expected_status": expected.get("status_code"),
            "passed": True,
            "errors": []
        }
        
        # Check status code
        expected_status = expected.get("status_code")
        if expected_status and response.status_code != expected_status:
            results["passed"] = False
            results["errors"].append(
                f"Expected status {expected_status}, got {response.status_code}"
            )
        
        # Check response fields exist
        if response.status_code < 400:
            try:
                response_data = response.json()
                required_fields = expected.get("response_fields", [])
                for field in required_fields:
                    if field not in response_data:
                        results["passed"] = False
                        results["errors"].append(f"Missing required field: {field}")
                
                # Run assertions
                assertions = expected.get("assertions", [])
                for assertion in assertions:
                    field = assertion.get("field")
                    expected_value = assertion.get("equals")
                    
                    if expected_value is not None:
                        # Substitute variables in expected value
                        expected_value = self._substitute_variables(expected_value)
                    
                    if field and expected_value is not None:
                        actual_value = response_data.get(field)
                        # Handle nested fields (e.g., "task.status")
                        if "." in field:
                            parts = field.split(".")
                            actual_value = response_data
                            for part in parts:
                                if isinstance(actual_value, dict):
                                    actual_value = actual_value.get(part)
                                else:
                                    actual_value = None
                                    break
                        
                        # Normalize types for comparison (handle string vs int)
                        if isinstance(expected_value, str) and expected_value.startswith("${"):
                            # This is a variable reference that should have been substituted
                            # If it wasn't substituted, it means the variable wasn't found
                            pass
                        elif isinstance(actual_value, int) and isinstance(expected_value, str):
                            # Try converting expected to int if actual is int
                            try:
                                expected_value = int(expected_value)
                            except (ValueError, TypeError):
                                pass
                        elif isinstance(actual_value, str) and isinstance(expected_value, int):
                            # Try converting actual to int if expected is int
                            try:
                                actual_value = int(actual_value)
                            except (ValueError, TypeError):
                                pass
                        
                        if actual_value != expected_value:
                            results["passed"] = False
                            results["errors"].append(
                                f"Field '{field}': expected {expected_value} (type {type(expected_value).__name__}), got {actual_value} (type {type(actual_value).__name__})"
                            )
                    
                    # Check for "in" assertions (field should contain value)
                    if assertion.get("contains"):
                        contains_value = self._substitute_variables(assertion.get("contains"))
                        field = assertion.get("field")
                        if field:
                            actual_value = response_data.get(field, "")
                            if contains_value not in str(actual_value):
                                results["passed"] = False
                                results["errors"].append(
                                    f"Field '{field}': expected to contain '{contains_value}', got '{actual_value}'"
                                )
                
                # Save response data for later use
                if "save_response" in test_case:
                    save_key = test_case["save_response"]
                    self.variables[save_key] = response_data
                    
            except Exception as e:
                results["passed"] = False
                results["errors"].append(f"Failed to parse response: {str(e)}")
        
        return results
    
    def _run_setup_step(self, setup_step: Dict[str, Any]):
        """Run a setup step (e.g., create a task)."""
        step_type = setup_step.get("type")
        save_as = setup_step.get("save_as")
        
        if step_type == "create_task":
            # Create a task and save its ID
            task_data = setup_step.get("data", {
                "title": "Setup Task",
                "task_type": "concrete",
                "task_instruction": "Test",
                "verification_instruction": "Verify",
                "agent_id": "test-agent"
            })
            
            # Substitute variables in task_data
            task_data = self._substitute_variables(task_data)
            
            # Add project_id if using auth_client
            if self.auth_client and "project_id" not in task_data:
                task_data["project_id"] = self.auth_client.project_id
            
            # Use auth_client if available, otherwise client
            client = self.auth_client if self.auth_client else self.client
            response = client.post("/api/Task/create", json=task_data)
            
            if response.status_code in [200, 201] and save_as:
                response_data = response.json()
                self.variables[save_as] = response_data.get("id")
        elif step_type == "set_project_id":
            # Set project_id variable from auth_client
            if self.auth_client:
                self.variables["project_id"] = self.auth_client.project_id
        # Add more setup step types as needed
    
    def _substitute_variables(self, data: Any) -> Any:
        """Substitute ${variable} references in data."""
        if isinstance(data, str):
            # Simple variable substitution: ${var_name}
            import re
            pattern = r'\$\{(\w+)\}'
            matches = re.findall(pattern, data)
            for var_name in matches:
                if var_name in self.variables:
                    data = data.replace(f"${{{var_name}}}", str(self.variables[var_name]))
            return data
        elif isinstance(data, dict):
            return {k: self._substitute_variables(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._substitute_variables(item) for item in data]
        else:
            return data


def load_yaml_tests(yaml_file: str) -> List[Dict[str, Any]]:
    """Load test cases from a YAML file."""
    with open(yaml_file, 'r') as f:
        data = yaml.safe_load(f)
        return data.get("test_cases", [])


# Note: The yaml_runner fixture and test_yaml_driven function should be added to test_api.py
# to use the existing client and auth_client fixtures

