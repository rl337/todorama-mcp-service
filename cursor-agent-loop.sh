#!/bin/bash
# Enhanced cursor-agent loop that properly uses MCP functions for task management
# Uses CLI tool to manage tasks directly instead of relying on generic prompts
# Exits on non-zero return code to allow for error handling and monitoring
# Usage: ./cursor-agent-loop.sh [LOOP_COUNT]
#   If LOOP_COUNT is provided (e.g., 10), the script will loop that many times
#   If no argument is provided, the script will loop indefinitely

set -euo pipefail

# Configuration
AGENT_ID="${CURSOR_AGENT_ID:-cursor-agent}"
PROJECT_ID="${CURSOR_PROJECT_ID:-}"
AGENT_TYPE="${CURSOR_AGENT_TYPE:-implementation}"
SLEEP_INTERVAL="${CURSOR_SLEEP_INTERVAL:-60}"
TODO_SERVICE_URL="${TODO_SERVICE_URL:-http://localhost:8004}"
CLI_SCRIPT="${CLI_SCRIPT:-python3 src/cli.py}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $*"
}

# Optional loop count from command line argument
MAX_LOOPS="${1:-}"
if [ -n "$MAX_LOOPS" ] && ! [[ "$MAX_LOOPS" =~ ^[0-9]+$ ]]; then
    log_error "Loop count must be a positive integer"
    echo "Usage: $0 [LOOP_COUNT]"
    exit 1
fi

# Function to call CLI and parse JSON response
cli_json() {
    local cmd="$1"
    shift
    $CLI_SCRIPT --url "$TODO_SERVICE_URL" "$cmd" --format json "$@" 2>/dev/null || echo "[]"
}

# Function to get task ID from JSON array
get_task_id() {
    local json="$1"
    echo "$json" | python3 -c "import sys, json; tasks=json.load(sys.stdin); print(tasks[0]['id'] if tasks and len(tasks) > 0 else '')" 2>/dev/null || echo ""
}

