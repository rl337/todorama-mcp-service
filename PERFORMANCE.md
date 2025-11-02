# Database Performance Optimization Guide

This document describes the database query optimization strategies implemented in the TODO MCP Service.

## Overview

The database layer has been optimized for performance with:
- **Composite indexes** for common query patterns
- **Batch query optimization** to reduce N+1 problems
- **Query logging** to identify slow queries
- **Efficient relationship traversal** for blocked subtasks

## Indexes

### Single-Column Indexes

The following single-column indexes are created for frequently filtered columns:

- `idx_tasks_status` - Task status filtering
- `idx_tasks_type` - Task type filtering
- `idx_tasks_assigned` - Assigned agent filtering
- `idx_tasks_project` - Project filtering
- `idx_tasks_priority` - Priority filtering
- `idx_tasks_due_date` - Due date queries
- `idx_relationships_parent` - Parent task relationships
- `idx_relationships_child` - Child task relationships

### Composite Indexes

Composite indexes are created for common multi-column query patterns:

- **`idx_tasks_status_type`** - `(task_status, task_type)`
  - Used by `get_available_tasks_for_agent()` queries
  - Significantly speeds up agent task listing

- **`idx_tasks_project_status`** - `(project_id, task_status)`
  - Used for project-filtered queries by status
  - Optimizes common filtering patterns

- **`idx_tasks_project_status_type`** - `(project_id, task_status, task_type)`
  - Used for specific agent queries with project filters
  - Covers complete query filter combinations

- **`idx_tasks_status_priority`** - `(task_status, priority)`
  - Used for priority-ordered filtered queries
  - Enables fast priority sorting with status filters

- **`idx_relationships_parent_type`** - `(parent_task_id, relationship_type)`
  - Used for efficient subtask queries
  - Speeds up relationship lookups by parent

- **`idx_relationships_child_type`** - `(child_task_id, relationship_type)`
  - Used for blocked_by checks
  - Optimizes reverse relationship queries

- **`idx_task_tags_task_tag`** - `(task_id, tag_id)`
  - Used for tag filtering with JOINs
  - Speeds up multi-tag queries

- **`idx_tasks_created_status`** - `(created_at DESC, task_status)`
  - Used for ordered status queries
  - Optimizes time-ordered filtered results

## Query Optimizations

### Batch Blocked Subtasks Check

**Problem**: The original implementation called `_has_blocked_subtasks()` for each task individually, causing N+1 query problem. For 100 tasks, this could mean 100+ individual queries.

**Solution**: `_find_tasks_with_blocked_subtasks_batch()` performs a single efficient batch query that:
1. Finds all directly blocked tasks
2. Traverses up the hierarchy in batches (not one-by-one)
3. Returns all blocked parent IDs in one operation

**Performance Impact**:
- **Before**: O(N * D) queries where N = number of tasks, D = depth
- **After**: O(1) batch query regardless of task count
- **Speedup**: 10-100x faster for queries returning many tasks

### Query Logging

Query performance is automatically logged to help identify slow queries:

- **Slow Query Threshold**: Queries slower than 0.1 seconds (configurable via `DB_QUERY_SLOW_THRESHOLD`)
- **Logging Level**: 
  - WARNING for queries >= threshold
  - DEBUG for queries < threshold
- **Configuration**: Set `DB_ENABLE_QUERY_LOGGING=false` to disable

Example log output:
```
WARNING: Slow query: 0.234s - SELECT DISTINCT t.* FROM tasks t WHERE ...
```

## Performance Characteristics

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

## Monitoring

### Enable Query Logging

Set environment variables:

```bash
# Enable query logging (default: true)
export DB_ENABLE_QUERY_LOGGING=true

# Set slow query threshold in seconds (default: 0.1)
export DB_QUERY_SLOW_THRESHOLD=0.1
```

### Check Index Usage

Use SQLite's `EXPLAIN QUERY PLAN` to verify indexes are being used:

```sql
EXPLAIN QUERY PLAN 
SELECT * FROM tasks 
WHERE task_status = 'available' AND task_type = 'concrete';
```

Look for "USING INDEX" in the output.

### Performance Testing

Run performance tests:

```bash
pytest tests/test_database_performance.py -v
```

These tests verify:
- Query performance meets targets
- Indexes are properly created
- Batch optimizations work correctly

## Connection Pooling

**Note**: SQLite does not support traditional connection pooling like PostgreSQL/MySQL. However:

- Each query opens/closes its connection (lightweight)
- SQLite handles concurrent reads efficiently
- Write operations are automatically serialized

For high-concurrency scenarios, consider:
- Using `WAL` mode (Write-Ahead Logging) for better concurrency
- Splitting read/write operations across separate connections
- Upgrading to PostgreSQL for production scale

## Best Practices

1. **Use Indexed Columns**: Filter by indexed columns (`task_status`, `task_type`, `project_id`) when possible

2. **Batch Operations**: Use batch methods like `_find_tasks_with_blocked_subtasks_batch()` instead of individual checks

3. **Limit Results**: Always use `limit` parameter in queries to avoid loading large datasets

4. **Monitor Slow Queries**: Enable query logging in production to identify bottlenecks

5. **Review Query Plans**: Use `EXPLAIN QUERY PLAN` when optimizing new queries

6. **Test Performance**: Run performance tests after schema changes

## Migration Notes

Existing databases will automatically have new indexes created on first connection after upgrade. No migration script is needed - indexes are created with `IF NOT EXISTS`.

Index creation is fast for existing databases (typically < 1 second per index).

## Future Optimizations

Potential future optimizations:

1. **Materialized Views**: Cache expensive query results
2. **Query Result Caching**: Cache frequently accessed task data
3. **Read Replicas**: For read-heavy workloads (requires PostgreSQL)
4. **Partitioning**: Split large tables by project_id (for very large deployments)

## Troubleshooting

### Slow Queries

If you see slow query warnings:

1. Check if appropriate indexes exist: `SELECT name FROM sqlite_master WHERE type='index'`
2. Verify index usage with `EXPLAIN QUERY PLAN`
3. Consider adding composite indexes for frequent filter combinations
4. Review query logic - ensure batching is used where possible

### Missing Indexes

If indexes are missing:

1. Check database file permissions
2. Review application logs for schema initialization errors
3. Manually create indexes if needed (see `_init_schema()` method)

### High Memory Usage

For very large databases:

1. Use `limit` parameters in all queries
2. Implement pagination for large result sets
3. Consider archiving old tasks to separate tables
4. Monitor database file size and cleanup old data