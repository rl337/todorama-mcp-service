"""
Adapter for HTTP framework (FastAPI).
Isolates FastAPI-specific imports to make library replacement easier.
"""
try:
    from fastapi import FastAPI, HTTPException, Query, Body, Path, Request, UploadFile, File, Form, Depends
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse, StreamingResponse, Response, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    HTTP_FRAMEWORK_AVAILABLE = True
except ImportError:
    HTTP_FRAMEWORK_AVAILABLE = False
    FastAPI = None
    HTTPException = Exception
    Query = None
    Body = None
    Path = None
    Request = None
    UploadFile = None
    File = None
    Form = None
    Depends = None
    RequestValidationError = Exception
    JSONResponse = None
    StreamingResponse = None
    Response = None
    HTMLResponse = None
    StaticFiles = None
    HTTPBearer = None
    HTTPAuthorizationCredentials = None


class HTTPFrameworkAdapter:
    """Adapter for HTTP framework operations."""
    
    def __init__(self):
        if not HTTP_FRAMEWORK_AVAILABLE:
            raise ImportError("FastAPI is not available. Install fastapi to use this adapter.")
        
        self.FastAPI = FastAPI
        self.HTTPException = HTTPException
        self.Query = Query
        self.Body = Body
        self.Path = Path
        self.Request = Request
        self.UploadFile = UploadFile
        self.File = File
        self.Form = Form
        self.Depends = Depends
        self.RequestValidationError = RequestValidationError
        self.JSONResponse = JSONResponse
        self.StreamingResponse = StreamingResponse
        self.Response = Response
        self.HTMLResponse = HTMLResponse
        self.StaticFiles = StaticFiles
        self.HTTPBearer = HTTPBearer
        self.HTTPAuthorizationCredentials = HTTPAuthorizationCredentials
    
    def create_app(self, *args, **kwargs):
        """Create a FastAPI application instance."""
        return self.FastAPI(*args, **kwargs)

