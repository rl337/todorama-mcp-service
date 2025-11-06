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

# Timeout configuration (in seconds)
AGENT_TIMEOUT="${AGENT_TIMEOUT:-3600}"  # 1 hour max for agent execution
GIT_TIMEOUT="${GIT_TIMEOUT:-300}"       # 5 minutes max for git operations
TEST_TIMEOUT="${TEST_TIMEOUT:-1800}"    # 30 minutes max for test suite
MCP_TIMEOUT="${MCP_TIMEOUT:-30}"        # 30 seconds max for MCP tool calls

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
    
    # Check for pre-commit failure semaphore (if agent is the only one working in this checkout)
    SEMAPHORE_FILE=".pre-commit-failed"
    if [ -f "$SEMAPHORE_FILE" ]; then
        log_warning "=========================================="
        log_warning "PRE-COMMIT FAILURE SEMAPHORE DETECTED!"
        log_warning "=========================================="
        log_warning "Semaphore file: $SEMAPHORE_FILE"
        log_warning "Previous commit attempt failed tests."
        log_warning "Agent MUST fix issues and commit BEFORE picking up any tasks."
        log_warning "=========================================="
        
        # Read semaphore file content for context
        SEMAPHORE_CONTENT=$(cat "$SEMAPHORE_FILE" 2>/dev/null || echo "Semaphore file exists but content unavailable")
        
        # Update agent prompt to prioritize fixing pre-commit issues
        AGENT_PROMPT="
        Your agent-id is $AGENT_ID
        
        🚨🚨🚨 CRITICAL PRIORITY: PRE-COMMIT CHECKS FAILED 🚨🚨🚨
        
        A semaphore file (.pre-commit-failed) exists in the repository root. This is a blocking signal that
        means the previous commit attempt failed due to test failures. You MUST fix these issues and commit
        successfully before doing ANY other work, including picking up new tasks.
        
        SEMAPHORE FILE CONTENT:
        ${SEMAPHORE_CONTENT}
        
        MANDATORY WORKFLOW (DO NOT SKIP ANY STEP):
        
        STEP 1: Assess the situation
          - Check git status: git status
          - Check what files have uncommitted changes: git diff --name-only
          - Review the semaphore file: cat .pre-commit-failed
          - Understand what tests are failing
        
        STEP 2: Run tests to see current failures
          - Run the test suite with timeout: cd /home/rlee/dev/todo-mcp-service && timeout 1800 ./run_checks.sh
          - CRITICAL: Always use 'timeout' command for long-running operations
          - If tests timeout, investigate what's hanging and fix it
          - Note all failing tests and errors
          - Pay attention to:
            * Integration test failures
            * Database schema test failures
            * Import errors
            * Validation errors
            * Timeout issues (indicates hanging tests)
        
        STEP 3: Fix the failing tests one by one
          - For each failing test, read the test file and understand what it's testing
          - Fix the code to make the test pass
          - Run the specific test with timeout: timeout 300 pytest tests/test_file.py::test_name -v
          - CRITICAL: Always use 'timeout 300' (5 minutes) for individual test runs
          - If a test times out, it's hanging - fix the root cause
          - Verify the fix works
        
        STEP 4: Fix import errors
          - Check for missing imports: python -m py_compile <file>
          - Fix any ModuleNotFoundError issues
          - Ensure all dependencies are properly imported
        
        STEP 5: Re-run all checks
          - Run with timeout: timeout 1800 ./run_checks.sh
          - CRITICAL: Always use 'timeout 1800' (30 minutes) for full test suite
          - Verify ALL tests pass
          - Verify no import errors
          - Verify code quality checks pass
          - Verify no timeouts occurred
        
        STEP 6: Commit the fixes
          - Stage all changes with timeout: timeout 60 git add -A
          - Commit with timeout: timeout 300 git commit -m \"Fix pre-commit test failures: <list of fixes>\"
          - CRITICAL: Always use 'timeout' for git operations (git add: 60s, git commit: 300s)
          - The commit will trigger the pre-commit hook again
          - If git operations timeout, check for hung processes and kill them
          - If it still fails, go back to STEP 2
        
        STEP 7: Remove semaphore file
          - After successful commit (pre-commit hook passes), remove the semaphore: rm .pre-commit-failed
          - Verify the file is gone: ls -la .pre-commit-failed (should show file not found)
        
        STEP 8: Push changes
          - Push to remote with timeout: timeout 300 git push origin main
          - CRITICAL: Always use 'timeout 300' (5 minutes) for git push
          - If push times out, check network connectivity and remote repository status
        
        CRITICAL RULES:
        - ALWAYS use 'timeout' command for ALL operations:
          * Test runs: timeout 300 (5 min) for single tests, timeout 1800 (30 min) for full suite
          * Git operations: timeout 60 (1 min) for git add, timeout 300 (5 min) for git commit/push
          * MCP tool calls: timeout 30 (30 sec) - if they hang, kill the process and investigate
        - If any operation times out, investigate and fix the root cause (usually a hanging test or network issue)
        - DO NOT pick up any new tasks until the semaphore file is removed
        - DO NOT work on any other code until tests pass
        - DO NOT skip the commit step - the semaphore must be cleared
        - The semaphore file removal is your signal that everything is fixed
        - If you cannot fix the tests, add a task update explaining the blocker and unlock any in-progress tasks
        - If you encounter hanging processes, kill them: pkill -9 -f \"process-name\"
        
        Once the semaphore file is removed, you may proceed with normal task work on the next iteration.
        Use the MCP TODO service tools directly with the 'todo-' prefix if needed for task updates."
        
        # Run agent to fix pre-commit issues with strict timeout
        log "Running agent to fix pre-commit failures (timeout: ${AGENT_TIMEOUT}s)..."
        if timeout "$AGENT_TIMEOUT" cursor-agent agent \
            -p \
            --model=auto \
            --stream-partial-output \
            --force \
            --approve-mcps \
            "${AGENT_PROMPT}" \
            --output-format stream-json; then
            
            # Check if semaphore was removed (tests fixed and committed)
            if [ ! -f "$SEMAPHORE_FILE" ]; then
                log_success "✅ Pre-commit issues fixed and committed. Semaphore removed."
                log_success "✅ Agent can now proceed with normal task work."
            else
                log_warning "⚠️  Semaphore still exists - tests may not be fully fixed yet."
                log_warning "⚠️  Agent will retry on next iteration."
            fi
            
            # Continue to next iteration (will check for tasks normally if semaphore is gone)
            if [ -n "$MAX_LOOPS" ] && [ "$LOOP_COUNT" -ge "$MAX_LOOPS" ]; then
                log "Completed ${LOOP_COUNT} iteration(s). Exiting."
                break
            fi
            
            log "Sleeping ${SLEEP_INTERVAL}s before next iteration..."
            sleep "$SLEEP_INTERVAL"
            continue
        else
            EXIT_CODE=$?
            if [ $EXIT_CODE -eq 124 ]; then
                log_error "❌ Agent TIMED OUT after ${AGENT_TIMEOUT}s while fixing pre-commit issues"
                log_error "❌ This may indicate the agent got stuck. Killing any remaining processes..."
                pkill -9 -f "cursor-agent.*pre-commit" 2>/dev/null || true
            else
                log_error "❌ Failed to fix pre-commit issues. Exit code: $EXIT_CODE"
            fi
            log_error "❌ Agent will retry on next iteration."
            # Continue loop - will retry on next iteration
            sleep "$SLEEP_INTERVAL"
            continue
        fi
    else
        # No semaphore file - normal workflow can proceed
        log "✅ No semaphore file detected - proceeding with normal task work"
    fi

    # Check MCP tools availability with timeout
    if ! timeout "$MCP_TIMEOUT" cursor-agent mcp list 2>/dev/null | grep -q "todo"; then
        log_warning "MCP tools check failed or timed out (${MCP_TIMEOUT}s), continuing anyway..."
    fi

    if ! timeout "$MCP_TIMEOUT" cursor-agent mcp list-tools todo 2>/dev/null; then
        log_warning "MCP tools list failed or timed out (${MCP_TIMEOUT}s), continuing anyway..."
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
        
        STEP 0: Check for pre-commit failure semaphore FIRST (MANDATORY)
          - ALWAYS check if .pre-commit-failed file exists in the repository root
          - If it exists, STOP immediately and do NOT proceed with task work
          - The semaphore indicates blocked commits due to test failures
          - You MUST fix the failing tests, commit successfully, and remove the semaphore file
          - Only proceed to STEP 1 after confirming .pre-commit-failed does NOT exist
        
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
          - Check git status with timeout: timeout 60 git status (in the project directory from context['project']['local_path'])
          - Review git diff with timeout: timeout 60 git diff (to see what previous work was done)
          - CRITICAL: Always use 'timeout 60' for git status/diff operations
          - If there's a stale_warning in the context, verify all previous work before continuing
        
        STEP 4: Work on the task
          - Continue from where previous work left off (don't start from scratch)
          - Follow the task_instruction and verification_instruction from the task context
          - For verification tasks (tasks showing needs_verification=True): Review the verification_instruction and verify the completed work satisfies those requirements
          - Add progress updates using todo-add_task_update() as you work (these should complete quickly - if they hang, kill the process)
          - Check git status regularly with timeout: timeout 60 git status (to see what changes you're making)
          - CRITICAL: If any MCP tool call hangs longer than 30 seconds, kill the process and investigate
          - If running tests: Always use 'timeout 300 pytest' for individual tests, 'timeout 1800 ./run_checks.sh' for full suite
        
        STEP 5: Complete the task
          - If successful, call todo-complete_task(task_id=<id>, agent_id='$AGENT_ID', notes='<completion notes>')
          - IMPORTANT: If the task is already complete but unverified, calling todo-complete_task() will automatically mark it as verified - no special handling needed!
          - If you cannot complete it, call todo-unlock_task(task_id=<id>, agent_id='$AGENT_ID') - THIS IS MANDATORY
          - Report success or failure
        
        CRITICAL RULES:
        - ALWAYS use 'timeout' command for ALL operations to prevent hangs:
          * Git operations: 'timeout 60 git status', 'timeout 60 git diff', 'timeout 300 git commit', 'timeout 300 git push'
          * Test runs: 'timeout 300 pytest tests/file.py::test' for single tests, 'timeout 1800 ./run_checks.sh' for full suite
          * MCP tool calls should complete quickly (under 30s) - if they hang, kill the process
        - If any operation times out, investigate the root cause (usually hanging test, network issue, or database lock)
        - Always check for your existing in-progress tasks BEFORE picking up new ones
        - Always check git status and previous updates before starting work (with timeouts!)
        - Always call either todo-complete_task() or todo-unlock_task() when done - never leave a task in_progress
        - Verification is transparent: if a task is complete but unverified, just complete it normally - the backend handles verification automatically
        - If you encounter any error that prevents completion, call todo-unlock_task() before exiting
        - Continue existing work rather than starting fresh
        - DO NOT create scripts or make HTTP requests - use the MCP tools directly!
        - If processes hang, kill them: 'pkill -9 -f process-name'"
    
    # Run agent with strict timeout to prevent hangs
    log "Running agent for task work (timeout: ${AGENT_TIMEOUT}s)..."
    if timeout "$AGENT_TIMEOUT" cursor-agent agent \
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
        if [ $EXIT_CODE -eq 124 ]; then
            log_error "❌ Agent TIMED OUT after ${AGENT_TIMEOUT}s during task work"
            log_error "❌ This may indicate the agent got stuck. Killing any remaining processes..."
            pkill -9 -f "cursor-agent.*agent.*-p" 2>/dev/null || true
            # Continue loop - don't exit on timeout, allow retry
        else
            log_error "cursor-agent returned non-zero exit code: $EXIT_CODE"
        fi
        
        # If we had a task reserved, try to unlock it
        if [ -n "$TASK_ID" ]; then
            unlock_task "$TASK_ID"
        fi
        
        # Don't exit on error - continue loop to allow retry
        log_warning "Will retry on next iteration..."
        sleep "$SLEEP_INTERVAL"
    fi
done

log "Agent loop finished. Completed ${LOOP_COUNT} iteration(s)."

