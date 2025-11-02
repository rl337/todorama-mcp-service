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

For detailed deployment instructions, see [DEPLOYMENT.md](DEPLOYMENT.md).

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

## License

MIT License
