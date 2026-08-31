"""Command submission route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from .auth import ApiPrincipal
from .dependencies import get_services, require_scope
from .schemas import CommandRequest
from .serialization import command_result_to_dict

router = APIRouter(tags=["commands"])

_HARDWARE_TRANSPORTS = {"ble", "can", "modbus", "robot", "ros2", "serial"}


@router.post("/v1/commands")
async def submit_command(
    body: CommandRequest,
    request: Request,
    principal: Annotated[
        ApiPrincipal,
        Depends(require_scope("commands:send")),
    ],
) -> dict[str, object]:
    """Authorize and dispatch one transport command.

    Args:
        body: Validated command request.
        request: Current FastAPI request.
        principal: Authorized caller.

    Returns:
        Stable command result.
    """
    services = get_services(request)
    command = body.to_core()
    if (
        command.target.transport.lower() in _HARDWARE_TRANSPORTS
        or command.type.startswith("robot.")
    ):
        services.api_keys.require(principal, "hardware:control")
    result = await services.runtime.execute(command)
    return command_result_to_dict(result)
