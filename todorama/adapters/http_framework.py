"""
Adapter for HTTP framework (FastAPI).
Isolates FastAPI-specific imports to make library replacement easier.
"""
from abc import ABC, abstractmethod
from typing import Callable, Any, Optional, Dict
try:
    from fastapi import FastAPI, APIRouter, HTTPException, Query, Body, Path, Request, UploadFile, File, Form, Depends
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse, StreamingResponse, Response, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    HTTP_FRAMEWORK_AVAILABLE = True
except ImportError:
    HTTP_FRAMEWORK_AVAILABLE = False
    FastAPI = None
    APIRouter = None
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


class RouterAdapter(ABC):
    """Abstract adapter for HTTP router operations."""
    
    @abstractmethod
    def get(self, path: str, **kwargs) -> Callable:
        """Register a GET route."""
        pass
    
    @abstractmethod
    def post(self, path: str, **kwargs) -> Callable:
        """Register a POST route."""
        pass
    
    @abstractmethod
    def put(self, path: str, **kwargs) -> Callable:
        """Register a PUT route."""
        pass
    
    @abstractmethod
    def patch(self, path: str, **kwargs) -> Callable:
        """Register a PATCH route."""
        pass
    
    @abstractmethod
    def delete(self, path: str, **kwargs) -> Callable:
        """Register a DELETE route."""
        pass
    
    @abstractmethod
    def include_router(self, router: Any, **kwargs) -> None:
        """Include another router."""
        pass


class AppAdapter(ABC):
    """Abstract adapter for HTTP application operations."""
    
    @abstractmethod
    def get(self, path: str, **kwargs) -> Callable:
        """Register a GET route."""
        pass
    
    @abstractmethod
    def post(self, path: str, **kwargs) -> Callable:
        """Register a POST route."""
        pass
    
    @abstractmethod
    def put(self, path: str, **kwargs) -> Callable:
        """Register a PUT route."""
        pass
    
    @abstractmethod
    def patch(self, path: str, **kwargs) -> Callable:
        """Register a PATCH route."""
        pass
    
    @abstractmethod
    def delete(self, path: str, **kwargs) -> Callable:
        """Register a DELETE route."""
        pass
    
    @abstractmethod
    def include_router(self, router: Any, **kwargs) -> None:
        """Include another router."""
        pass
    
    @abstractmethod
    def mount(self, path: str, app: Any, name: Optional[str] = None) -> None:
        """Mount a sub-application."""
        pass
    
    @abstractmethod
    def add_middleware(self, middleware_class: type, **kwargs) -> None:
        """Add middleware to the application."""
        pass
    
    @abstractmethod
    def exception_handler(self, exc_class: type) -> Callable:
        """Register an exception handler."""
        pass


class FastAPIRouterAdapter(RouterAdapter):
    """FastAPI implementation of RouterAdapter."""
    
    def __init__(self, router: APIRouter):
        """Initialize with a FastAPI APIRouter instance."""
        self._router = router
    
    def get(self, path: str, **kwargs) -> Callable:
        """Register a GET route."""
        return self._router.get(path, **kwargs)
    
    def post(self, path: str, **kwargs) -> Callable:
        """Register a POST route."""
        return self._router.post(path, **kwargs)
    
    def put(self, path: str, **kwargs) -> Callable:
        """Register a PUT route."""
        return self._router.put(path, **kwargs)
    
    def patch(self, path: str, **kwargs) -> Callable:
        """Register a PATCH route."""
        return self._router.patch(path, **kwargs)
    
    def delete(self, path: str, **kwargs) -> Callable:
        """Register a DELETE route."""
        return self._router.delete(path, **kwargs)
    
    def include_router(self, router: Any, **kwargs) -> None:
        """Include another router."""
        # If router is a FastAPIRouterAdapter, extract the underlying router
        if isinstance(router, FastAPIRouterAdapter):
            router = router._router
        self._router.include_router(router, **kwargs)
    
    @property
    def router(self) -> APIRouter:
        """Get the underlying FastAPI router."""
        return self._router
    
    # Expose FastAPI router attributes for compatibility
    @property
    def routes(self):
        """Expose routes attribute for FastAPI compatibility."""
        return self._router.routes
    
    def __getattr__(self, name: str):
        """Delegate attribute access to underlying router for FastAPI compatibility."""
        return getattr(self._router, name)


class FastAPIAppAdapter(AppAdapter):
    """FastAPI implementation of AppAdapter."""
    
    def __init__(self, app: FastAPI):
        """Initialize with a FastAPI application instance."""
        self._app = app
    
    def get(self, path: str, **kwargs) -> Callable:
        """Register a GET route."""
        return self._app.get(path, **kwargs)
    
    def post(self, path: str, **kwargs) -> Callable:
        """Register a POST route."""
        return self._app.post(path, **kwargs)
    
    def put(self, path: str, **kwargs) -> Callable:
        """Register a PUT route."""
        return self._app.put(path, **kwargs)
    
    def patch(self, path: str, **kwargs) -> Callable:
        """Register a PATCH route."""
        return self._app.patch(path, **kwargs)
    
    def delete(self, path: str, **kwargs) -> Callable:
        """Register a DELETE route."""
        return self._app.delete(path, **kwargs)
    
    def include_router(self, router: Any, **kwargs) -> None:
        """Include another router."""
        # If router is a FastAPIRouterAdapter, extract the underlying router
        if isinstance(router, FastAPIRouterAdapter):
            router = router._router
        elif hasattr(router, 'router'):
            # Handle case where router is accessed via .router property
            router = router.router
        self._app.include_router(router, **kwargs)
    
    def mount(self, path: str, app: Any, name: Optional[str] = None) -> None:
        """Mount a sub-application."""
        self._app.mount(path, app, name=name)
    
    def add_middleware(self, middleware_class: type, **kwargs) -> None:
        """Add middleware to the application."""
        self._app.add_middleware(middleware_class, **kwargs)
    
    def exception_handler(self, exc_class: type) -> Callable:
        """Register an exception handler."""
        return self._app.exception_handler(exc_class)
    
    @property
    def app(self) -> FastAPI:
        """Get the underlying FastAPI application."""
        return self._app


class HTTPFrameworkAdapter:
    """Adapter for HTTP framework operations."""
    
    def __init__(self):
        if not HTTP_FRAMEWORK_AVAILABLE:
            raise ImportError("FastAPI is not available. Install fastapi to use this adapter.")
        
        self.FastAPI = FastAPI
        self.APIRouter = APIRouter
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
    
    def create_app(self, *args, **kwargs) -> FastAPIAppAdapter:
        """Create a FastAPI application instance wrapped in AppAdapter."""
        app = self.FastAPI(*args, **kwargs)
        return FastAPIAppAdapter(app)
    
    def create_router(self, *args, **kwargs) -> FastAPIRouterAdapter:
        """Create an APIRouter instance wrapped in RouterAdapter."""
        router = self.APIRouter(*args, **kwargs)
        return FastAPIRouterAdapter(router)

