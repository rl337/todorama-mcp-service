"""
Tag service - business logic for tag operations.
This layer contains no HTTP framework dependencies.
Handles all business logic including validation and error handling.
"""
import logging
from typing import Optional, Dict, Any, List

from todorama.database import TodoDatabase

logger = logging.getLogger(__name__)


class TagService:
    """Service for tag business logic."""
    
    def __init__(self, db: TodoDatabase):
        """Initialize tag service with database dependency."""
        self.db = db
    
    def create_tag(self, name: str) -> Dict[str, Any]:
        """
        Create a new tag (or return existing tag if name already exists).
        
        Args:
            name: Tag name
            
        Returns:
            Created tag data as dictionary
            
        Raises:
            ValueError: If tag name is empty or whitespace
            Exception: If tag creation fails
        """
        # Validate tag name
        if not name or not name.strip():
            raise ValueError("Tag name cannot be empty or whitespace")
        
        # Create tag (database method handles duplicate detection)
        try:
            tag_id = self.db.create_tag(name.strip())
        except Exception as e:
            logger.error(f"Failed to create tag: {str(e)}", exc_info=True)
            raise Exception("Failed to create tag. Please try again or contact support if the issue persists.")
        
        # Retrieve created tag
        tag = self.db.get_tag(tag_id)
        if not tag:
            logger.error(f"Tag {tag_id} was created but could not be retrieved")
            raise Exception("Tag was created but could not be retrieved. Please check tag status.")
        
        return dict(tag)
    
    def get_tag(self, tag_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a tag by ID.
        
        Args:
            tag_id: Tag ID
            
        Returns:
            Tag data as dictionary, or None if not found
        """
        tag = self.db.get_tag(tag_id)
        return dict(tag) if tag else None
    
    def get_tag_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get a tag by name.
        
        Args:
            name: Tag name
            
        Returns:
            Tag data as dictionary, or None if not found
        """
        tag = self.db.get_tag_by_name(name)
        return dict(tag) if tag else None
    
    def list_tags(self) -> List[Dict[str, Any]]:
        """
        List all tags.
        
        Returns:
            List of tag dictionaries
        """
        tags = self.db.list_tags()
        return [dict(tag) for tag in tags]
    
    def assign_tag_to_task(self, task_id: int, tag_id: int) -> Dict[str, Any]:
        """
        Assign a tag to a task.
        
        Args:
            task_id: Task ID
            tag_id: Tag ID
            
        Returns:
            Dictionary with success status and message
            
        Raises:
            ValueError: If task or tag not found
            Exception: If assignment fails
        """
        # Verify task exists
        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found. Please verify the task_id is correct.")
        
        # Verify tag exists
        tag = self.db.get_tag(tag_id)
        if not tag:
            raise ValueError(f"Tag {tag_id} not found. Please verify the tag_id is correct.")
        
        try:
            self.db.assign_tag_to_task(task_id, tag_id)
            logger.info(f"Assigned tag {tag_id} to task {task_id}")
            return {
                "success": True,
                "task_id": task_id,
                "tag_id": tag_id,
                "message": f"Tag {tag_id} assigned to task {task_id}"
            }
        except Exception as e:
            logger.error(f"Failed to assign tag {tag_id} to task {task_id}: {str(e)}", exc_info=True)
            raise Exception(f"Failed to assign tag: {str(e)}")
    
    def remove_tag_from_task(self, task_id: int, tag_id: int) -> Dict[str, Any]:
        """
        Remove a tag from a task.
        
        Args:
            task_id: Task ID
            tag_id: Tag ID
            
        Returns:
            Dictionary with success status and message
            
        Raises:
            ValueError: If task not found
            Exception: If removal fails
        """
        # Verify task exists
        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found. Please verify the task_id is correct.")
        
        try:
            self.db.remove_tag_from_task(task_id, tag_id)
            logger.info(f"Removed tag {tag_id} from task {task_id}")
            return {
                "success": True,
                "task_id": task_id,
                "tag_id": tag_id,
                "message": f"Tag {tag_id} removed from task {task_id}"
            }
        except Exception as e:
            logger.error(f"Failed to remove tag {tag_id} from task {task_id}: {str(e)}", exc_info=True)
            raise Exception(f"Failed to remove tag: {str(e)}")
    
    def get_task_tags(self, task_id: int) -> List[Dict[str, Any]]:
        """
        Get all tags assigned to a task.
        
        Args:
            task_id: Task ID
            
        Returns:
            List of tag dictionaries
            
        Raises:
            ValueError: If task not found
        """
        # Verify task exists
        task = self.db.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found. Please verify the task_id is correct.")
        
        tags = self.db.get_task_tags(task_id)
        return [dict(tag) for tag in tags]
    
    def delete_tag(self, tag_id: int) -> Dict[str, Any]:
        """
        Delete a tag (cascades to task_tags via foreign key).
        
        Args:
            tag_id: Tag ID
            
        Returns:
            Dictionary with success status and message
            
        Raises:
            ValueError: If tag not found
            Exception: If deletion fails
        """
        # Verify tag exists
        tag = self.db.get_tag(tag_id)
        if not tag:
            raise ValueError(f"Tag {tag_id} not found. Please verify the tag_id is correct.")
        
        try:
            self.db.delete_tag(tag_id)
            logger.info(f"Deleted tag {tag_id}")
            return {
                "success": True,
                "tag_id": tag_id,
                "message": f"Tag {tag_id} deleted"
            }
        except Exception as e:
            logger.error(f"Failed to delete tag {tag_id}: {str(e)}", exc_info=True)
            raise Exception(f"Failed to delete tag: {str(e)}")
