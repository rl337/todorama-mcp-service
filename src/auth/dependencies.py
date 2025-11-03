"""
Authentication and authorization dependencies for FastAPI.
"""
from typing import Optional, Dict, Any
from adapters.http_framework import HTTPFrameworkAdapter
from adapters.validation import ValidationAdapter

# Initialize adapters
http_adapter = HTTPFrameworkAdapter()
HTTPException = http_adapter.HTTPException
Request = http_adapter.Request
HTTPAuthorizationCredentials = http_adapter.HTTPAuthorizationCredentials
Depends = http_adapter.Depends


async def verify_api_key(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = None,
    db=None  # Will be injected from dependencies - use global db if None for backward compatibility
) -> Dict[str, Any]:
    """
    Verify API key from request headers.
    Supports both X-API-Key header and Authorization: Bearer token.
    
    Returns:
        Dictionary with 'key_id' and 'project_id' if authenticated
    Raises:
        HTTPException 401 if authentication fails
    """
    if db is None:
        # For backward compatibility with main.py, try to use global db
        # Otherwise use service container
        try:
            import main
            db = main.db
        except (AttributeError, ImportError):
            from dependencies.services import get_db
            db = get_db()
    
    api_key = None
    
    # Try X-API-Key header first
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        api_key = api_key_header
    
    # Try Authorization: Bearer token
    if not api_key and authorization:
        api_key = authorization.credentials
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide X-API-Key header or Authorization: Bearer token."
        )
    
    # Hash the key and look it up
    key_hash = db._hash_api_key(api_key)
    key_info = db.get_api_key_by_hash(key_hash)
    
    if not key_info:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
    
    if key_info["enabled"] != 1:
        raise HTTPException(
            status_code=401,
            detail="API key has been revoked"
        )
    
    # Update last used timestamp
    db.update_api_key_last_used(key_info["id"])
    
    # Store in request state for use in endpoints
    request.state.project_id = key_info["project_id"]
    request.state.key_id = key_info["id"]
    
    # Get admin status
    is_admin = db.is_api_key_admin(key_info["id"])
    request.state.is_admin = is_admin
    
    return {
        "key_id": key_info["id"],
        "project_id": key_info["project_id"],
        "is_admin": is_admin
    }


async def verify_admin_api_key(
    request: Request,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Verify that the API key has admin privileges.
    
    Returns:
        Same as verify_api_key if admin, else raises 403
    Raises:
        HTTPException 403 if not admin
    """
    if not auth.get("is_admin", False):
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required"
        )
    return auth


async def verify_session_token(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = None,
    db=None  # Will be injected from dependencies
) -> Dict[str, Any]:
    """
    Verify session token from Authorization: Bearer token.
    
    Returns:
        Dictionary with 'user_id', 'session_id', and 'session_token' if authenticated
    Raises:
        HTTPException 401 if authentication fails
    """
    if db is None:
        try:
            import main
            db = main.db
        except (AttributeError, ImportError):
            from dependencies.services import get_db
            db = get_db()
    
    token = None
    
    # Get token from Authorization header
    if authorization:
        token = authorization.credentials
    else:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Session token required. Provide Authorization: Bearer token."
        )
    
    # Look up session
    session = db.get_session_by_token(token)
    
    if not session:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session token"
        )
    
    # Store in request state
    request.state.user_id = session["user_id"]
    request.state.session_id = session["id"]
    request.state.session_token = token
    
    return {
        "user_id": session["user_id"],
        "session_id": session["id"],
        "session_token": token
    }


async def verify_user_auth(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = None,
    db=None  # Will be injected from dependencies
) -> Dict[str, Any]:
    """
    Verify either API key or session token authentication.
    Tries session token first, then API key.
    
    Returns:
        Dictionary with authentication info
    """
    if db is None:
        try:
            import main
            db = main.db
        except (AttributeError, ImportError):
            from dependencies.services import get_db
            db = get_db()
    
    # Try session token first
    token = None
    if authorization:
        token = authorization.credentials
    else:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if token:
        # Try as session token first
        session = db.get_session_by_token(token)
        if session:
            request.state.user_id = session["user_id"]
            request.state.session_id = session["id"]
            return {
                "user_id": session["user_id"],
                "session_id": session["id"],
                "auth_type": "session"
            }
    
    # Try API key if no session token found
    api_key = None
    api_key_header = request.headers.get("X-API-Key")
    if api_key_header:
        api_key = api_key_header
    
    if api_key:
        # Hash the key and look it up
        key_hash = db._hash_api_key(api_key)
        key_info = db.get_api_key_by_hash(key_hash)
        
        if key_info and key_info["enabled"] == 1:
            db.update_api_key_last_used(key_info["id"])
            request.state.project_id = key_info["project_id"]
            request.state.key_id = key_info["id"]
            return {
                "key_id": key_info["id"],
                "project_id": key_info["project_id"],
                "auth_type": "api_key"
            }
    
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide X-API-Key header or Authorization: Bearer token."
    )


async def optional_api_key(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = None,
    db=None  # Will be injected from dependencies
) -> Optional[Dict[str, Any]]:
    """
    Optional API key verification.
    Returns None if no API key provided (instead of raising error).
    """
    if db is None:
        try:
            import main
            db = main.db
        except (AttributeError, ImportError):
            from dependencies.services import get_db
            db = get_db()
    
    try:
        return await verify_api_key(request, authorization, db)
    except HTTPException:
        return None

