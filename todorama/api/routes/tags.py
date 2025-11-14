"""
Tag API routes.
"""
from typing import Dict, Any
import logging

from todorama.adapters.http_framework import HTTPFrameworkAdapter
from todorama.dependencies.services import get_db
from todorama.services.tag_service import TagService

# Initialize adapter
http_adapter = HTTPFrameworkAdapter()
Body = http_adapter.Body
HTTPException = http_adapter.HTTPException

# Create router using adapter, expose underlying router for compatibility
router_adapter = http_adapter.create_router(prefix="/tags", tags=["tags"])
router = router_adapter.router

logger = logging.getLogger(__name__)


@router.post("", status_code=201)
async def create_tag(
    tag_data: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    """Create a new tag."""
    tag_service = TagService(get_db())
    try:
        if "name" not in tag_data:
            raise HTTPException(status_code=422, detail=[{
                "loc": ["body", "name"],
                "msg": "Tag name is required",
                "type": "value_error.missing"
            }])
        tag = tag_service.create_tag(tag_data["name"])
        return tag
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=[{
            "loc": ["body", "name"],
            "msg": str(e),
            "type": "value_error"
        }])
    except Exception as e:
        logger.error(f"Failed to create tag: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create tag")
