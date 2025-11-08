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
    
    def get_relationships(self, task_id) -> Dict[str, Any]:
        """
        Get relationships for a task.
        
        GET /api/Task/{task_id}/relationships
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
            
            if task_id <= 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"task_id must be a positive integer, got {task_id}"
                )
            
            # Verify task exists
            task = self.db.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            
            # Get relationships
            relationships = self.db.get_related_tasks(task_id)
            return {"relationships": relationships}
        except HTTPException:
            raise
        except Exception as e:
            self._handle_error(e, "Failed to get task relationships")
    
    def list(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        List/query tasks with optional filters.
        
        GET /api/Task/list?task_type=concrete&task_status=available
        """
        try:
            # Use database query_tasks method with filters
            filters = filters or {}
            
            # Validate enum values
            valid_task_types = ["concrete", "abstract", "epic"]
            valid_task_statuses = ["available", "in_progress", "complete", "blocked", "cancelled"]
            valid_priorities = ["low", "medium", "high", "critical"]
            valid_order_by = ["priority", "priority_asc"]
            
            if filters.get("task_type") and filters["task_type"] not in valid_task_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid task_type '{filters['task_type']}'. Must be one of: {', '.join(valid_task_types)}"
                )
            
            if filters.get("task_status") and filters["task_status"] not in valid_task_statuses:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid task_status '{filters['task_status']}'. Must be one of: {', '.join(valid_task_statuses)}"
                )
            
            if filters.get("priority") and filters["priority"] not in valid_priorities:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid priority '{filters['priority']}'. Must be one of: {', '.join(valid_priorities)}"
                )
            
            if filters.get("order_by") and filters["order_by"] not in valid_order_by:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid order_by '{filters['order_by']}'. Must be one of: {', '.join(valid_order_by)}"
                )
            
            # Validate numeric values (must be positive)
            if filters.get("project_id") is not None:
                project_id = filters["project_id"]
                try:
                    project_id = int(project_id)
                    if project_id <= 0:
                        raise HTTPException(
                            status_code=422,
                            detail=f"project_id must be a positive integer, got {project_id}"
                        )
                    filters["project_id"] = project_id
                except (ValueError, TypeError):
                    raise HTTPException(
                        status_code=422,
                        detail=f"project_id must be an integer, got {project_id}"
                    )
            
            if filters.get("tag_id") is not None:
                tag_id = filters["tag_id"]
                try:
                    tag_id = int(tag_id)
                    if tag_id <= 0:
                        raise HTTPException(
                            status_code=422,
                            detail=f"tag_id must be a positive integer, got {tag_id}"
                        )
                    filters["tag_id"] = tag_id
                except (ValueError, TypeError):
                    raise HTTPException(
                        status_code=422,
                        detail=f"tag_id must be an integer, got {tag_id}"
                    )
            
            # Validate tag_ids format (comma-separated integers)
            if filters.get("tag_ids"):
                tag_ids_str = filters["tag_ids"]
                if isinstance(tag_ids_str, str):
                    try:
                        tag_ids_list = [int(tid.strip()) for tid in tag_ids_str.split(",") if tid.strip()]
                        for tid in tag_ids_list:
                            if tid <= 0:
                                raise HTTPException(
                                    status_code=400,
                                    detail=f"Invalid tag_id '{tid}' in tag_ids. All tag IDs must be positive integers"
                                )
                        filters["tag_ids"] = tag_ids_list
                    except ValueError as e:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid tag_ids format '{tag_ids_str}'. Must be comma-separated positive integers (e.g., '1,2,3'). Error: {str(e)}"
                        )
            
            tasks = self.db.query_tasks(
                task_type=filters.get("task_type"),
                task_status=filters.get("task_status"),
                assigned_agent=filters.get("assigned_agent"),
                project_id=filters.get("project_id"),
                priority=filters.get("priority"),
                order_by=filters.get("order_by"),
                search=filters.get("search"),
                limit=filters.get("limit", 100),
                tag_id=filters.get("tag_id"),
                tag_ids=filters.get("tag_ids")
            )
            return [dict(task) for task in tasks]
        except HTTPException:
            raise
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
                
                if task_update.priority is not None:
                    updates.append("priority = ?")
                    params.append(task_update.priority)
                
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
            # Validate agent_id is not empty or whitespace
            if not agent_id or not agent_id.strip():
                raise HTTPException(
                    status_code=422,
                    detail=[{
                        "loc": ["body", "agent_id"],
                        "msg": "agent_id cannot be empty or whitespace",
                        "type": "value_error"
                    }]
                )
            
            # Check if task exists first
            task = self.db.get_task(task_id)
            if not task:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
            
            success = self.db.lock_task(task_id, agent_id.strip())
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
            # Validate actual_hours if provided (must be positive)
            if actual_hours is not None:
                if actual_hours <= 0:
                    raise HTTPException(
                        status_code=422,
                        detail=[{
                            "loc": ["body", "actual_hours"],
                            "msg": "actual_hours must be a positive number",
                            "type": "value_error"
                        }]
                    )
            
            self.db.complete_task(task_id, agent_id, actual_hours=actual_hours, notes=notes)
            task = self.db.get_task(task_id)
            return dict(task)
        except HTTPException:
            raise
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
    
    def import_json(self, format: str = "json", **kwargs) -> Dict[str, Any]:
        """
        Import tasks from JSON format.
        
        POST /api/Task/import/json
        Body: {"tasks": [...], "agent_id": "...", "project_id": ..., "handle_duplicates": "skip"}
        """
        try:
            tasks = kwargs.get("tasks", [])
            agent_id = kwargs.get("agent_id") or (self.auth_info.get("agent_id") if self.auth_info else "system")
            project_id = kwargs.get("project_id")
            handle_duplicates = kwargs.get("handle_duplicates", "error")  # "skip" or "error"
            
            imported = []
            skipped = []
            errors = []
            import_id_map = {}  # Map import_id to task_id for relationship creation
            seen_titles = set()  # Track titles seen in this import batch
            
            for task_data in tasks:
                try:
                    title = task_data.get("title", "").strip()
                    
                    # Check for duplicates if handle_duplicates is "skip"
                    if handle_duplicates == "skip":
                        # First check within the import batch
                        if title in seen_titles:
                            skipped.append({"title": title, "reason": "duplicate in batch"})
                            continue
                        
                        # Then check against existing tasks in database
                        if title:
                            existing = self.db.query_tasks(
                                search=title,
                                project_id=project_id or task_data.get("project_id"),
                                limit=10
                            )
                            # Filter to exact title match
                            exact_match = [t for t in existing if t.get("title", "").strip() == title]
                            if exact_match:
                                skipped.append({"title": title, "reason": "duplicate"})
                                continue
                        
                        # Mark this title as seen
                        seen_titles.add(title)
                    
                    # Parse due_date if provided
                    due_date_obj = None
                    if task_data.get("due_date"):
                        from datetime import datetime
                        try:
                            due_date_str = task_data["due_date"]
                            if due_date_str.endswith('Z'):
                                due_date_obj = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
                            else:
                                due_date_obj = datetime.fromisoformat(due_date_str)
                        except (ValueError, AttributeError):
                            pass
                    
                    task_id = self.db.create_task(
                        title=task_data["title"],
                        task_type=task_data["task_type"],
                        task_instruction=task_data["task_instruction"],
                        verification_instruction=task_data["verification_instruction"],
                        agent_id=agent_id,
                        project_id=project_id or task_data.get("project_id"),
                        priority=task_data.get("priority"),
                        estimated_hours=task_data.get("estimated_hours"),
                        notes=task_data.get("notes"),
                        due_date=due_date_obj
                    )
                    imported.append(task_id)
                    
                    # Store import_id mapping for relationship creation
                    if task_data.get("import_id"):
                        import_id_map[task_data["import_id"]] = task_id
                        
                except Exception as e:
                    errors.append({"task": task_data.get("title", "Unknown"), "error": str(e)})
            
            # Create relationships if import_id and parent_import_id are provided
            for task_data in tasks:
                if task_data.get("parent_import_id") and task_data.get("import_id"):
                    parent_id = import_id_map.get(task_data["parent_import_id"])
                    child_id = import_id_map.get(task_data["import_id"])
                    relationship_type = task_data.get("relationship_type", "subtask")
                    
                    if parent_id and child_id:
                        try:
                            self.db.create_relationship(
                                parent_task_id=parent_id,
                                child_task_id=child_id,
                                relationship_type=relationship_type,
                                agent_id=agent_id
                            )
                        except Exception as e:
                            # Relationship creation failed, but task was created
                            errors.append({"relationship": f"{parent_id}->{child_id}", "error": str(e)})
            
            return {
                "success": True,
                "created": len(imported),
                "skipped": len(skipped),
                "error_count": len(errors),
                "imported_count": len(imported),
                "task_ids": imported,  # Alias for imported_task_ids
                "imported_task_ids": imported,
                "skipped_tasks": skipped,
                "errors": errors
            }
        except Exception as e:
            self._handle_error(e, "Failed to import tasks from JSON")
    
    def import_csv(self, format: str = "csv", **kwargs) -> Dict[str, Any]:
        """
        Import tasks from CSV format.
        
        POST /api/Task/import/csv
        Body: CSV content as text, with optional field_mapping and handle_duplicates
        """
        import csv
        import io
        import json
        from datetime import datetime
        
        try:
            # CSV content should be in kwargs as "content" or "csv_data"
            csv_content = kwargs.get("content") or kwargs.get("csv_data") or ""
            csv_file = io.StringIO(csv_content)
            reader = csv.DictReader(csv_file)
            
            agent_id = kwargs.get("agent_id") or (self.auth_info.get("agent_id") if self.auth_info else "system")
            project_id = kwargs.get("project_id")
            handle_duplicates = kwargs.get("handle_duplicates", "error")  # "skip" or "error"
            
            # Parse field mapping if provided
            field_mapping = {}
            if kwargs.get("field_mapping"):
                try:
                    if isinstance(kwargs["field_mapping"], str):
                        field_mapping = json.loads(kwargs["field_mapping"])
                    else:
                        field_mapping = kwargs["field_mapping"]
                except (json.JSONDecodeError, TypeError):
                    pass
            
            imported = []
            skipped = []
            errors = []
            
            for row in reader:
                try:
                    # Apply field mapping if provided
                    mapped_row = {}
                    if field_mapping:
                        for target_field, source_field in field_mapping.items():
                            mapped_row[target_field] = row.get(source_field, "")
                        # Copy unmapped fields as-is
                        for key, value in row.items():
                            if key not in field_mapping.values():
                                mapped_row[key] = value
                    else:
                        mapped_row = row
                    
                    title = mapped_row.get("title", "").strip()
                    task_type = mapped_row.get("task_type", "concrete")
                    task_instruction = mapped_row.get("task_instruction", "")
                    verification_instruction = mapped_row.get("verification_instruction", "")
                    
                    # Validate required fields
                    if not title:
                        errors.append({"row": "Unknown", "error": "Missing required field: title"})
                        continue
                    if not task_instruction:
                        errors.append({"row": title, "error": "Missing required field: task_instruction"})
                        continue
                    if not verification_instruction:
                        errors.append({"row": title, "error": "Missing required field: verification_instruction"})
                        continue
                    
                    # Check for duplicates if handle_duplicates is "skip"
                    if handle_duplicates == "skip" and title:
                        existing = self.db.query_tasks(
                            search=title,
                            project_id=project_id or (int(mapped_row["project_id"]) if mapped_row.get("project_id") else None),
                            limit=10
                        )
                        # Filter to exact title match
                        exact_match = [t for t in existing if t.get("title", "").strip() == title]
                        if exact_match:
                            skipped.append({"title": title, "reason": "duplicate"})
                            continue
                    
                    # Parse optional fields
                    parsed_project_id = project_id
                    if not parsed_project_id and mapped_row.get("project_id"):
                        try:
                            parsed_project_id = int(mapped_row["project_id"])
                        except (ValueError, TypeError):
                            pass
                    
                    parsed_estimated_hours = None
                    if mapped_row.get("estimated_hours"):
                        try:
                            parsed_estimated_hours = float(mapped_row["estimated_hours"])
                        except (ValueError, TypeError):
                            pass
                    
                    parsed_due_date = None
                    if mapped_row.get("due_date"):
                        try:
                            parsed_due_date = datetime.fromisoformat(mapped_row["due_date"])
                        except (ValueError, AttributeError):
                            pass
                    
                    task_id = self.db.create_task(
                        title=title,
                        task_type=task_type,
                        task_instruction=task_instruction,
                        verification_instruction=verification_instruction,
                        agent_id=agent_id,
                        project_id=parsed_project_id,
                        priority=mapped_row.get("priority"),
                        estimated_hours=parsed_estimated_hours,
                        notes=mapped_row.get("notes"),
                        due_date=parsed_due_date
                    )
                    imported.append(task_id)
                except Exception as e:
                    errors.append({"row": row.get("title", "Unknown"), "error": str(e)})
            
            return {
                "success": True,
                "created": len(imported),
                "skipped": len(skipped),
                "error_count": len(errors),
                "imported_count": len(imported),
                "task_ids": imported,  # Add task_ids alias for consistency
                "imported_task_ids": imported,
                "skipped_tasks": skipped,
                "errors": errors
            }
        except Exception as e:
            self._handle_error(e, "Failed to import tasks from CSV")
    
    def bulk_complete(self, **kwargs) -> Dict[str, Any]:
        """
        Bulk complete tasks.
        
        POST /api/Task/bulk/complete
        Body: {"task_ids": [1, 2, 3], "agent_id": "..."}
        """
        try:
            task_ids = kwargs.get("task_ids", [])
            agent_id = kwargs.get("agent_id") or (self.auth_info.get("agent_id") if self.auth_info else "system")
            result = self.db.bulk_complete_tasks(task_ids, agent_id)
            return result
        except Exception as e:
            self._handle_error(e, "Failed to bulk complete tasks")
    
    def bulk_assign(self, **kwargs) -> Dict[str, Any]:
        """
        Bulk assign tasks to an agent.
        
        POST /api/Task/bulk/assign
        Body: {"task_ids": [1, 2, 3], "agent_id": "..."}
        """
        try:
            task_ids = kwargs.get("task_ids", [])
            agent_id = kwargs.get("agent_id") or (self.auth_info.get("agent_id") if self.auth_info else "system")
            result = self.db.bulk_assign_tasks(task_ids, agent_id)
            return result
        except Exception as e:
            self._handle_error(e, "Failed to bulk assign tasks")
    
    def bulk_update_status(self, **kwargs) -> Dict[str, Any]:
        """
        Bulk update task status.
        
        POST /api/Task/bulk/update-status
        Body: {"task_ids": [1, 2, 3], "status": "complete", "agent_id": "..."}
        """
        try:
            task_ids = kwargs.get("task_ids", [])
            status = kwargs.get("status")
            agent_id = kwargs.get("agent_id") or (self.auth_info.get("agent_id") if self.auth_info else "system")
            result = self.db.bulk_update_status(task_ids, status, agent_id)
            return result
        except Exception as e:
            self._handle_error(e, "Failed to bulk update status")
    
    def bulk_delete(self, **kwargs) -> Dict[str, Any]:
        """
        Bulk delete tasks.
        
        POST /api/Task/bulk/delete
        Body: {"task_ids": [1, 2, 3], "agent_id": "...", "confirmation": true}
        """
        try:
            task_ids = kwargs.get("task_ids", [])
            agent_id = kwargs.get("agent_id") or (self.auth_info.get("agent_id") if self.auth_info else "system")
            confirmation = kwargs.get("confirmation", False)
            if not confirmation:
                raise HTTPException(status_code=400, detail="Confirmation required for bulk delete")
            result = self.db.bulk_delete_tasks(task_ids, agent_id)
            return result
        except HTTPException:
            raise
        except Exception as e:
            self._handle_error(e, "Failed to bulk delete tasks")

