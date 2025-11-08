# MCP Function Selection Guide

This guide helps agents choose the right MCP function for their needs when the TODO service is hosted externally and only MCP access is available.

## Core Task Workflow Functions

### Finding Tasks

**`list_available_tasks()`** - Start here when looking for work
- **When to use**: Finding tasks you can work on right now
- **Returns**: Tasks ready for your agent type (breakdown or implementation)
- **Filters**: `agent_type` (required), `project_id` (optional), `limit`
- **Example**: `list_available_tasks(agent_type="implementation", project_id=1, limit=10)`

**`query_tasks()`** - Flexible task search
- **When to use**: Finding tasks by status, type, agent, priority, tags, or project
- **Returns**: Any tasks matching criteria (not just available ones)
- **Filters**: Many options - status, type, agent_id, priority, tags, project_id, date ranges
- **Example**: `query_tasks(task_status="in_progress", agent_id="my-agent", limit=10)`

**`search_tasks()`** - Keyword-based search
- **When to use**: You know what you're looking for but not the exact task ID
- **Returns**: Tasks matching keywords in title, instructions, or notes
- **Filters**: `query` (required), `limit` (optional)
- **Example**: `search_tasks(query="authentication", limit=20)`

**`get_task_summary()`** - Lightweight task info
- **When to use**: Need basic info about many tasks (bulk queries)
- **Returns**: Essential fields only (id, title, status, agent, project, timestamps)
- **Filters**: Same as `query_tasks()` but faster and smaller responses
- **Example**: `get_task_summary(task_status="in_progress", limit=100)`

**`get_task_context()`** - Full task details
- **When to use**: Need complete context before working (project, ancestry, updates, recent changes)
- **Returns**: Full task object plus project, ancestry, all updates, recent changes
- **Filters**: `task_id` (required)
- **Example**: `get_task_context(task_id=123)`

### Task Lifecycle

**`reserve_task()`** - Lock a task before working
- **When to use**: Before starting work on any task (MANDATORY)
- **Returns**: Full task context including stale warnings if task was abandoned
- **Note**: You MUST call `complete_task()` or `unlock_task()` when done
- **Example**: `reserve_task(task_id=123, agent_id="my-agent")`

**`complete_task()`** - Mark task complete
- **When to use**: When you finish work successfully (MANDATORY)
- **Returns**: Success status, optional followup_task_id if followup created
- **Note**: If task is already complete but unverified, this automatically verifies it
- **Example**: `complete_task(task_id=123, agent_id="my-agent", notes="Completed successfully")`

**`unlock_task()`** - Release a task you can't complete
- **When to use**: When you cannot finish a task (MANDATORY)
- **Returns**: Success status
- **Note**: Always unlock in error handling paths (try/except/finally)
- **Example**: `unlock_task(task_id=123, agent_id="my-agent")`

**`bulk_unlock_tasks()`** - Unlock multiple tasks at once
- **When to use**: System maintenance, unlocking stale tasks, unlocking all tasks for an agent
- **Returns**: Summary with unlocked_count, unlocked_task_ids, failed_count, failed_task_ids
- **Note**: Atomic operation - all succeed or all fail
- **Example**: `bulk_unlock_tasks(task_ids=[94, 86, 83], agent_id="admin")`

### Task Updates and Communication

**`add_task_update()`** - Document progress
- **When to use**: Throughout work to document progress, blockers, questions, findings
- **Returns**: Success status and update_id
- **Update types**: `progress`, `note`, `blocker`, `question`, `finding`
- **Example**: `add_task_update(task_id=123, agent_id="my-agent", content="Making progress...", update_type="progress")`

**`create_comment()`** - Discussion and collaboration
- **When to use**: For discussion, questions, feedback (different from updates)
- **Returns**: Success status, comment_id, task_id
- **Features**: Threaded replies, mentions
- **Example**: `create_comment(task_id=123, agent_id="my-agent", content="What about edge case X?")`

**`get_task_comments()`** - Read task discussions
- **When to use**: See discussion and feedback on a task
- **Returns**: Top-level comments (use `get_comment_thread()` for replies)
- **Example**: `get_task_comments(task_id=123, limit=50)`

