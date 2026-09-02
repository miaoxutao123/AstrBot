"""Async client using only AstrBot-Gateway's public HTTP and WebSocket wire API."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect

from .models import GatewayEvent, GatewayInventory, SourceEndpoint


class GatewayWebSocketAuthenticationError(RuntimeError):
    """Raised when Gateway rejects an event stream with close code 4401/4403."""


class AsyncGatewayClient:
    """Async Gateway API client for agents and service integrations."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        reconnect_delay: float = 0.2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.reconnect_delay = reconnect_delay
        self._client = client or httpx.AsyncClient(base_url=self.base_url)
        self._owns_client = client is None
        self._closed = False

    async def __aenter__(self) -> "AsyncGatewayClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def health(self) -> Mapping[str, Any]:
        return await self._get("/v1/health")

    async def list_adapters(self) -> list[Mapping[str, Any]]:
        return list((await self._get("/v1/adapters")).get("adapters", []))

    async def list_endpoints(self) -> list[Mapping[str, Any]]:
        return list((await self._get("/v1/endpoints")).get("endpoints", []))

    async def discover(self) -> GatewayInventory:
        """Return the Gateway's complete authorized agent-facing inventory."""
        return GatewayInventory.from_wire(await self._get("/v1/discovery"))

    async def find_endpoints(
        self, *, family: str | None = None, adapter_type: str | None = None,
        adapter_id: str | None = None, capability: str | None = None,
        direction: str | None = None,
    ) -> list[Mapping[str, Any]]:
        """Filter the aggregate inventory without reconstructing it manually."""
        endpoints = (await self.discover()).endpoints
        return [endpoint.raw for endpoint in endpoints if
                (family is None or endpoint.source.family == family) and
                (adapter_type is None or endpoint.source.adapter_type == adapter_type) and
                (adapter_id is None or endpoint.source.adapter_id == adapter_id) and
                (direction is None or endpoint.direction == direction) and
                (capability is None or any(item.name == capability for item in endpoint.capabilities))]

    async def get_capabilities(
        self, endpoint: str | Mapping[str, Any]
    ) -> list[Mapping[str, Any]]:
        endpoint_id = endpoint if isinstance(endpoint, str) else str(endpoint["id"])
        response = await self._get(f"/v1/endpoints/{endpoint_id}/capabilities")
        return list(response.get("capabilities", []))

    async def send_text(
        self, endpoint: SourceEndpoint | Mapping[str, Any], text: str
    ) -> Mapping[str, Any]:
        target = self._endpoint_wire(endpoint)
        return await self._command(
            target,
            "im.message.send",
            {"segments": [{"type": "text", "data": {"text": text}}]},
        )

    async def reply(self, event: GatewayEvent, text: str) -> Mapping[str, Any]:
        message = event.message
        if message is None or not message.id:
            raise ValueError("reply requires an event with an im.message.v1 message_id")
        return await self._command(
            event.source.to_wire(),
            "im.message.reply",
            {
                "segments": [{"type": "text", "data": {"text": text}}],
                "reply_to": message.id,
            },
            correlation_id=event.id,
        )

    async def upload_media(
        self,
        data: bytes,
        *,
        filename: str = "upload.bin",
        mime_type: str = "application/octet-stream",
        ttl_seconds: float | None = None,
    ) -> Mapping[str, Any]:
        params = {"ttl_seconds": str(ttl_seconds)} if ttl_seconds is not None else None
        response = await self._client.post(
            "/v1/media",
            params=params,
            headers=self._headers,
            files={"upload": (filename, data, mime_type)},
        )
        return self._json(response).get("media", {})

    async def events(
        self,
        *,
        family: str | None = None,
        adapter_type: str | None = None,
        adapter_id: str | None = None,
        event_type: str | None = None,
    ) -> AsyncIterator[GatewayEvent]:
        last_event_id: str | None = None
        while not self._closed:
            query = {
                key: value
                for key, value in {
                    "family": family,
                    "adapter_type": adapter_type,
                    "adapter_id": adapter_id,
                    "event_type": event_type,
                    "last_event_id": last_event_id,
                }.items()
                if value is not None
            }
            try:
                async with connect(
                    self._websocket_url(query), additional_headers=self._headers
                ) as socket:
                    async for raw in socket:
                        envelope = json.loads(raw)
                        if envelope.get("type") != "event":
                            continue
                        data = envelope.get("data")
                        if not isinstance(data, Mapping):
                            continue
                        event = GatewayEvent.from_wire(data)
                        last_event_id = event.id
                        yield event
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._closed:
                    return
                close_code = self._websocket_close_code(exc)
                if close_code in {4401, 4403}:
                    raise GatewayWebSocketAuthenticationError(
                        f"Gateway WebSocket authorization failed ({close_code})"
                    ) from exc
                await asyncio.sleep(self.reconnect_delay)

    async def _get(self, path: str) -> Mapping[str, Any]:
        return self._json(await self._client.get(path, headers=self._headers))

    async def _command(
        self,
        target: Mapping[str, str],
        command_type: str,
        data: Mapping[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> Mapping[str, Any]:
        body: dict[str, Any] = {
            "id": f"sdk_{uuid.uuid4().hex}",
            "target": dict(target),
            "type": command_type,
            "payload": {"schema": "im.message.outbound.v1", "data": dict(data)},
        }
        if correlation_id is not None:
            body["correlation_id"] = correlation_id
        return self._json(
            await self._client.post("/v1/commands", headers=self._headers, json=body)
        )

    def _websocket_url(self, query: Mapping[str, str]) -> str:
        parts = urlsplit(self.base_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        return urlunsplit((scheme, parts.netloc, "/v1/events/ws", urlencode(query), ""))

    @staticmethod
    def _websocket_close_code(exc: BaseException) -> int | None:
        received = getattr(exc, "rcvd", None)
        code = getattr(received, "code", None)
        return code if isinstance(code, int) else None

    @staticmethod
    def _endpoint_wire(
        endpoint: SourceEndpoint | Mapping[str, Any],
    ) -> Mapping[str, str]:
        if isinstance(endpoint, SourceEndpoint):
            return endpoint.to_wire()
        value = endpoint.get("endpoint", endpoint)
        if not isinstance(value, Mapping):
            raise ValueError("endpoint must be a Gateway endpoint response or identity")
        return {
            key: str(value[key])
            for key in ("family", "adapter_type", "adapter_id", "endpoint_id")
        }

    @staticmethod
    def _json(response: httpx.Response) -> Mapping[str, Any]:
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, Mapping):
            raise ValueError("Gateway returned a non-object JSON response")
        return value
