"""
Task entity with command pattern methods.
All task operations are exposed as methods that can be called via /api/Task/<method>
"""
from typing import Dict, Any, List, Optional
from fastapi import HTTPException
from pydantic import ValidationError
from datetime import datetime, UTC

from api.entities.base_entity import BaseEntity
from models.task_models import TaskCreate, TaskUpdate, TaskResponse
from services.task_service import TaskService


class TaskEntity(BaseEntity):
    """Task entity with command pattern methods."""
    
    def __init__(self, db, auth_info: Optional[Dict[str, Any]] = None):
        """Initialize task entity."""
        super().__init__(db, auth_info)
        self.service = TaskService(db)
    
    def create(self, **kwargs) -> Dict[str, Any]:
        """
        Create a new task.
        
        POST /api/Task/create
        Body: TaskCreate model fields directly (title, task_type, etc.)
        """
        try:
            # Extract task data from kwargs (allow both direct fields and task_data wrapper)
            if "task_data" in kwargs:
                task_data = kwargs["task_data"]
            else:
                task_data = kwargs
            
            # Convert dict to TaskCreate model - catch validation errors
            try:
                task_create = TaskCreate(**task_data)
            except ValidationError as e:
                # Convert Pydantic validation errors to 422 HTTPException
                # Format errors in FastAPI style
                errors = []
                for error in e.errors():
                    errors.append({
                        "loc": list(error["loc"]),
                        "msg": error["msg"],
                        "type": error["type"]
                    })
                raise HTTPException(
                    status_code=422,
                    detail=errors  # FastAPI format: list of error objects
                )
            
            created_task = self.service.create_task(task_create, self.auth_info)
            return created_task
        except HTTPException:
            raise
        except Exception as e:
            self._handle_error(e, "Failed to create task")
    
    def get(self, task_id) -> Dict[str, Any]:
        """
        Get a task by ID.
        
        GET /api/Task/get?task_id=123
        """
        try:
            # Convert to int and validate
            try:
                task_id = int(task_id)
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=422,
                    detail=f"task_id must be an integer, got {task_id}"
                )
            
            # Validate task_id is positive
            if task_id <= 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"task_id must be a positive integer, got {task_id}"
                )
            task = self.service.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            return task
        except HTTPException:
            raise
        except Exception as e:
            self._handle_error(e, "Failed to get task")
    
    def list(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        List/query tasks with optional filters.
        
        GET /api/Task/list?task_type=concrete&task_status=available
        """
        try:
            # Use database query_tasks method with filters
            filters = filters or {}
            tasks = self.db.query_tasks(
                task_type=filters.get("task_type"),
                task_status=filters.get("task_status"),
                assigned_agent=filters.get("assigned_agent"),
                project_id=filters.get("project_id"),
                priority=filters.get("priority"),
                order_by=filters.get("order_by"),
                search=filters.get("search"),
                limit=filters.get("limit", 100)
            )
            return [dict(task) for task in tasks]
        except Exception as e:
            self._handle_error(e, "Failed to list tasks")
    
    def update(self, task_id: int, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a task.
        
        PATCH /api/Task/get?task_id=123
        Body: {"task_status": "in_progress", "verification_status": "verified", "notes": "..."}
        """
        try:
            # Validate update data using TaskUpdate model
            try:
                task_update = TaskUpdate(**update_data)
            except ValidationError as e:
                # Convert Pydantic validation errors to 422 HTTPException
                errors = []
                for error in e.errors():
                    errors.append({
                        "loc": list(error["loc"]),
                        "msg": error["msg"],
                        "type": error["type"]
                    })
                raise HTTPException(
                    status_code=422,
                    detail=errors  # FastAPI format: list of error objects
                )
            
            # Check if task exists
            task = self.db.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            
            # Update task fields in database
            conn = self.db._get_connection()
            try:
                cursor = conn.cursor()
                
                # Build UPDATE query dynamically based on provided fields
                updates = []
                params = []
                
                if task_update.task_status is not None:
                    updates.append("task_status = ?")
                    params.append(task_update.task_status)
                
                if task_update.verification_status is not None:
                    updates.append("verification_status = ?")
                    params.append(task_update.verification_status)
                
                if task_update.notes is not None:
                    updates.append("notes = ?")
                    params.append(task_update.notes)
                
                if updates:
                    updates.append("updated_at = CURRENT_TIMESTAMP")
                    params.append(task_id)
                    
                    query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
                    cursor.execute(query, params)
                    conn.commit()
                
                # Get updated task
                updated_task = self.db.get_task(task_id)
                return dict(updated_task)
            finally:
                self.db.adapter.close(conn)
        except HTTPException:
            raise
        except Exception as e:
            self._handle_error(e, "Failed to update task")
    
    def delete(self, task_id: int) -> Dict[str, Any]:
        """
        Delete a task.
        
        POST /api/Task/delete
        Body: {"task_id": 123}
        """
        try:
            task = self.db.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            
            # Delete via database (if method exists, otherwise mark as cancelled)
            if hasattr(self.db, 'delete_task'):
                self.db.delete_task(task_id)
            else:
                # Fallback: mark as cancelled if delete not available
                self.db.update_task_status(task_id, "cancelled")
            return {"success": True, "task_id": task_id}
        except Exception as e:
            self._handle_error(e, "Failed to delete task")
    
    def lock(self, task_id: int, agent_id: str) -> Dict[str, Any]:
        """
        Lock a task for an agent.
        
        POST /api/Task/lock
        Body: {"task_id": 123, "agent_id": "agent-1"}
        """
        try:
            # Check if task exists first
            task = self.db.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            
            success = self.db.lock_task(task_id, agent_id)
            if not success:
                raise HTTPException(status_code=409, detail="Task is already locked")
            task = self.db.get_task(task_id)
            return dict(task)
        except HTTPException:
            raise
        except Exception as e:
            self._handle_error(e, "Failed to lock task")
    
    def unlock(self, task_id: int, agent_id: str) -> Dict[str, Any]:
        """
        Unlock a task.
        
        POST /api/Task/unlock
        Body: {"task_id": 123, "agent_id": "agent-1"}
        """
        try:
            self.db.unlock_task(task_id, agent_id)
            task = self.db.get_task(task_id)
            return dict(task)
        except Exception as e:
            self._handle_error(e, "Failed to unlock task")
    
    def complete(self, task_id: int, agent_id: str, actual_hours: Optional[float] = None, notes: Optional[str] = None) -> Dict[str, Any]:
        """
        Complete a task.
        
        POST /api/Task/complete
        Body: {"task_id": 123, "agent_id": "agent-1", "actual_hours": 2.5, "notes": "Done"}
        """
        try:
            self.db.complete_task(task_id, agent_id, actual_hours=actual_hours, notes=notes)
            task = self.db.get_task(task_id)
            return dict(task)
        except Exception as e:
            self._handle_error(e, "Failed to complete task")
    
    def search(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Search tasks by text.
        
        GET /api/Task/search?query=test&limit=50
        """
        try:
            tasks = self.db.search_tasks(query, limit=limit)
            return [dict(task) for task in tasks]
        except Exception as e:
            self._handle_error(e, "Failed to search tasks")
    
    def export(self, format: str = "json", filters: Optional[Dict[str, Any]] = None) -> Any:
        """
        Export tasks in specified format.
        
        GET /api/Task/export/json or /api/Task/export/csv
        Query params: project_id, task_status, start_date, end_date, etc.
        """
        try:
            from fastapi.responses import Response
            filters = filters or {}
            # Get tasks with filters
            tasks = self.db.query_tasks(
                task_type=filters.get("task_type"),
                task_status=filters.get("task_status"),
                project_id=filters.get("project_id"),
                limit=filters.get("limit", 10000)
            )
            
            if format == "json":
                import json
                # Return as dict with "tasks" key to match API expectations
                tasks_data = {"tasks": [dict(task) for task in tasks]}
                content = json.dumps(tasks_data, indent=2)
                return Response(
                    content=content,
                    media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=tasks.json"}
                )
            elif format == "csv":
                import csv
                import io
                output = io.StringIO()
                if tasks:
                    writer = csv.DictWriter(output, fieldnames=dict(tasks[0]).keys())
                    writer.writeheader()
                    for task in tasks:
                        writer.writerow(dict(task))
                content = output.getvalue()
                return Response(
                    content=content,
                    media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=tasks.csv"}
                )
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
        except HTTPException:
            raise
        except Exception as e:
            self._handle_error(e, "Failed to export tasks")
    
    def overdue(self, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get overdue tasks.
        
        GET /api/Task/overdue
        Query params: project_id, etc.
        """
        try:
            filters = filters or {}
            tasks = self.db.get_overdue_tasks(limit=filters.get("limit", 100))
            # Filter by project_id if provided (database method doesn't support it)
            if filters.get("project_id"):
                tasks = [t for t in tasks if dict(t).get("project_id") == filters.get("project_id")]
            return {"tasks": [dict(task) for task in tasks]}
        except Exception as e:
            self._handle_error(e, "Failed to get overdue tasks")
    
    def approaching_deadline(self, days_ahead: int = 3, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Get tasks approaching deadline.
        
        GET /api/Task/approaching-deadline?days_ahead=3
        Query params: days_ahead, project_id, etc.
        """
        try:
            filters = filters or {}
            days = filters.get("days_ahead", days_ahead)
            # Database method only takes days_ahead, not project_id
            tasks = self.db.get_tasks_approaching_deadline(days_ahead=days)
            # Filter by project_id if provided
            if filters.get("project_id"):
                tasks = [t for t in tasks if dict(t).get("project_id") == filters.get("project_id")]
            return {"tasks": [dict(task) for task in tasks]}
        except Exception as e:
            self._handle_error(e, "Failed to get tasks approaching deadline")
    
    def activity_feed(self, task_id: Optional[int] = None, agent_id: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 1000) -> Dict[str, Any]:
        """
        Get activity feed showing all task updates, completions, and relationship changes.
        
        GET /api/Task/activity-feed?task_id=123&agent_id=agent-1&start_date=2024-01-01&end_date=2024-12-31&limit=100
        """
        try:
            from datetime import datetime
            # Validate date formats if provided
            if start_date:
                try:
                    if start_date.endswith('Z'):
                        datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                    else:
                        datetime.fromisoformat(start_date)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid start_date format '{start_date}'. Must be ISO 8601 format."
                    )
            
            if end_date:
                try:
                    if end_date.endswith('Z'):
                        datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    else:
                        datetime.fromisoformat(end_date)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid end_date format '{end_date}'. Must be ISO 8601 format."
                    )
            
            feed = self.db.get_activity_feed(
                task_id=task_id,
                agent_id=agent_id,
                start_date=start_date,
                end_date=end_date,
                limit=limit
            )
            return {
                "feed": feed,
                "count": len(feed),
                "filters": {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "limit": limit
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            self._handle_error(e, "Failed to get activity feed")
    
    def get_stale(self, hours: Optional[int] = None) -> Dict[str, Any]:
        """
        Get stale tasks (tasks in_progress longer than timeout).
        
        GET /api/Task/get_stale?hours=24
        """
        try:
            tasks = self.db.get_stale_tasks(hours=hours)
            return {
                "stale_tasks": [dict(task) for task in tasks],
                "count": len(tasks),
                "hours": hours or 24
            }
        except Exception as e:
            self._handle_error(e, "Failed to get stale tasks")
    
    def unlock_stale(self, hours: Optional[int] = None, system_agent_id: str = "system") -> Dict[str, Any]:
        """
        Unlock stale tasks.
        
        POST /api/Task/unlock_stale
        Body: {"hours": 24, "system_agent_id": "system"}
        """
        try:
            count = self.db.unlock_stale_tasks(hours=hours, system_agent_id=system_agent_id)
            return {
                "success": True,
                "unlocked_count": count,
                "hours": hours or 24
            }
        except Exception as e:
            self._handle_error(e, "Failed to unlock stale tasks")

