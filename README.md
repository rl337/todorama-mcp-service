# TODO MCP Service

A standalone SQLite-based task management service for AI agents with change history tracking, project support, and MCP (Model Context Protocol) API.

## Features

- **Task Management**: Create, update, track tasks with types (concrete, abstract, epic)
- **Project Support**: Organize tasks by project with origin URLs and local paths
- **Change History**: Full audit trail with agent identity tracking
- **Agent Performance**: Statistics and success rate tracking per agent
- **Backup & Restore**: Automatic nightly backups with gzip compression
- **Rate Limiting**: Sliding window rate limiting with global, per-endpoint, and per-agent limits
- **MCP API**: Minimal 5-function API for LLM agent frameworks
- **REST API**: Full CRUD operations via FastAPI

## Quick Start

### Using Docker Compose

```bash
# Clone and navigate
git clone <repository-url>
cd todorama-mcp-service

# Set data directory (optional)
export TODO_DATA_DIR=/path/to/data
export TODO_SERVICE_PORT=8004

# Start the service
docker compose up -d

# Check status
docker compose ps
docker compose logs -f
```

**Note**: This service follows the [MCP Services Containerization Standards](../agenticness/CONTAINERIZATION.md). The Dockerfile uses UV for dependency management and follows standard patterns for security and reproducibility.

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

**Note**: The Dockerfile uses the `uv export` pattern (an alternative to the standard `uv sync --frozen` pattern). Both patterns are valid and documented in the [Containerization Standards](../agenticness/CONTAINERIZATION.md).

### Local Development

For local development without Docker:

