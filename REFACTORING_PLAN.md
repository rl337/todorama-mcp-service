# Main.py Refactoring Plan

## Current State
- **Lines**: 7,689
- **Route definitions**: 197
- **Function definitions**: 201
- **Global initializations**: 22

## Target State
- **main.py**: < 50 lines - just imports factory and runs app
- **app/factory.py**: All initialization logic
- **api/routes/**: All route handlers (already started)
- **app/middleware/**: Middleware setup
- **app/handlers/**: Exception handlers

## Extraction Plan

### 1. Initialization Logic → `app/factory.py`
- Database initialization (lines 153-172)
- Backup manager initialization (lines 174-195)
- Conversation storage initialization (lines 197-263)
- Job queue initialization (lines 206-215)
- NATS queue initialization (lines 217-235)
- Signal handlers (lines 269-277)
- Lifespan management (lines 285-340)

### 2. Routes → `api/routes/` modules
- ✅ Tasks routes (started - create_task, get_task)
- ⏳ Remaining task routes (query_tasks, lock_task, complete_task, etc.)
- ⏳ Project routes (already in api/routes/projects.py but duplicates in main.py)
- ⏳ Template routes
- ⏳ Recurring task routes
- ⏳ Bulk operation routes
- ⏳ Admin routes
- ⏳ Import/export routes
- ⏳ Attachment routes
- ⏳ Tag routes
- ⏳ GitHub integration routes
- ⏳ Slack routes
- ⏳ Health/metrics routes

### 3. Middleware → `app/middleware/`
- Already extracted to middleware/setup.py
- Just need to call from factory

### 4. Exception Handlers → `app/handlers/`
- Already extracted to exceptions/handlers.py
- Just need to call from factory

### 5. App Configuration → `app/factory.py`
- FastAPI app creation (lines 344-349)
- Router registration (lines 357-363)
- Static files mounting (lines 366-368)
- Root endpoint (lines 371-384)

### 6. Main Entry Point → `main.py` (minimal)
```python
"""Main entry point for TODO MCP Service."""
from app import create_app
import uvicorn

if __name__ == "__main__":
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Implementation Order
1. ✅ Create app/factory.py structure
2. ⏳ Extract initialization logic
3. ⏳ Extract app configuration
4. ⏳ Extract remaining routes
5. ⏳ Simplify main.py
6. ⏳ Test and verify










