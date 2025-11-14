"""
Repository pattern implementation for todorama data access layer.

This module provides repository classes that abstract database operations
for core entities (Task, Project, Organization), following the standardized
repository pattern used across MCP services.

Repositories wrap TodoDatabase methods and provide a clean interface for
services to interact with data, enabling better separation of concerns,
testability, and maintainability.
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from todorama.database import TodoDatabase


class TaskRepository:
    """Repository for task operations."""

    def __init__(self, db: "TodoDatabase"):
        """Initialize repository with TodoDatabase instance.
        
        Args:
            db: TodoDatabase instance for database access
        """
        self.db = db

    def create(
        self,
        title: str,
        task_type: str,
        task_instruction: str,
        verification_instruction: str,
        agent_id: str,
        project_id: Optional[int] = None,
        notes: Optional[str] = None,
        priority: Optional[str] = None,
        estimated_hours: Optional[float] = None,
        due_date: Optional[datetime] = None,
        organization_id: Optional[int] = None,
    ) -> int:
        """Create a new task.
        
        Args:
            title: Task title
            task_type: Task type ('concrete', 'abstract', 'epic')
            task_instruction: Task instruction text
            verification_instruction: Verification instruction text
            agent_id: Agent ID creating the task
            project_id: Optional project ID
            notes: Optional notes
            priority: Optional priority ('low', 'medium', 'high', 'critical')
            estimated_hours: Optional estimated hours
            due_date: Optional due date
            organization_id: Optional organization ID for multi-tenancy
            
        Returns:
            Created task ID
        """
        return self.db.create_task(
            title=title,
            task_type=task_type,
            task_instruction=task_instruction,
            verification_instruction=verification_instruction,
            agent_id=agent_id,
            project_id=project_id,
            notes=notes,
            priority=priority,
            estimated_hours=estimated_hours,
            due_date=due_date,
            organization_id=organization_id,
        )

    def get_by_id(
        self, task_id: int, organization_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Get task by ID.
        
        Args:
            task_id: Task ID
            organization_id: Optional organization ID for multi-tenancy filtering
            
        Returns:
            Task dictionary if found, None otherwise
        """
        return self.db.get_task(task_id, organization_id=organization_id)

    def list(
        self,
        task_type: Optional[str] = None,
        task_status: Optional[str] = None,
        assigned_agent: Optional[str] = None,
        project_id: Optional[int] = None,
        priority: Optional[str] = None,
        organization_id: Optional[int] = None,
        limit: int = 100,
        order_by: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List tasks with filters.
        
        Args:
            task_type: Optional task type filter
            task_status: Optional task status filter
            assigned_agent: Optional assigned agent filter
            project_id: Optional project ID filter
            priority: Optional priority filter
            organization_id: Optional organization ID for multi-tenancy
            limit: Maximum number of results
            order_by: Optional ordering (e.g., 'priority', 'created_at')
            
        Returns:
            List of task dictionaries
        """
        return self.db.query_tasks(
            task_type=task_type,
            task_status=task_status,
            assigned_agent=assigned_agent,
            project_id=project_id,
            priority=priority,
            organization_id=organization_id,
            limit=limit,
            order_by=order_by,
        )

    def search(
        self, query: str, organization_id: Optional[int] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Search tasks by query string.
        
        Args:
            query: Search query string
            organization_id: Optional organization ID for multi-tenancy
            limit: Maximum number of results
            
        Returns:
            List of matching task dictionaries
        """
        return self.db.search_tasks(query, limit=limit, organization_id=organization_id)

    def update(
        self, task_id: int, **kwargs: Any
    ) -> bool:
        """Update an existing task.
        
        Note: This method wraps TodoDatabase's task update functionality.
        Specific update methods may need to be called directly on the database
        for complex updates.
        
        Args:
            task_id: Task ID to update
            **kwargs: Fields to update (title, notes, priority, etc.)
            
        Returns:
            True if update was successful, False otherwise
        """
        # TODO: Implement update_task in TodoDatabase or create adapter
        # For now, this is a placeholder that can be extended
        # Complex updates may need to call specific database methods
        raise NotImplementedError(
            "Task update not yet implemented. Use specific database methods for updates."
        )

    def delete(self, task_id: int) -> bool:
        """Delete a task.
        
        Note: This method wraps TodoDatabase's task deletion functionality.
        Task deletion may have cascading effects on relationships.
        
        Args:
            task_id: Task ID to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        # TODO: Implement delete_task in TodoDatabase or create adapter
        # For now, this is a placeholder that can be extended
        raise NotImplementedError(
            "Task deletion not yet implemented. Use specific database methods for deletion."
        )


class ProjectRepository:
    """Repository for project operations."""

    def __init__(self, db: "TodoDatabase"):
        """Initialize repository with TodoDatabase instance.
        
        Args:
            db: TodoDatabase instance for database access
        """
        self.db = db

    def create(
        self,
        name: str,
        local_path: str,
        origin_url: Optional[str] = None,
        description: Optional[str] = None,
        organization_id: Optional[int] = None,
    ) -> int:
        """Create a new project.
        
        Args:
            name: Project name
            local_path: Local filesystem path
            origin_url: Optional origin URL (e.g., GitHub repository)
            description: Optional project description
            organization_id: Organization ID (required for multi-tenancy)
            
        Returns:
            Created project ID
            
        Raises:
            ValueError: If organization_id is required but not provided
        """
        return self.db.create_project(
            name=name,
            local_path=local_path,
            origin_url=origin_url,
            description=description,
            organization_id=organization_id,
        )

    def get_by_id(
        self, project_id: int, organization_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Get project by ID.
        
        Args:
            project_id: Project ID
            organization_id: Optional organization ID for multi-tenancy filtering
            
        Returns:
            Project dictionary if found, None otherwise
        """
        return self.db.get_project(project_id, organization_id=organization_id)

    def get_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get project by name.
        
        Args:
            name: Project name
            
        Returns:
            Project dictionary if found, None otherwise
        """
        return self.db.get_project_by_name(name)

    def list(self, organization_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """List projects with optional organization filter.
        
        Args:
            organization_id: Optional organization ID for multi-tenancy filtering
            
        Returns:
            List of project dictionaries
        """
        return self.db.list_projects(organization_id=organization_id)

    def update(
        self,
        project_id: int,
        name: Optional[str] = None,
        local_path: Optional[str] = None,
        origin_url: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Update an existing project.
        
        Args:
            project_id: Project ID to update
            name: Optional new name
            local_path: Optional new local path
            origin_url: Optional new origin URL
            description: Optional new description
            
        Returns:
            True if update was successful, False otherwise
        """
        # TODO: Implement update_project in TodoDatabase or create adapter
        # For now, this is a placeholder that can be extended
        raise NotImplementedError(
            "Project update not yet implemented. Use specific database methods for updates."
        )

    def delete(self, project_id: int) -> bool:
        """Delete a project.
        
        Note: Project deletion may have cascading effects on tasks.
        
        Args:
            project_id: Project ID to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        # TODO: Implement delete_project in TodoDatabase or create adapter
        # For now, this is a placeholder that can be extended
        raise NotImplementedError(
            "Project deletion not yet implemented. Use specific database methods for deletion."
        )


class OrganizationRepository:
    """Repository for organization operations."""

    def __init__(self, db: "TodoDatabase"):
        """Initialize repository with TodoDatabase instance.
        
        Args:
            db: TodoDatabase instance for database access
        """
        self.db = db

    def create(
        self, name: str, description: Optional[str] = None
    ) -> int:
        """Create a new organization.
        
        Args:
            name: Organization name
            description: Optional organization description
            
        Returns:
            Created organization ID
        """
        return self.db.create_organization(name=name, description=description)

    def get_by_id(self, organization_id: int) -> Optional[Dict[str, Any]]:
        """Get organization by ID.
        
        Args:
            organization_id: Organization ID
            
        Returns:
            Organization dictionary if found, None otherwise
        """
        return self.db.get_organization(organization_id)

    def get_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Get organization by slug.
        
        Args:
            slug: Organization slug (URL-friendly identifier)
            
        Returns:
            Organization dictionary if found, None otherwise
        """
        return self.db.get_organization_by_slug(slug)

    def list(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """List organizations.
        
        Args:
            user_id: Optional user ID to filter organizations the user is a member of
            
        Returns:
            List of organization dictionaries
        """
        return self.db.list_organizations(user_id=user_id)

    def update(
        self,
        organization_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Update an existing organization.
        
        Args:
            organization_id: Organization ID to update
            name: Optional new name
            description: Optional new description
            
        Returns:
            True if update was successful, False otherwise
        """
        return self.db.update_organization(
            organization_id=organization_id, name=name, description=description
        )

    def delete(self, organization_id: int) -> bool:
        """Delete an organization.
        
        Note: Organization deletion cascades to teams, roles, and members.
        
        Args:
            organization_id: Organization ID to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        return self.db.delete_organization(organization_id)
