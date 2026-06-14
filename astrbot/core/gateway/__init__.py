"""Gateway module for AstraBot — Unified IM Gateway.

Provides three outbound channels for external Agent systems:
- Webhook (push)
- Long Polling (pull)
- WebSocket (full-duplex)

All channels share the same MessageEnvelope schema.
"""

from .envelope import MessageEnvelope, EventType
from .serializer import MessageSerializer
from .dispatcher import GatewayDispatcher
from .webhook import WebhookPusher
from .longpoll import LongPollQueue
from .websocket import GatewayWebSocketHandler

__all__ = [
    "MessageEnvelope",
    "EventType",
    "MessageSerializer",
    "GatewayDispatcher",
    "WebhookPusher",
    "LongPollQueue",
    "GatewayWebSocketHandler",
]