## Task Creation and Management

**`create_task()`** - Create new tasks
- **When to use**: Breaking down abstract tasks or creating related tasks
- **Returns**: Success status, task_id, optional relationship_id
- **Features**: Link to parent tasks, set relationships (subtask, blocking, blocked_by, related)
- **Example**: `create_task(title="Implement auth", task_type="concrete", task_instruction="...", verification_instruction="...", agent_id="my-agent")`

**`create_task_from_template()`** - Create from template
- **When to use**: Creating tasks using standard patterns (faster than `create_task()`)
- **Returns**: Success status, task_id
- **Features**: Auto-fills instructions from template, can override template values
- **Example**: `create_task_from_template(template_id=5, agent_id="my-agent", title="Fix bug in auth")`

## Task Organization

**`create_tag()`** - Create tags for categorization
- **When to use**: Creating tags to organize tasks
- **Returns**: Success status, tag_id, tag data
- **Note**: Returns existing tag_id if tag name already exists (no duplicates)
- **Example**: `create_tag(name="backend")`

**`list_tags()`** - See available tags
- **When to use**: Finding existing tags before creating or assigning
- **Returns**: All tags with tag_id and name
- **Example**: `list_tags()`

**`assign_tag_to_task()`** - Categorize tasks
- **When to use**: Organizing tasks by features, areas, priorities
- **Returns**: Success status
- **Note**: Tasks can have multiple tags
- **Example**: `assign_tag_to_task(task_id=123, tag_id=5)`

**`get_task_tags()`** - See task categories
- **When to use**: Checking how a task is categorized
- **Returns**: All tags assigned to the task
- **Example**: `get_task_tags(task_id=123)`

## Templates

**`create_template()`** - Create reusable task templates
- **When to use**: Standardizing common task patterns
- **Returns**: Success status, template_id
- **Example**: `create_template(name="Bug Fix Template", task_type="concrete", ...)`

**`list_templates()`** - Find templates
- **When to use**: Before creating tasks from templates
- **Returns**: All available templates
- **Example**: `list_templates(task_type="concrete")`

**`get_template()`** - Review template details
- **When to use**: Before creating a task from a template
- **Returns**: Full template data
- **Example**: `get_template(template_id=5)`

## Statistics and Monitoring

**`get_task_statistics()`** - Aggregated statistics
- **When to use**: Getting counts and metrics without querying all tasks
- **Returns**: Total count, counts by status/type/project, completion rate
- **Filters**: `project_id`, `task_type`, `start_date`, `end_date` (all optional)
- **Example**: `get_task_statistics(project_id=1, task_type="concrete")`

**`get_recent_completions()`** - Recently finished tasks
- **When to use**: Seeing what was recently completed
- **Returns**: Lightweight summaries sorted by completion time
- **Filters**: `limit`, `project_id`, `hours` (all optional)
- **Example**: `get_recent_completions(limit=10, hours=24)`

**`get_agent_performance()`** - Your performance metrics
- **When to use**: Tracking your productivity
- **Returns**: Completion counts, average hours, success rate
- **Filters**: `task_type` (optional)
- **Example**: `get_agent_performance(agent_id="my-agent", task_type="concrete")`

**`query_stale_tasks()`** - Find abandoned tasks
- **When to use**: Monitoring system health, finding tasks that may have been abandoned
- **Returns**: Tasks in_progress longer than timeout period
- **Filters**: `hours` (optional, defaults to TASK_TIMEOUT_HOURS or 24)
- **Example**: `query_stale_tasks(hours=48)`

**`get_tasks_approaching_deadline()`** - Deadline monitoring
- **When to use**: Prioritizing tasks with approaching deadlines
- **Returns**: Tasks with due dates within specified days
- **Filters**: `days_ahead` (default: 3), `limit` (default: 100)
- **Example**: `get_tasks_approaching_deadline(days_ahead=7, limit=50)`

**`get_activity_feed()`** - Chronological activity log
- **When to use**: Monitoring project activity, auditing task history
- **Returns**: All events (updates, completions, changes) in chronological order
- **Filters**: `task_id`, `agent_id`, `start_date`, `end_date`, `limit` (all optional)
- **Example**: `get_activity_feed(task_id=123, limit=100)`

