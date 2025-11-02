# TODO MCP Service - API Documentation

Comprehensive API documentation for the TODO MCP Service, a task management service for AI agents.

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Base URL](#base-url)
4. [Error Handling](#error-handling)
5. [REST API Endpoints](#rest-api-endpoints)
6. [MCP API Endpoints](#mcp-api-endpoints)
7. [GraphQL API](#graphql-api)
8. [Code Examples](#code-examples)
9. [OpenAPI/Swagger Specification](#openapiswagger-specification)
10. [Best Practices](#best-practices)

---

## Overview

The TODO MCP Service provides a comprehensive REST API, MCP (Model Context Protocol) API, and GraphQL API for managing tasks, projects, relationships, comments, tags, templates, and more.

### Key Features

- **Task Management**: Create, update, query, and track tasks with types (concrete, abstract, epic)
- **Project Support**: Organize tasks by project with origin URLs and local paths
- **Change History**: Full audit trail with agent identity tracking
- **Agent Performance**: Statistics and success rate tracking per agent
- **Backup & Restore**: Automatic nightly backups with gzip compression
- **Rate Limiting**: Sliding window rate limiting with global, per-endpoint, and per-agent limits
- **File Attachments**: Upload and manage file attachments for tasks
- **Comments & Threads**: Comment system with threaded replies and mentions
- **Tags & Templates**: Tagging system and reusable task templates

---

## Authentication

The API uses API key authentication. API keys are project-scoped and must be provided in requests.

### Authentication Methods

1. **X-API-Key Header** (Recommended)
   ```
   X-API-Key: todo_xxxxx...
   ```

2. **Authorization Bearer Token**
   ```
   Authorization: Bearer todo_xxxxx...
   ```

### Creating API Keys

```bash
# Create an API key for a project
curl -X POST http://localhost:8004/projects/{project_id}/api-keys \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <admin-key>" \
  -d '{
    "name": "My API Key"
  }'
```

**Response:**
```json
{
  "key_id": 1,
  "project_id": 1,
  "name": "My API Key",
  "key_prefix": "todo_abc",
  "api_key": "todo_abc123...",
  "enabled": true,
  "created_at": "2025-11-01T12:00:00",
  "updated_at": "2025-11-01T12:00:00"
}
```

**Important:** The full API key is only returned on creation. Store it securely immediately.

### Authentication Errors

- `401 Unauthorized`: Missing or invalid API key
- `403 Forbidden`: API key not authorized for the requested resource
- `401 Unauthorized`: API key has been revoked

---

## Base URL

```
http://localhost:8004
```

For production, replace `localhost:8004` with your server's hostname and port.

---

## Error Handling

### Error Response Format

All errors follow a consistent format:

```json
{
  "error": "Error type",
  "detail": "Detailed error message",
  "path": "/tasks/123",
  "method": "GET",
  "request_id": "abc123"
}
```

### HTTP Status Codes

| Status Code | Description |
|-------------|-------------|
| 200 | Success |
| 201 | Created successfully |
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Missing or invalid API key |
| 403 | Forbidden - API key not authorized |
| 404 | Not Found - Resource doesn't exist |
| 409 | Conflict - Resource already exists |
| 422 | Unprocessable Entity - Validation error |
| 429 | Too Many Requests - Rate limit exceeded |
| 500 | Internal Server Error |
| 503 | Service Unavailable |

### Rate Limiting

When rate limits are exceeded, the service returns `429 Too Many Requests` with headers:

- `Retry-After`: Seconds until retry
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Remaining requests in window
- `X-RateLimit-Reset`: Timestamp when limit resets

### Validation Errors

Validation errors include detailed field-level information:

```json
{
  "error": "Validation error",
  "detail": "One or more fields failed validation",
  "errors": [
    "title: Field cannot be empty or contain only whitespace",
    "task_type: Invalid task_type 'invalid'. Must be one of: concrete, abstract, epic"
  ],
  "path": "/tasks",
  "method": "POST",
  "request_id": "abc123"
}
```

---

## REST API Endpoints

### Health & Metrics

#### GET /health

Health check endpoint with service status.

**Authentication:** None required

**Response:**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "database": "connected",
  "uptime_seconds": 3600
}
```

---

#### GET /metrics

Prometheus metrics endpoint.

**Authentication:** None required

**Response:** Prometheus-formatted metrics

---

### Projects

#### POST /projects

Create a new project.

**Authentication:** None required (optional)

**Request Body:**
```json
{
  "name": "my-project",
  "local_path": "/path/to/project",
  "origin_url": "https://github.com/user/repo",
  "description": "Project description"
}
```

**Response:** `201 Created`
```json
{
  "id": 1,
  "name": "my-project",
  "local_path": "/path/to/project",
  "origin_url": "https://github.com/user/repo",
  "description": "Project description",
  "created_at": "2025-11-01T12:00:00",
  "updated_at": "2025-11-01T12:00:00"
}
```

---

#### GET /projects

List all projects.

**Authentication:** Optional

**Query Parameters:**
- None

**Response:**
```json
[
  {
    "id": 1,
    "name": "my-project",
    "local_path": "/path/to/project",
    "origin_url": "https://github.com/user/repo",
    "description": "Project description",
    "created_at": "2025-11-01T12:00:00",
    "updated_at": "2025-11-01T12:00:00"
  }
]
```

---

#### GET /projects/{project_id}

Get a project by ID.

**Authentication:** None required

**Path Parameters:**
- `project_id` (integer, required): Project ID

**Response:**
```json
{
  "id": 1,
  "name": "my-project",
  "local_path": "/path/to/project",
  "origin_url": "https://github.com/user/repo",
  "description": "Project description",
  "created_at": "2025-11-01T12:00:00",
  "updated_at": "2025-11-01T12:00:00"
}
```

---

#### GET /projects/name/{project_name}

Get a project by name.

**Authentication:** None required

**Path Parameters:**
- `project_name` (string, required): Project name

**Response:** Same as GET /projects/{project_id}

---

### Tasks

#### POST /tasks

Create a new task.

**Authentication:** Required

**Request Body:**
```json
{
  "title": "Implement feature X",
  "task_type": "concrete",
  "task_instruction": "Implement the feature",
  "verification_instruction": "Run tests and verify",
  "agent_id": "agent-123",
  "project_id": 1,
  "notes": "Additional notes",
  "priority": "high",
  "estimated_hours": 4.5,
  "due_date": "2025-12-01T12:00:00"
}
```

**Field Descriptions:**
- `title` (string, required): Task title
- `task_type` (string, required): One of `concrete`, `abstract`, `epic`
- `task_instruction` (string, required): What to do
- `verification_instruction` (string, required): How to verify completion
- `agent_id` (string, required): Agent ID creating this task
- `project_id` (integer, optional): Project ID (must match API key's project)
- `notes` (string, optional): Optional notes
- `priority` (string, optional): One of `low`, `medium`, `high`, `critical` (default: `medium`)
- `estimated_hours` (float, optional): Estimated hours for the task
- `due_date` (string, optional): Due date in ISO format

**Response:** `201 Created`
```json
{
  "id": 123,
  "project_id": 1,
  "title": "Implement feature X",
  "task_type": "concrete",
  "task_instruction": "Implement the feature",
  "verification_instruction": "Run tests and verify",
  "task_status": "available",
  "verification_status": "unverified",
  "priority": "high",
  "assigned_agent": null,
  "created_at": "2025-11-01T12:00:00",
  "updated_at": "2025-11-01T12:00:00",
  "completed_at": null,
  "notes": "Additional notes",
  "due_date": "2025-12-01T12:00:00"
}
```

---

#### GET /tasks/{task_id}

Get a task by ID.

**Authentication:** None required

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Response:**
```json
{
  "id": 123,
  "project_id": 1,
  "title": "Implement feature X",
  "task_type": "concrete",
  "task_instruction": "Implement the feature",
  "verification_instruction": "Run tests and verify",
  "task_status": "available",
  "verification_status": "unverified",
  "priority": "high",
  "assigned_agent": null,
  "created_at": "2025-11-01T12:00:00",
  "updated_at": "2025-11-01T12:00:00",
  "completed_at": null,
  "notes": "Additional notes",
  "due_date": "2025-12-01T12:00:00"
}
```

---

#### GET /tasks

Query tasks with filters.

**Authentication:** Optional

**Query Parameters:**
- `project_id` (integer, optional): Filter by project ID
- `task_type` (string, optional): Filter by task type (`concrete`, `abstract`, `epic`)
- `task_status` (string, optional): Filter by status (`available`, `in_progress`, `complete`, `blocked`, `cancelled`)
- `assigned_agent` (string, optional): Filter by assigned agent
- `priority` (string, optional): Filter by priority (`low`, `medium`, `high`, `critical`)
- `tag_id` (integer, optional): Filter by tag ID
- `order_by` (string, optional): Order by (`priority`, `priority_asc`)
- `limit` (integer, optional): Maximum results (default: 100)

**Response:**
```json
[
  {
    "id": 123,
    "project_id": 1,
    "title": "Implement feature X",
    ...
  }
]
```

---

#### POST /tasks/{task_id}/lock

Lock (reserve) a task for an agent.

**Authentication:** None required

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Request Body:**
```json
{
  "agent_id": "agent-123"
}
```

**Response:**
```json
{
  "task_id": 123,
  "agent_id": "agent-123",
  "status": "locked"
}
```

---

#### POST /tasks/{task_id}/unlock

Unlock (release) a task.

**Authentication:** None required

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Request Body:**
```json
{
  "agent_id": "agent-123"
}
```

**Response:**
```json
{
  "task_id": 123,
  "agent_id": "agent-123",
  "status": "unlocked"
}
```

---

#### POST /tasks/{task_id}/complete

Mark a task as complete.

**Authentication:** None required

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Request Body:**
```json
{
  "agent_id": "agent-123",
  "notes": "Completed successfully",
  "actual_hours": 4.5
}
```

**Response:**
```json
{
  "task_id": 123,
  "completed": true,
  "completed_at": "2025-11-01T12:00:00"
}
```

---

#### POST /tasks/{task_id}/verify

Verify a task's completion.

**Authentication:** None required

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Request Body:**
```json
{
  "agent_id": "agent-123",
  "verified": true
}
```

**Response:**
```json
{
  "task_id": 123,
  "verified": true
}
```

---

#### PATCH /tasks/{task_id}

Update a task.

**Authentication:** Optional (required if project-scoped)

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Request Body:**
```json
{
  "task_status": "in_progress",
  "verification_status": "verified",
  "notes": "Updated notes"
}
```

**Response:** Updated task object

---

#### GET /tasks/search

Search tasks using full-text search.

**Authentication:** Optional

**Query Parameters:**
- `q` (string, required): Search query
- `limit` (integer, optional): Maximum results (default: 100)

**Response:** List of matching tasks

---

#### GET /tasks/overdue

Get overdue tasks.

**Authentication:** Optional

**Response:** List of overdue tasks

---

#### GET /tasks/approaching-deadline

Get tasks approaching deadline.

**Authentication:** Optional

**Query Parameters:**
- `days_ahead` (integer, optional): Days ahead to look (default: 3)
- `limit` (integer, optional): Maximum results (default: 100)

**Response:** List of tasks approaching deadline

---

#### GET /tasks/activity-feed

Get activity feed for tasks.

**Authentication:** Optional

**Query Parameters:**
- `task_id` (integer, optional): Filter by task ID
- `agent_id` (string, optional): Filter by agent ID
- `start_date` (string, optional): Start date (ISO format)
- `end_date` (string, optional): End date (ISO format)
- `limit` (integer, optional): Maximum results (default: 1000)

**Response:**
```json
{
  "feed": [
    {
      "id": 1,
      "task_id": 123,
      "agent_id": "agent-123",
      "change_type": "status_change",
      "old_value": "available",
      "new_value": "in_progress",
      "created_at": "2025-11-01T12:00:00"
    }
  ],
  "count": 1
}
```

---

### Bulk Operations

#### POST /tasks/bulk/complete

Complete multiple tasks.

**Authentication:** None required

**Request Body:**
```json
{
  "task_ids": [123, 124, 125],
  "agent_id": "agent-123",
  "notes": "Bulk completion",
  "actual_hours": 10.0
}
```

**Response:**
```json
{
  "completed": [123, 124, 125],
  "failed": []
}
```

---

#### POST /tasks/bulk/assign

Assign multiple tasks to an agent.

**Authentication:** None required

**Request Body:**
```json
{
  "task_ids": [123, 124, 125],
  "agent_id": "agent-123",
  "require_all": false
}
```

**Response:**
```json
{
  "assigned": [123, 124, 125],
  "failed": []
}
```

---

#### POST /tasks/bulk/update-status

Update status of multiple tasks.

**Authentication:** None required

**Request Body:**
```json
{
  "task_ids": [123, 124, 125],
  "task_status": "in_progress",
  "agent_id": "agent-123",
  "require_all": false
}
```

**Response:**
```json
{
  "updated": [123, 124, 125],
  "failed": []
}
```

---

#### POST /tasks/bulk/delete

Delete multiple tasks.

**Authentication:** None required

**Request Body:**
```json
{
  "task_ids": [123, 124, 125],
  "confirm": true,
  "require_all": false
}
```

**Response:**
```json
{
  "deleted": [123, 124, 125],
  "failed": []
}
```

---

### File Attachments

#### POST /tasks/{task_id}/attachments

Upload a file attachment to a task.

**Authentication:** Optional (required if project-scoped)

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Request:** Multipart form data
- `file` (file, required): File to upload
- `description` (string, optional): File description

**File Constraints:**
- Maximum size: 10MB (default, configurable)
- Allowed types: Images, documents, archives, code files

**Response:** `201 Created`
```json
{
  "attachment_id": 1,
  "task_id": 123,
  "filename": "document.pdf",
  "file_size": 1024,
  "content_type": "application/pdf",
  "description": "Task document",
  "created_at": "2025-11-01T12:00:00"
}
```

---

#### GET /tasks/{task_id}/attachments

List attachments for a task.

**Authentication:** Optional

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Response:**
```json
[
  {
    "id": 1,
    "task_id": 123,
    "filename": "document.pdf",
    "file_size": 1024,
    "content_type": "application/pdf",
    "description": "Task document",
    "created_at": "2025-11-01T12:00:00"
  }
]
```

---

#### GET /tasks/{task_id}/attachments/{attachment_id}

Get attachment metadata.

**Authentication:** Optional

**Path Parameters:**
- `task_id` (integer, required): Task ID
- `attachment_id` (integer, required): Attachment ID

**Response:** Attachment metadata object

---

#### GET /tasks/{task_id}/attachments/{attachment_id}/download

Download an attachment.

**Authentication:** Optional

**Path Parameters:**
- `task_id` (integer, required): Task ID
- `attachment_id` (integer, required): Attachment ID

**Response:** File download with appropriate content-type

---

#### DELETE /tasks/{task_id}/attachments/{attachment_id}

Delete an attachment.

**Authentication:** Optional (required if project-scoped)

**Path Parameters:**
- `task_id` (integer, required): Task ID
- `attachment_id` (integer, required): Attachment ID

**Response:**
```json
{
  "message": "Attachment deleted",
  "attachment_id": 1
}
```

---

### Comments

#### POST /tasks/{task_id}/comments

Create a comment on a task.

**Authentication:** Optional (required if project-scoped)

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Request Body:**
```json
{
  "agent_id": "agent-123",
  "content": "This looks good!",
  "parent_comment_id": null,
  "mentions": ["agent-456"]
}
```

**Response:** `201 Created`
```json
{
  "id": 1,
  "task_id": 123,
  "agent_id": "agent-123",
  "content": "This looks good!",
  "parent_comment_id": null,
  "mentions": ["agent-456"],
  "created_at": "2025-11-01T12:00:00",
  "updated_at": null
}
```

---

#### GET /tasks/{task_id}/comments

Get all comments for a task.

**Authentication:** Optional

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Query Parameters:**
- `limit` (integer, optional): Maximum results (default: 100)

**Response:** List of comments

---

#### GET /tasks/{task_id}/comments/{comment_id}

Get a specific comment.

**Authentication:** Optional

**Path Parameters:**
- `task_id` (integer, required): Task ID
- `comment_id` (integer, required): Comment ID

**Response:** Comment object

---

#### GET /comments/{comment_id}/thread

Get a comment thread (parent and all replies).

**Authentication:** Optional

**Path Parameters:**
- `comment_id` (integer, required): Parent comment ID

**Response:** List of comments in thread

---

#### PUT /tasks/{task_id}/comments/{comment_id}

Update a comment.

**Authentication:** Optional (required if project-scoped)

**Path Parameters:**
- `task_id` (integer, required): Task ID
- `comment_id` (integer, required): Comment ID

**Request Body:**
```json
{
  "content": "Updated comment"
}
```

**Response:** Updated comment object

---

#### DELETE /tasks/{task_id}/comments/{comment_id}

Delete a comment (cascades to replies).

**Authentication:** Optional (required if project-scoped)

**Path Parameters:**
- `task_id` (integer, required): Task ID
- `comment_id` (integer, required): Comment ID

**Request Body:**
```json
{
  "agent_id": "agent-123"
}
```

**Response:**
```json
{
  "message": "Comment deleted",
  "comment_id": 1
}
```

---

### Relationships

#### POST /relationships

Create a relationship between tasks.

**Authentication:** None required

**Request Body:**
```json
{
  "parent_task_id": 100,
  "child_task_id": 123,
  "relationship_type": "subtask",
  "agent_id": "agent-123"
}
```

**Relationship Types:**
- `subtask`: Child is a subtask of parent
- `blocking`: Child blocks parent
- `blocked_by`: Child is blocked by parent
- `followup`: Child is a followup to parent
- `related`: Tasks are related

**Response:** `201 Created`
```json
{
  "relationship_id": 1,
  "parent_task_id": 100,
  "child_task_id": 123,
  "relationship_type": "subtask"
}
```

---

#### GET /tasks/{task_id}/relationships

Get relationships for a task.

**Authentication:** Optional

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Response:** List of relationships

---

#### GET /tasks/{task_id}/blocking

Get tasks blocking this task.

**Authentication:** Optional

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Response:** List of blocking tasks

---

### Tags

#### POST /tags

Create a tag.

**Authentication:** None required

**Request Body:**
```json
{
  "name": "urgent"
}
```

**Response:** `201 Created`
```json
{
  "id": 1,
  "name": "urgent",
  "created_at": "2025-11-01T12:00:00"
}
```

---

#### GET /tags

List all tags.

**Authentication:** None required

**Response:** List of tags

---

#### GET /tags/{tag_id}

Get a tag by ID.

**Authentication:** None required

**Path Parameters:**
- `tag_id` (integer, required): Tag ID

**Response:** Tag object

---

#### GET /tags/name/{tag_name}

Get a tag by name.

**Authentication:** None required

**Path Parameters:**
- `tag_name` (string, required): Tag name

**Response:** Tag object

---

#### POST /tasks/{task_id}/tags/{tag_id}

Assign a tag to a task.

**Authentication:** Optional (required if project-scoped)

**Path Parameters:**
- `task_id` (integer, required): Task ID
- `tag_id` (integer, required): Tag ID

**Response:**
```json
{
  "message": "Tag assigned",
  "task_id": 123,
  "tag_id": 1
}
```

---

#### DELETE /tasks/{task_id}/tags/{tag_id}

Remove a tag from a task.

**Authentication:** Optional (required if project-scoped)

**Path Parameters:**
- `task_id` (integer, required): Task ID
- `tag_id` (integer, required): Tag ID

**Response:**
```json
{
  "message": "Tag removed",
  "task_id": 123,
  "tag_id": 1
}
```

---

#### GET /tasks/{task_id}/tags

Get all tags for a task.

**Authentication:** Optional

**Path Parameters:**
- `task_id` (integer, required): Task ID

**Response:** List of tags

---

#### DELETE /tags/{tag_id}

Delete a tag (removes from all tasks).

**Authentication:** None required

**Path Parameters:**
- `tag_id` (integer, required): Tag ID

**Response:**
```json
{
  "message": "Tag deleted",
  "tag_id": 1
}
```

---

### Templates

#### POST /templates

Create a task template.

**Authentication:** None required

**Request Body:**
```json
{
  "name": "Bug Fix Template",
  "task_type": "concrete",
  "task_instruction": "Fix the bug described in the issue",
  "verification_instruction": "Run tests and verify the bug is fixed",
  "description": "Template for bug fixes",
  "priority": "high",
  "estimated_hours": 2.0,
  "notes": "Template notes"
}
```

**Response:** `201 Created`
```json
{
  "id": 1,
  "name": "Bug Fix Template",
  "description": "Template for bug fixes",
  "task_type": "concrete",
  "task_instruction": "Fix the bug described in the issue",
  "verification_instruction": "Run tests and verify the bug is fixed",
  "priority": "high",
  "estimated_hours": 2.0,
  "notes": "Template notes",
  "created_at": "2025-11-01T12:00:00",
  "updated_at": "2025-11-01T12:00:00"
}
```

---

#### GET /templates

List all templates.

**Authentication:** None required

**Query Parameters:**
- `task_type` (string, optional): Filter by task type

**Response:** List of templates

---

#### GET /templates/{template_id}

Get a template by ID.

**Authentication:** None required

**Path Parameters:**
- `template_id` (integer, required): Template ID

**Response:** Template object

---

#### POST /templates/{template_id}/create-task

Create a task from a template.

**Authentication:** Required

**Path Parameters:**
- `template_id` (integer, required): Template ID

**Request Body:**
```json
{
  "agent_id": "agent-123",
  "title": "Fix bug #123",
  "project_id": 1,
  "notes": "Additional notes",
  "priority": "critical",
  "estimated_hours": 3.0,
  "due_date": "2025-12-01T12:00:00"
}
```

**Response:** `201 Created` - Task object

---

### Backup & Restore

#### POST /backup/create

Create a backup of the database.

**Authentication:** None required

**Response:**
```json
{
  "backup_file": "backup_20251101_120000.db.gz",
  "created_at": "2025-11-01T12:00:00",
  "size_bytes": 1024
}
```

---

#### GET /backup/list

List all backups.

**Authentication:** None required

**Response:**
```json
[
  {
    "filename": "backup_20251101_120000.db.gz",
    "size_bytes": 1024,
    "created_at": "2025-11-01T12:00:00"
  }
]
```

---

#### POST /backup/restore

Restore from a backup.

**Authentication:** None required

**Request Body:**
```json
{
  "backup_file": "backup_20251101_120000.db.gz",
  "confirm": true
}
```

**Response:**
```json
{
  "message": "Backup restored",
  "backup_file": "backup_20251101_120000.db.gz"
}
```

---

#### POST /backup/cleanup

Clean up old backups.

**Authentication:** None required

**Request Body:**
```json
{
  "keep_last_n": 10,
  "older_than_days": 30
}
```

**Response:**
```json
{
  "deleted": 5,
  "kept": 10
}
```

---

### Webhooks

#### POST /projects/{project_id}/webhooks

Create a webhook for a project.

**Authentication:** Required

**Path Parameters:**
- `project_id` (integer, required): Project ID

**Request Body:**
```json
{
  "url": "https://example.com/webhook",
  "events": ["task.created", "task.completed"],
  "secret": "webhook-secret",
  "enabled": true
}
```

**Response:** `201 Created`
```json
{
  "id": 1,
  "project_id": 1,
  "url": "https://example.com/webhook",
  "events": ["task.created", "task.completed"],
  "enabled": true,
  "created_at": "2025-11-01T12:00:00"
}
```

---

#### GET /projects/{project_id}/webhooks

List webhooks for a project.

**Authentication:** Required

**Path Parameters:**
- `project_id` (integer, required): Project ID

**Response:** List of webhooks

---

#### GET /webhooks/{webhook_id}

Get a webhook by ID.

**Authentication:** Required

**Path Parameters:**
- `webhook_id` (integer, required): Webhook ID

**Response:** Webhook object

---

#### DELETE /webhooks/{webhook_id}

Delete a webhook.

**Authentication:** Required

**Path Parameters:**
- `webhook_id` (integer, required): Webhook ID

**Response:**
```json
{
  "message": "Webhook deleted",
  "webhook_id": 1
}
```

---

### API Keys

#### POST /projects/{project_id}/api-keys

Create an API key for a project.

**Authentication:** Required (admin key)

**Path Parameters:**
- `project_id` (integer, required): Project ID

**Request Body:**
```json
{
  "name": "My API Key"
}
```

**Response:** `201 Created`
```json
{
  "key_id": 1,
  "project_id": 1,
  "name": "My API Key",
  "key_prefix": "todo_abc",
  "api_key": "todo_abc123...",
  "enabled": true,
  "created_at": "2025-11-01T12:00:00",
  "updated_at": "2025-11-01T12:00:00"
}
```

---

#### GET /projects/{project_id}/api-keys

List API keys for a project.

**Authentication:** Required

**Path Parameters:**
- `project_id` (integer, required): Project ID

**Response:** List of API keys (without full key)

---

#### DELETE /api-keys/{key_id}

Delete (revoke) an API key.

**Authentication:** Required

**Path Parameters:**
- `key_id` (integer, required): Key ID

**Response:**
```json
{
  "message": "API key revoked",
  "key_id": 1
}
```

---

#### POST /api-keys/{key_id}/rotate

Rotate an API key (generates new key, revokes old).

**Authentication:** Required

**Path Parameters:**
- `key_id` (integer, required): Key ID

**Response:**
```json
{
  "key_id": 1,
  "project_id": 1,
  "name": "My API Key",
  "key_prefix": "todo_xyz",
  "api_key": "todo_xyz789...",
  "enabled": true,
  "created_at": "2025-11-01T12:00:00",
  "updated_at": "2025-11-01T12:00:00"
}
```

---

### Analytics

#### GET /analytics/metrics

Get analytics metrics.

**Authentication:** Optional

**Response:**
```json
{
  "total_tasks": 1000,
  "tasks_by_status": {
    "available": 500,
    "in_progress": 200,
    "complete": 300
  },
  "tasks_by_type": {
    "concrete": 800,
    "abstract": 150,
    "epic": 50
  }
}
```

---

#### GET /analytics/bottlenecks

Get bottleneck analysis.

**Authentication:** Optional

**Response:** Bottleneck information

---

#### GET /analytics/agents

Get agent analytics.

**Authentication:** Optional

**Response:** Agent performance statistics

---

#### GET /analytics/visualization

Get visualization data.

**Authentication:** Optional

**Response:** Visualization data

---

### Export/Import

#### GET /tasks/export/json

Export tasks as JSON.

**Authentication:** Optional

**Query Parameters:**
- `project_id` (integer, optional): Filter by project
- `task_type` (string, optional): Filter by type
- `task_status` (string, optional): Filter by status

**Response:** JSON file download

---

#### GET /tasks/export/csv

Export tasks as CSV.

**Authentication:** Optional

**Query Parameters:** Same as JSON export

**Response:** CSV file download

---

#### POST /tasks/import/json

Import tasks from JSON.

**Authentication:** Required

**Request Body:**
```json
{
  "tasks": [
    {
      "title": "Task 1",
      "task_type": "concrete",
      ...
    }
  ],
  "agent_id": "agent-123",
  "handle_duplicates": "skip"
}
```

**Response:**
```json
{
  "imported": 10,
  "skipped": 2,
  "errors": []
}
```

---

#### POST /tasks/import/csv

Import tasks from CSV.

**Authentication:** Required

**Request:** Multipart form data with CSV file

**Response:** Same as JSON import

---

## MCP API Endpoints

The MCP (Model Context Protocol) API provides a standardized interface for AI agents. All MCP endpoints use POST requests with JSON bodies.

### Base Endpoint

All MCP endpoints are available at `/mcp/{function_name}`.

### MCP Functions

#### POST /mcp/list_available_tasks

List available tasks for an agent type.

**Request Body:**
```json
{
  "agent_type": "implementation",
  "project_id": 1,
  "limit": 10
}
```

**Response:**
```json
[
  {
    "id": 123,
    "project_id": 1,
    "title": "Implement feature X",
    "task_type": "concrete",
    "task_status": "available",
    ...
  }
]
```

---

#### POST /mcp/reserve_task

Reserve (lock) a task for an agent.

**Request Body:**
```json
{
  "task_id": 123,
  "agent_id": "agent-123"
}
```

**Response:**
```json
{
  "success": true,
  "task": {
    "id": 123,
    "title": "Implement feature X",
    ...
  }
}
```

---

#### POST /mcp/complete_task

Complete a task.

**Request Body:**
```json
{
  "task_id": 123,
  "agent_id": "agent-123",
  "notes": "Completed successfully",
  "actual_hours": 4.5
}
```

**Response:**
```json
{
  "success": true,
  "task_id": 123,
  "completed": true
}
```

---

#### POST /mcp/create_task

Create a new task.

**Request Body:**
```json
{
  "title": "New task",
  "task_type": "concrete",
  "task_instruction": "Do something",
  "verification_instruction": "Verify it's done",
  "agent_id": "agent-123",
  "project_id": 1
}
```

**Response:**
```json
{
  "success": true,
  "task_id": 124
}
```

---

#### POST /mcp/get_agent_performance

Get agent performance statistics.

**Request Body:**
```json
{
  "agent_id": "agent-123",
  "task_type": "concrete"
}
```

**Response:**
```json
{
  "agent_id": "agent-123",
  "total_tasks": 50,
  "completed_tasks": 45,
  "success_rate": 0.9,
  ...
}
```

---

#### POST /mcp/unlock_task

Unlock a reserved task.

**Request Body:**
```json
{
  "task_id": 123,
  "agent_id": "agent-123"
}
```

**Response:**
```json
{
  "success": true,
  "task_id": 123,
  "message": "Task 123 unlocked successfully"
}
```

---

#### POST /mcp/query_tasks

Query tasks by various criteria.

**Request Body:**
```json
{
  "project_id": 1,
  "task_type": "concrete",
  "task_status": "available",
  "limit": 100
}
```

**Response:** List of matching tasks

---

#### POST /mcp/add_task_update

Add a task update (progress, note, blocker, question, finding).

**Request Body:**
```json
{
  "task_id": 123,
  "agent_id": "agent-123",
  "content": "Making good progress",
  "update_type": "progress",
  "metadata": {}
}
```

**Response:**
```json
{
  "success": true,
  "update_id": 1,
  "task_id": 123
}
```

---

#### POST /mcp/get_task_context

Get full context for a task.

**Request Body:**
```json
{
  "task_id": 123
}
```

**Response:**
```json
{
  "success": true,
  "task": {...},
  "project": {...},
  "updates": [...],
  "ancestry": [...],
  "recent_changes": [...]
}
```

---

#### POST /mcp/search_tasks

Search tasks using full-text search.

**Request Body:**
```json
{
  "query": "implement feature",
  "limit": 100
}
```

**Response:** List of matching tasks

---

#### POST /mcp/get_tasks_approaching_deadline

Get tasks approaching deadline.

**Request Body:**
```json
{
  "days_ahead": 3,
  "limit": 100
}
```

**Response:**
```json
{
  "success": true,
  "tasks": [...],
  "days_ahead": 3
}
```

---

#### POST /mcp/create_tag

Create a tag.

**Request Body:**
```json
{
  "name": "urgent"
}
```

**Response:**
```json
{
  "success": true,
  "tag_id": 1,
  "tag": {...}
}
```

---

#### POST /mcp/list_tags

List all tags.

**Request Body:**
```json
{}
```

**Response:**
```json
{
  "success": true,
  "tags": [...]
}
```

---

#### POST /mcp/assign_tag_to_task

Assign a tag to a task.

**Request Body:**
```json
{
  "task_id": 123,
  "tag_id": 1
}
```

**Response:**
```json
{
  "success": true,
  "task_id": 123,
  "tag_id": 1
}
```

---

#### POST /mcp/remove_tag_from_task

Remove a tag from a task.

**Request Body:**
```json
{
  "task_id": 123,
  "tag_id": 1
}
```

**Response:**
```json
{
  "success": true,
  "task_id": 123,
  "tag_id": 1
}
```

---

#### POST /mcp/get_task_tags

Get all tags for a task.

**Request Body:**
```json
{
  "task_id": 123
}
```

**Response:**
```json
{
  "success": true,
  "task_id": 123,
  "tags": [...]
}
```

---

#### POST /mcp/create_template

Create a task template.

**Request Body:**
```json
{
  "name": "Bug Fix Template",
  "task_type": "concrete",
  "task_instruction": "Fix the bug",
  "verification_instruction": "Verify it's fixed",
  "description": "Template for bugs",
  "priority": "high"
}
```

**Response:**
```json
{
  "success": true,
  "template_id": 1,
  "template": {...}
}
```

---

#### POST /mcp/list_templates

List all templates.

**Request Body:**
```json
{
  "task_type": "concrete"
}
```

**Response:**
```json
{
  "success": true,
  "templates": [...]
}
```

---

#### POST /mcp/get_template

Get a template by ID.

**Request Body:**
```json
{
  "template_id": 1
}
```

**Response:**
```json
{
  "success": true,
  "template": {...}
}
```

---

#### POST /mcp/create_task_from_template

Create a task from a template.

**Request Body:**
```json
{
  "template_id": 1,
  "agent_id": "agent-123",
  "title": "Fix bug #123",
  "project_id": 1
}
```

**Response:**
```json
{
  "success": true,
  "task_id": 124
}
```

---

#### POST /mcp/get_activity_feed

Get activity feed.

**Request Body:**
```json
{
  "task_id": 123,
  "agent_id": "agent-123",
  "start_date": "2025-11-01T00:00:00",
  "end_date": "2025-11-02T00:00:00",
  "limit": 1000
}
```

**Response:**
```json
{
  "success": true,
  "feed": [...],
  "count": 50
}
```

---

#### POST /mcp/create_comment

Create a comment on a task.

**Request Body:**
```json
{
  "task_id": 123,
  "agent_id": "agent-123",
  "content": "This looks good!",
  "parent_comment_id": null,
  "mentions": ["agent-456"]
}
```

**Response:**
```json
{
  "success": true,
  "comment_id": 1,
  "task_id": 123
}
```

---

#### POST /mcp/get_task_comments

Get comments for a task.

**Request Body:**
```json
{
  "task_id": 123,
  "limit": 100
}
```

**Response:**
```json
{
  "success": true,
  "task_id": 123,
  "comments": [...],
  "count": 10
}
```

---

#### POST /mcp/get_comment_thread

Get a comment thread.

**Request Body:**
```json
{
  "comment_id": 1
}
```

**Response:**
```json
{
  "success": true,
  "comment_id": 1,
  "thread": [...],
  "count": 5
}
```

---

#### POST /mcp/update_comment

Update a comment.

**Request Body:**
```json
{
  "comment_id": 1,
  "agent_id": "agent-123",
  "content": "Updated content"
}
```

**Response:**
```json
{
  "success": true,
  "comment_id": 1,
  "comment": {...}
}
```

---

#### POST /mcp/delete_comment

Delete a comment.

**Request Body:**
```json
{
  "comment_id": 1,
  "agent_id": "agent-123"
}
```

**Response:**
```json
{
  "success": true,
  "comment_id": 1,
  "message": "Comment 1 deleted successfully"
}
```

---

#### POST /mcp/functions

List all available MCP functions.

**Request Body:**
```json
{}
```

**Response:** List of MCP function definitions

---

#### POST /mcp/sse

MCP Server-Sent Events (SSE) endpoint for streaming.

**Authentication:** None required

This endpoint supports MCP protocol over SSE for real-time communication.

---

## GraphQL API

The service also provides a GraphQL API at `/graphql`.

### GraphQL Endpoint

```
POST /graphql
```

### GraphQL Schema

Query the GraphQL schema using introspection:

```graphql
query {
  __schema {
    types {
      name
      fields {
        name
        type {
          name
        }
      }
    }
  }
}
```

### Example GraphQL Query

```graphql
query {
  tasks(projectId: 1, taskStatus: "available") {
    id
    title
    taskType
    taskStatus
    priority
    assignedAgent
  }
}
```

---

## Code Examples

### Python

```python
import requests

# Base URL
BASE_URL = "http://localhost:8004"
API_KEY = "todo_xxxxx..."

# Headers
headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

# Create a task
response = requests.post(
    f"{BASE_URL}/tasks",
    json={
        "title": "Implement feature X",
        "task_type": "concrete",
        "task_instruction": "Implement the feature",
        "verification_instruction": "Run tests and verify",
        "agent_id": "agent-123",
        "project_id": 1,
        "priority": "high"
    },
    headers=headers
)
task = response.json()
print(f"Created task: {task['id']}")

# Get a task
response = requests.get(
    f"{BASE_URL}/tasks/{task['id']}",
    headers=headers
)
task_data = response.json()
print(f"Task: {task_data['title']}")

# Complete a task
response = requests.post(
    f"{BASE_URL}/tasks/{task['id']}/complete",
    json={
        "agent_id": "agent-123",
        "notes": "Completed successfully"
    },
    headers=headers
)
print("Task completed")
```

---

### JavaScript (Node.js)

```javascript
const axios = require('axios');

const BASE_URL = 'http://localhost:8004';
const API_KEY = 'todo_xxxxx...';

const client = axios.create({
  baseURL: BASE_URL,
  headers: {
    'X-API-Key': API_KEY,
    'Content-Type': 'application/json'
  }
});

// Create a task
async function createTask() {
  const response = await client.post('/tasks', {
    title: 'Implement feature X',
    task_type: 'concrete',
    task_instruction: 'Implement the feature',
    verification_instruction: 'Run tests and verify',
    agent_id: 'agent-123',
    project_id: 1,
    priority: 'high'
  });
  
  console.log(`Created task: ${response.data.id}`);
  return response.data;
}

// Get a task
async function getTask(taskId) {
  const response = await client.get(`/tasks/${taskId}`);
  return response.data;
}

// Complete a task
async function completeTask(taskId) {
  const response = await client.post(`/tasks/${taskId}/complete`, {
    agent_id: 'agent-123',
    notes: 'Completed successfully'
  });
  return response.data;
}

// Usage
(async () => {
  const task = await createTask();
  const taskData = await getTask(task.id);
  await completeTask(task.id);
})();
```

---

### cURL

```bash
# Set API key
API_KEY="todo_xxxxx..."
BASE_URL="http://localhost:8004"

# Create a task
curl -X POST "${BASE_URL}/tasks" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Implement feature X",
    "task_type": "concrete",
    "task_instruction": "Implement the feature",
    "verification_instruction": "Run tests and verify",
    "agent_id": "agent-123",
    "project_id": 1,
    "priority": "high"
  }'

# Get a task
curl -X GET "${BASE_URL}/tasks/123" \
  -H "X-API-Key: ${API_KEY}"

# Complete a task
curl -X POST "${BASE_URL}/tasks/123/complete" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent-123",
    "notes": "Completed successfully"
  }'
```

---

### Go

```go
package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "net/http"
)

const (
    baseURL = "http://localhost:8004"
    apiKey  = "todo_xxxxx..."
)

type TaskCreate struct {
    Title                 string  `json:"title"`
    TaskType              string  `json:"task_type"`
    TaskInstruction       string  `json:"task_instruction"`
    VerificationInstruction string `json:"verification_instruction"`
    AgentID               string  `json:"agent_id"`
    ProjectID             int     `json:"project_id"`
    Priority              string  `json:"priority"`
}

func createTask(task TaskCreate) error {
    body, err := json.Marshal(task)
    if err != nil {
        return err
    }

    req, err := http.NewRequest("POST", baseURL+"/tasks", bytes.NewBuffer(body))
    if err != nil {
        return err
    }

    req.Header.Set("X-API-Key", apiKey)
    req.Header.Set("Content-Type", "application/json")

    client := &http.Client{}
    resp, err := client.Do(req)
    if err != nil {
        return err
    }
    defer resp.Body.Close()

    var result map[string]interface{}
    json.NewDecoder(resp.Body).Decode(&result)
    fmt.Printf("Created task: %v\n", result["id"])
    return nil
}

func main() {
    task := TaskCreate{
        Title:                 "Implement feature X",
        TaskType:              "concrete",
        TaskInstruction:       "Implement the feature",
        VerificationInstruction: "Run tests and verify",
        AgentID:               "agent-123",
        ProjectID:             1,
        Priority:              "high",
    }

    if err := createTask(task); err != nil {
        fmt.Printf("Error: %v\n", err)
    }
}
```

---

### Rust

```rust
use reqwest::Client;
use serde::{Deserialize, Serialize};

const BASE_URL: &str = "http://localhost:8004";
const API_KEY: &str = "todo_xxxxx...";

#[derive(Serialize)]
struct TaskCreate {
    title: String,
    task_type: String,
    task_instruction: String,
    verification_instruction: String,
    agent_id: String,
    project_id: i32,
    priority: String,
}

#[derive(Deserialize)]
struct TaskResponse {
    id: i32,
    title: String,
}

async fn create_task() -> Result<TaskResponse, Box<dyn std::error::Error>> {
    let client = Client::new();
    
    let task = TaskCreate {
        title: "Implement feature X".to_string(),
        task_type: "concrete".to_string(),
        task_instruction: "Implement the feature".to_string(),
        verification_instruction: "Run tests and verify".to_string(),
        agent_id: "agent-123".to_string(),
        project_id: 1,
        priority: "high".to_string(),
    };

    let response = client
        .post(&format!("{}/tasks", BASE_URL))
        .header("X-API-Key", API_KEY)
        .json(&task)
        .send()
        .await?;

    let task_response: TaskResponse = response.json().await?;
    Ok(task_response)
}

#[tokio::main]
async fn main() {
    match create_task().await {
        Ok(task) => println!("Created task: {}", task.id),
        Err(e) => eprintln!("Error: {}", e),
    }
}
```

---

## OpenAPI/Swagger Specification

FastAPI automatically generates an OpenAPI 3.0 specification. Access it at:

- **Swagger UI**: `http://localhost:8004/docs`
- **ReDoc**: `http://localhost:8004/redoc`
- **OpenAPI JSON**: `http://localhost:8004/openapi.json`

### Exporting OpenAPI Spec

```bash
# Get OpenAPI JSON
curl http://localhost:8004/openapi.json > openapi.json

# Validate OpenAPI spec
npm install -g swagger-cli
swagger-cli validate openapi.json
```

---

## Best Practices

### 1. Error Handling

Always handle errors appropriately:

```python
try:
    response = requests.post(url, json=data, headers=headers)
    response.raise_for_status()
    return response.json()
except requests.HTTPError as e:
    if e.response.status_code == 429:
        retry_after = e.response.headers.get('Retry-After')
        print(f"Rate limited. Retry after {retry_after} seconds")
    elif e.response.status_code == 401:
        print("Authentication failed. Check your API key.")
    else:
        print(f"Error: {e.response.json()}")
```

### 2. Rate Limiting

Respect rate limits and implement exponential backoff:

```python
import time
import random

def make_request_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=data, headers=headers)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                wait_time = retry_after + random.uniform(0, 1)
                time.sleep(wait_time)
                continue
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = (2 ** attempt) + random.uniform(0, 1)
            time.sleep(wait_time)
```

### 3. Task Lifecycle

Follow proper task lifecycle:

1. **List available tasks** ? `GET /tasks?task_status=available`
2. **Reserve task** ? `POST /tasks/{id}/lock`
3. **Work on task** ? Add updates with `POST /mcp/add_task_update`
4. **Complete task** ? `POST /tasks/{id}/complete`
5. **Or unlock if unable to complete** ? `POST /tasks/{id}/unlock`

### 4. API Key Security

- Never commit API keys to version control
- Use environment variables or secure secret management
- Rotate keys periodically
- Use different keys for different environments

### 5. Pagination

When querying large datasets, use pagination:

```python
def get_all_tasks(limit=100):
    all_tasks = []
    offset = 0
    
    while True:
        response = requests.get(
            f"{BASE_URL}/tasks",
            params={"limit": limit, "offset": offset},
            headers=headers
        )
        tasks = response.json()
        if not tasks:
            break
        all_tasks.extend(tasks)
        offset += limit
        
    return all_tasks
```

### 6. Idempotency

Many operations are idempotent. This allows safe retries:

- Task completion can be called multiple times
- Tag assignment/removal is idempotent
- Task updates are additive

### 7. Monitoring

Monitor API usage:

- Check `/health` endpoint regularly
- Monitor rate limit headers
- Log request IDs for debugging
- Track error rates and types

---

## Support

For issues, questions, or contributions, please see the project repository.

---

**Documentation Version:** 1.0  
**Last Updated:** 2025-11-01  
**API Version:** 0.1.0
