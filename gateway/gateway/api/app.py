"""FastAPI application factory for Gateway Phase 2."""

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from gateway import __version__
from gateway.core import (
    AdapterRuntime,
    GatewayError,
    GatewayErrorCode,
    GatewayException,
    GatewayLifecycle,
    MemoryEventBus,
)

from . import adapters, commands, endpoints, events, health, websocket
from .auth import ApiKey, ApiKeyStore
from .dependencies import ApiServices
from .errors import GatewayApiError
from .event_stream import EventStream
from .serialization import error_to_dict

logger = logging.getLogger("gateway.api")


def create_app(
    runtime: AdapterRuntime,
    event_bus: MemoryEventBus,
    api_keys: Sequence[ApiKey],
    *,
    lifecycle: GatewayLifecycle | None = None,
    manage_lifecycle: bool = True,
    heartbeat_interval: float = 20.0,
    event_history_size: int = 1024,
    client_queue_size: int = 256,
) -> FastAPI:
    """Create a Gateway API bound to existing Core services.

    Args:
        runtime: Configured adapter runtime.
        event_bus: Runtime's shared event bus.
        api_keys: API keys and caller scopes.
        lifecycle: Optional lifecycle using the same runtime and event bus.
        manage_lifecycle: Start and stop Core through FastAPI lifespan.
        heartbeat_interval: WebSocket heartbeat interval in seconds.
        event_history_size: Number of recent events retained in memory.
        client_queue_size: Pending event limit per WebSocket connection.

    Returns:
        Configured FastAPI application.

    Raises:
        ValueError: If heartbeat interval is not positive.
    """
    if heartbeat_interval <= 0:
        raise ValueError("heartbeat interval must be positive")
    gateway_lifecycle = lifecycle or GatewayLifecycle(event_bus, runtime)
    event_stream = EventStream(event_history_size, client_queue_size)
    services = ApiServices(
        runtime=runtime,
        event_bus=event_bus,
        lifecycle=gateway_lifecycle,
        api_keys=ApiKeyStore(api_keys),
        events=event_stream,
        heartbeat_interval=heartbeat_interval,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        subscription_token = event_bus.subscribe(event_stream.ingest)
        try:
            if manage_lifecycle:
                await gateway_lifecycle.start()
            elif not event_bus.running:
                raise RuntimeError(
                    "event bus must be running when API lifecycle management is disabled"
                )
            yield
        finally:
            if manage_lifecycle:
                await gateway_lifecycle.stop()
            event_bus.unsubscribe(subscription_token)

    app = FastAPI(
        title="Agent Transport Gateway",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.gateway_services = services

    @app.exception_handler(GatewayApiError)
    async def handle_api_error(
        _request: Request,
        exc: GatewayApiError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": error_to_dict(exc.error)},
        )

    @app.exception_handler(GatewayException)
    async def handle_core_error(
        _request: Request,
        exc: GatewayException,
    ) -> JSONResponse:
        status_code = 400
        if exc.error.code in {
            GatewayErrorCode.ADAPTER_NOT_FOUND,
            GatewayErrorCode.ENDPOINT_NOT_FOUND,
            GatewayErrorCode.EVENT_NOT_FOUND,
        }:
            status_code = 404
        elif exc.error.code == GatewayErrorCode.ADAPTER_OFFLINE:
            status_code = 409
        return JSONResponse(
            status_code=status_code,
            content={"error": error_to_dict(exc.error)},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        error = GatewayError(
            GatewayErrorCode.INVALID_COMMAND,
            "request validation failed",
        )
        return JSONResponse(
            status_code=422,
            content={"error": error_to_dict(error)},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception(
            "API request failed method=%s path=%s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        error = GatewayError(
            GatewayErrorCode.INTERNAL_ERROR,
            "internal server error",
        )
        return JSONResponse(
            status_code=500,
            content={"error": error_to_dict(error)},
        )

    app.include_router(health.router)
    app.include_router(adapters.router)
    app.include_router(endpoints.router)
    app.include_router(commands.router)
    app.include_router(events.router)
    app.include_router(websocket.router)
    return app
