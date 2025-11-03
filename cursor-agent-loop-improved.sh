#!/bin/bash
# Enhanced cursor-agent loop that properly uses MCP functions for task management
# Exits on non-zero return code to allow for error handling and monitoring
# Usage: ./cursor-agent-loop-improved.sh [LOOP_COUNT]
#   If LOOP_COUNT is provided (e.g., 10), the script will loop that many times
#   If no argument is provided, the script will loop indefinitely

set -euo pipefail

HOSTNAME=$(hostname)

# Configuration
AGENT_ID="${CURSOR_AGENT_ID:-cursor-${HOSTNAME}-cli}"
PROJECT_ID="${CURSOR_PROJECT_ID:-}"
AGENT_TYPE="${CURSOR_AGENT_TYPE:-implementation}"
SLEEP_INTERVAL="${CURSOR_SLEEP_INTERVAL:-60}"
TODO_SERVICE_URL="${TODO_SERVICE_URL:-http://localhost:8004}"

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

# Function to unlock task on error
unlock_task() {
    local task_id=$1
    log_warning "Unlocking task $task_id due to error"
    # Note: This would use MCP unlock_task function
    # For now, we log the intention
    # cursor-agent should handle this via MCP if it has access
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

    cursor-agent mcp list | grep "todo"
    if [ $? -ne 0 ]; then
        log_error "Failed to list MCP tools"
        exit 1
    fi

    cursor-agent mcp list-tools todo
    if [ $? -ne 0 ]; then
        log_error "Failed to list MCP tools"
        exit 1
    fi
    
    AGENT_PROMPT="
        Your agent-id is $AGENT_ID
        Use the MCP TODO service tools directly (available through Cursor's MCP integration) to work on tasks. DO NOT create scripts or make HTTP requests - use the MCP tools directly. Follow this workflow:
        
        IMPORTANT: The MCP tools are already available to you. Use them directly with the 'todo-' prefix:
          - todo-query_tasks() - NOT query_tasks() or HTTP requests
          - todo-list_available_tasks() - NOT list_available_tasks() or HTTP requests
          - todo-reserve_task() - NOT reserve_task() or HTTP requests
          - todo-get_task_context() - NOT get_task_context() or HTTP requests
          - todo-add_task_update() - NOT add_task_update() or HTTP requests
          - todo-complete_task() - NOT complete_task() or HTTP requests
          - todo-unlock_task() - NOT unlock_task() or HTTP requests
        
        CRITICAL: DO NOT:
          - Create Python scripts (work_on_task*.py, etc.)
          - Make HTTP requests to /mcp/* endpoints
          - Import or use requests library for TODO operations
          - Write wrapper functions around MCP calls
        The MCP tools are already integrated - just call them directly!
        
        STEP 1: Check for your existing in-progress tasks FIRST
          - Call todo-query_tasks(agent_id='$AGENT_ID', task_status='in_progress', limit=10) to find tasks already assigned to you
          - If you find any tasks, continue working on the first one (call todo-get_task_context(task_id=<id>) to get full context)
          - Add an update to the task saying what you found and what you're going to do (use todo-add_task_update)
          - Review previous updates, check git status for uncommitted changes, and resume where you left off
          - If the task is done and there are uncommitted changes, commit the changes and then complete the task
          - If no tasks are found, proceed to STEP 2
        
        STEP 2: Pick up a new task (only if you have no in-progress tasks)
          - Call todo-list_available_tasks(agent_type='$AGENT_TYPE', project_id=${PROJECT_ID:-None}, limit=10) to find available tasks
          - If a task is found, call todo-reserve_task(task_id=<id>, agent_id='$AGENT_ID') to lock it
          - Get full context: call todo-get_task_context(task_id=<id>) to see previous work, updates, and stale warnings
          - Note: Tasks may be regular implementation tasks OR verification tasks (complete but unverified) - both work the same way
        
        STEP 3: Review previous work and check git status
          - Read all previous updates from the context to understand what was already tried
          - Check git status in the project directory (from context['project']['local_path']) for uncommitted changes
          - Review git diff to see what previous work was done
          - If there's a stale_warning in the context, verify all previous work before continuing
        
        STEP 4: Work on the task
          - Continue from where previous work left off (don't start from scratch)
          - Follow the task_instruction and verification_instruction from the task context
          - For verification tasks (tasks showing needs_verification=True): Review the verification_instruction and verify the completed work satisfies those requirements
          - Add progress updates using todo-add_task_update() as you work
          - Check git status regularly to see what changes you're making
        
        STEP 5: Complete the task
          - If successful, call todo-complete_task(task_id=<id>, agent_id='$AGENT_ID', notes='<completion notes>')
          - IMPORTANT: If the task is already complete but unverified, calling todo-complete_task() will automatically mark it as verified - no special handling needed!
          - If you cannot complete it, call todo-unlock_task(task_id=<id>, agent_id='$AGENT_ID') - THIS IS MANDATORY
          - Report success or failure
        
        CRITICAL RULES:
        - Always check for your existing in-progress tasks BEFORE picking up new ones
        - Always check git status and previous updates before starting work
        - Always call either todo-complete_task() or todo-unlock_task() when done - never leave a task in_progress
        - Verification is transparent: if a task is complete but unverified, just complete it normally - the backend handles verification automatically
        - If you encounter any error that prevents completion, call todo-unlock_task() before exiting
        - Continue existing work rather than starting fresh
        - DO NOT create scripts or make HTTP requests - use the MCP tools directly!"
    
    if cursor-agent agent \
        -p \
        --model=auto \
        --stream-partial-output \
        --force \
        --approve-mcps \
        "${AGENT_PROMPT}" \
        --output-format stream-json; then
        
        log_success "Task completed successfully"
        
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
        
        # If we had a task reserved, try to unlock it
        if [ -n "$TASK_ID" ]; then
            unlock_task "$TASK_ID"
        fi
        
        log_error "Exiting loop due to error"
        exit "$EXIT_CODE"
    fi
done

log "Agent loop finished. Completed ${LOOP_COUNT} iteration(s)."

