# Agent Guidelines for TODO MCP Service

## Core Principles

### Test-First Development (TDD)
**All agents MUST follow test-first behavior:**

1. **Write tests BEFORE implementing features**
   - Define test cases that describe expected behavior
   - Tests should initially fail (red phase)
   - Implement minimal code to make tests pass (green phase)
   - Refactor while keeping tests green

2. **Run tests before any commit**
   - Always run `./run_checks.sh` before committing
   - Never commit code that breaks existing tests
   - Ensure all new tests pass before pushing

3. **Test Coverage Requirements**
   - All database operations must have tests
   - All API endpoints must have tests
   - Backup/restore functionality must be tested
   - MCP API functions must be tested

## Agent Identification

**All agents MUST provide an `agent_id` when calling MCP functions that require it.**

### Agent ID Rules:

1. **If an agent-id is explicitly specified** (e.g., via environment variable `CURSOR_AGENT_ID`), use that value.

2. **If an agent-id is NOT specified**, use `agent-unset` as the default agent-id.

3. **When calling MCP functions**, always provide the `agent_id` parameter:
   ```python
   # Example: If CURSOR_AGENT_ID is set, use it; otherwise use "agent-unset"
   agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
   
   # Use in MCP calls
   mcp_todo_reserve_task(task_id=123, agent_id=agent_id)
   mcp_todo_add_task_update(task_id=123, agent_id=agent_id, content="...", update_type="progress")
   mcp_todo_complete_task(task_id=123, agent_id=agent_id, notes="...")
   ```

4. **Why this matters:**
   - Agent IDs distinguish who performed what actions in the system
   - Logs and task history track actions by agent
   - This enables debugging, performance tracking, and accountability
   - Using `agent-unset` as default ensures actions are still tracked even when agent-id isn't explicitly configured

## Development Workflow

## When starting a task
1. Consider how much work the task is.  If it is a lot of work, creating subtasks
2. If a task seems critical in its functionality proactively add tasks to deeply very / test what was implemented
3. If there is something outside of the scope of work that should be cleaned up create a task to specifically clean that up

### Before Starting Work
1. Read the task description and acceptance criteria
2. Review existing tests related to the feature
3. Write failing tests for the new functionality
4. Ensure tests are comprehensive and cover edge cases

### During Development
1. Run tests frequently: `./run_checks.sh`
2. Fix failing tests immediately
3. Add tests for bugs as you discover them
4. Refactor with confidence (tests protect you)

### Before Committing
**MANDATORY**: 
1. Run `./run_checks.sh` - All tests must pass
   - No linting errors
   - Code coverage maintained or improved
   - Documentation updated if needed

2. **Write meaningful commit messages**
   - Commit messages MUST clearly describe what changed and why
   - Format: Use imperative mood (e.g., "Add feature X" not "Added feature X")
   - Include context: What problem does this solve? What functionality is added/changed?
   - Examples of good commit messages:
     ```
     Add stale task detection to reserve_task() and get_task_context()
     
     Implements stale warning system that detects when tasks were previously
     abandoned. When reserve_task() is called for a stale task, it includes
     stale_warning field with previous agent info and verification reminder.
     get_task_context() also surfaces stale_info prominently.
     
     This addresses the requirement that agents must verify work before
     continuing on previously abandoned tasks.
     ```
     
     ```
     Fix MCP POST endpoint to handle tools/call requests correctly
     
     Updates /mcp/sse POST endpoint to properly route tools/call requests
     to appropriate MCP functions. Handles JSON-RPC error responses and
     validates tool parameters before execution.
     ```
   - Examples of bad commit messages:
     ```
     ❌ "fix"
     ❌ "update"
     ❌ "changes"
     ❌ "wip"
     ❌ "commit"
     ```
   - For multi-part changes, use detailed messages explaining each component

### Before Pushing
**MANDATORY**: 
1. Run `./run_checks.sh` - Verify all tests pass
   - Check that the service starts correctly
   - Ensure database migrations work
   - Verify backup/restore functionality

2. **Verify commit messages are meaningful**
   - Review your commit history: `git log --oneline -5`
   - Ensure each commit has a clear, descriptive message
   - If you have commits with poor messages, use `git commit --amend` or `git rebase -i` to fix them before pushing
   - Never push commits with meaningless messages like "fix", "update", "wip"

3. **Rebase repeated check-ins into feature-based commits**
   - **MANDATORY**: Before pushing, review your local commit history
   - If you have multiple small commits that are part of one feature/fix, rebase them together
   - Use `git rebase -i HEAD~N` where N is the number of commits to review
   - Squash related commits into logical, feature-based commits
   - Example workflow:
     ```bash
     # Check your recent commits
     git log --oneline -10
     
     # If you have commits like:
     # abc123 "Add function to detect stale tasks"
     # def456 "Fix typo in stale detection"
     # ghi789 "Add tests for stale detection"
     # jkl012 "Update documentation for stale detection"
     
     # These should be rebased into one feature commit:
     git rebase -i HEAD~4
     # In the editor, change "pick" to "squash" for commits 2-4
     # Write a comprehensive commit message describing the feature
     
     # Final result: One commit "Implement stale task detection"
     ```
   - **Why**: Keeps git history clean, makes code reviews easier, groups related changes together
   - **When to rebase**: 
     - Multiple commits implementing one feature
     - Multiple commits fixing one bug
     - WIP commits that should be combined
     - Typo fixes that belong with the original feature commit
   - **When NOT to rebase**:
     - Commits that are already pushed to remote (unless working on feature branch)
     - Unrelated changes that should remain separate

4. **🚨 MANDATORY: Push changes to remote**
   - **After completing work and committing changes, you MUST push to origin**
   - Check if you have unpushed commits: `git status` (look for "ahead of 'origin/main'")
   - If you have unpushed commits, push them immediately:
     ```bash
     # Check what will be pushed
     git log origin/main..HEAD --oneline
     
     # Push all local commits to remote
     git push origin main
     # Or if on a different branch:
     git push origin <branch-name>
     ```
   - **Why this matters:**
     - Unpushed commits are only local - they can be lost if the machine crashes
     - Other agents/developers can't see your work until it's pushed
     - CI/CD pipelines won't run on unpushed commits
     - Collaboration requires shared repository state
   - **When to push:**
     - After completing a task and committing changes
     - After fixing bugs and committing fixes
     - After verification work that includes code changes
     - Before moving to a new task (if you have unpushed commits)
   - **Exception**: If you're working on a feature branch that shouldn't be pushed yet, document this in task updates
   - **CRITICAL: Always use timeouts for git push:**
     ```bash
     timeout 300 git push origin main  # 5 minutes max
     ```

## ⏱️ Timeout Requirements (CRITICAL)

**ALL agents MUST use timeouts for ALL operations to prevent hanging processes.**

### Why Timeouts Matter
- Hanging processes consume resources indefinitely
- They block the agent loop from continuing
- They can cause cascading failures
- They prevent proper task management

### Mandatory Timeout Rules

**1. Git Operations:**
```bash
# ALWAYS use timeouts for git operations
timeout 60 git status          # 1 minute max
timeout 60 git diff            # 1 minute max
timeout 60 git add -A          # 1 minute max
timeout 300 git commit         # 5 minutes max
timeout 300 git push           # 5 minutes max
```

**2. Test Operations:**
```bash
# ALWAYS use timeouts for test runs
timeout 300 pytest tests/file.py::test_name -v     # 5 minutes max for single test
timeout 1800 ./run_checks.sh                        # 30 minutes max for full suite
```

**3. MCP Tool Calls:**
- MCP tool calls should complete quickly (under 30 seconds)
- If an MCP call hangs longer than 30 seconds, kill the process and investigate
- Common causes: database locks, network issues, infinite loops

**4. Agent Execution:**
- The agent loop script enforces a 1-hour timeout for agent execution
- If the agent times out, it will be killed and retried on the next iteration

### What to Do When Timeouts Occur

