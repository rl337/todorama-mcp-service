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

## Development Workflow

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

**Agents MUST use the TODO service via MCP (Model Context Protocol) functions rather than running direct API calls or code.**

The TODO service exposes a comprehensive MCP interface that allows agents to:
- List and reserve tasks
- Add progress updates and findings
- Create and complete tasks
- Query task context and relationships
- Track agent performance

**Why use MCP instead of direct API calls:**
1. **Consistency**: All agents interact with tasks in a standardized way
2. **Context**: MCP functions automatically provide full context (project, ancestry, updates)
3. **Tracking**: All actions are properly logged with agent identity
4. **Simplicity**: No need to write HTTP client code or manage API endpoints
5. **Integration**: Works seamlessly with MCP-compatible agent frameworks

### Available MCP Functions

1. **`list_available_tasks`** - Get available tasks for your agent type
   - Parameters: `agent_type` (breakdown/implementation), `project_id` (optional), `limit`
   - Returns: List of available tasks

2. **`reserve_task`** - Lock and reserve a task (automatically returns full context)
   - Parameters: `task_id`, `agent_id`
   - Returns: Full context including project, ancestry, updates, recent changes

3. **`add_task_update`** - Add progress updates, findings, blockers, or questions
   - Parameters: `task_id`, `agent_id`, `content`, `update_type` (progress/note/blocker/question/finding), `metadata` (optional)
   - Returns: Update ID and success status

4. **`get_task_context`** - Get full context for a task (project, ancestry, updates)
   - Parameters: `task_id`
   - Returns: Full task context

5. **`complete_task`** - Mark task complete and optionally create followups
   - Parameters: `task_id`, `agent_id`, `notes` (optional), followup fields (optional)
   - Returns: Completion status and optional followup task ID

6. **`create_task`** - Create new tasks with automatic relationship linking
   - Parameters: `title`, `task_type`, `task_instruction`, `verification_instruction`, `agent_id`, `project_id` (optional), `parent_task_id` (optional), `relationship_type` (optional), `notes` (optional)
   - Returns: Created task ID and optional relationship ID

7. **`unlock_task`** - Release a reserved task if unable to complete
   - Parameters: `task_id`, `agent_id`
   - Returns: Unlock status

8. **`query_tasks`** - Query tasks by various criteria
   - Parameters: `project_id`, `task_type`, `task_status`, `agent_id` (all optional), `limit`
   - Returns: List of matching tasks

9. **`get_agent_performance`** - Get your performance statistics
   - Parameters: `agent_id`, `task_type` (optional)
   - Returns: Performance statistics

### Recommended Workflow

**⚠️ IMPORTANT: Always wrap your workflow in try/except blocks to ensure mandatory completion/unlock. See the "CRITICAL: Task Completion is MANDATORY" section above for full examples.**

1. **Start working on a task:**
   ```python
   task_id = None
   try:
       tasks = list_available_tasks(agent_type="implementation", project_id=1)
       task = reserve_task(task_id=123, agent_id="my-agent-id")
       task_id = 123
   except Exception as e:
       logger.error(f"Failed to reserve task: {e}")
       raise
   ```

2. **While working:**
   ```python
   add_task_update(task_id=task_id, agent_id="my-agent-id", content="Making progress...", update_type="progress")
   add_task_update(task_id=task_id, agent_id="my-agent-id", content="Found an issue", update_type="blocker")
   ```

3. **Get context when needed:**
   ```python
   context = get_task_context(task_id=task_id)  # Returns project, ancestry, all updates
   ```

4. **🚨 MANDATORY: Complete the task when done:**
   ```python
   complete_task(task_id=task_id, agent_id="my-agent-id", notes="Completed successfully")
   ```

5. **🚨 MANDATORY: If unable to complete, unlock immediately:**
   ```python
   unlock_task(task_id=task_id, agent_id="my-agent-id")
   ```

