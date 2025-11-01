# TODO Service - Standalone Task Management Service

A standalone SQLite-based task management service for AI agents with change history tracking and MCP (Model Context Protocol) API support.

## Overview

The TODO service provides structured task management with:
- **Task Types**: concrete, abstract, epic
- **Task Relationships**: subtask, blocking, blocked_by, followup, related
- **Change History**: Full audit trail with agent identity tracking
- **Agent Performance**: Statistics and success rate tracking
- **MCP API**: Minimal 5-function API for LLM agent frameworks

## Quick Start

### Using Docker Compose (Recommended)

```bash
# From the todo-service directory
cd services/todo-service

# Set data directory (optional, defaults to ./data)
export TODO_DATA_DIR=/path/to/data
export TODO_SERVICE_PORT=8004

# Start the service
docker compose up -d

# Check status
docker compose ps
docker compose logs -f

# Stop the service
docker compose down
```

### Using Docker Directly

```bash
# Build the image
docker build -t todo-service:latest -f services/todo-service/Dockerfile .

# Run the service
docker run -d \
  --name todo-service \
  -p 8004:8004 \
  -v /path/to/data:/app/data \
  -e TODO_DB_PATH=/app/data/todos.db \
  -e TODO_SERVICE_PORT=8004 \
  todo-service:latest
```

### Using Python Directly

```bash
# Install dependencies
pip install fastapi uvicorn

# Run the service
cd services/todo-service
export TODO_DB_PATH=./todos.db
export TODO_SERVICE_PORT=8004
python main.py
```

## Configuration

### Environment Variables

- `TODO_DB_PATH`: Path to SQLite database file (default: `/app/data/todos.db`)
- `TODO_SERVICE_PORT`: HTTP port for the service (default: `8004`)

### Data Directory

The service stores its SQLite database in the configured data directory. Ensure the directory exists and is writable:

```bash
mkdir -p /path/to/data
chmod 755 /path/to/data
```

## API Documentation

### Health Check

```bash
curl http://localhost:8004/health
```

### MCP Functions

Get available MCP functions:

```bash
curl http://localhost:8004/mcp/functions
```

### Core MCP Endpoints

1. **List Available Tasks**
   ```bash
   curl -X POST http://localhost:8004/mcp/list_available_tasks \
     -H "Content-Type: application/json" \
     -d '{"agent_type": "implementation", "limit": 10}'
   ```

2. **Reserve Task**
   ```bash
   curl -X POST http://localhost:8004/mcp/reserve_task \
     -H "Content-Type: application/json" \
     -d '{"task_id": 1, "agent_id": "agent-123"}'
   ```

3. **Complete Task**
   ```bash
   curl -X POST http://localhost:8004/mcp/complete_task \
     -H "Content-Type: application/json" \
     -d '{
       "task_id": 1,
       "agent_id": "agent-123",
       "notes": "Task completed successfully"
     }'
   ```

4. **Create Task**
   ```bash
   curl -X POST http://localhost:8004/mcp/create_task \
     -H "Content-Type: application/json" \
     -d '{
       "title": "Implement feature X",
       "task_type": "concrete",
       "task_instruction": "Implement the feature as specified",
       "verification_instruction": "Run tests and verify feature works",
       "agent_id": "agent-123"
     }'
   ```

5. **Get Agent Performance**
   ```bash
   curl -X POST http://localhost:8004/mcp/get_agent_performance \
     -H "Content-Type: application/json" \
     -d '{"agent_id": "agent-123"}'
   ```

## Full API Endpoints

See the FastAPI documentation at `http://localhost:8004/docs` for complete API documentation.

Key endpoints:
- `POST /tasks` - Create task
- `GET /tasks/{id}` - Get task
- `GET /tasks` - Query tasks
- `POST /tasks/{id}/lock` - Lock task
- `POST /tasks/{id}/complete` - Complete task
- `POST /tasks/{id}/verify` - Verify task
- `GET /change-history` - Get change history
- `GET /agents/{id}/stats` - Get agent statistics

## Integration with June Infrastructure

Even though the TODO service runs standalone, agents in the June infrastructure can connect to it:

```python
from inference_core.todo_client import get_todo_client

# Configure TODO service URL (can be external)
import os
os.environ["TODO_SERVICE_URL"] = "http://localhost:8004"  # or external URL

client = get_todo_client()
tasks = client.get_available_tasks("implementation", limit=10)
```

## Agent Workflow

### Breakdown Agent

```python
# 1. Get abstract tasks to break down
tasks = client.get_available_tasks("breakdown", limit=5)

# 2. Reserve a task
if client.lock_task(tasks[0].id, "breakdown-agent-1"):
    # 3. Break down into concrete tasks
    subtasks = [...]  # Your breakdown logic
    
    # 4. Create subtasks
    for subtask in subtasks:
        client.create_task(
            title=subtask.title,
            task_type="concrete",
            task_instruction=subtask.instruction,
            verification_instruction=subtask.verification,
            agent_id="breakdown-agent-1",
            parent_task_id=tasks[0].id,
            relationship_type="subtask"
        )
    
    # 5. Complete the breakdown task
    client.complete_task(tasks[0].id, "breakdown-agent-1")
```

### Implementation Agent

```python
# 1. Get concrete tasks to implement
tasks = client.get_available_tasks("implementation", limit=10)

# 2. Reserve a task
if client.lock_task(tasks[0].id, "impl-agent-1"):
    # 3. Implement the task
    # ... your implementation ...
    
    # 4. Complete and optionally add followup
    client.complete_task(
        tasks[0].id,
        "impl-agent-1",
        notes="Implementation complete",
        followup_title="Test the implementation",
        followup_task_type="concrete",
        followup_instruction="Run test suite",
        followup_verification="All tests pass"
    )
```

## Database Schema

The service uses SQLite with three main tables:

- **tasks**: Task information and status
- **task_relationships**: Links between tasks
- **change_history**: Full audit trail of all changes

See `database.py` for schema details.

## Monitoring

### Health Check

```bash
curl http://localhost:8004/health
```

### Change History

```bash
# Get all changes
curl http://localhost:8004/change-history

# Filter by agent
curl http://localhost:8004/change-history?agent_id=agent-123

# Filter by task
curl http://localhost:8004/change-history?task_id=1
```

### Agent Statistics

```bash
curl http://localhost:8004/agents/agent-123/stats
```

## Production Deployment

For production, consider:

1. **Database Backups**: Regularly backup the SQLite database
2. **SSL/TLS**: Use a reverse proxy (nginx, traefik) for HTTPS
3. **Authentication**: Add authentication middleware for secure access
4. **Rate Limiting**: Add rate limiting to prevent abuse
5. **Monitoring**: Integrate with monitoring systems (Prometheus, etc.)

## Troubleshooting

### Database Permissions

If you see permission errors:

```bash
# Fix data directory permissions
chmod 755 /path/to/data
chown -R $USER:$USER /path/to/data
```

### Port Already in Use

```bash
# Use a different port
export TODO_SERVICE_PORT=8005
docker compose up -d
```

### Database Locked

SQLite can only handle one writer at a time. If you see "database is locked" errors:

1. Check for long-running transactions
2. Consider migrating to PostgreSQL for higher concurrency
3. Use connection pooling if needed

## License

Part of the June Agent project.