1. **Investigate the root cause:**
   - Check for hanging tests (infinite loops, network waits)
   - Check for database locks (multiple processes accessing same DB)
   - Check for network issues (can't reach remote services)

2. **Fix the underlying issue:**
   - Fix hanging tests (add proper cleanup, use mocks for network calls)
   - Fix database lock issues (use transactions, proper connection handling)
   - Fix network issues (add retries, connection timeouts)

3. **Kill hung processes:**
   ```bash
   # Find hung processes
   ps aux | grep -E "pytest|cursor-agent|git"
   
   # Kill specific process
   kill -9 <PID>
   
   # Kill by pattern
   pkill -9 -f "pytest.*test_mcp_api"
   ```

4. **Retry the operation:**
   - After fixing the issue, retry the operation
   - Monitor for timeout issues
   - Document any recurring timeout problems

### Timeout Configuration

The agent loop script uses these default timeouts (configurable via environment variables):
- `AGENT_TIMEOUT=3600` (1 hour) - Maximum time for agent execution
- `GIT_TIMEOUT=300` (5 minutes) - Maximum time for git operations
- `TEST_TIMEOUT=1800` (30 minutes) - Maximum time for test suite
- `MCP_TIMEOUT=30` (30 seconds) - Maximum time for MCP tool calls

### Examples of Timeout Usage

```bash
# ✅ CORRECT: Using timeout for test run
timeout 300 pytest tests/test_database.py::test_create_task -v

# ❌ WRONG: No timeout - can hang indefinitely
pytest tests/test_database.py::test_create_task -v

# ✅ CORRECT: Using timeout for git operations
timeout 300 git commit -m "Fix timeout issues in test suite"

# ❌ WRONG: No timeout - can hang if pre-commit hook hangs
git commit -m "Fix timeout issues in test suite"

# ✅ CORRECT: Using timeout for full test suite
timeout 1800 ./run_checks.sh

# ❌ WRONG: No timeout - can hang if any test hangs
./run_checks.sh
```

### Critical Rules

1. **NEVER run operations without timeouts** - Always use the `timeout` command
2. **If an operation times out, investigate immediately** - Don't ignore timeout errors
3. **Kill hung processes before retrying** - Don't let them accumulate
4. **Document timeout issues** - Add task updates explaining what timed out and why
5. **Fix root causes** - Don't just increase timeouts, fix the underlying issue

## Test Structure

### Test Files
- `tests/test_database.py` - Database operations and schema
- `tests/test_backup.py` - Backup and restore functionality
- `tests/test_api.py` - REST API endpoints
- `tests/test_mcp_api.py` - MCP API functions

### Running Tests
```bash
# Run all tests
./run_checks.sh

# Run specific test file
python3 -m pytest tests/test_database.py -v

# Run with coverage
python3 -m pytest --cov=src tests/
```

## Code Quality Standards

1. **Test Coverage**: Maintain at least 80% code coverage
2. **Type Hints**: Use Python type hints throughout
3. **Documentation**: Docstrings for all public functions
4. **Error Handling**: Comprehensive error handling with tests
5. **Database**: Always use transactions, test rollback scenarios
6. **Logging**: Use logging module, never print() statements

## Logging Standards (CRITICAL)

**MANDATORY:** All agents MUST use proper logging instead of print statements.

### Core Rules
1. **NEVER use print() for application output**
   - Use `logging` module for all output
   - Print statements should only appear in tests or one-off scripts
   - Print statements are not captured by log aggregation systems

2. **Set up logging in entrypoints**
   - Configure logging at application startup
   - Use appropriate log levels
   - Include context in log messages

### Logging Setup in Entrypoints

**Example for main.py (FastAPI/Flask):**
```python
import logging
import os
from logging.handlers import RotatingFileHandler

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Create logger for this module
logger = logging.getLogger(__name__)

# Optional: Add file handler for production
if os.getenv("LOG_FILE"):
    file_handler = RotatingFileHandler(
        os.getenv("LOG_FILE"),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    logging.getLogger().addHandler(file_handler)

logger.info("Application starting...")
```

**Example for service modules:**
```python
import logging

# Get logger for this module (not __main__)
logger = logging.getLogger(__name__)

# Use appropriate log levels
logger.debug("Detailed debugging information")
logger.info("General informational message")
logger.warning("Warning message for potential issues")
logger.error("Error occurred but application continues")
logger.critical("Critical error, application may stop")
```

### Log Levels
- **DEBUG**: Detailed information for diagnosing problems
- **INFO**: General informational messages (startup, normal operations)
- **WARNING**: Warning messages for unusual but non-error situations
- **ERROR**: Error messages for failures that don't stop the application
- **CRITICAL**: Critical errors that may cause the application to stop

### Best Practices
1. **Use structured logging**: Include context in log messages
   ```python
   # Bad
   logger.info("Task created")
   
   # Good
   logger.info("Task created", extra={"task_id": task_id, "agent_id": agent_id})
   ```

2. **Log at appropriate levels**
   - Use DEBUG for detailed flow information
   - Use INFO for important state changes
   - Use WARNING for recoverable errors
   - Use ERROR for failures
   - Use CRITICAL sparingly

3. **Include exception information**
   ```python
   try:
       risky_operation()
   except Exception as e:
       logger.error("Operation failed", exc_info=True)
       # or
       logger.exception("Operation failed")  # Automatically includes exception
   ```

4. **Log entry and exit of functions** (when debugging)
   ```python
   def important_function():
       logger.debug("Entering important_function")
       try:
           result = do_work()
           logger.debug("Exiting important_function successfully")
           return result
       except Exception as e:
           logger.error("important_function failed", exc_info=True)
           raise
   ```

5. **Avoid logging sensitive data**
   - Never log passwords, tokens, or secrets
   - Redact or mask sensitive information

### Environment-Based Logging
Configure log level via environment variable:
```python
import os
import logging

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL))
```

Set in docker-compose.yml:
```yaml
environment:
  - LOG_LEVEL=${LOG_LEVEL:-INFO}
```

### Common Mistakes to Avoid
1. ❌ Using print() for application output
2. ❌ Not setting up logging in entrypoints
3. ❌ Using logger.info() for debug information
4. ❌ Logging without context
5. ❌ Logging sensitive information
6. ❌ Creating new logger instances instead of using `getLogger(__name__)`

## TODO Service Integration (CRITICAL)

**Agents MUST use the TODO service via MCP (Model Context Protocol) tools directly. These tools are already available through Cursor's MCP integration. DO NOT create scripts, make HTTP requests, or write wrapper functions.**

The TODO service exposes MCP tools that are automatically available to you. Use them directly:
- `mcp_todo_list_available_tasks` - NOT `list_available_tasks()` or HTTP requests
- `mcp_todo_reserve_task` - NOT `reserve_task()` or HTTP requests
- `mcp_todo_complete_task` - NOT `complete_task()` or HTTP requests
- `mcp_todo_add_task_update` - NOT `add_task_update()` or HTTP requests
- `mcp_todo_get_task_context` - NOT `get_task_context()` or HTTP requests
- `mcp_todo_unlock_task` - NOT `unlock_task()` or HTTP requests
- `mcp_todo_query_tasks` - NOT `query_tasks()` or HTTP requests
- `mcp_todo_create_task` - NOT `create_task()` or HTTP requests
- `mcp_todo_get_agent_performance` - NOT `get_agent_performance()` or HTTP requests

**CRITICAL: DO NOT:**
- ❌ Create Python scripts (`work_on_task*.py`, etc.)
- ❌ Make HTTP requests to `/mcp/*` endpoints using `requests` library
- ❌ Import `requests` or write wrapper functions around MCP calls
- ❌ Create helper scripts to "call MCP functions"
- ❌ Use the service code directly (import `mcp_api`, `database`, etc.)

**Why use MCP tools directly:**
1. **Already Available**: The tools are integrated and ready to use - no setup needed
2. **Consistency**: All agents interact with tasks in a standardized way
3. **Context**: MCP tools automatically provide full context (project, ancestry, updates)
4. **Tracking**: All actions are properly logged with agent identity
5. **Simplicity**: No need to write HTTP client code or manage API endpoints
6. **Integration**: Works seamlessly with Cursor's MCP integration

### Available MCP Tools (Use These Directly)

1. **`mcp_todo_list_available_tasks`** - Get available tasks for your agent type
   - Parameters: `agent_type` (breakdown/implementation), `project_id` (optional), `limit`
   - Returns: List of available tasks

2. **`mcp_todo_reserve_task`** - Lock and reserve a task (automatically returns full context)
   - Parameters: `task_id`, `agent_id`
   - Returns: Full context including project, ancestry, updates, recent changes

3. **`mcp_todo_add_task_update`** - Add progress updates, findings, blockers, or questions
   - Parameters: `task_id`, `agent_id`, `content`, `update_type` (progress/note/blocker/question/finding), `metadata` (optional)
   - Returns: Update ID and success status

4. **`mcp_todo_get_task_context`** - Get full context for a task (project, ancestry, updates)
   - Parameters: `task_id`
   - Returns: Full task context

5. **`mcp_todo_complete_task`** - Mark task complete and optionally create followups
   - Parameters: `task_id`, `agent_id`, `notes` (optional), followup fields (optional)
   - Returns: Completion status and optional followup task ID

6. **`mcp_todo_create_task`** - Create new tasks with automatic relationship linking
   - Parameters: `title`, `task_type`, `task_instruction`, `verification_instruction`, `agent_id`, `project_id` (optional), `parent_task_id` (optional), `relationship_type` (optional), `notes` (optional)
   - Returns: Created task ID and optional relationship ID

7. **`mcp_todo_unlock_task`** - Release a reserved task if unable to complete
   - Parameters: `task_id`, `agent_id`
   - Returns: Unlock status

8. **`mcp_todo_query_tasks`** - Query tasks by various criteria
   - Parameters: `project_id`, `task_type`, `task_status`, `agent_id` (all optional), `limit`
   - Returns: List of matching tasks

9. **`mcp_todo_get_agent_performance`** - Get your performance statistics
   - Parameters: `agent_id`, `task_type` (optional)
   - Returns: Performance statistics

### Recommended Workflow

**⚠️ IMPORTANT: Always wrap your workflow in try/except blocks to ensure mandatory completion/unlock. See the "CRITICAL: Task Completion is MANDATORY" section above for full examples.**

1. **Start working on a task (use MCP tools directly):**
   ```python
   import os
   agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
   
   task_id = None
   try:
       # Use mcp_todo_list_available_tasks - it's already available as a tool
       tasks = mcp_todo_list_available_tasks(agent_type="implementation", project_id=1)
       # Use mcp_todo_reserve_task - it's already available as a tool
       task = mcp_todo_reserve_task(task_id=123, agent_id=agent_id)
       task_id = 123
   except Exception as e:
       logger.error(f"Failed to reserve task: {e}")
       raise
   ```

2. **While working (use MCP tools directly):**
   ```python
   # Use mcp_todo_add_task_update - it's already available as a tool
   mcp_todo_add_task_update(task_id=task_id, agent_id=agent_id, content="Making progress...", update_type="progress")
   mcp_todo_add_task_update(task_id=task_id, agent_id=agent_id, content="Found an issue", update_type="blocker")
   ```

3. **Get context when needed (use MCP tools directly):**
   ```python
   # Use mcp_todo_get_task_context - it's already available as a tool
   context = mcp_todo_get_task_context(task_id=task_id)  # Returns project, ancestry, all updates
   ```

4. **🚨 MANDATORY: Complete the task when done (use MCP tools directly):**
   ```python
   # Use mcp_todo_complete_task - it's already available as a tool
   mcp_todo_complete_task(task_id=task_id, agent_id=agent_id, notes="Completed successfully")
   ```

5. **🚨 MANDATORY: Push changes after completing work:**
   - After completing a task, check if you have unpushed commits: `git status`
   - If you have unpushed commits, push them immediately: `git push origin main`
   - This ensures your work is backed up and available to other agents/developers
   - See "Before Pushing" section for detailed push requirements

6. **🚨 MANDATORY: If unable to complete, unlock immediately (use MCP tools directly):**
   ```python
   # Use mcp_todo_unlock_task - it's already available as a tool
   mcp_todo_unlock_task(task_id=task_id, agent_id=agent_id)
   ```

**REMINDER: These are MCP tools that Cursor exposes automatically. You don't need to import anything or create scripts - just call them directly like any other tool.**

**Remember: Steps 4 or 5 are MANDATORY - one of them MUST be called when you're done working on the task.**

## 🔄 Resuming and Continuing Tasks (CRITICAL)

**Agents MUST check for previous work and continue existing tasks before starting new ones.**

### Priority: Continue Your In-Progress Tasks First

**Before picking up a new task, ALWAYS check if you already have tasks in progress:**

```python
# 1. First, check for tasks already assigned to you
my_tasks = query_tasks(
    agent_id=agent_id,
    task_status="in_progress",
    limit=10
)

if my_tasks:
    # You have existing work - continue it first!
    logger.info(f"Found {len(my_tasks)} task(s) already in progress")
    for task in my_tasks:
        logger.info(f"  - Task {task['id']}: {task['title']}")
    
    # Continue the first in-progress task
    task_id = my_tasks[0]['id']
    context = get_task_context(task_id=task_id)
else:
    # No existing tasks, can pick up a new one
    tasks = list_available_tasks(agent_type="implementation", project_id=1)
    if tasks:
        task_id = tasks[0]['id']
        context = reserve_task(task_id=task_id, agent_id=agent_id)
```

### The Problem

Agents currently pick up new tasks without checking if they already have work in progress, leading to:
- ❌ Duplicate work (re-doing what another agent already completed)
- ❌ Ignoring previous progress and updates
- ❌ Missing uncommitted changes in git
- ❌ Not resuming where previous agent left off
- ❌ No documentation of progress

### Mandatory Workflow: Check Previous Work

**When you pick up a task (new or existing), you MUST:**

1. **Check for Previous Context:**
   ```python
   # Immediately after reserving, get full context
   context = get_task_context(task_id=task_id)
   
   # Check for:
   # - Previous updates (context["updates"])
   # - Recent changes (context["recent_changes"])
   # - Stale warnings (context.get("stale_warning"))
   # - Parent tasks and relationships (context["ancestry"])
   # - Project information (context["project"])
   ```

2. **Check Git Status for Uncommitted Work:**
   ```python
   # ALWAYS check git status before starting
   import subprocess
   
   # Check for uncommitted changes in the project directory
   project_path = context["project"]["local_path"]
   git_status = subprocess.run(
       ["git", "status", "--short"],
       cwd=project_path,
       capture_output=True,
       text=True
   ).stdout
   
   if git_status.strip():
       # There are uncommitted changes - review them first!
       # They might be work from a previous agent session
       logger.info(f"Found uncommitted changes:\n{git_status}")
       
       # Show the diff to understand what was done
       git_diff = subprocess.run(
           ["git", "diff"],
           cwd=project_path,
           capture_output=True,
           text=True
       ).stdout
       
       # Review the changes and determine if work should continue
   ```

3. **Review Previous Updates:**
   ```python
   # Check what the previous agent(s) documented
   updates = context.get("updates", [])
   
   for update in updates:
       logger.info(f"Previous update [{update['update_type']}]: {update['content']}")
       # Understand what was tried, what worked, what failed
       
   # If there are blockers, address them
   blockers = [u for u in updates if u["update_type"] == "blocker"]
   if blockers:
       logger.warning(f"Found {len(blockers)} blocker(s) from previous work")
       # Address blockers before continuing
   ```

4. **Check for Stale Task Warnings:**
   ```python
   # If task was previously abandoned, you MUST verify work
   stale_warning = context.get("stale_warning")
   if stale_warning:
       logger.warning(f"⚠️ STALE TASK WARNING: {stale_warning['message']}")
       logger.warning(f"Previous agent: {stale_warning['previous_agent']}")
       logger.warning(f"Previously unlocked at: {stale_warning['unlocked_at']}")
       
       # MANDATORY: Verify all previous work before continuing
       # - Check if any code changes are correct
       # - Verify if tests pass
       # - Confirm no regressions
       # - Document your verification in an update
       
       add_task_update(
           task_id=task_id,
           agent_id=agent_id,
           content=f"Verifying previous work by {stale_warning['previous_agent']}. Checking git status, reviewing changes, running tests.",
           update_type="progress"
       )
   ```

5. **Resume Where Previous Work Left Off:**
   ```python
   # Based on updates and git status, determine:
   # - What was already implemented
   # - What still needs to be done
   # - What tests already pass
   # - What needs to be fixed or completed
   
   # Create a plan that builds on previous work
   # Don't start from scratch - continue the work
   
   add_task_update(
       task_id=task_id,
       agent_id=agent_id,
       content="Resuming work. Reviewed previous updates and git status. Previous agent made progress on X, Y. Will continue with Z.",
       update_type="progress"
   )
   ```

6. **Document Your Progress Continuously:**
   ```python
   # As you work, add updates frequently:
   add_task_update(
       task_id=task_id,
       agent_id=agent_id,
       content="Completed step 1: Implemented X function with tests",
       update_type="progress"
   )
   
   add_task_update(
       task_id=task_id,
       agent_id=agent_id,
       content="Found issue with Y - needs refactoring. Creating followup task.",
       update_type="finding"
   )
   
   # This helps the next agent understand what happened
   ```

### Complete Workflow Example: Continuing Existing or Starting New

```python
import os
agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
task_id = None

try:
    # 1. FIRST: Check for tasks already assigned to you
    my_tasks = query_tasks(
        agent_id=agent_id,
        task_status="in_progress",
        limit=10
    )
    
    if my_tasks:
        # Continue existing work first
        logger.info(f"Found {len(my_tasks)} task(s) already in progress - continuing work")
        task_id = my_tasks[0]['id']
        context = get_task_context(task_id=task_id)
        logger.info(f"Continuing task {task_id}: {context['task']['title']}")
    else:
        # No existing work, pick up a new task
        logger.info("No tasks in progress, picking up new task")
        tasks = list_available_tasks(agent_type="implementation", project_id=1, limit=1)
        if not tasks:
            logger.info("No available tasks")
            return
        
        task_id = tasks[0]['id']
        result = reserve_task(task_id=task_id, agent_id=agent_id)
        context = result  # reserve_task returns full context
    
    # 2. CHECK FOR STALE WARNING (MANDATORY)
    stale_warning = context.get("stale_warning")
    if stale_warning:
        logger.warning(f"⚠️ Picking up stale task: {stale_warning['message']}")
        add_task_update(
            task_id=task_id,
            agent_id=agent_id,
            content=f"Resuming stale task. Verifying previous work by {stale_warning['previous_agent']}.",
            update_type="progress"
        )
    
    # 3. REVIEW PREVIOUS UPDATES (MANDATORY)
    updates = context.get("updates", [])
    logger.info(f"Found {len(updates)} previous update(s)")
    for update in updates:
        logger.info(f"  - [{update['update_type']}] {update['content']}")
    
    # 4. CHECK GIT STATUS (MANDATORY)
    project_path = context["project"]["local_path"]
    git_status = subprocess.run(
        ["git", "status", "--short"],
        cwd=project_path,
        capture_output=True,
        text=True
    ).stdout
    
    if git_status.strip():
        logger.info(f"Found uncommitted changes:\n{git_status}")
        
        # Review the diff
        git_diff = subprocess.run(
            ["git", "diff"],
            cwd=project_path,
            capture_output=True,
            text=True
        ).stdout
        
        logger.info(f"Reviewing changes:\n{git_diff[:500]}...")  # First 500 chars
        
        # Document that you're reviewing previous work
        add_task_update(
            task_id=task_id,
            agent_id=agent_id,
            content="Found uncommitted changes from previous work. Reviewing diff to understand progress.",
            update_type="progress"
        )
    
    # 5. CHECK RECENT CHANGES (MANDATORY)
    recent_changes = context.get("recent_changes", [])
    logger.info(f"Recent changes: {len(recent_changes)}")
    for change in recent_changes[-5:]:  # Last 5 changes
        logger.info(f"  - {change['change_type']}: {change.get('field_name', 'N/A')}")
    
    # 6. DETERMINE WHERE TO RESUME (MANDATORY)
    # Based on updates, git status, and recent changes:
    # - What was already done?
    # - What still needs to be done?
    # - What should be tested?
    
    add_task_update(
        task_id=task_id,
        agent_id=agent_id,
        content="Completed context review. Resuming work based on previous progress. Plan: [your plan here]",
        update_type="progress"
    )
    
    # 7. DO THE WORK (resuming from where previous agent left off)
    # ... your implementation ...
    
    # 8. DOCUMENT PROGRESS AS YOU WORK
    add_task_update(
        task_id=task_id,
        agent_id=agent_id,
        content="Completed implementation of X. Running tests...",
        update_type="progress"
    )
    
    # 9. COMPLETE THE TASK
    complete_task(
        task_id=task_id,
        agent_id=agent_id,
        notes="Completed successfully. Built on previous work: [summary of what was done]"
    )
    
    # 10. PUSH CHANGES (MANDATORY)
    # Check for unpushed commits and push them
    git_status = subprocess.run(["git", "status"], capture_output=True, text=True)
    if "ahead of" in git_status.stdout:
        subprocess.run(["git", "push", "origin", "main"])
        logger.info("Pushed local commits to remote")
    
except Exception as e:
    logger.error(f"Failed to complete task {task_id}: {e}", exc_info=True)
    
    # Always unlock on error
    if task_id:
        try:
            unlock_task(task_id=task_id, agent_id=agent_id)
            add_task_update(
                task_id=task_id,
                agent_id=agent_id,
                content=f"Unlocking task due to error: {str(e)}",
                update_type="blocker"
            )
        except Exception as unlock_error:
            logger.error(f"Failed to unlock task {task_id}: {unlock_error}", exc_info=True)
    
    raise
```

### Benefits of Continuing Existing Tasks

- ✅ **No duplicate work** - Agents build on previous progress
- ✅ **Better continuity** - Work continues seamlessly across agent sessions
- ✅ **Documented progress** - Updates show what was done and why
- ✅ **Faster completion** - Don't re-do what's already done
- ✅ **Better debugging** - Clear history of attempts and issues
- ✅ **Resource efficiency** - Don't waste time on completed work

### Common Mistakes to Avoid

- ❌ Starting work without checking `get_task_context()`
- ❌ Ignoring `stale_warning` - you MUST verify previous work
- ❌ Not checking git status - uncommitted changes might be previous work
- ❌ Not reading previous updates - you might repeat failed attempts
- ❌ Starting from scratch when work was already done
- ❌ Not documenting progress - next agent won't know what happened
- ❌ Not checking for blockers - you might hit the same issues

**This is CRITICAL for maintaining work continuity and preventing duplicate effort.**

## ⚠️ CRITICAL: Task Completion is MANDATORY ⚠️

**🚨 SYSTEM CRITICAL REQUIREMENT 🚨**

Task completion/unlocking is **NOT OPTIONAL** - it is **MANDATORY** for system operation. Failure to complete or unlock tasks blocks other agents and degrades system performance.

### Mandatory Requirements

1. **You MUST call `complete_task()` when finished** OR **`unlock_task()` if you cannot complete**
   - There is no exception to this rule
   - Every reserved task must be either completed or unlocked
   - No task should remain in `in_progress` status when you're done

2. **Tasks left in_progress will block other agents**
   - Only one agent can work on a task at a time
   - If you leave a task in_progress, no other agent can pick it up
   - This creates bottlenecks and prevents work from progressing

3. **Always use try/except/finally blocks to ensure unlock on errors**
   - **MANDATORY**: Wrap task work in proper error handling
   - Use `finally` blocks to guarantee unlock even if exceptions occur
   - Never rely on exceptions propagating without cleanup

4. **Example error handling that ensures unlock on failure:**
   ```python
   import os
   agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
   task_id = None
   
   try:
       # Reserve the task
       result = reserve_task(task_id=123, agent_id=agent_id)
       task_id = 123
       
       # Work on the task...
       do_work()
       
       # If successful, complete it
       complete_task(task_id=task_id, agent_id=agent_id, notes="Completed successfully")
       
   except Exception as e:
       # Log the error for debugging
       logger.error(f"Failed to complete task {task_id}: {e}", exc_info=True)
       
       # ALWAYS unlock on error - this is MANDATORY
       if task_id:
           try:
               unlock_task(task_id=task_id, agent_id=agent_id)
           except Exception as unlock_error:
               logger.error(f"Failed to unlock task {task_id}: {unlock_error}", exc_info=True)
       
       # Re-raise the original exception
       raise
   ```

5. **Alternative pattern using context manager (recommended):**
   ```python
   def work_on_task(task_id: int, agent_id: str):
       """Context manager pattern ensures automatic unlock."""
       try:
           reserve_task(task_id=task_id, agent_id=agent_id)
           yield  # Allow work to happen here
           complete_task(task_id=task_id, agent_id=agent_id)
       except Exception:
           unlock_task(task_id=task_id, agent_id=agent_id)
           raise
   
   # Usage:
   import os
   agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
   with work_on_task(task_id=123, agent_id=agent_id):
       do_work()  # Automatic unlock if exception occurs
   ```

6. **Document the workflow: try/except blocks that guarantee unlock:**
   - **Every agent MUST follow this pattern when working on tasks:**
     ```python
     import os
     agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
     
     # 1. Reserve task
     task = reserve_task(task_id=123, agent_id=agent_id)
     
     # 2. Wrap ALL work in try/except/finally
     try:
         # All your task work here
         process_task()
         
         # 3. Complete if successful
         complete_task(task_id=123, agent_id=agent_id, notes="Done")
         
     except Exception as e:
         # 4. ALWAYS unlock on any error
         unlock_task(task_id=123, agent_id=agent_id)
         raise  # Re-raise to maintain error visibility
     
     # Note: You can also use finally block:
     # finally:
     #     if not completed:
     #         unlock_task(task_id=123, agent_id=agent_id)
     ```

### Task Cleanup and Stale Task Prevention

**Automatic Timeout System:**
- Tasks left in_progress for longer than the configured timeout will be automatically unlocked
- The default timeout is 24 hours, configurable via `TASK_TIMEOUT_HOURS` environment variable
- **This is a safety net, NOT an excuse to skip manual completion/unlock**

**Stale Task Prevention Best Practices:**
1. **Complete tasks as soon as work is finished** - don't delay
2. **Unlock immediately if you cannot complete** - don't wait for timeout
3. **Use monitoring tools** to check for stale tasks in your queue
4. **Set appropriate timeouts** based on expected task duration
5. **Always verify previous work** if picking up a stale task (check `stale_warning` in task context)

**Failing to complete/unlock tasks:**
- ❌ Degrades system performance
- ❌ Blocks other agents from working
- ❌ Creates resource contention
- ❌ Violates system operational requirements

**This is a CRITICAL system requirement - there are no exceptions.**

### DO NOT:
- ❌ Make direct HTTP requests to the TODO service API
- ❌ Write Python code using `requests` library to interact with the service
- ❌ Bypass the MCP interface
- ❌ Hardcode API endpoints or URLs

### DO:
- ✅ Use the MCP functions exposed through your agent framework
- ✅ Add updates as you work (`add_task_update`)
- ✅ Reserve tasks before working (`reserve_task`)
- ✅ **🚨 ALWAYS complete tasks when done** (`complete_task`) - **THIS IS MANDATORY, NOT OPTIONAL**
- ✅ **🚨 ALWAYS unlock tasks if unable to complete** (`unlock_task`) - **THIS IS MANDATORY, NOT OPTIONAL**
- ✅ **Use try/except/finally blocks to guarantee unlock on errors** - See section above for examples
- ✅ Query tasks when needed (`query_tasks`, `get_task_context`)
- ✅ Query stale tasks using `query_stale_tasks()` to monitor system health
- ✅ **Verify task completion/unlock happened successfully** - check return values from complete_task/unlock_task
- ✅ **Complete or unlock immediately when done** - don't wait, don't delay, don't forget

### Example Integration

If your agent framework supports MCP:
```python
# Good - using MCP with mandatory error handling
import os
agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
task_id = 123

try:
    # Reserve the task
    task = mcp.call("reserve_task", {"task_id": task_id, "agent_id": agent_id})
    context = task["context"]
    
    # Work with task...
    mcp.call("add_task_update", {
        "task_id": task_id, 
        "agent_id": agent_id, 
        "content": "Progress update", 
        "update_type": "progress"
    })
    
    # Do the actual work
    process_task(context)
    
    # MANDATORY: Complete when done
    mcp.call("complete_task", {"task_id": task_id, "agent_id": agent_id, "notes": "Completed"})
    
except Exception as e:
    # MANDATORY: Unlock on any error
    try:
        mcp.call("unlock_task", {"task_id": task_id, "agent_id": agent_id})
    except Exception:
        pass  # Log but don't fail on unlock errors
    raise  # Re-raise original exception
```

```python
# Bad - direct API calls (DON'T DO THIS)
import requests
import os
agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
response = requests.post("http://localhost:5080/mcp/reserve_task", json={"task_id": 123, "agent_id": agent_id})
# Don't do this - use MCP functions instead!
```

```python
# Bad - missing error handling (DON'T DO THIS)
import os
agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
task = mcp.call("reserve_task", {"task_id": 123, "agent_id": agent_id})
do_work()  # If this fails, task stays locked forever!
# Missing: complete_task or unlock_task
```

## Task Timeout and Stale Task Monitoring

The TODO service includes automatic timeout handling for tasks that remain in_progress too long:

### Configuration

- **Environment Variable**: `TASK_TIMEOUT_HOURS` (default: 24)
  - Sets how many hours a task can be in_progress before considered stale
  - Example: `TASK_TIMEOUT_HOURS=48` for 48-hour timeout

### Automatic Unlocking

Tasks that remain in_progress longer than the timeout are automatically unlocked:
- Task status changes from `in_progress` to `available`
- Assigned agent is cleared
- A "finding" update is added noting the automatic unlock
- Change history records the unlock event

### Monitoring Stale Tasks

1. **MCP Function**: `query_stale_tasks(hours=None)`
   - Returns list of currently stale tasks
   - Optional `hours` parameter overrides default timeout
   
2. **REST API Endpoint**: `GET /monitoring/stale-tasks?hours=24`
   - Returns JSON with stale tasks list and count
   
3. **Manual Unlock Endpoint**: `POST /tasks/{task_id}/unlock-stale`
   - Manually unlock a stale task (bypasses normal unlock restrictions)
   - Useful for administrative intervention

### Best Practices

- Monitor stale tasks regularly to identify systemic issues
- If a task becomes stale, the next agent should verify all previous work before continuing
- The stale warning system automatically detects and warns about previously abandoned tasks
- Use `query_stale_tasks()` in monitoring dashboards or health checks

## Proactive Task Management (ENCOURAGED)

**Agents are ENCOURAGED to be proactive in task management and identify opportunities for improvement.**

### Breaking Down Large Tasks

When working on a task, if you discover it's too large or complex:

1. **Break it down into subtasks:**
   - Use `create_task()` to create smaller, focused subtasks
   - Link them as `subtask` relationships to the parent task
   - Each subtask should be independently completable
   - Add clear `task_instruction` and `verification_instruction` for each subtask

2. **Example workflow:**
   ```python
   import os
   agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
   
   # While working on task 123, you realize it needs to be split:
   parent_task_id = 123
   
   # Create subtasks
   subtask1 = create_task(
       title="Implement authentication endpoint",
       task_type="concrete",
       task_instruction="Create POST /auth/login endpoint with JWT token generation",
       verification_instruction="Test endpoint with valid/invalid credentials, verify JWT token format",
       agent_id=agent_id,
       project_id=1,
       parent_task_id=parent_task_id,
       relationship_type="subtask"
   )
   
   subtask2 = create_task(
       title="Add authentication middleware",
       task_type="concrete",
       task_instruction="Create middleware to validate JWT tokens on protected routes",
       verification_instruction="Test middleware rejects invalid tokens, accepts valid tokens",
       agent_id=agent_id,
       project_id=1,
       parent_task_id=parent_task_id,
       relationship_type="subtask"
   )
   ```

### Creating Tasks for Good Ideas

**If you notice something that would improve the codebase but is out of scope for your current task:**

1. **Create a task immediately** - Don't wait, don't forget
   - Use `create_task()` to capture the idea
   - Set appropriate `priority` (usually "medium" unless critical)
   - Add `notes` explaining why this would be beneficial
   - Link to current task with `relationship_type="related"` if relevant

2. **Common scenarios:**
   - **Performance improvements**: "Optimize database query in X function"
   - **Code quality**: "Refactor Y module to reduce complexity"
   - **User experience**: "Add better error messages for X endpoint"
   - **Documentation**: "Add API examples for Y feature"
   - **Testing**: "Add integration tests for Z functionality"
   - **Security**: "Review authentication in X module"

3. **Example:**
   ```python
   import os
   agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
   
   # While working on task 123, you notice a refactoring opportunity:
   create_task(
       title="Refactor database.py to use connection pooling",
       task_type="concrete",
       task_instruction="Replace direct SQLite connections with connection pool to improve performance under load. Current code creates new connection per query which is inefficient.",
       verification_instruction="Verify connection pooling reduces connection overhead, run performance tests comparing before/after",
       agent_id=agent_id,
       project_id=1,
       parent_task_id=123,  # Related to current work
       relationship_type="related",
       priority="medium",
       notes="Noticed while working on task 123. Current implementation creates many short-lived connections."
   )
   ```

### Creating Tasks for Refactoring

**When you identify code that needs refactoring but it's not part of your current task:**

1. **Create refactoring tasks with clear scope:**
   - Specify exactly what needs refactoring
   - Explain why (code smell, technical debt, performance, maintainability)
   - Estimate complexity with `estimated_hours`
   - Set priority based on impact

2. **Examples of refactoring to capture:**
   - Duplicated code that should be extracted
   - Complex functions that need simplification
   - Outdated patterns that should be modernized
   - Poor separation of concerns
   - Missing abstraction layers

3. **Example:**
   ```python
   import os
   agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
   
   # You notice duplicated validation logic:
   create_task(
       title="Extract common validation logic into shared module",
       task_type="concrete",
       task_instruction="Three endpoints (A, B, C) have identical validation logic. Extract to shared validation module to reduce duplication and ensure consistency.",
       verification_instruction="Verify all three endpoints use new validation module, no duplicated code remains, tests still pass",
       agent_id=agent_id,
       project_id=1,
       priority="medium",
       estimated_hours=2.0,
       notes="Found duplication while reviewing endpoint implementations. Affects: /api/users, /api/projects, /api/tasks"
   )
   ```

### Creating Tasks for Missing Tests

**When you notice test coverage gaps or tests that should exist but don't:**

1. **Create test tasks for out-of-scope areas:**
   - If current task doesn't include tests (e.g., refactoring existing code)
   - If you notice edge cases not covered by existing tests
   - If integration tests are missing for a feature
   - If test infrastructure improvements are needed

2. **Specify test requirements clearly:**
   - What should be tested (specific functions, endpoints, scenarios)
   - Why it matters (edge cases, critical paths, regression prevention)
   - Test type (unit, integration, performance, etc.)

3. **Example:**
   ```python
   import os
   agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")
   
   # You're refactoring code but notice missing tests:
   create_task(
       title="Add integration tests for MCP bulk operations",
       task_type="concrete",
       task_instruction="Add comprehensive integration tests for bulk_unlock_tasks, bulk_create_tasks, and other bulk MCP operations. Test partial failures, transaction rollback, and error handling.",
       verification_instruction="Verify all bulk operations have integration tests, edge cases covered, tests pass, coverage increased",
       agent_id=agent_id,
       project_id=2,
       priority="high",
       estimated_hours=4.0,
       notes="Noticed while working on task 127. Bulk operations are critical for agent workflows but lack integration tests."
   )
   ```

### Best Practices for Proactive Task Creation

1. **Don't let good ideas slip away** - Create the task immediately when you notice something
2. **Be specific** - Clear `task_instruction` and `verification_instruction` help future agents
3. **Link related work** - Use `relationship_type` to connect related tasks
4. **Set appropriate priority** - Balance impact vs urgency
5. **Add context in notes** - Explain where/when you noticed the issue
6. **Break down large refactoring** - Large refactors should be broken into smaller tasks
7. **Don't create duplicates** - Check if similar task exists using `search_tasks()` first

### Workflow Integration

**Recommended workflow when working on a task:**
```python
import os
agent_id = os.getenv("CURSOR_AGENT_ID", "agent-unset")

# 1. Reserve your main task
task = reserve_task(task_id=123, agent_id=agent_id)
task_id = 123

try:
    # 2. While working, keep a list of ideas:
    ideas = []
    
    # 3. Work on the main task
    implement_feature()
    
    # 4. When you notice something out of scope:
    if notice_refactoring_opportunity():
        ideas.append(("refactor", "description"))
    
    if notice_missing_tests():
        ideas.append(("test", "description"))
    
    if notice_improvement():
        ideas.append(("improvement", "description"))
    
    # 5. Complete main task first
    complete_task(task_id=task_id, agent_id=agent_id, notes="Main feature implemented")
    
    # 6. Create tasks for all ideas (don't forget!)
    for idea_type, description in ideas:
        create_task(
            title=description["title"],
            task_type="concrete",
            task_instruction=description["instruction"],
            verification_instruction=description["verification"],
            agent_id=agent_id,
            project_id=task["project_id"],
            priority="medium",
            notes=f"Noticed while working on task {task_id}"
        )
        
except Exception as e:
    unlock_task(task_id=task_id, agent_id=agent_id)
    raise
```

### Task Queue Health

**Maintain a healthy task queue by:**
- Creating more tasks than you complete (positive growth)
- Breaking down large tasks into manageable pieces
- Capturing technical debt and refactoring opportunities
- Identifying missing test coverage
- Documenting improvement ideas as you encounter them

**A well-maintained task queue:**
- Always has available tasks for agents to pick up
- Prevents work from blocking on large, complex tasks
- Ensures good ideas and improvements are captured
- Makes the codebase progressively better over time

## Task Verification

### Overview

When a task is marked `complete` but has `verification_status="unverified"`, it is in a **`needs_verification` state**. The TODO service displays this as `effective_status="needs_verification"` and sets `needs_verification=True`.

**Agents don't need to understand the mechanics** - they just need to:
1. Pick up tasks that show `needs_verification=True` or `effective_status="needs_verification"`
2. Verify the task satisfies its `verification_instruction`
3. Complete it using `complete_task()` - if the task is already complete but unverified, completing it will automatically mark it as verified.

### Working on Verification Tasks

**Verification is now transparent to agents - no special handling needed!**

Tasks that need verification (complete but unverified) appear in `list_available_tasks()` just like regular tasks. When you work on them:

1. **Reserve the task** (same as any task):
   ```python
   task_context = reserve_task(task_id=165, agent_id=agent_id)
   task = task_context["task"]
   
   # Check the verification_instruction field - this tells you what to verify
   verification_instruction = task["verification_instruction"]
   ```

2. **Evaluate against verification instructions:**
   - Review the task's `verification_instruction` field
   - Check if the work satisfies those instructions
   - Test the implementation (run tests, check functionality, review code)
   - Verify all requirements are met
   - Check if code is committed (if applicable)

3. **Complete the task** (same as any task):
   ```python
   # If verification passes, just complete the task normally
   # The backend automatically detects that it's already complete but unverified
   # and marks it as verified instead of completing again
   
   complete_task(
       task_id=task_id,
       agent_id=agent_id,
       notes="Verification PASSED. All verification instructions satisfied. Tests pass, functionality works as specified."
   )
   # This will automatically:
   # - Mark verification_status as "verified" (if task was complete but unverified)
   # - Or complete the task normally (if task was in_progress)
   ```

   **If verification fails:**
   ```python
   # Add update explaining the failure
   add_task_update(
       task_id=task_id,
       agent_id=agent_id,
       content=f"Verification FAILED. Issues found: [describe]. Task unlocked for fixes.",
       update_type="blocker"
   )
   
   # Create followup task explaining the issue
   followup = create_task(
       title=f"Fix verification issues for task {task_id}: {task['title']}",
       task_type="concrete",
       task_instruction=f"Task {task_id} failed verification. Issues: [describe]. Please fix or improve verification instructions.",
       verification_instruction="Verify issues are resolved.",
       agent_id=agent_id,
       project_id=task["project_id"],
       parent_task_id=task_id,
       relationship_type="related",
       priority="high"
   )
   
   # Unlock the task so it can be fixed
   unlock_task(task_id=task_id, agent_id=agent_id)
   ```

### Important Notes

- **No special verification workflow needed** - verification tasks are handled exactly like regular tasks
- **Complete automatically verifies** - When you call `complete_task()` on a task that's already complete but unverified, it automatically marks it as verified
- **Transparent to agents** - From the agent's perspective, there's no difference between implementation tasks and verification tasks
- **Tasks needing verification appear in `list_available_tasks()`** - They show up as regular available tasks with `needs_verification=True` or `effective_status="needs_verification"` for informational purposes only

## Refactoring Large Hub Files

**When a file becomes large (e.g., >2000 lines) or has complex import dependencies, it should be broken down into smaller, focused modules using design patterns.**

### When to Refactor

Refactor when you notice:
- **File size**: >2000 lines is a strong indicator
- **Import complexity**: Many optional imports with try/except blocks
- **Mixed concerns**: Multiple domains in one file (e.g., auth, endpoints, models, middleware)
- **Hard to navigate**: Difficult to find specific functionality
- **Test complexity**: Tests require mocking many dependencies

### Design Patterns for Refactoring

Use these patterns to organize code:

#### 1. **Adapter Pattern** - For External Dependencies
When integrating multiple external services with similar interfaces:

```python
# Instead of direct imports in main.py:
from service_a import ServiceA
from service_b import ServiceB

# Create adapters:
# src/adapters/job_queue_adapter.py
class JobQueueAdapter:
    """Adapter for job queue implementations."""
    def __init__(self):
        self._queue = self._create_queue()
    
    def _create_queue(self):
        try:
            from job_queue import JobQueue
            return JobQueue(...)
        except ImportError:
            return None
```

#### 1.5. **Third-Party Library Isolation** - For External Libraries
**When you have more than 3 distinct third-party libraries, isolate them in adapters to make library replacement easier:**

```python
# BAD: Direct third-party imports scattered throughout main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from prometheus_client import generate_latest
from httpx import Client
from strawberry.fastapi import GraphQLRouter
# ... many more third-party imports

# GOOD: Isolate third-party libraries in adapters
# src/adapters/http_framework.py
class HTTPFrameworkAdapter:
    """Adapter for HTTP framework (FastAPI/Flask/etc)."""
    def __init__(self):
        from fastapi import FastAPI
        self.FastAPI = FastAPI
        from fastapi import HTTPException
        self.HTTPException = HTTPException
    
    def create_app(self):
        return self.FastAPI()

# src/adapters/validation.py
class ValidationAdapter:
    """Adapter for validation library (Pydantic/marshmallow/etc)."""
    def __init__(self):
        from pydantic import BaseModel, Field
        self.BaseModel = BaseModel
        self.Field = Field

# src/adapters/metrics.py
class MetricsAdapter:
    """Adapter for metrics library (Prometheus/etc)."""
    def generate_metrics(self):
        from prometheus_client import generate_latest
        return generate_latest()

# In main.py or service container:
from adapters.http_framework import HTTPFrameworkAdapter
from adapters.validation import ValidationAdapter
from adapters.metrics import MetricsAdapter

http_adapter = HTTPFrameworkAdapter()
validation_adapter = ValidationAdapter()
metrics_adapter = MetricsAdapter()

app = http_adapter.create_app()
```

**Benefits:**
- Easy to swap libraries (e.g., FastAPI → Flask, Pydantic → marshmallow)
- Centralized import logic (handle version differences, optional dependencies)
- Easier testing (mock the adapter, not the library)
- Clear dependency boundaries

**When to isolate:**
- **More than 3 distinct third-party libraries** in a single file
- Library might be replaced in the future
- Library has version compatibility issues
- Library is optional/feature-flagged

#### 2. **Strategy Pattern** - For Alternative Implementations
When you have multiple ways to do the same thing:

```python
# src/strategies/backup_strategy.py
class BackupStrategy:
    """Strategy interface for backup implementations."""
    def backup(self, data): raise NotImplementedError
    def restore(self, backup_id): raise NotImplementedError

class FileBackupStrategy(BackupStrategy):
    """File-based backup strategy."""
    ...

class S3BackupStrategy(BackupStrategy):
    """S3-based backup strategy."""
    ...
```

#### 3. **Command Pattern** - For Endpoint Handlers
Group related endpoints into command modules:

```python
# src/api/commands/task_commands.py
class TaskCommands:
    """Command handlers for task-related endpoints."""
    
    @staticmethod
    async def create_task(task_data, auth):
        """Create a new task."""
        ...
    
    @staticmethod
    async def complete_task(task_id, agent_id):
        """Complete a task."""
        ...
```

#### 4. **Dependency Injection** - For Shared Services
Centralize service initialization:

```python
# src/dependencies/services.py
class ServiceContainer:
    """Container for all application services."""
    
    def __init__(self):
        self.db = TodoDatabase(...)
        self.backup_manager = BackupManager(...)
        self.job_queue = JobQueueAdapter().get_queue()
        # ... other services

# In main.py:
from dependencies.services import ServiceContainer
services = ServiceContainer()
```

### Recommended Module Structure

Break down `main.py` into:

```
src/
├── main.py                    # Minimal: app creation, routing, lifespan
├── api/                       # API route handlers
│   ├── __init__.py
│   ├── routes/               # Route modules by domain
│   │   ├── projects.py       # Project endpoints
│   │   ├── tasks.py          # Task endpoints
│   │   ├── comments.py       # Comment endpoints
│   │   ├── attachments.py    # Attachment endpoints
│   │   ├── relationships.py  # Relationship endpoints
│   │   └── mcp.py            # MCP endpoints
│   └── commands/             # Command handlers (optional)
│       ├── task_commands.py
│       └── project_commands.py
├── models/                    # Pydantic models
│   ├── __init__.py
│   ├── project_models.py
│   ├── task_models.py
│   └── request_models.py
├── auth/                      # Authentication/authorization
│   ├── __init__.py
│   ├── dependencies.py       # FastAPI dependencies
│   └── strategies.py         # Auth strategies
├── middleware/               # Middleware setup
│   ├── __init__.py
│   └── setup.py              # Middleware configuration
├── exceptions/               # Exception handlers
│   ├── __init__.py
│   └── handlers.py           # Global exception handlers
├── dependencies/             # Dependency injection
│   ├── __init__.py
│   └── services.py           # Service container
└── adapters/                 # External service adapters
    ├── __init__.py
    ├── job_queue_adapter.py  # Service adapters
    ├── http_framework.py     # HTTP framework adapter (FastAPI/etc)
    ├── validation.py        # Validation library adapter (Pydantic/etc)
    ├── metrics.py            # Metrics library adapter (Prometheus/etc)
    └── third_party.py        # Other third-party library adapters
```

### Refactoring Steps

1. **Create module structure** (as above)
2. **Isolate third-party libraries** (if >3 distinct libraries):
   - Create adapters in `adapters/` for each major third-party library
   - Move all imports and library-specific code to adapters
   - Use adapters throughout application code
3. **Move Pydantic models** to `models/` (group by domain)
4. **Extract route handlers** to `api/routes/` (one file per domain)
5. **Extract authentication** to `auth/dependencies.py`
6. **Extract exception handlers** to `exceptions/handlers.py`
7. **Extract middleware setup** to `middleware/setup.py`
8. **Create service container** in `dependencies/services.py`
9. **Update main.py** to:
   - Import routes
   - Register routes with app
   - Set up middleware
   - Configure exception handlers
   - Initialize services

### Example: Breaking Down main.py

**Before (in main.py):**
```python
# 1000+ lines of mixed concerns
@app.post("/tasks")
async def create_task(...): ...

class TaskCreate(BaseModel): ...

async def verify_api_key(...): ...
```

**After:**

```python
# src/main.py (minimal)
from fastapi import FastAPI
from api.routes import tasks, projects, comments
from middleware.setup import setup_middleware
from exceptions.handlers import setup_exception_handlers
from dependencies.services import ServiceContainer

app = FastAPI()
services = ServiceContainer()

setup_middleware(app)
setup_exception_handlers(app)

app.include_router(tasks.router)
app.include_router(projects.router)
app.include_router(comments.router)
```

```python
# src/api/routes/tasks.py
from fastapi import APIRouter, Depends
from models.task_models import TaskCreate, TaskResponse
from auth.dependencies import verify_api_key
from dependencies.services import get_services

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.post("/", response_model=TaskResponse)
async def create_task(
    task: TaskCreate,
    auth: dict = Depends(verify_api_key),
    services = Depends(get_services)
):
    """Create a new task."""
    return services.db.create_task(...)
```

### Best Practices

1. **One domain per file**: Tasks in `tasks.py`, Projects in `projects.py`
2. **Isolate third-party libraries**: When you have >3 distinct external libraries, create adapters to isolate library-specific code
3. **Shared utilities**: Put in `utils/` or `common/`
4. **Service dependencies**: Inject via FastAPI `Depends()` or service container
5. **Keep main.py minimal**: Should only orchestrate, not implement
6. **Test modules independently**: Each module should have its own tests
7. **Preserve existing APIs**: Refactoring shouldn't change external behavior
8. **Library abstraction**: Use adapters to abstract library-specific APIs, making replacements easier in the future

### Creating Tasks for Refactoring

When you encounter a large hub file:
1. **Create a task** to break it down:
   - Title: "Refactor main.py into modular structure"
   - Include target structure in instructions
   - List specific modules to extract
2. **Break into subtasks**:
   - Extract models to `models/`
   - Extract routes to `api/routes/`
   - Extract auth to `auth/`
   - etc.
3. **Test after each extraction**: Ensure tests still pass
4. **Commit incrementally**: Don't wait until everything is done

## Common Tasks

### Adding a New Endpoint
1. Write test in `tests/test_api.py` (it will fail)
2. Implement endpoint in appropriate `src/api/routes/` module (or `src/main.py` if refactoring not done yet)
3. Run tests to verify it works
4. Update API documentation if needed

### Adding Database Functionality
1. Write test in `tests/test_database.py`
2. Update schema if needed in `todorama/database.py`
3. Implement functionality
4. Test with various data scenarios

### Modifying Backup Logic
1. Write test in `tests/test_backup.py`
2. Modify `src/backup.py`
3. Test backup creation, listing, and restore
4. Verify cleanup functionality

## Failure Handling

If `run_checks.sh` fails:
1. **DO NOT** commit or push
2. Review the error messages
3. Fix all failing tests
4. Run `run_checks.sh` again
5. Only commit when all checks pass

## Integration with June Project

When working on TODO MCP Service that affects June:
1. Run `./run_checks.sh` in todo-mcp-service
2. Run `../june/run_checks.sh` to verify integration
3. Ensure both test suites pass
4. Update June's `run_checks.sh` if needed

## Emergency Situations

If you must push without tests passing:
1. Document why in commit message
2. Create an issue to track test fixes
3. Fix tests in a follow-up commit ASAP
4. Never skip tests for convenience

---

## Fixing Test Failures: Systematic Approach

**When fixing test failures, especially routing-related ones, use a systematic approach to fix many issues at once.**

### Pattern Recognition for Test Failures

**Most test failures fall into these categories:**

1. **Missing Routes (404 errors)** - Most common and easiest to fix
   - **Symptom**: Tests return `404 Not Found`
   - **Solution**: Add missing routes to `all_routes.py` or command router
   - **Pattern**: Many tests failing with 404 usually means missing route definitions
   - **Example**: If 10 tests fail with 404 for `/api/Task/bulk/*`, add all bulk routes at once

2. **Route Conflicts** - Routes under `/api/` conflict with command router
   - **Symptom**: Routes exist but return 404 or wrong handler
   - **Solution**: 
     - Routes under `/api/{entity}/{action}` are handled by command router
     - Use `/tasks/`, `/projects/`, etc. for traditional REST routes
     - Or add special handling in command router for sub-paths like `import/json`
   - **Example**: `/api/Task/import/json` conflicts with command router - use `/tasks/import/json` or handle in command router

3. **Validation Errors (422)** - Request body format issues
   - **Symptom**: Tests return `422 Unprocessable Entity`
   - **Solution**: Check request body format, parameter names, required fields
   - **Pattern**: Similar validation errors suggest common parameter handling issue

4. **Test Isolation Issues** - Tests finding data from other tests
   - **Symptom**: Tests pass individually but fail in suite, wrong data in results
   - **Solution**: Make tests filter to their own data, use unique identifiers, or improve test cleanup
   - **Pattern**: Search/list tests returning unexpected results

5. **Response Format Mismatches** - Tests expect different response structure
   - **Symptom**: `KeyError` accessing response fields, wrong status codes
   - **Solution**: Check test expectations vs actual response format
   - **Pattern**: Multiple tests failing with same KeyError suggests response format change needed

### Systematic Fix Strategy

**When you see many test failures:**

1. **Categorize failures first:**
   ```bash
   # Run tests and categorize by error type
   pytest tests/test_api.py -v --tb=no 2>&1 | grep -E "FAILED|404|422|KeyError" | sort | uniq -c
   ```

2. **Fix by category, not one-by-one:**
   - **404 errors**: Identify all missing routes, add them all at once
   - **422 errors**: Fix parameter handling pattern, apply to all affected routes
   - **Test isolation**: Fix test data filtering pattern, apply to all affected tests
   - **Response format**: Fix response structure, apply to all affected endpoints

3. **Example: Fixing Missing Routes**
   ```python
   # Instead of fixing one route at a time:
   # ❌ BAD: Add route, test, add next route, test...
   
   # ✅ GOOD: Identify all missing routes, add them all:
   # 1. Find all 404 errors:
   #    grep -r "404\|Not Found" test_output
   
   # 2. List all missing routes:
   #    - /tags (POST)
   #    - /api/Task/import/json (POST)
   #    - /api/Task/bulk/* (POST)
   #    - /analytics/* (GET)
   #    - /api-keys/* (POST/GET/DELETE)
   
   # 3. Add all routes to all_routes.py in one go
   # 4. Run tests - many should pass now
   ```

4. **Example: Fixing Route Conflicts**
   ```python
   # Problem: Routes under /api/ conflict with command router
   # Command router handles: /api/{entity}/{action}
   # So /api/Task/import/json gets caught by command router
   
   # Solution options:
   # Option 1: Use traditional REST paths (recommended)
   @router.post("/tasks/import/json")  # Not /api/Task/import/json
   @router.post("/tasks/bulk/complete")  # Not /api/Task/bulk/complete
   
   # Option 2: Add special handling in command router
   # In command_router.py, add before generic route:
   @router.post("/{entity_name}/import/{format}")
   async def entity_import(...):
       # Handle import actions
   ```

5. **Example: Fixing Test Isolation**
   ```python
   # Problem: Search tests finding tasks from other tests
   # Solution: Filter to test's own data
   
   # ❌ BAD: Assumes only test's data exists
   assert len(tasks) == 1
   
   # ✅ GOOD: Filter to test's own tasks
   our_tasks = [t for t in tasks if t["id"] in [task1_id, task2_id]]
   assert len(our_tasks) == 1
   assert our_tasks[0]["id"] == task1_id
   ```

### Route Registration Order Matters

**FastAPI matches routes in order - more specific routes must come before generic ones:**

```python
# ✅ CORRECT ORDER:
# 1. Specific routes first
@router.get("/tasks/export/{format}")  # Specific
@router.get("/tasks/{task_id}")        # Generic (comes after)

# 2. Command router routes (generic pattern)
app.include_router(command_router)  # Handles /api/{entity}/{action}

# 3. All routes (traditional REST)
app.include_router(all_routes_router)  # Handles /tasks, /projects, etc.
```

### Quick Fix Checklist

**When fixing test failures:**

- [ ] **Categorize failures** - Group by error type (404, 422, KeyError, etc.)
- [ ] **Identify patterns** - Are multiple failures the same root cause?
- [ ] **Fix systematically** - Address category, not individual tests
- [ ] **Check route conflicts** - Routes under `/api/` may conflict with command router
- [ ] **Verify route order** - Specific routes before generic ones
- [ ] **Test in batches** - Run related tests together to verify fixes
- [ ] **Document patterns** - Note common issues for future reference

### Common Patterns

**Pattern 1: Missing Routes (404)**
- **Fix**: Add routes to `all_routes.py` or command router
- **Impact**: Fixes many tests at once

**Pattern 2: Route Conflicts**
- **Fix**: Move routes out of `/api/` or add special handling
- **Impact**: Fixes all routes in that category

**Pattern 3: Validation (422)**
- **Fix**: Check parameter names, required fields, body format
- **Impact**: Fixes all endpoints with same validation issue

**Pattern 4: Test Isolation**
- **Fix**: Filter test data, use unique identifiers
- **Impact**: Fixes all tests with isolation issues

**Pattern 5: Response Format**
- **Fix**: Update response structure or test expectations
- **Impact**: Fixes all tests expecting that format

### Overnight Agent Strategy

**For agents running overnight to fix test failures:**

1. **Start with categorization** - Run full test suite, group failures
2. **Fix by category** - Don't fix tests one-by-one, fix patterns
3. **Commit after each category** - Small, focused commits
4. **Monitor progress** - Track failure count reduction
5. **Document patterns** - Note what worked for future reference
6. **Don't get stuck** - If a fix doesn't work after 2-3 attempts, move on and document

**Remember**: Fixing patterns fixes many tests. Fixing individual tests is slow and doesn't address root causes.

---

## MCP Interface Testing (CRITICAL)

The MCP (Model Context Protocol) interface is **CRITICAL** for data integrity. Any failures in the MCP interface can result in:
- Loss of task data
- Incorrect task status updates
- Locked tasks that can't be released
- Corruption of task relationships

### Test Coverage

All MCP tests are in `tests/test_mcp_api.py` and include:

**Protocol-Level Tests (CRITICAL):**
1. **`test_mcp_sse_endpoint_connectivity`** - Verifies SSE endpoint returns proper JSON-RPC format
2. **`test_mcp_post_initialize`** - Tests MCP initialize handshake (CRITICAL: Cursor must be able to initialize)
3. **`test_mcp_post_tools_list`** - Tests tool discovery (CRITICAL: Cursor must discover all tools)

**Tool Execution Tests (CRITICAL):**
4. **`test_mcp_post_tools_call_list_available_tasks`** - Tests listing tasks via MCP
5. **`test_mcp_post_tools_call_reserve_task`** - Tests task locking via MCP
6. **`test_mcp_post_tools_call_complete_task`** - Tests task completion via MCP

**End-to-End Workflow Test (CRITICAL):**
7. **`test_mcp_complete_workflow`** - Tests full workflow: list → reserve → update → complete

### Running MCP Tests

```bash
# Run all MCP tests
pytest tests/test_mcp_api.py -v

# Run specific critical tests
pytest tests/test_mcp_api.py::test_mcp_post_initialize -v
pytest tests/test_mcp_api.py::test_mcp_post_tools_list -v

# Run full test suite
./run_checks.sh
```

### Before Any MCP Changes

**MANDATORY**: Before modifying any MCP-related code:
1. Run all MCP tests: `pytest tests/test_mcp_api.py -v`
2. Verify all tests pass
3. Test with Cursor MCP client to ensure compatibility
4. Verify SSE endpoint returns proper JSON-RPC format
5. Verify POST endpoint handles tools/call requests correctly

### Known Failure Modes (Prevented by Tests)

The MCP tests prevent these critical issues:
- **SSE endpoint JSON-RPC format errors** (id: null, missing method)
- **Missing POST endpoint handler** for /mcp/sse
- **Incorrect tool execution response format**
- **Missing initialize and tools/list handlers**
- **Task locking failures** (concurrent access issues)
- **Task completion failures** (data persistence issues)

For detailed MCP testing documentation, see [MCP_TESTING.md](MCP_TESTING.md).

**Remember**: Tests are not optional. They are your safety net and documentation.
Every feature should have tests, and every commit should pass all tests.

