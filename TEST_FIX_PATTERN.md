# Test Fix Pattern for API Tests

## Overview
Many tests in `test_api.py` are failing because they:
1. Don't use authentication (need `auth_client` instead of `client`)
2. Don't wrap task creation in `"task"` field
3. Don't wrap lock/complete/verify requests in `"request"` field
4. Don't include `project_id` in task creation requests

## Fix Pattern

### Pattern 1: Task Creation Tests
**Before:**
```python
def test_something(client):
    response = client.post("/tasks", json={
        "title": "Test",
        "task_type": "concrete",
        "task_instruction": "Do something",
        "verification_instruction": "Verify",
        "agent_id": "test-agent"
    })
```

**After:**
```python
def test_something(auth_client):
    response = auth_client.post("/tasks", json={
        "task": {
            "title": "Test",
            "task_type": "concrete",
            "task_instruction": "Do something",
            "verification_instruction": "Verify",
            "agent_id": "test-agent",
            "project_id": auth_client.project_id
        }
    })
```

### Pattern 2: Lock/Complete/Verify Tests
**Before:**
```python
client.post(f"/tasks/{task_id}/lock", json={"agent_id": "agent-1"})
client.post(f"/tasks/{task_id}/complete", json={"agent_id": "agent-1", "notes": "Done"})
client.post(f"/tasks/{task_id}/verify", json={"agent_id": "agent-1"})
```

**After:**
```python
auth_client.post(f"/tasks/{task_id}/lock", json={"request": {"agent_id": "agent-1"}})
auth_client.post(f"/tasks/{task_id}/complete", json={"request": {"agent_id": "agent-1", "notes": "Done"}})
auth_client.post(f"/tasks/{task_id}/verify", json={"request": {"agent_id": "agent-1"}})
```

### Pattern 3: GET Requests
**Before:**
```python
response = client.get("/tasks")
response = client.get(f"/tasks/{task_id}")
```

**After:**
```python
response = auth_client.get("/tasks")
response = auth_client.get(f"/tasks/{task_id}")
```

## Implementation Checklist

- [x] Fixed service container override in test fixtures
- [x] Added auth_client fixture
- [x] Fixed test_create_task, test_lock_task, test_complete_task
- [x] Fixed test_backup_restore
- [x] Fixed test_error_handling_* tests
- [x] Fixed test_create_task_with_priority, test_create_task_default_priority
- [x] Fixed test_query_tasks_by_priority, test_query_tasks_ordered_by_priority
- [x] Fixed test_create_task_with_due_date
- [x] Fixed test_query_overdue_tasks, test_query_tasks_approaching_deadline
- [x] Fixed test_query_tasks_by_date_range_* tests
- [x] Fixed test_query_tasks_by_text_search, test_query_tasks_combined_filters
- [x] Fixed test_validation_* tests
- [x] Fixed test_search_tasks_* tests
- [x] Fixed test_invalid_priority_error
- [ ] Fix remaining ~137 tests following the same pattern

## Remaining Tests to Fix

Most remaining tests follow the same patterns:
1. Change `client` parameter to `auth_client`
2. Wrap task creation JSON in `{"task": {...}}`
3. Add `"project_id": auth_client.project_id` to task creation
4. Wrap lock/complete/verify JSON in `{"request": {...}}`
5. Change `client.get/post/put/delete` to `auth_client.get/post/put/delete`

## Notes

- Some tests don't need authentication (e.g., health check, metrics) - these should keep using `client`
- Template, export, import, and other non-task endpoints may have different patterns
- Rate limiting tests may need special handling
- User authentication tests may need different fixtures
