"""Host-owned metadata used to configure built-in adapter instances."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AdapterTypeDefinition:
    """Describe a Gateway adapter form without extending Adapter API v1."""

    adapter_type: str
    name: str
    family: str
    auth_mode: str
    fields: tuple[dict[str, Any], ...] = ()

    def wire(self) -> dict[str, Any]:
        return {
            "type": self.adapter_type,
            "name": self.name,
            "family": self.family,
            "auth_mode": self.auth_mode,
            "fields": list(self.fields),
        }


_IM_TYPES: tuple[AdapterTypeDefinition, ...] = (
    AdapterTypeDefinition(
        "onebot",
        "OneBot",
        "im",
        "none",
        (
            {
                "name": "mode",
                "label": "Mode",
                "label_key": "gateway.adapterFields.mode",
                "type": "select",
                "required": True,
                "default": "websocket",
            },
            {
                "name": "endpoint",
                "label": "WebSocket endpoint",
                "label_key": "gateway.adapterFields.websocketEndpoint",
                "type": "url",
                "required": True,
            },
            {
                "name": "token",
                "label": "Access token",
                "label_key": "gateway.adapterFields.accessToken",
                "type": "password",
                "secret": True,
            },
        ),
    ),
    AdapterTypeDefinition(
        "telegram",
        "Telegram",
        "im",
        "credentials",
        (
            {
                "name": "token",
                "label": "Bot token",
                "label_key": "gateway.adapterFields.botToken",
                "type": "password",
                "secret": True,
                "required": True,
            },
        ),
    ),
    AdapterTypeDefinition("weixin", "Weixin OC", "im", "interactive"),
    AdapterTypeDefinition(
        "satori",
        "Satori",
        "im",
        "credentials",
        (
            {
                "name": "endpoint",
                "label": "Event endpoint",
                "label_key": "gateway.adapterFields.eventEndpoint",
                "type": "url",
                "required": True,
            },
            {
                "name": "api_base_url",
                "label": "API base URL",
                "label_key": "gateway.adapterFields.apiBaseUrl",
                "type": "url",
                "required": True,
            },
            {
                "name": "token",
                "label": "Access token",
                "type": "password",
                "secret": True,
            },
        ),
    ),
    AdapterTypeDefinition(
        "qq_official",
        "QQ Official",
        "im",
        "credentials",
        (
            {
                "name": "app_id",
                "label": "App ID",
                "label_key": "gateway.adapterFields.appId",
                "type": "text",
                "required": True,
            },
            {
                "name": "secret",
                "label": "App secret",
                "label_key": "gateway.adapterFields.appSecret",
                "type": "password",
                "secret": True,
                "required": True,
            },
        ),
    ),
)


class AdapterTypeCatalog:
    """Return safe UI metadata for the adapter factories discovered by Host."""

    def list(self, available_types: tuple[str, ...]) -> list[dict[str, Any]]:
        available = set(available_types)
        return [
            definition.wire()
            for definition in _IM_TYPES
            if definition.adapter_type in available
        ]