# Function to reserve task via CLI
reserve_task_cli() {
    local task_id=$1
    log "Reserving task $task_id for agent $AGENT_ID"
    if $CLI_SCRIPT --url "$TODO_SERVICE_URL" reserve --task-id "$task_id" --agent-id "$AGENT_ID" >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Function to unlock task via CLI (mandatory on errors)
unlock_task_cli() {
    local task_id=$1
    log_warning "Unlocking task $task_id due to error"
    $CLI_SCRIPT --url "$TODO_SERVICE_URL" unlock --task-id "$task_id" --agent-id "$AGENT_ID" >/dev/null 2>&1 || true
}

# Function to complete task via CLI
complete_task_cli() {
    local task_id=$1
    local notes="${2:-Completed successfully}"
    log "Completing task $task_id"
    $CLI_SCRIPT --url "$TODO_SERVICE_URL" complete --task-id "$task_id" --agent-id "$AGENT_ID" --notes "$notes" >/dev/null 2>&1
}

# Function to get task context as JSON
get_task_context_cli() {
    local task_id=$1
    $CLI_SCRIPT --url "$TODO_SERVICE_URL" show --task-id "$task_id" --format json 2>/dev/null || echo "{}"
}

# Function to check for in-progress tasks
check_in_progress_tasks() {
    local filter_args=()
    filter_args+=(--status in_progress)
    filter_args+=(--agent "$AGENT_ID")
    filter_args+=(--limit 10)
    
    cli_json list "${filter_args[@]}"
}

# Function to find available tasks
# For implementation agents: returns concrete tasks
# For breakdown agents: returns abstract tasks (epic tasks handled separately)
find_available_task() {
    local filter_args=()
    filter_args+=(--status available)
    filter_args+=(--limit 1)
    
    if [ -n "$PROJECT_ID" ]; then
        filter_args+=(--project-id "$PROJECT_ID")
    fi
    
    # Map agent_type to task_type
    local task_type=""
    if [ "$AGENT_TYPE" = "implementation" ]; then
        task_type="concrete"
    elif [ "$AGENT_TYPE" = "breakdown" ]; then
        # For breakdown agents, try abstract first, then epic
        # First try abstract tasks (build args without type yet)
        local abstract_filter_args=()
        abstract_filter_args+=(--status available)
        abstract_filter_args+=(--type abstract)
        abstract_filter_args+=(--limit 1)
        if [ -n "$PROJECT_ID" ]; then
            abstract_filter_args+=(--project-id "$PROJECT_ID")
        fi
        
        local abstract_tasks=$(cli_json list "${abstract_filter_args[@]}")
        local abstract_id=$(get_task_id "$abstract_tasks")
        if [ -n "$abstract_id" ]; then
            echo "$abstract_tasks"
            return 0
        fi
        # If no abstract tasks, try epic tasks
        task_type="epic"
    else
        log_error "Unknown agent_type: $AGENT_TYPE"
        return 1
    fi
    
    filter_args+=(--type "$task_type")
    cli_json list "${filter_args[@]}"
}

# Function to build task prompt for cursor-agent
build_task_prompt() {
    local task_id=$1
    local task_context="$2"
    
    # Extract task information from context
    local title=$(echo "$task_context" | python3 -c "import sys, json; t=json.load(sys.stdin); print(t.get('title', 'Unknown'))" 2>/dev/null || echo "Unknown")
    local instruction=$(echo "$task_context" | python3 -c "import sys, json; t=json.load(sys.stdin); print(t.get('task_instruction', ''))" 2>/dev/null || echo "")
    local verification=$(echo "$task_context" | python3 -c "import sys, json; t=json.load(sys.stdin); print(t.get('verification_instruction', ''))" 2>/dev/null || echo "")
    local project_path=$(echo "$task_context" | python3 -c "import sys, json; t=json.load(sys.stdin); p=t.get('project', {}); print(p.get('local_path', ''))" 2>/dev/null || echo "")
    
    cat <<EOF
Work on task #$task_id: $title

TASK INSTRUCTIONS:
$instruction

VERIFICATION CRITERIA:
$verification

IMPORTANT: 
- Use MCP TODO service tools directly (mcp_todo_* functions)
- Check git status in: ${project_path:-current directory}
- Add progress updates using mcp_todo_add_task_update() as you work
- When complete, call mcp_todo_complete_task(task_id=$task_id, agent_id='$AGENT_ID', notes='...')
- If you cannot complete, call mcp_todo_unlock_task(task_id=$task_id, agent_id='$AGENT_ID') - THIS IS MANDATORY

CRITICAL: DO NOT create scripts or make HTTP requests - use MCP tools directly!
EOF
}

# Main loop
log "Starting cursor-agent loop"
log "Agent ID: $AGENT_ID"
log "Project ID: ${PROJECT_ID:-all projects}"
log "Agent Type: $AGENT_TYPE"
log "Sleep interval: ${SLEEP_INTERVAL}s"
if [ -n "$MAX_LOOPS" ]; then
    log "Maximum loops: $MAX_LOOPS"
else
    log "Running indefinitely (no loop limit)"
fi

TASK_ID=""
LOOP_COUNT=0

while true; do
    LOOP_COUNT=$((LOOP_COUNT + 1))
    TASK_ID=""
    
    # Check if we've reached the maximum loop count
    if [ -n "$MAX_LOOPS" ] && [ "$LOOP_COUNT" -gt "$MAX_LOOPS" ]; then
        log "Reached maximum loop count of ${MAX_LOOPS}. Exiting."
        break
    fi
    
    log "Starting task iteration #${LOOP_COUNT}${MAX_LOOPS:+ / ${MAX_LOOPS}}..."
    
    # STEP 1: Check for existing in-progress tasks FIRST
    log "Checking for in-progress tasks..."
    IN_PROGRESS_TASKS=$(check_in_progress_tasks)
    IN_PROGRESS_ID=$(get_task_id "$IN_PROGRESS_TASKS")
    
    if [ -n "$IN_PROGRESS_ID" ]; then
        log "Found in-progress task: $IN_PROGRESS_ID"
        TASK_ID="$IN_PROGRESS_ID"
    else
        # STEP 2: No in-progress tasks, find available task
        log "No in-progress tasks, searching for available tasks..."
        AVAILABLE_TASKS=$(find_available_task)
        AVAILABLE_ID=$(get_task_id "$AVAILABLE_TASKS")
        
        if [ -z "$AVAILABLE_ID" ]; then
            log_warning "No available tasks found. Sleeping ${SLEEP_INTERVAL}s before retry..."
            sleep "$SLEEP_INTERVAL"
            continue
        fi
        
        log "Found available task: $AVAILABLE_ID"
        
        # Reserve the task
        if ! reserve_task_cli "$AVAILABLE_ID"; then
            log_error "Failed to reserve task $AVAILABLE_ID (may have been taken by another agent)"
            log "Continuing to next iteration..."
            sleep "$SLEEP_INTERVAL"
            continue
        fi
        
        TASK_ID="$AVAILABLE_ID"
    fi
    
    # STEP 3: Get task context
    log "Getting context for task $TASK_ID..."
    TASK_CONTEXT=$(get_task_context_cli "$TASK_ID")
    
    if [ "$TASK_CONTEXT" = "{}" ] || [ -z "$TASK_CONTEXT" ]; then
        log_error "Failed to get task context for task $TASK_ID"
        unlock_task_cli "$TASK_ID"
        continue
    fi
    
    # STEP 4: Build prompt with task context and invoke cursor-agent
    log "Invoking cursor-agent for task $TASK_ID..."
    TASK_PROMPT=$(build_task_prompt "$TASK_ID" "$TASK_CONTEXT")
    
    # Create temporary file for prompt to avoid shell escaping issues
    PROMPT_FILE=$(mktemp)
    echo "$TASK_PROMPT" > "$PROMPT_FILE"
    
    if cursor-agent agent \
        -p \
        --model=auto \
        --stream-partial-output \
        --force \
        --approve-mcps \
        "$(cat "$PROMPT_FILE")" \
        --output-format stream-json; then
        
        log_success "cursor-agent completed successfully for task $TASK_ID"
        
        # Try to complete the task (cursor-agent should have done this via MCP, but we do it here as backup)
        # Note: If cursor-agent already completed it via MCP, this will fail gracefully
        if complete_task_cli "$TASK_ID" "Completed via cursor-agent-loop.sh"; then
            log_success "Task $TASK_ID marked as complete"
        else
            log_warning "Task $TASK_ID may have already been completed by cursor-agent"
        fi
        
        # Cleanup
        rm -f "$PROMPT_FILE"
        
        # Check if we've reached the maximum loop count before sleeping
        if [ -n "$MAX_LOOPS" ] && [ "$LOOP_COUNT" -ge "$MAX_LOOPS" ]; then
            log "Completed ${LOOP_COUNT} iteration(s). Exiting."
            break
        fi
        
        log "Sleeping ${SLEEP_INTERVAL}s before next iteration..."
        sleep "$SLEEP_INTERVAL"
    else
        EXIT_CODE=$?
        log_error "cursor-agent returned non-zero exit code: $EXIT_CODE"
        
        # Cleanup
        rm -f "$PROMPT_FILE"
        
        # MANDATORY: Unlock task on error
        if [ -n "$TASK_ID" ]; then
            unlock_task_cli "$TASK_ID"
        fi
        
        # Determine if we should exit or continue
        # Continue on recoverable errors (task already taken, network issues)
        # Exit on unrecoverable errors (script errors, configuration issues)
        if [ "$EXIT_CODE" -eq 1 ]; then
            log_warning "Recoverable error detected, continuing to next iteration..."
            sleep "$SLEEP_INTERVAL"
            continue
        else
            log_error "Unrecoverable error detected, exiting loop"
            exit "$EXIT_CODE"
        fi
    fi
done

log "Agent loop finished. Completed ${LOOP_COUNT} iteration(s)."
