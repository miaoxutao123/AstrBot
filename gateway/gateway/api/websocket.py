"""Live WebSocket event subscription route."""

import asyncio
import time
from typing import cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from gateway.core import GatewayError, GatewayErrorCode

from .dependencies import ApiServices
from .errors import GatewayApiError
from .event_stream import EventFilter, StreamClosed
from .serialization import error_to_dict, event_to_dict

router = APIRouter(tags=["events"])


@router.websocket("/v1/events/ws")
async def event_websocket(websocket: WebSocket) -> None:
    """Stream filtered events with heartbeat and in-memory reconnect support.

    Args:
        websocket: FastAPI WebSocket connection.
    """
    services = cast(ApiServices, websocket.app.state.gateway_services)
    try:
        principal = services.api_keys.authenticate(websocket.headers)
        services.api_keys.require(principal, "events:read")
    except GatewayApiError as exc:
        await websocket.close(code=4401 if exc.status_code == 401 else 4403)
        return
    event_filter = EventFilter(
        family=websocket.query_params.get("family"),
        adapter_type=websocket.query_params.get("adapter_type"),
        adapter_id=websocket.query_params.get("adapter_id"),
        event_type=websocket.query_params.get("event_type"),
    )
    last_event_id = websocket.query_params.get("last_event_id")
    if last_event_id is None:
        last_event_id = websocket.query_params.get("cursor")
    subscription = services.events.subscribe(event_filter, last_event_id)
    await websocket.accept()
    if last_event_id is not None and not subscription.cursor_found:
        await websocket.send_json(
            {
                "type": "gap",
                "data": {
                    "reason": "cursor_not_retained",
                    "last_event_id": last_event_id,
                },
            }
        )
    if subscription.replay_truncated:
        await websocket.send_json(
            {
                "type": "gap",
                "data": {"reason": "replay_truncated"},
            }
        )
    current_cursor = last_event_id
    try:
        while True:
            try:
                item = await asyncio.wait_for(
                    subscription.queue.get(),
                    timeout=services.heartbeat_interval,
                )
            except asyncio.TimeoutError:
                await websocket.send_json(
                    {
                        "type": "heartbeat",
                        "data": {
                            "timestamp": time.time(),
                            "cursor": current_cursor,
                        },
                    }
                )
                continue
            if isinstance(item, StreamClosed):
                error = GatewayError(
                    GatewayErrorCode.DELIVERY_FAILED,
                    item.reason,
                    retryable=True,
                )
                await websocket.send_json(
                    {"type": "error", "data": error_to_dict(error)}
                )
                await websocket.close(code=1013)
                return
            current_cursor = item.id
            await websocket.send_json({"type": "event", "data": event_to_dict(item)})
    except WebSocketDisconnect:
        return
    finally:
        services.events.unsubscribe(subscription.token)
