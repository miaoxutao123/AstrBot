"""GatewayStage — replaces internal Agent/LLM processing with external forwarding.

When gateway mode is enabled, incoming IM messages are serialized into
MessageEnvelope and dispatched via Webhook / LongPoll / WebSocket
instead of being processed by the built-in LLM pipeline.
"""

from collections.abc import AsyncGenerator

from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.message.message_event_result import MessageEventResult
from ..context import PipelineContext
from ..stage import Stage, register_stage
from astrbot.core.gateway import MessageSerializer, GatewayDispatcher


@register_stage
class GatewayStage(Stage):
    """Intercepts messages and forwards them to external Agent systems."""

    async def initialize(self, ctx: PipelineContext) -> None:
        self.ctx = ctx
        self.config = ctx.astrbot_config
        gateway_cfg = self.config.get("gateway", {})
        self.enabled = gateway_cfg.get("enabled", False)
        self.dispatcher: GatewayDispatcher | None = None
        if self.enabled:
            self.dispatcher = GatewayDispatcher(gateway_cfg)
            await self.dispatcher.initialize()
            ctx.gateway_dispatcher = self.dispatcher

    async def process(self, event: AstrMessageEvent) -> None | AsyncGenerator[None, None]:
        if not self.enabled or not self.dispatcher:
            return

        # 如果事件已经被插件处理（Star handler），跳过网关转发
        activated_handlers = event.get_extra("activated_handlers")
        if activated_handlers:
            return

        # 序列化并分发
        envelope = await MessageSerializer.to_envelope(event)
        result = await self.dispatcher.dispatch(envelope)

        if result:
            try:
                import json
                data = json.loads(result)
                reply = data.get("reply", result)
            except Exception:
                reply = result
            event.set_result(
                MessageEventResult().message(reply)
            )
        else:
            event.set_result(
                MessageEventResult().message("[消息已转发至外部 Agent]")
            )
        event.stop_event()