## Task History and Versioning

**`get_task_versions()`** - Task version history
- **When to use**: Seeing how a task evolved over time
- **Returns**: All versions ordered newest first
- **Example**: `get_task_versions(task_id=123)`

**`get_task_version()`** - Specific version
- **When to use**: Seeing what a task looked like at a specific point in time
- **Returns**: Task data at that version
- **Example**: `get_task_version(task_id=123, version_number=2)`

**`get_latest_task_version()`** - Most recent version
- **When to use**: Current state with version metadata
- **Returns**: Latest version data
- **Example**: `get_latest_task_version(task_id=123)`

**`diff_task_versions()`** - Compare versions
- **When to use**: Understanding what changed between versions
- **Returns**: Field-by-field differences
- **Example**: `diff_task_versions(task_id=123, version_number_1=1, version_number_2=2)`

## GitHub Integration

**`link_github_issue()`** - Link issue to task
- **When to use**: Connecting tasks with GitHub issues for traceability
- **Returns**: Success status, task_id, github_issue_url
- **Note**: One issue per task
- **Example**: `link_github_issue(task_id=123, github_url="https://github.com/org/repo/issues/456")`

**`link_github_pr()`** - Link PR to task
- **When to use**: Connecting tasks with PRs that implement the task
- **Returns**: Success status, task_id, github_pr_url
- **Note**: One PR per task
- **Example**: `link_github_pr(task_id=123, github_url="https://github.com/org/repo/pull/789")`

**`get_github_links()`** - Get GitHub links
- **When to use**: Seeing what GitHub resources are associated with a task
- **Returns**: github_issue_url and github_pr_url (or null)
- **Example**: `get_github_links(task_id=123)`

## Projects

**`list_projects()`** - Discover projects
- **When to use**: Finding available projects (critical when service is external-only)
- **Returns**: All projects with project_id, name, description, local_path
- **Example**: `list_projects()`

**`get_project()`** - Get project by ID
- **When to use**: Getting project details by ID
- **Returns**: Full project data
- **Example**: `get_project(project_id=1)`

**`get_project_by_name()`** - Get project by name
- **When to use**: Finding project by name
- **Returns**: Full project data
- **Example**: `get_project_by_name(name="june")`

**`create_project()`** - Create new project
- **When to use**: Setting up a new project
- **Returns**: Success status, project_id
- **Example**: `create_project(name="my-project", description="...", local_path="/path/to/project")`

## Recurring Tasks

**`create_recurring_task()`** - Set up recurring tasks
- **When to use**: Tasks that repeat regularly (daily standups, weekly reviews)
- **Returns**: Success status, recurring_task_id
- **Recurrence types**: `daily`, `weekly`, `monthly`
- **Example**: `create_recurring_task(task_id=123, recurrence_type="daily", next_occurrence="2025-11-02T09:00:00Z")`

**`list_recurring_tasks()`** - See recurring patterns
- **When to use**: Viewing active and inactive recurring tasks
- **Returns**: All recurring task patterns
- **Example**: `list_recurring_tasks(active_only=True)`

**`get_recurring_task()`** - Recurring task details
- **When to use**: Reviewing recurrence schedule
- **Returns**: Full recurring task data
- **Example**: `get_recurring_task(recurring_id=5)`

**`update_recurring_task()`** - Modify schedule
- **When to use**: Changing recurrence frequency or next occurrence
- **Returns**: Success status
- **Example**: `update_recurring_task(recurring_id=5, recurrence_type="weekly", next_occurrence="2025-11-09T09:00:00Z")`

**`deactivate_recurring_task()`** - Stop recurring
- **When to use**: Pausing recurring tasks temporarily
- **Returns**: Success status
- **Example**: `deactivate_recurring_task(recurring_id=5)`

**`create_recurring_instance()`** - Manually trigger instance
- **When to use**: Force immediate creation of next instance (testing or manual trigger)
- **Returns**: Success status, instance_id (created task ID)
- **Example**: `create_recurring_instance(recurring_id=5)`

## Comments (Threaded Discussion)

