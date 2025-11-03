"""
Health and metrics API routes.
"""
from fastapi import APIRouter
from dependencies.services import get_services
from monitoring import get_health_info, get_metrics
from adapters.http_framework import HTTPFrameworkAdapter
from adapters.metrics import MetricsAdapter

# Initialize adapters
http_adapter = HTTPFrameworkAdapter()
Response = http_adapter.Response
metrics_adapter = MetricsAdapter()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Comprehensive health check endpoint with component status (database, service)."""
    services = get_services()
    health_info = get_health_info(services.db)
    
    # Return appropriate HTTP status based on overall health
    if health_info.get("status") == "unhealthy":
        from fastapi import status as http_status
        from adapters.http_framework import HTTPFrameworkAdapter
        http_adapter = HTTPFrameworkAdapter()
        JSONResponse = http_adapter.JSONResponse
        return JSONResponse(
            content=health_info,
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    return health_info


@router.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=get_metrics(),
        media_type=metrics_adapter.get_content_type()
    )

