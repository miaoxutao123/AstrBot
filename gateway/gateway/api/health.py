"""Gateway health route."""

from fastapi import APIRouter, Request

from gateway.core import AdapterState

from .dependencies import get_services
from .serialization import runtime_info_to_dict

router = APIRouter(tags=["health"])


@router.get("/v1/health")
async def get_health(request: Request) -> dict[str, object]:
    """Return unauthenticated process and adapter health.

    Args:
        request: Current FastAPI request.

    Returns:
        Gateway health summary without sensitive configuration.
    """
    services = get_services(request)
    adapters = services.runtime.list_info()
    failed = sum(info.state == AdapterState.FAILED for info in adapters)
    degraded = sum(info.state == AdapterState.DEGRADED for info in adapters)
    status = "ok"
    if failed:
        status = "degraded"
    elif degraded:
        status = "degraded"
    return {
        "status": status,
        "event_bus": "running" if services.event_bus.running else "stopped",
        "adapters": [runtime_info_to_dict(info) for info in adapters],
        "summary": {
            "total": len(adapters),
            "failed": failed,
            "degraded": degraded,
        },
    }