**Remember: Steps 4 or 5 are MANDATORY - one of them MUST be called when you're done working on the task.**

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
   task_id = None
   agent_id = "my-agent-id"
   
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
   with work_on_task(task_id=123, agent_id="my-agent-id"):
       do_work()  # Automatic unlock if exception occurs
   ```

6. **Document the workflow: try/except blocks that guarantee unlock:**
   - **Every agent MUST follow this pattern when working on tasks:**
     ```python
     # 1. Reserve task
     task = reserve_task(task_id=123, agent_id="my-agent-id")
     
     # 2. Wrap ALL work in try/except/finally
     try:
         # All your task work here
         process_task()
         
         # 3. Complete if successful
         complete_task(task_id=123, agent_id="my-agent-id", notes="Done")
         
     except Exception as e:
         # 4. ALWAYS unlock on any error
         unlock_task(task_id=123, agent_id="my-agent-id")
         raise  # Re-raise to maintain error visibility
     
     # Note: You can also use finally block:
     # finally:
     #     if not completed:
     #         unlock_task(task_id=123, agent_id="my-agent-id")
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
task_id = 123
agent_id = "my-agent"

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
response = requests.post("http://localhost:5080/mcp/reserve_task", json={"task_id": 123, "agent_id": "my-agent"})
# Don't do this - use MCP functions instead!
```

```python
# Bad - missing error handling (DON'T DO THIS)
task = mcp.call("reserve_task", {"task_id": 123, "agent_id": "my-agent"})
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
   # While working on task 123, you realize it needs to be split:
   parent_task_id = 123
   
   # Create subtasks
   subtask1 = create_task(
       title="Implement authentication endpoint",
       task_type="concrete",
       task_instruction="Create POST /auth/login endpoint with JWT token generation",
       verification_instruction="Test endpoint with valid/invalid credentials, verify JWT token format",
       agent_id="my-agent",
       project_id=1,
       parent_task_id=parent_task_id,
       relationship_type="subtask"
   )
   
   subtask2 = create_task(
       title="Add authentication middleware",
       task_type="concrete",
       task_instruction="Create middleware to validate JWT tokens on protected routes",
       verification_instruction="Test middleware rejects invalid tokens, accepts valid tokens",
       agent_id="my-agent",
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
   # While working on task 123, you notice a refactoring opportunity:
   create_task(
       title="Refactor database.py to use connection pooling",
       task_type="concrete",
       task_instruction="Replace direct SQLite connections with connection pool to improve performance under load. Current code creates new connection per query which is inefficient.",
       verification_instruction="Verify connection pooling reduces connection overhead, run performance tests comparing before/after",
       agent_id="my-agent",
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
   # You notice duplicated validation logic:
   create_task(
       title="Extract common validation logic into shared module",
       task_type="concrete",
       task_instruction="Three endpoints (A, B, C) have identical validation logic. Extract to shared validation module to reduce duplication and ensure consistency.",
       verification_instruction="Verify all three endpoints use new validation module, no duplicated code remains, tests still pass",
       agent_id="my-agent",
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
   # You're refactoring code but notice missing tests:
   create_task(
       title="Add integration tests for MCP bulk operations",
       task_type="concrete",
       task_instruction="Add comprehensive integration tests for bulk_unlock_tasks, bulk_create_tasks, and other bulk MCP operations. Test partial failures, transaction rollback, and error handling.",
       verification_instruction="Verify all bulk operations have integration tests, edge cases covered, tests pass, coverage increased",
       agent_id="my-agent",
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
# 1. Reserve your main task
task = reserve_task(task_id=123, agent_id="my-agent")
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
    complete_task(task_id=task_id, agent_id="my-agent", notes="Main feature implemented")
    
    # 6. Create tasks for all ideas (don't forget!)
    for idea_type, description in ideas:
        create_task(
            title=description["title"],
            task_type="concrete",
            task_instruction=description["instruction"],
            verification_instruction=description["verification"],
            agent_id="my-agent",
            project_id=task["project_id"],
            priority="medium",
            notes=f"Noticed while working on task {task_id}"
        )
        
except Exception as e:
    unlock_task(task_id=task_id, agent_id="my-agent")
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

## Common Tasks

### Adding a New Endpoint
1. Write test in `tests/test_api.py` (it will fail)
2. Implement endpoint in `src/main.py`
3. Run tests to verify it works
4. Update API documentation if needed

### Adding Database Functionality
1. Write test in `tests/test_database.py`
2. Update schema if needed in `src/database.py`
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

**Remember**: Tests are not optional. They are your safety net and documentation.
Every feature should have tests, and every commit should pass all tests.