**Prerequisites:**
- **Python 3.11+**
- **UV** (for dependency management) - [Install UV](https://github.com/astral-sh/uv#installation)

**Note**: UV is the standard dependency manager for all MCP services (TODO service, Bucket-O-Facts, Doc-O-Matic) for consistency and performance.

**Setup:**
```bash
# Clone the repository
git clone <repository-url>
cd todorama-mcp-service

# Install dependencies using UV
uv sync

# Activate virtual environment (optional)
source .venv/bin/activate

# Or use uv run for commands (no activation needed)
uv run python -m src.main

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=src --cov-report=html
```

**Common UV Commands:**
- `uv sync` - Install dependencies from `pyproject.toml` and `uv.lock`
- `uv run <command>` - Run a command in the virtual environment
- `uv add <package>` - Add a new dependency
- `uv remove <package>` - Remove a dependency
- `uv lock` - Update the lock file

For more information about UV, see the [UV documentation](https://github.com/astral-sh/uv).

## CI/CD Pipeline

The project includes a comprehensive CI/CD pipeline implemented with GitHub Actions.

### Features

- **Automated Testing**: Runs unit tests with pytest and enforces 80% code coverage
- **Code Quality**: Checks formatting (Black), import sorting (isort), linting (flake8, pylint), and type checking (mypy)
- **Security Scanning**: Dependency vulnerability checks (Safety), code security analysis (Bandit), and container scanning (Trivy)
- **Docker Builds**: Automated Docker image builds and pushes to GitHub Container Registry
- **Automated Deployments**: Staging deployments on `develop` branch, production deployments on `main` branch
- **Rollback Capabilities**: Automatic rollback on deployment failures

### Workflow Files

- `.github/workflows/ci-cd.yml` - Main CI/CD pipeline
- `.github/workflows/deploy.yml` - Manual deployment workflow

### Deployment Environments

- **Staging**: `docker-compose.staging.yml` - Pre-production testing
- **Production**: `docker-compose.production.yml` - Live production service

For detailed deployment instructions, see the [Deployment](#deployment) section below.

### Pre-Commit Checks

Before committing code, run the comprehensive check script:

```bash
./run_checks.sh
```

This runs:
- Dependency verification
- Database schema validation
- Code quality checks
- Unit tests
- Backup functionality tests
- Service startup verification

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

## CLI Tool

The TODO MCP Service includes a command-line interface (CLI) for managing tasks from the terminal.

### Installation

The CLI is available as `src/cli.py` and can be used directly:

```bash
# Direct execution
python3 src/cli.py --help

# Or make it executable and run directly
chmod +x src/cli.py
./src/cli.py --help
```

### Configuration

Configure the CLI using environment variables or command-line options:

```bash
# Environment variables
export TODO_SERVICE_URL=http://localhost:8004
export TODO_API_KEY=your-api-key-here

# Or use command-line options
python3 src/cli.py --url http://localhost:8004 --api-key your-key list
```

### CLI Commands

#### List Tasks

```bash
# List all tasks
python3 src/cli.py list

# Filter by status
python3 src/cli.py list --status in_progress

# Filter by type and project
python3 src/cli.py list --type concrete --project-id 1

# Output as JSON
python3 src/cli.py list --format json
```

#### Create Task

```bash
python3 src/cli.py create \
  --title "Implement feature X" \
  --type concrete \
  --instruction "Implement the feature" \
  --verification "Run tests and verify" \
  --agent-id "my-agent" \
  --project-id 1 \
  --priority high \
  --notes "Additional notes"
```

#### Show Task Details

```bash
python3 src/cli.py show --task-id 123

# JSON output
python3 src/cli.py show --task-id 123 --format json
```

#### Complete Task

```bash
python3 src/cli.py complete \
  --task-id 123 \
  --agent-id "my-agent" \
  --notes "Completed successfully" \
  --actual-hours 4.5
```

#### Reserve/Unlock Task

```bash
# Reserve a task
python3 src/cli.py reserve --task-id 123 --agent-id "my-agent"

# Unlock a task
python3 src/cli.py unlock --task-id 123 --agent-id "my-agent"
```

### Filtering Options

The `list` command supports various filters:

- `--status`: Filter by task status (available, in_progress, complete, blocked, cancelled)
- `--type`: Filter by task type (concrete, abstract, epic)
- `--project-id`: Filter by project ID
- `--agent`: Filter by assigned agent
- `--priority`: Filter by priority (low, medium, high, critical)
- `--limit`: Maximum number of results (default: 100)

### Examples

```bash
# List all available concrete tasks in project 1
python3 src/cli.py list --status available --type concrete --project-id 1

# Create a high-priority task
python3 src/cli.py create \
  --title "Fix critical bug" \
  --type concrete \
  --instruction "Fix the bug in module X" \
  --verification "Verify bug is fixed and tests pass" \
  --agent-id "dev-agent" \
  --project-id 1 \
  --priority critical

# Reserve and complete a task
python3 src/cli.py reserve --task-id 456 --agent-id "dev-agent"
python3 src/cli.py complete --task-id 456 --agent-id "dev-agent" --notes "Done!"

# View task details
python3 src/cli.py show --task-id 456
```

## Development Commands

The service provides several development utility commands accessible via `python -m todorama <command>`:

### Analyze Command

Analyze cursor-agent.log files to understand agent behavior:

```bash
# Analyze log file (default: cursor-agent.log)
python -m todorama analyze cursor-agent.log

# Show detailed analysis for a specific task
python -m todorama analyze cursor-agent.log --task 123

# List all tasks found in log
python -m todorama analyze cursor-agent.log --list-tasks
```

**Features:**
- Task activity tracking (reservations, completions, unlocks, updates)
- Tool call breakdown and frequency
- Loop detection (identifies rapid repeated updates)
- Timeline of events per task
- Success/failure rate analysis

### Audit Command

Audit MCP tool parameter types to verify they match implementations:

```bash
# Audit MCP function parameter types
python -m todorama audit

# Specify custom paths
python -m todorama audit --mcp-api todorama/mcp_api.py --main todorama/main.py
```

**Features:**
- Compares MCP_FUNCTIONS definitions with MCPTodoAPI method signatures
- Verifies parameter types, optional flags, and default values
- Checks routing handlers in main.py
- Identifies type mismatches and missing handlers

### Verify Command

Verify that all MCP_FUNCTIONS have corresponding handlers:

```bash
# Verify MCP function routing
python -m todorama verify

# Specify custom paths
python -m todorama verify --functions todorama/mcp/functions.py --request-handlers todorama/mcp/request_handlers.py
```

**Features:**
- Lists all functions defined in MCP_FUNCTIONS
- Lists all handlers in request_handlers.py
- Identifies missing handlers (functions without routes)
- Identifies extra handlers (routes without function definitions)

## Utilities

### Cursor Agent Log Parser

The `parse_cursor_agent.py` utility extracts human-readable content from Cursor Agent JSON output.

**Usage:**

```bash
# Pipe cursor agent output through the parser
cursor-agent command | tee cursor-agent.log | python3 parse_cursor_agent.py

# Or just parse an existing log file
cat cursor-agent.log | python3 parse_cursor_agent.py

# Parse and save to a readable log
cursor-agent command | tee cursor-agent.log | python3 parse_cursor_agent.py > readable.log
```

**What it extracts:**
- **Task operations**: Task reservations (🔒), completions (✅), and creation (➕)
- **Tool calls**: Shows what tools the agent is calling (file reads, terminal commands, etc.)
- **Task summaries**: Extracts summaries from task execution results
- **Messages**: Shows user and assistant messages
- **Errors**: Highlights error messages
- **Duration**: Shows execution time for long-running operations

**Output format:**
- `→` Tool calls
- `📝` Content/messages
- `❌` Errors
- `⚠️` Warnings/status
- `🔧` Functions
- `📋` Plain text log lines

**Examples:**

```bash
# Watch agent work in real-time
cursor-agent fix-tests | tee cursor-agent.log | python3 parse_cursor_agent.py

# Parse existing log file
cat cursor-agent.log | python3 parse_cursor_agent.py

# Or use stdin redirection
python3 parse_cursor_agent.py < cursor-agent.log

# Save both raw and readable logs
cursor-agent command | tee cursor-agent.log | python3 parse_cursor_agent.py | tee cursor-agent-readable.log
```

### Agent Automation

The `cursor-agent-loop-improved.sh` script provides an enhanced cursor-agent loop that properly uses MCP functions for task management. It supports multiple agent modes, timeout configuration, error handling, and monitoring.

**Location:** `cursor-agent-loop-improved.sh` (project root)

**Usage:**

```bash
# Run indefinitely
./cursor-agent-loop-improved.sh

# Run 10 iterations
./cursor-agent-loop-improved.sh 10

# Run in precommit mode
CURSOR_AGENT_MODE=precommit ./cursor-agent-loop-improved.sh
```

**Agent Modes:**

The script supports multiple agent modes via the `CURSOR_AGENT_MODE` environment variable:

- **`normal`** (default): Standard task work - picks up and completes tasks from the TODO service
- **`precommit`**: Fix pre-commit test failures (also auto-triggered by `.pre-commit-failed` semaphore)
- **`refactor-planner`**: Analyzes codebase and creates refactoring tasks (does not make changes)
- **`project-cleanup`**: Analyzes project and creates cleanup tasks for docs/scripts (does not make changes)

**Environment Variables:**

- **`CURSOR_AGENT_ID`**: Agent identifier (default: `cursor-${HOSTNAME}-cli`)
- **`CURSOR_PROJECT_ID`**: Project ID to filter tasks (optional)
- **`CURSOR_AGENT_TYPE`**: Agent type - `implementation` or `breakdown` (default: `implementation`)
- **`CURSOR_AGENT_MODE`**: Agent mode - `normal`, `precommit`, `refactor-planner`, `project-cleanup` (default: `normal`)
- **`CURSOR_SLEEP_INTERVAL`**: Sleep time between iterations in seconds (default: `60`)
- **`AGENT_TIMEOUT`**: Maximum time for agent execution in seconds (default: `3600`)

**Features:**

- **MCP Integration**: Properly uses MCP TODO service tools for task management
- **Timeout Configuration**: Configurable timeouts for agent execution, git operations, tests, and MCP calls
- **Error Handling**: Exits on non-zero return codes for proper error handling and monitoring
- **Monitoring**: Logs all operations with timestamps and status indicators
- **Loop Control**: Supports both infinite loops and fixed iteration counts

**Examples:**

```bash
# Run indefinitely in normal mode
./cursor-agent-loop-improved.sh

# Run 5 iterations
./cursor-agent-loop-improved.sh 5

# Run in precommit mode with custom timeout
CURSOR_AGENT_MODE=precommit AGENT_TIMEOUT=1800 ./cursor-agent-loop-improved.sh

# Run for a specific project
CURSOR_PROJECT_ID=2 ./cursor-agent-loop-improved.sh

# Run with custom sleep interval
CURSOR_SLEEP_INTERVAL=30 ./cursor-agent-loop-improved.sh 10

# Run as breakdown agent
CURSOR_AGENT_TYPE=breakdown ./cursor-agent-loop-improved.sh
```

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

## API Key Management and Authorization

The TODO service uses API key-based authentication with project-scoped authorization.

### Authentication Methods

API keys can be provided in two ways:

1. **X-API-Key Header** (Recommended)
   ```
   X-API-Key: todo_xxxxx...
   ```

2. **Authorization Bearer Token**
   ```
   Authorization: Bearer todo_xxxxx...
   ```

### Authorization Model

**Project-Scoped Keys:**
- Each API key is associated with a specific `project_id`
- Regular API keys can only create/update tasks for their assigned project
- When creating a task, the API key's `project_id` must match the task's `project_id`
- Error: `403 Forbidden - API key is not authorized for this project` if project IDs don't match

**Admin Keys:**
- Admin API keys can work across all projects
- Admin keys bypass project-scoped restrictions
- Use admin keys for system-level operations or multi-project access
- Admin status is stored in the `api_key_admin` table

### Creating API Keys

```bash
# Create an API key for a specific project
curl -X POST http://localhost:8004/api/projects/{project_id}/api-keys \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <admin-key>" \
  -d '{
    "name": "My API Key",
    "organization_id": 1
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
  "created_at": "2025-11-01T12:00:00"
}
```

**Important:** The full API key is only returned on creation. Store it securely immediately - it cannot be retrieved later.

### Managing API Keys

```bash
# List API keys for a project
curl -X GET http://localhost:8004/api/projects/{project_id}/api-keys \
  -H "X-API-Key: <admin-key>"

# Rotate an API key (generates new key, revokes old)
curl -X POST http://localhost:8004/api/api-keys/{key_id}/rotate \
  -H "X-API-Key: <admin-key>"

# Revoke an API key
curl -X DELETE http://localhost:8004/api/api-keys/{key_id} \
  -H "X-API-Key: <admin-key>"
```

### Key Management

The service includes a key management command utility:

1. **Issue Admin Key:**
   ```bash
   python3 -m todorama key-management issue --admin --save
   ```
   Creates an admin API key with cross-project access and optionally saves it to `api_keys.json`.

2. **Issue Project Key:**
   ```bash
   # Issue key for a specific project
   python3 -m todorama key-management issue --project 1 --save
   
   # Issue keys for all projects
   python3 -m todorama key-management issue --project-all --save
   ```
   Creates project-scoped API keys. Use `--project-all` to create keys for all projects.

3. **Invalidate (Revoke) Keys:**
   ```bash
   # Invalidate by key ID
   python3 -m todorama key-management invalidate --key-id 123
   
   # Invalidate by key prefix
   python3 -m todorama key-management invalidate --key-prefix "admin_ab"
   
   # Invalidate all keys for a project (requires --confirm)
   python3 -m todorama key-management invalidate --project 1 --confirm
   
   # Invalidate all keys (requires --confirm)
   python3 -m todorama key-management invalidate --all --confirm
   ```

4. **List Keys:**
   ```bash
   # Table format (default)
   python3 -m todorama key-management list
   
   # JSON format
   python3 -m todorama key-management list --format json
   
   # List keys for a specific project
   python3 -m todorama key-management list --project 1
   
   # List only admin keys
   python3 -m todorama key-management list --admin-only
   ```

5. **Save Keys:**
   ```bash
   # Save current keys to api_keys.json
   python3 -m todorama key-management save
   ```

6. **Using Generated Keys:**
   ```bash
   # Load keys from JSON file
   python3 -c "
   import json
   with open('api_keys.json') as f:
       keys = json.load(f)
       print(f\"Admin key: {keys['admin_key']}\")
       print(f\"Project 1 key: {keys['project_keys'][1]['api_key']}\")
   "
   ```

**Important:** The `api_keys.json` file is automatically added to `.gitignore` and should NEVER be committed to version control.

### Making an API Key Admin (Manual)

To manually grant admin privileges to an existing API key, insert a record into the `api_key_admin` table:

```sql
INSERT INTO api_key_admin (api_key_id) VALUES (<key_id>);
```

Admin keys can:
- Create tasks for any project (bypasses project-scoped restrictions)
- Access all projects regardless of the key's assigned `project_id`
- Perform system-level operations

### Common Authorization Errors

- **401 Unauthorized**: Missing or invalid API key
- **403 Forbidden**: API key not authorized for the requested project (for non-admin keys)
- **401 Unauthorized**: API key has been revoked (`enabled = 0`)

### Best Practices

1. **Use Admin Keys Sparingly**: Only grant admin privileges to keys that need cross-project access
2. **Project-Specific Keys**: Create separate API keys for each project when possible
3. **Key Rotation**: Regularly rotate API keys for security
4. **Secure Storage**: Never commit API keys to version control
5. **Environment Variables**: Store API keys in environment variables or secure secret management systems

### Example: Creating Tasks with Project-Scoped Keys

```bash
# This works: API key is for project 1, task is for project 1
curl -X POST http://localhost:8004/api/Task/create \
  -H "X-API-Key: project1-key" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Task in project 1",
    "task_type": "concrete",
    "task_instruction": "Do something",
    "verification_instruction": "Verify it",
    "project_id": 1
  }'

# This fails: API key is for project 1, task is for project 2
curl -X POST http://localhost:8004/api/Task/create \
  -H "X-API-Key: project1-key" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Task in project 2",
    "task_type": "concrete",
    "task_instruction": "Do something",
    "verification_instruction": "Verify it",
    "project_id": 2
  }'
# Response: 403 Forbidden - API key is not authorized for this project

# This works: Admin key can create tasks for any project
curl -X POST http://localhost:8004/api/Task/create \
  -H "X-API-Key: admin-key" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Task in project 2",
    "task_type": "concrete",
    "task_instruction": "Do something",
    "verification_instruction": "Verify it",
    "project_id": 2
  }'
```

For comprehensive API documentation, see [API.md](API.md) for detailed endpoint specifications, request/response formats, and code examples.

## Configuration

The TODO MCP Service uses **Pydantic Settings** for type-safe configuration management with support for `.env` files and environment variable overrides. This standardized approach ensures consistency across all MCP services.

### Standardized Configuration Pattern

The service uses Pydantic's `BaseSettings` with the following features:

- **`.env` file support**: Create a `.env` file in the project root for local development
- **Environment variable overrides**: All settings can be overridden via environment variables
- **Type validation**: Automatic validation of configuration values with helpful error messages
- **Default values**: Sensible defaults provided for development convenience
- **Case-insensitive**: Environment variable names are case-insensitive

Configuration is accessed via the `get_settings()` function which returns a cached singleton instance:

```python
from todorama.config import get_settings

settings = get_settings()
db_path = settings.database_path
log_level = settings.log_level
```

### Configuration Options

#### Standardized Database Configuration

- **`database_path`** / **`TODO_DB_PATH`** (string, required)
  - Database file path for SQLite
  - Default: Automatically resolved based on environment
    - Local development: `data/todos.db` (relative to project root)
    - Container: `/app/data/todos.db`
  - Environment variable: `TODO_DB_PATH` (backward compatibility) or `DATABASE_PATH`
  - **Path Resolution**: The service automatically detects if it's running in a container and adjusts the default path accordingly. The `TODO_DB_PATH` environment variable takes highest priority.

- **`db_pool_size`** (integer, default: `5`)
  - Connection pool size (for future PostgreSQL support)
  - Environment variable: `DB_POOL_SIZE`

- **`db_max_overflow`** (integer, default: `10`)
  - Maximum overflow connections
  - Environment variable: `DB_MAX_OVERFLOW`

- **`db_pool_timeout`** (integer, default: `30`)
  - Connection timeout in seconds
  - Environment variable: `DB_POOL_TIMEOUT`

- **`sql_echo`** (boolean, default: `false`)
  - Enable SQL query logging for debugging
  - Environment variable: `SQL_ECHO` (set to `"true"` to enable)

#### Standardized Logging Configuration

- **`log_level`** (string, default: `"INFO"`)
  - Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
  - Environment variable: `LOG_LEVEL`

- **`log_format`** (string, default: `"json"`)
  - Logging format: `"json"` or `"text"`
  - Environment variable: `LOG_FORMAT`

#### Standardized Environment Configuration

- **`environment`** (string, default: `"development"`)
  - Environment name: `"development"`, `"staging"`, `"production"`
  - Environment variable: `ENVIRONMENT`

- **`debug`** (boolean, default: `false`)
  - Enable debug mode
  - Environment variable: `DEBUG` (set to `"true"` to enable)

#### Service-Specific Configuration

- **`TODO_BACKUPS_DIR`** (string, default: `/app/backups`)
  - Backup directory path
  - Environment variable: `TODO_BACKUPS_DIR`

- **`TODO_SERVICE_PORT`** (integer, default: `8004`)
  - HTTP service port
  - Environment variable: `TODO_SERVICE_PORT`

- **`TODO_BACKUP_INTERVAL_HOURS`** (integer, default: `24`)
  - Backup interval in hours
  - Environment variable: `TODO_BACKUP_INTERVAL_HOURS`

### Configuration Examples

#### Example `.env` File for Local Development

Create a `.env` file in the project root:

```bash
# Database Configuration
TODO_DB_PATH=data/todos.db
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
SQL_ECHO=false

# Logging Configuration
LOG_LEVEL=INFO
LOG_FORMAT=json

# Environment Configuration
ENVIRONMENT=development
DEBUG=false

# Service-Specific Configuration
TODO_BACKUPS_DIR=./backups
TODO_SERVICE_PORT=8004
TODO_BACKUP_INTERVAL_HOURS=24
```

#### Example `.env` File for Containerized Deployment

```bash
# Database Configuration
TODO_DB_PATH=/app/data/todos.db
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
SQL_ECHO=false

# Logging Configuration
LOG_LEVEL=INFO
LOG_FORMAT=json

# Environment Configuration
ENVIRONMENT=production
DEBUG=false

# Service-Specific Configuration
TODO_BACKUPS_DIR=/app/backups
TODO_SERVICE_PORT=8004
TODO_BACKUP_INTERVAL_HOURS=24
```

#### Example Environment Variable Overrides

Override specific settings without modifying `.env` file:

```bash
# Override database path
export TODO_DB_PATH=/custom/path/todos.db

# Enable SQL query logging for debugging
export SQL_ECHO=true

# Change log level
export LOG_LEVEL=DEBUG

# Enable debug mode
export DEBUG=true
```

#### Example for Different Environments

**Development:**
```bash
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG
SQL_ECHO=true
TODO_DB_PATH=./data/todos.db
```

**Staging:**
```bash
ENVIRONMENT=staging
DEBUG=false
LOG_LEVEL=INFO
SQL_ECHO=false
TODO_DB_PATH=/app/data/todos.db
```

**Production:**
```bash
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=WARNING
SQL_ECHO=false
TODO_DB_PATH=/app/data/todos.db
```

### Database Configuration

#### SQLite Configuration (Default)

The service uses SQLite by default for local development and can be configured for containerized deployments:

- **Local Development**: Database file is created at `data/todos.db` (relative to project root)
- **Container**: Database file is created at `/app/data/todos.db` (should be mounted from a volume)
- **Path Resolution**: The service automatically detects the environment and uses appropriate defaults
- **Backward Compatibility**: The `TODO_DB_PATH` environment variable takes highest priority

#### PostgreSQL Configuration (Future)

The service is designed to support PostgreSQL in the future. Connection pool settings are already configured:

- **Connection Pool**: Configured via `db_pool_size`, `db_max_overflow`, `db_pool_timeout`
- **SQL Logging**: Enable via `sql_echo=true` for debugging

#### SQL Query Logging

Enable SQL query logging for debugging:

```bash
# In .env file
SQL_ECHO=true

# Or via environment variable
export SQL_ECHO=true
```

This will log all SQL queries to the console, useful for debugging database operations.

### Configuration Precedence

Configuration values are resolved in the following order (highest to lowest priority):

1. **Environment variables** (highest priority)
2. **`.env` file** (if present)
3. **Default values** (lowest priority)

For example, if you set `TODO_DB_PATH` as an environment variable, it will override any value in the `.env` file.

### Type Validation and Error Handling

Pydantic Settings automatically validates configuration values:

- **Type checking**: Invalid types raise `ValidationError` with clear error messages
- **Required fields**: Missing required fields are detected at startup
- **Default values**: Sensible defaults are provided for optional fields

Example error message:
```
ValidationError: 1 validation error for Settings
database_path
  Field required [type=missing, input_value=None, input_type=NoneType]
```

### Container Detection

The service automatically detects if it's running in a container by checking:

1. Presence of `/.dockerenv` file
2. Container indicators in `/proc/1/cgroup`

When running in a container, the default database path is `/app/data/todos.db`. For local development, it uses `data/todos.db` relative to the project root.

### Rate Limiting

The service implements sliding window rate limiting to prevent abuse. Three types of limits are enforced:

1. **Global Rate Limit**: Applies to all requests across all endpoints
   - `RATE_LIMIT_GLOBAL_MAX`: Maximum requests (default: `100`)
   - `RATE_LIMIT_GLOBAL_WINDOW`: Time window in seconds (default: `60`)

2. **Per-Endpoint Rate Limit**: Different limits for each endpoint
   - `RATE_LIMIT_ENDPOINT_MAX`: Maximum requests per endpoint (default: `200`)
   - `RATE_LIMIT_ENDPOINT_WINDOW`: Time window in seconds (default: `60`)
   - `RATE_LIMIT_ENDPOINT_OVERRIDES`: Comma-separated list of endpoint-specific overrides
     Format: `ENDPOINT_PATH:max:window` (e.g., `/health:500:60,/mcp/sse:10:60`)

3. **Per-Agent Rate Limit**: Limits per agent ID (extracted from headers or query params)
   - `RATE_LIMIT_AGENT_MAX`: Maximum requests per agent (default: `50`)
   - `RATE_LIMIT_AGENT_WINDOW`: Time window in seconds (default: `60`)
   - `RATE_LIMIT_AGENT_OVERRIDES`: Comma-separated list of agent-specific overrides
     Format: `AGENT_ID:max:window` (e.g., `agent-1:200:60,agent-2:100:60`)

4. **Per-User Rate Limit**: Limits per authenticated user (extracted from session tokens) - uses **token bucket algorithm**
   - `RATE_LIMIT_USER_MAX`: Bucket capacity / maximum requests per user (default: `100`)
   - `RATE_LIMIT_USER_WINDOW`: Time window in seconds for calculating refill rate (default: `60`)
   - **Token bucket** allows burst traffic up to capacity and refills tokens at a steady rate (max_requests/window_seconds)
   - `RATE_LIMIT_USER_OVERRIDES`: Comma-separated list of user-specific overrides
     Format: `USER_ID:max:window` (e.g., `123:200:60,456:150:60`)

When a rate limit is exceeded, the service returns HTTP 429 (Too Many Requests) with:
- `Retry-After` header indicating seconds until retry
- `X-RateLimit-Limit` header showing the limit
- `X-RateLimit-Remaining` header showing remaining requests
- `X-RateLimit-Reset` header showing when the limit resets

Example configuration:
```bash
export RATE_LIMIT_GLOBAL_MAX=100
export RATE_LIMIT_GLOBAL_WINDOW=60
export RATE_LIMIT_ENDPOINT_OVERRIDES="/health:500:60,/mcp/sse:10:60"
```

### Security Headers

The service automatically adds security headers to all HTTP responses to protect against common web vulnerabilities. All headers are configurable via environment variables:

#### Standard Security Headers

- **X-Content-Type-Options**: Prevents MIME type sniffing
  - `SECURITY_HEADER_X_CONTENT_TYPE_OPTIONS` (default: `nosniff`)

- **X-Frame-Options**: Prevents clickjacking attacks
  - `SECURITY_HEADER_X_FRAME_OPTIONS` (default: `DENY`, options: `DENY`, `SAMEORIGIN`)

- **X-XSS-Protection**: Legacy XSS protection (for older browsers)
  - `SECURITY_HEADER_X_XSS_PROTECTION` (default: `1; mode=block`)

- **Referrer-Policy**: Controls referrer information sent with requests
  - `SECURITY_HEADER_REFERRER_POLICY` (default: `strict-origin-when-cross-origin`)

- **Content-Security-Policy**: Restricts resource loading to prevent XSS
  - `SECURITY_HEADER_CSP` (default: restrictive policy, customizable)

- **Permissions-Policy**: Restricts browser features and APIs
  - `SECURITY_HEADER_PERMISSIONS_POLICY` (default: restrictive permissions)

- **Cross-Origin-Opener-Policy**: Isolates browsing context
  - `SECURITY_HEADER_CROSS_ORIGIN_OPENER_POLICY` (default: `same-origin`)

- **Cross-Origin-Resource-Policy**: Restricts resource loading
  - `SECURITY_HEADER_CROSS_ORIGIN_RESOURCE_POLICY` (default: `same-origin`)

- **Cross-Origin-Embedder-Policy**: Requires CORP headers (optional, disabled by default)
  - `SECURITY_HEADER_COEP_ENABLED` (default: `false`)
  - `SECURITY_HEADER_CROSS_ORIGIN_EMBEDDER_POLICY` (default: `require-corp`)

#### HSTS (HTTP Strict Transport Security)

HSTS is only set when both conditions are met:
1. `SECURITY_HSTS_ENABLED=true`
2. Request is over HTTPS (or uses `X-Forwarded-Proto: https` header)

Configuration:
- `SECURITY_HSTS_ENABLED`: Enable HSTS (default: `false`)
- `SECURITY_HSTS_MAX_AGE`: Max age in seconds (default: `31536000` = 1 year)
- `SECURITY_HSTS_INCLUDE_SUBDOMAINS`: Include subdomains (default: `true`)
- `SECURITY_HSTS_PRELOAD`: Enable HSTS preload (default: `false`)

Example configuration:
```bash
# Enable HSTS for HTTPS deployments
export SECURITY_HSTS_ENABLED=true
export SECURITY_HSTS_MAX_AGE=31536000
export SECURITY_HSTS_INCLUDE_SUBDOMAINS=true

# Customize CSP policy
export SECURITY_HEADER_CSP="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"

# Allow same-origin framing
export SECURITY_HEADER_X_FRAME_OPTIONS=SAMEORIGIN
```

**Note**: Security headers are automatically applied to all endpoints. No additional configuration is required for basic operation.

## Repository Pattern

The TODO MCP Service uses the **repository pattern** for data access, providing a clean separation between business logic (services) and data access (repositories). This pattern is standardized across all MCP services for consistency and maintainability.

### Standardized Repository Pattern

The service uses repository classes that abstract database operations for core entities (Task, Project, Organization). Repositories wrap `TodoDatabase` methods and provide a clean interface for services to interact with data.

**Repository Structure:**
- Repositories are located in `todorama/storage/repositories.py`
- Each entity type has its own repository class (e.g., `TaskRepository`, `ProjectRepository`, `OrganizationRepository`)
- Repositories receive `TodoDatabase` instance via dependency injection

**Benefits:**
- **Separation of Concerns**: Business logic (services) is separated from data access (repositories)
- **Testability**: Repositories can be easily mocked for service testing
- **Maintainability**: Clear structure and responsibilities
- **Consistency**: Standard interface across all MCP services

### Repository Interface

All repositories implement standard CRUD operations:

**Core Methods:**
- `create(**kwargs)` - Create a new entity, returns entity ID
- `get_by_id(entity_id, organization_id=None)` - Get entity by ID
- `get_by_<field>(field_value)` - Get entity by unique field (e.g., `get_by_name()`)
- `update(entity_id, **kwargs)` - Update existing entity
- `delete(entity_id)` - Delete entity
- `list(**filters)` - List entities with optional filters
- `search(query, **filters)` - Full-text search

**Method Naming Conventions:**
- Use descriptive method names: `get_by_id()`, `get_by_name()`, `list()`, `search()`
- Use consistent parameter names: `entity_id`, `organization_id`, `limit`, `offset`
- Return types: `Optional[Dict[str, Any]]` for single entities, `List[Dict[str, Any]]` for lists

**Parameter Patterns:**
- **ID Parameters**: Use `entity_id` for primary keys
- **Filters**: Use keyword arguments with descriptive names (e.g., `status`, `type`, `organization_id`)
- **Pagination**: Use `limit` (default: 100) and `offset` (default: 0)
- **Ordering**: Use `order_by` parameter (e.g., `'created_at'`, `'priority'`)
- **Multi-tenancy**: Use `organization_id` parameter for tenant isolation

### Service-Repository Relationship

Services use repositories via dependency injection:

```python
from todorama.storage.repositories import TaskRepository, ProjectRepository
from todorama.database import TodoDatabase

# Initialize database
db = TodoDatabase()

# Initialize repositories
task_repository = TaskRepository(db)
project_repository = ProjectRepository(db)

# Services receive repositories via constructor
class TaskService:
    def __init__(self, task_repository: TaskRepository):
        self.task_repository = task_repository
    
    def create_task(self, **kwargs):
        # Business logic validation
        if not kwargs.get('title'):
            raise ValueError("Title is required")
        
        # Delegate to repository
        return self.task_repository.create(**kwargs)
```

**Separation of Concerns:**
- **Repositories**: Handle database operations (queries, transactions)
- **Services**: Handle business logic (validation, orchestration, computed fields)
- **Clear Boundaries**: Services never directly access database; repositories never contain business logic

### Examples

**Example: TaskRepository Usage**

```python
from todorama.storage.repositories import TaskRepository
from todorama.database import TodoDatabase

# Initialize
db = TodoDatabase()
task_repo = TaskRepository(db)

# Create a task
task_id = task_repo.create(
    title="Implement feature X",
    task_type="concrete",
    task_instruction="Implement the feature",
    verification_instruction="Run tests",
    agent_id="agent-123",
    project_id=1,
    priority="high"
)

# Get task by ID
task = task_repo.get_by_id(task_id)

# List tasks with filters
tasks = task_repo.list(
    task_status="available",
    task_type="concrete",
    project_id=1,
    limit=50,
    order_by="priority"
)

# Search tasks
results = task_repo.search("feature X", limit=20)
```

**Example: Testing with Repository Mocks**

```python
from unittest.mock import Mock
from todorama.services.task_service import TaskService

def test_task_service():
    # Create mock repository
    mock_repo = Mock(spec=TaskRepository)
    mock_repo.create.return_value = 123
    mock_repo.get_by_id.return_value = {
        'id': 123,
        'title': 'Test Task',
        'task_status': 'available'
    }
    
    # Initialize service with mock
    service = TaskService(mock_repo)
    
    # Test service methods
    task_id = service.create_task(title="Test Task", ...)
    assert task_id == 123
    
    task = service.get_task(task_id)
    assert task['title'] == 'Test Task'
```

### Repository Code

Repository implementations are located in:
- **File**: `todorama/storage/repositories.py`
- **Classes**: `TaskRepository`, `ProjectRepository`, `OrganizationRepository`

For the complete repository template and best practices, see [REPOSITORY_PATTERN.md](../../agenticness/REPOSITORY_PATTERN.md).

## Database Migrations

The TODO MCP Service uses **Alembic** for database schema migrations, providing version control and rollback capabilities for database changes. This standardized approach is used across all MCP services for consistency and maintainability.

### Standardized Migration Approach

The service uses Alembic for managing database schema changes. All schema modifications are tracked through migration scripts, enabling:
- **Version Control**: Track all schema changes over time
- **Rollback Support**: Ability to rollback migrations if needed
- **Team Collaboration**: Standard workflow for multiple developers
- **Testing**: Test migrations in isolation before applying to production

**Alembic Directory Structure:**
- `alembic/` - Alembic migration directory (at project root)
- `alembic/versions/` - Migration script files
- `alembic/env.py` - Alembic environment configuration
- `alembic.ini` - Alembic configuration file

**Migration History:**
The service has migrated from ad-hoc migration logic (embedded in `database.py`) to Alembic. All new schema changes should be created as Alembic migrations.

### Migration Commands

**Apply Migrations:**
```bash
# Apply all pending migrations
alembic upgrade head

# Apply migrations up to a specific revision
alembic upgrade <revision>

# Apply one migration at a time
alembic upgrade +1
```

**Rollback Migrations:**
```bash
# Rollback last migration
alembic downgrade -1

# Rollback to a specific revision
alembic downgrade <revision>

# Rollback all migrations (use with caution)
alembic downgrade base
```

**Check Migration Status:**
```bash
# Show current migration version
alembic current

# Show migration history
alembic history

# Show detailed history with revisions
alembic history --verbose
```

**Create New Migration:**
```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "description of changes"

# Create empty migration script (manual)
alembic revision -m "description of changes"
```

### Examples

**Local Development (SQLite):**
```bash
# Set database path
export TODO_DB_PATH=./data/todos.db

# Apply all migrations
alembic upgrade head

# Check current version
alembic current

# Create new migration after model changes
alembic revision --autogenerate -m "add new column to tasks"
```

**Containerized Deployment (PostgreSQL):**
```bash
# Set database connection
export DB_TYPE=postgresql
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=todos
export DB_USER=postgres
export DB_PASSWORD=your_password

# Apply migrations in container
docker exec -it todo-mcp-service alembic upgrade head

# Or run migrations before starting service
alembic upgrade head
python -m todorama.server
```

**Creating a New Migration:**
```bash
# 1. Make changes to models in todorama/models/ or database schema
# 2. Generate migration automatically
alembic revision --autogenerate -m "add priority column to tasks"

# 3. Review the generated migration in alembic/versions/
# 4. Edit if needed (add data migrations, custom logic)
# 5. Test the migration
alembic upgrade head
alembic downgrade -1  # Test rollback
alembic upgrade head   # Re-apply
```

**Testing Migrations:**
```bash
# Test migration on a copy of production database
cp production.db test.db
export TODO_DB_PATH=./test.db
alembic upgrade head

# Verify schema changes
sqlite3 test.db ".schema tasks"

# Test rollback
alembic downgrade -1
alembic upgrade head
```

### Troubleshooting

**Common Migration Errors:**

1. **"Target database is not up to date"**
   ```bash
   # Check current version
   alembic current
   
   # Apply pending migrations
   alembic upgrade head
   ```

2. **"Can't locate revision identified by 'xyz'"**
   - Migration history mismatch - check `alembic_version` table
   - May need to manually set version: `alembic stamp <revision>`

3. **"Multiple heads detected"**
   - Multiple migration branches exist
   - Merge branches: `alembic merge -m "merge branches" heads`

4. **Migration conflicts with existing schema**
   - Review migration script for conflicts
   - May need to adjust migration or manually fix schema
   - Use `alembic revision --autogenerate` to detect differences

**Checking Migration Status:**
```bash
# Show current database version
alembic current

# Compare with latest migration
alembic heads

# Show pending migrations
alembic history | head -5
```

**Rollback Procedures:**
```bash
# Rollback last migration (safe)
alembic downgrade -1

# Rollback to specific version
alembic downgrade <revision_id>

# Verify rollback
alembic current

# Re-apply if needed
alembic upgrade head
```

**Resolving Migration Conflicts:**
1. Check migration history: `alembic history`
2. Identify conflicting migrations
3. Review migration scripts in `alembic/versions/`
4. Merge branches if needed: `alembic merge -m "merge" <rev1> <rev2>`
5. Test merged migration: `alembic upgrade head`

### Service-Specific Notes

**SQLite and PostgreSQL Support:**
- Migrations work with both SQLite (local development) and PostgreSQL (production)
- Some PostgreSQL-specific features (e.g., certain index types) may require conditional logic in migrations
- Test migrations on both database types when possible

**Multi-Tenancy Migrations:**
- Organization-related migrations are handled through Alembic
- See `alembic/versions/228b7c679817_add_organization_id_columns.py` for reference

**Migration from Ad-Hoc to Alembic:**
- The service previously used ad-hoc migration logic in `database.py`
- All schema changes are now managed through Alembic migrations
- Historical migrations have been converted to Alembic scripts

### Migration Best Practices

1. **Always Review Auto-Generated Migrations**
   - `alembic revision --autogenerate` is a starting point
   - Review and edit migration scripts before applying
   - Add data migrations if schema changes require data transformation

2. **Test Migrations Before Production**
   - Test on a copy of production database
   - Test both upgrade and downgrade paths
   - Verify data integrity after migrations

3. **Use Descriptive Migration Messages**
   - Clear, descriptive messages: `"add priority column to tasks"`
   - Avoid vague messages: `"update schema"`

4. **Keep Migrations Small and Focused**
   - One logical change per migration when possible
   - Easier to review, test, and rollback

5. **Document Complex Migrations**
   - Add comments in migration scripts for complex logic
   - Document data transformations
   - Note any manual steps required

For more information, see the [Alembic documentation](https://alembic.sqlalchemy.org/).

## Production Deployment

### Resource Limits

The service includes resource limits in `docker-compose.yml` to prevent resource exhaustion:

```bash
# Set resource limits via environment variables
export TODO_SERVICE_CPU_LIMIT=2.0
export TODO_SERVICE_MEMORY_LIMIT=512M
export TODO_SERVICE_CPU_RESERVATION=0.5
export TODO_SERVICE_MEMORY_RESERVATION=256M

export POSTGRES_CPU_LIMIT=1.0
export POSTGRES_MEMORY_LIMIT=512M
export POSTGRES_CPU_RESERVATION=0.25
export POSTGRES_MEMORY_RESERVATION=128M
```

Defaults are conservative but can be adjusted based on workload.

### Graceful Shutdown

The service implements graceful shutdown handling:

- **Signal Handling**: Responds to SIGTERM and SIGINT signals
- **FastAPI Lifespan Events**: Properly shuts down background tasks (backup scheduler)
- **Uvicorn Configuration**: 30-second timeout for graceful shutdown
- **Clean Resource Cleanup**: Ensures backup scheduler and connections are closed

When deploying to production:
- Ensure orchestrators (Docker, Kubernetes) send SIGTERM before force-killing
- Allow at least 30 seconds for graceful shutdown
- Monitor logs for "Application shutting down..." to confirm clean shutdown

### Webhook Configuration for Production

The service supports webhooks for real-time event notifications. In production, configure webhooks properly:

#### Webhook Setup

1. **Create a webhook endpoint** (in your application/service):

```bash
curl -X POST http://localhost:8004/webhooks \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-service.com/webhooks/todo-events",
    "events": ["task.created", "task.completed", "task.status_changed"],
    "secret": "your-webhook-secret-here",
    "enabled": true,
    "retry_count": 3,
    "timeout_seconds": 10
  }'
```

2. **For Telegram Bot Services** (using webhooks instead of polling):

Set environment variables in `docker-compose.yml`:
```yaml
environment:
  - TELEGRAM_WEBHOOK_URL=https://your-domain.com/telegram/webhook
  - TELEGRAM_WEBHOOK_SECRET=your-secret-key
  - TELEGRAM_USE_POLLING=false  # Set to true for development
```

**Production vs Development:**
- **Production**: Use webhooks (`TELEGRAM_USE_POLLING=false`) - more efficient, real-time, scalable
- **Development**: Use polling (`TELEGRAM_USE_POLLING=true`) - simpler setup, no public URL needed

#### Webhook Security

- **HMAC Signatures**: Use the `secret` field to set a secret. The service sends `X-Webhook-Signature` header with HMAC-SHA256.
- **HTTPS Only**: Always use HTTPS for webhook URLs in production.
- **Secret Rotation**: Regularly rotate webhook secrets.
- **Verification**: Verify signatures on your webhook receiver:

```python
import hmac
import hashlib

def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

#### Webhook Retries

Webhooks are retried on failure (default: 3 retries, 10-second timeout). Failed webhooks are logged but don't block task operations.

### Production Checklist

- [ ] Resource limits configured in `docker-compose.yml`
- [ ] Environment variables set for production (database, ports, logging)
- [ ] Webhooks configured with HTTPS URLs and secrets
- [ ] Rate limiting adjusted for expected load
- [ ] Backups scheduled and tested
- [ ] Health checks configured and monitored
- [ ] Logging level set appropriately (INFO for production, DEBUG for troubleshooting)
- [ ] Graceful shutdown tested (send SIGTERM, verify clean shutdown)

### Monitoring

The service exposes Prometheus metrics at `/metrics`:

```bash
curl http://localhost:8004/metrics
```

Key metrics:
- `http_requests_total`: Total request count by endpoint/status
- `http_request_duration_seconds`: Request latency histograms
- `http_errors_total`: Error counts by type
- `service_uptime_seconds`: Service uptime

Health endpoint: `http://localhost:8004/health`

## Deployment

### CI/CD Pipeline

The project includes a comprehensive CI/CD pipeline implemented with GitHub Actions:

- **Automated Testing**: Runs unit tests with pytest and enforces 80% code coverage
- **Code Quality**: Checks formatting (Black), import sorting (isort), linting (flake8, pylint), and type checking (mypy)
- **Security Scanning**: Dependency vulnerability checks (Safety), code security analysis (Bandit), and container scanning (Trivy)
- **Docker Builds**: Automated Docker image builds and pushes to GitHub Container Registry
- **Automated Deployments**: Staging deployments on `develop` branch, production deployments on `main` branch
- **Rollback Capabilities**: Automatic rollback on deployment failures

### Deployment Environments

- **Staging**: `docker-compose.staging.yml` - Pre-production testing (port 8005)
- **Production**: `docker-compose.production.yml` - Live production service (port 8004)

### Manual Deployment

**Using Docker Compose:**

```bash
# Staging
export STAGING_PORT=8005
export STAGING_DATA_DIR=./data/staging
docker-compose -f docker-compose.staging.yml up -d

# Production
export PRODUCTION_PORT=8004
export PRODUCTION_DATA_DIR=./data/production
export POSTGRES_PASSWORD=your-secure-password
docker-compose -f docker-compose.production.yml up -d
```

**Using GitHub Actions:**

1. Go to Actions → Deploy workflow
2. Click "Run workflow"
3. Select environment (staging/production)
4. Optionally specify image tag (default: latest)
5. Click "Run workflow"

### Rollback Procedures

**Automatic Rollback:**
- Pipeline automatically rolls back on deployment failure
- Detects deployment health check failures
- Restores previous container version

**Manual Rollback:**
```bash
# Rollback using Docker Compose
docker-compose -f docker-compose.production.yml down
docker-compose -f docker-compose.production.yml up -d

# Or pull previous image tag
docker pull ghcr.io/your-repo/todo-mcp-service:previous-tag
# Update docker-compose.yml with previous tag, then redeploy
```

## Performance

### Query Performance Targets

| Operation | Expected Performance | Notes |
|-----------|---------------------|-------|
| `query_tasks()` (simple filter) | < 50ms | With indexes |
| `query_tasks()` (complex filters) | < 100ms | Multiple conditions |
| `query_tasks()` (with blocked check) | < 200ms | Batch optimization |
| `get_available_tasks_for_agent()` | < 50ms | Uses composite index |
| `_find_tasks_with_blocked_subtasks_batch()` | < 100ms | For 1000 tasks |

### Scalability

The optimizations support:
- **Tasks**: 10,000+ tasks per project
- **Relationships**: Deep hierarchies (10+ levels)
- **Queries**: 100+ concurrent queries

### Performance Monitoring

Enable query logging:
```bash
export DB_ENABLE_QUERY_LOGGING=true
export DB_QUERY_SLOW_THRESHOLD=0.1  # seconds
```

Run performance tests:
```bash
pytest tests/test_database_performance.py -v
```

### Best Practices

1. **Use Indexed Columns**: Filter by indexed columns (`task_status`, `task_type`, `project_id`) when possible
2. **Batch Operations**: Use batch methods instead of individual checks
3. **Limit Results**: Always use `limit` parameter in queries
4. **Monitor Slow Queries**: Enable query logging in production
5. **Review Query Plans**: Use `EXPLAIN QUERY PLAN` when optimizing queries

For detailed performance optimization guide, see [PERFORMANCE.md](PERFORMANCE.md).

## Slack Integration

The TODO service supports Slack integration for task notifications and slash commands.

### Features

- **Task Notifications**: Receive notifications in Slack channels when tasks are created, completed, or blocked
- **Slash Commands**: Use `/todo` commands to list, reserve, and complete tasks
- **Interactive Components**: Click buttons in Slack messages to reserve tasks

### Setup

1. **Create a Slack App** at [api.slack.com/apps](https://api.slack.com/apps)
2. **Configure Bot Token Scopes**: `chat:write`, `commands`, `users:read`
3. **Set Up Slash Commands**: `/todo` pointing to `https://your-domain.com/slack/commands`
4. **Configure Event Subscriptions**: Point to `https://your-domain.com/slack/events`
5. **Enable Interactive Components**: Point to `https://your-domain.com/slack/interactive`
6. **Set Environment Variables**:
   ```bash
   SLACK_BOT_TOKEN=xoxb-<your-token>
   SLACK_SIGNING_SECRET=<your-secret>
   SLACK_DEFAULT_CHANNEL=#general
   ```

### Usage

**Slash Commands:**
- `/todo list` - List available tasks (up to 10)
- `/todo reserve <task_id>` - Reserve a task
- `/todo complete <task_id> [notes]` - Complete a task
- `/todo help` - Show available commands

**Security:**
- All Slack requests are verified using HMAC-SHA256 signatures
- Timestamp validation prevents replay attacks
- Bot tokens and signing secrets should be kept secure

For detailed setup instructions, see [SLACK_SETUP.md](SLACK_SETUP.md).

## Audio Converter

The service includes an audio converter utility for Telegram voice messages.

### Features

- Converts PCM/WAV audio files to OGG/OPUS format (Telegram's preferred format)
- Handles Telegram's ~1 minute duration limit (automatically truncates longer audio)
- Optimizes audio quality and file size
- Supports compression for smaller file sizes

### Requirements

**System Dependency:**
- `ffmpeg` must be installed on the system

**Installation:**
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg
```

### Usage

```python
from audio_converter import TelegramAudioConverter

converter = TelegramAudioConverter()

# Convert WAV to OGG/OPUS for Telegram
converter.convert_for_telegram(
    input_path="input.wav",
    output_path="output.ogg",
    compress=True  # Optional compression
)
```

### Telegram Constraints

- **Maximum Duration:** ~60 seconds (automatically enforced)
- **Recommended Bitrate:** 64 kbps
- **Maximum File Size:** 20 MB
- **Format:** OGG/OPUS
- **Sample Rate:** 48000 Hz (automatically set)
- **Channels:** Mono (automatically set)

The audio converter is located in `todorama/services/audio_converter.py`.

## MCP Function Guide

The TODO service exposes MCP functions for agent interaction. See [MCP_FUNCTION_GUIDE.md](MCP_FUNCTION_GUIDE.md) for a comprehensive guide on selecting the right MCP function for your needs.

### Core Task Workflow Functions

- **`list_available_tasks()`** - Get tasks ready for your agent type
- **`reserve_task()`** - Lock a task before working (MANDATORY)
- **`complete_task()`** - Mark task complete (MANDATORY when done)
- **`create_task()`** - Create new tasks with automatic relationship linking
- **`get_task_context()`** - Get full task details including project, ancestry, updates
- **`add_task_update()`** - Add progress updates, findings, blockers, or questions
- **`query_tasks()`** - Flexible task search by status, type, agent, priority, tags
- **`search_tasks()`** - Keyword-based search across task titles and instructions

### Function Selection Decision Tree

- **I need to find a task to work on**: Use `list_available_tasks()` or `query_tasks()`
- **I need task information**: Use `get_task_context()` for full details
- **I need statistics**: Use `get_agent_performance()` or `get_project_statistics()`
- **I need to organize tasks**: Use `create_task()` with relationships, or `add_task_tags()`
- **I need to communicate**: Use `add_task_update()` with appropriate `update_type`

For complete function reference and best practices, see [MCP_FUNCTION_GUIDE.md](MCP_FUNCTION_GUIDE.md).

## Documentation

- **[AGENTS.md](./AGENTS.md)** - Agent guidelines and development practices
- **[API.md](./API.md)** - Comprehensive API documentation
- **[MCP_FUNCTION_GUIDE.md](./MCP_FUNCTION_GUIDE.md)** - MCP function selection guide
- **[PERFORMANCE.md](./PERFORMANCE.md)** - Database performance optimization guide
- **[SLACK_SETUP.md](./SLACK_SETUP.md)** - Slack integration setup guide

## License

MIT License
