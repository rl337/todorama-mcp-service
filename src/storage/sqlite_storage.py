"""
SQLite implementation of storage interface.
Wraps TodoDatabase to provide clean abstraction.
"""
from typing import Optional, List, Dict, Any
from database import TodoDatabase
from .interface import StorageInterface


class SQLiteStorage(StorageInterface):
    """SQLite-based storage implementation."""
    
    def __init__(self, db_path: str):
        """Initialize SQLite storage."""
        self._db = TodoDatabase(db_path)
    
    # Task operations
    def create_task(self, **kwargs) -> int:
        """Create a task and return its ID."""
        return self._db.create_task(**kwargs)
    
    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get a task by ID."""
        task = self._db.get_task(task_id)
        return dict(task) if task else None
    
    def update_task(self, task_id: int, **kwargs) -> bool:
        """Update a task."""
        # TODO: Implement update_task in database or create adapter
        # For now, delegate to database methods
        return True
    
    def list_tasks(self, **filters) -> List[Dict[str, Any]]:
        """List tasks with optional filters."""
        # TODO: Implement filtered query
        tasks = self._db.query_tasks(**filters)
        return [dict(task) for task in tasks] if tasks else []
    
    # Project operations
    def create_project(self, **kwargs) -> int:
        """Create a project and return its ID."""
        return self._db.create_project(**kwargs)
    
    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get a project by ID."""
        project = self._db.get_project(project_id)
        return dict(project) if project else None
    
    def list_projects(self) -> List[Dict[str, Any]]:
        """List all projects."""
        projects = self._db.list_projects()
        return [dict(project) for project in projects] if projects else []
    
    # Expose database for complex operations (will be abstracted over time)
    @property
    def db(self):
        """Access underlying database for complex operations."""
        return self._db










