"""
Comment-related API routes.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Path
from models.comment_models import CommentCreate, CommentUpdate, CommentResponse
from auth.dependencies import verify_user_auth
from dependencies.services import get_db
from adapters.http_framework import HTTPFrameworkAdapter

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
HTTPException = http_adapter.HTTPException
Request = http_adapter.Request

router = APIRouter(prefix="/tasks/{task_id}/comments", tags=["comments"])

# Separate router for comment thread (not nested under task)
comment_router = APIRouter(prefix="/comments", tags=["comments"])


@router.post("", response_model=CommentResponse, status_code=201)
async def create_comment(
    task_id: int = Path(..., gt=0, description="Task ID"),
    comment: CommentCreate = ...,
    request: Request = ...,
    auth: dict = Depends(verify_user_auth)
):
    """Create a comment on a task."""
    db = get_db()
    
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    # Create comment
    comment_id = db.create_comment(
        task_id=task_id,
        agent_id=comment.agent_id,
        content=comment.content,
        parent_comment_id=comment.parent_comment_id,
        mentions=comment.mentions or []
    )
    
    # Retrieve created comment
    created_comment = db.get_comment(comment_id)
    if not created_comment:
        raise HTTPException(status_code=500, detail="Failed to retrieve created comment")
    
    return CommentResponse(**created_comment)


@router.get("", response_model=List[CommentResponse])
async def list_task_comments(task_id: int = Path(..., gt=0, description="Task ID")):
    """List all comments for a task."""
    db = get_db()
    
    # Verify task exists
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found. Please verify the task_id is correct."
        )
    
    comments = db.list_task_comments(task_id)
    return [CommentResponse(**comment) for comment in comments]


@router.get("/{comment_id}", response_model=CommentResponse)
async def get_comment(
    task_id: int = Path(..., gt=0, description="Task ID"),
    comment_id: int = Path(..., gt=0, description="Comment ID")
):
    """Get a specific comment."""
    db = get_db()
    
    comment = db.get_comment(comment_id)
    if not comment:
        raise HTTPException(
            status_code=404,
            detail=f"Comment {comment_id} not found. Please verify the comment_id is correct."
        )
    
    # Verify comment belongs to task
    if comment["task_id"] != task_id:
        raise HTTPException(
            status_code=400,
            detail=f"Comment {comment_id} does not belong to task {task_id}"
        )
    
    return CommentResponse(**comment)



@comment_router.get("/{comment_id}/thread", response_model=List[CommentResponse])
async def get_comment_thread(comment_id: int = Path(..., gt=0, description="Parent comment ID")):
    """Get a comment thread (parent comment and all replies)."""
    db = get_db()
    
    comment = db.get_comment(comment_id)
    if not comment:
        raise HTTPException(
            status_code=404,
            detail=f"Comment {comment_id} not found. Please verify the comment_id is correct."
        )
    
    thread = db.get_comment_thread(comment_id)
    return [CommentResponse(**comment) for comment in thread]


@router.put("/{comment_id}", response_model=CommentResponse)
async def update_comment(
    task_id: int = Path(..., gt=0, description="Task ID"),
    comment_id: int = Path(..., gt=0, description="Comment ID"),
    comment: CommentUpdate = ...,
    request: Request = ...,
    auth: dict = Depends(verify_user_auth)
):
    """Update a comment."""
    db = get_db()
    
    # Get existing comment
    existing_comment = db.get_comment(comment_id)
    if not existing_comment:
        raise HTTPException(
            status_code=404,
            detail=f"Comment {comment_id} not found. Please verify the comment_id is correct."
        )
    
    # Verify comment belongs to task
    if existing_comment["task_id"] != task_id:
        raise HTTPException(
            status_code=400,
            detail=f"Comment {comment_id} does not belong to task {task_id}"
        )
    
    # Update comment
    db.update_comment(comment_id, comment.content)
    
    # Retrieve updated comment
    updated_comment = db.get_comment(comment_id)
    if not updated_comment:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated comment")
    
    return CommentResponse(**updated_comment)


@router.delete("/{comment_id}")
async def delete_comment(
    task_id: int = Path(..., gt=0, description="Task ID"),
    comment_id: int = Path(..., gt=0, description="Comment ID"),
    request: Request = ...,
    auth: dict = Depends(verify_user_auth)
):
    """Delete a comment."""
    db = get_db()
    
    # Get existing comment
    existing_comment = db.get_comment(comment_id)
    if not existing_comment:
        raise HTTPException(
            status_code=404,
            detail=f"Comment {comment_id} not found. Please verify the comment_id is correct."
        )
    
    # Verify comment belongs to task
    if existing_comment["task_id"] != task_id:
        raise HTTPException(
            status_code=400,
            detail=f"Comment {comment_id} does not belong to task {task_id}"
        )
    
    # Delete comment (cascades to replies)
    db.delete_comment(comment_id)
    
    return {"message": f"Comment {comment_id} deleted successfully"}