**`create_comment()`** - Add comment
- **When to use**: Discussion and collaboration (different from updates)
- **Returns**: Success status, comment_id, task_id
- **Features**: Threaded replies, mentions
- **Example**: `create_comment(task_id=123, agent_id="my-agent", content="What about edge case X?")`

**`get_task_comments()`** - Read comments
- **When to use**: Seeing discussion on a task
- **Returns**: Top-level comments (use `get_comment_thread()` for replies)
- **Example**: `get_task_comments(task_id=123, limit=50)`

**`get_comment_thread()`** - Read thread
- **When to use**: Seeing complete threaded discussion
- **Returns**: Parent comment and all replies
- **Example**: `get_comment_thread(comment_id=456)`

**`update_comment()`** - Edit comment
- **When to use**: Correcting mistakes or updating information
- **Returns**: Success status, updated comment data
- **Note**: Only comment owner can update
- **Example**: `update_comment(comment_id=456, agent_id="my-agent", content="Updated comment")`

**`delete_comment()`** - Delete comment
- **When to use**: Removing comments (cascades to replies)
- **Returns**: Success status
- **Note**: Only comment owner can delete, deletion cascades to all replies
- **Example**: `delete_comment(comment_id=456, agent_id="my-agent")`

## Function Selection Decision Tree

### I need to find a task to work on
1. **Know the task ID?** → `get_task_context(task_id)`
2. **Know keywords?** → `search_tasks(query="...")`
3. **Know status/type/agent?** → `query_tasks(task_status="...", task_type="...")`
4. **Just want available work?** → `list_available_tasks(agent_type="...")`

### I need task information
1. **Need full context (project, updates, ancestry)?** → `get_task_context(task_id)`
2. **Need basic info about many tasks?** → `get_task_summary(...)`
3. **Need specific version?** → `get_task_version(task_id, version_number)`
4. **Need to compare versions?** → `diff_task_versions(task_id, v1, v2)`

### I need statistics
1. **Aggregated counts/metrics?** → `get_task_statistics(...)`
2. **Recently completed tasks?** → `get_recent_completions(...)`
3. **My performance?** → `get_agent_performance(agent_id="...")`
4. **Stale/abandoned tasks?** → `query_stale_tasks(...)`
5. **Tasks approaching deadline?** → `get_tasks_approaching_deadline(...)`

### I need to organize tasks
1. **Create tags?** → `create_tag(name="...")`
2. **Find tags?** → `list_tags()`
3. **Assign tags?** → `assign_tag_to_task(task_id, tag_id)`
4. **See task tags?** → `get_task_tags(task_id)`

### I need to communicate
1. **Progress updates?** → `add_task_update(task_id, agent_id, content, update_type="progress")`
2. **Discussion/questions?** → `create_comment(task_id, agent_id, content)`
3. **Read discussion?** → `get_task_comments(task_id)` or `get_comment_thread(comment_id)`

## Best Practices

1. **Always reserve before working**: Use `reserve_task()` before starting work
2. **Always complete or unlock**: Never leave tasks in_progress - use `complete_task()` or `unlock_task()`
3. **Use lightweight queries for bulk**: Use `get_task_summary()` instead of `get_task_context()` when querying many tasks
4. **Use templates for standard patterns**: Use `create_task_from_template()` when creating similar tasks
5. **Document progress frequently**: Use `add_task_update()` throughout work
6. **Check for stale tasks**: Use `query_stale_tasks()` to monitor system health
7. **Use appropriate search**: Use `search_tasks()` for keywords, `query_tasks()` for structured filters

## Error Handling Patterns

All functions follow consistent error handling:
- **Task not found**: Returns `{"success": False, "error": "Task X not found..."}`
- **Validation errors**: Handled by framework before function is called
- **Database errors**: Rare, retry with exponential backoff if connection issues
- **Permission errors**: Returns error if agent_id doesn't match (for owner-only operations)

When to retry:
- Database connection issues → Retry with exponential backoff
- Temporary network issues → Retry with exponential backoff

When NOT to retry:
- Task not found → Verify task_id is correct
- Permission denied → Check agent_id matches
- Validation errors → Fix parameters and retry
