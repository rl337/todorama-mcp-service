# TODO MCP Service

A standalone SQLite-based task management service for AI agents with change history tracking, project support, and MCP (Model Context Protocol) API.

## Features

- **Task Management**: Create, update, track tasks with types (concrete, abstract, epic)
- **Project Support**: Organize tasks by project with origin URLs and local paths
- **Change History**: Full audit trail with agent identity tracking
- **Agent Performance**: Statistics and success rate tracking per agent
- **Backup & Restore**: Automatic nightly backups with gzip compression
- **MCP API**: Minimal 5-function API for LLM agent frameworks
- **REST API**: Full CRUD operations via FastAPI

## Quick Start

### Using Docker Compose

```bash
# Clone and navigate
git clone <repository-url>
cd todo-mcp-service

# Set data directory (optional)
export TODO_DATA_DIR=/path/to/data
export TODO_SERVICE_PORT=8004

# Start the service
docker compose up -d

# Check status
docker compose ps
docker compose logs -f
```

### Using Docker Directly

```bash
# Build the image
docker build -t todo-mcp-service:latest -f src/Dockerfile .

# Run the service
docker run -d \
  --name todo-mcp-service \
  -p 8004:8004 \
  -v /path/to/data:/app/data \
  -v /path/to/backups:/app/backups \
  -e TODO_DB_PATH=/app/data/todos.db \
  -e TODO_BACKUPS_DIR=/app/backups \
  todo-mcp-service:latest
```

## Project Support

Tasks are organized into projects. Each project has:
- **Name**: Unique project identifier
- **Local Path**: Absolute path where the project code is located
- **Origin URL**: Source location (GitHub URL, file:// path, etc.)
- **Description**: Optional project description

### Creating Projects

```bash
curl -X POST http://localhost:8004/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "june-agent",
    "local_path": "/home/rlee/dev/june",
    "origin_url": "https://github.com/your-org/june",
    "description": "June Agent project"
  }'
```

### Working with Project Tasks

```bash
# Create task in a project
curl -X POST http://localhost:8004/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Implement feature X",
    "task_type": "concrete",
    "task_instruction": "Implement the feature",
    "verification_instruction": "Run tests and verify",
    "agent_id": "agent-123",
    "project_id": 1
  }'

# Query tasks by project
curl "http://localhost:8004/tasks?project_id=1"
```

## MCP Functions

1. **list_available_tasks** - Get tasks for agent type (with optional project filter)
2. **reserve_task** - Lock task for agent
3. **complete_task** - Complete with optional followup
4. **create_task** - Create new task (optionally in project)
5. **get_agent_performance** - Get agent statistics

## API Documentation

Full API docs available at `http://localhost:8004/docs` when service is running.

Key endpoints:
- `POST /projects` - Create project
- `GET /projects` - List projects
- `GET /projects/{id}` - Get project
- `POST /tasks` - Create task
- `GET /tasks` - Query tasks (filter by project_id)
- `POST /backup/create` - Create backup
- `POST /backup/restore` - Restore from backup

## Configuration

Environment variables:
- `TODO_DB_PATH`: Database file path (default: `/app/data/todos.db`)
- `TODO_BACKUPS_DIR`: Backup directory (default: `/app/backups`)
- `TODO_SERVICE_PORT`: HTTP port (default: `8004`)
- `TODO_BACKUP_INTERVAL_HOURS`: Backup interval (default: `24`)

## License

MIT License
