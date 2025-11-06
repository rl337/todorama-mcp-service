"""
Storage interface - defines the contract for all storage backends.
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class StorageInterface(ABC):
    """Abstract interface for storage operations."""
    
    # Task operations
    @abstractmethod
    def create_task(self, **kwargs) -> int:
        """Create a task and return its ID."""
        pass
    
    @abstractmethod
    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get a task by ID."""
        pass
    
    @abstractmethod
    def update_task(self, task_id: int, **kwargs) -> bool:
        """Update a task."""
        pass
    
    @abstractmethod
    def list_tasks(self, **filters) -> List[Dict[str, Any]]:
        """List tasks with optional filters."""
        pass
    
    # Project operations
    @abstractmethod
    def create_project(self, **kwargs) -> int:
        """Create a project and return its ID."""
        pass
    
    @abstractmethod
    def get_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get a project by ID."""
        pass
    
    @abstractmethod
    def list_projects(self) -> List[Dict[str, Any]]:
        """List all projects."""
        pass
    
    # Add more operations as needed...










