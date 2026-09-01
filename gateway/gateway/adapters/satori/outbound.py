"""Gateway IM to Satori XML conversion."""

import base64
import html

from gateway.media import MediaStore
from gateway.profiles.im import IMOutboundMessage, IMSegment

from .client import SatoriClient
from .protocol import parse_endpoint


async def _segment(segment: IMSegment, media: MediaStore) -> str:
    if segment.type == "text":
        return html.escape(str(segment.data["text"]))
    if segment.type == "mention":
        target = html.escape(str(segment.data["id"]), quote=True)
        return f'<at id="{target}"/>'
    if segment.type == "reply":
        message_id = html.escape(str(segment.data["message_id"]), quote=True)
        return f'<quote id="{message_id}"/>'
    if segment.type in {"image", "audio", "video", "file"}:
        reference = segment.data.get("media")
        if not isinstance(reference, dict):
            raise ValueError("invalid media segment")
        content = await media.get(str(reference.get("media_id", "")))
        encoded = base64.b64encode(content.data).decode()
        tag = "img" if segment.type == "image" else segment.type
        name = html.escape(content.metadata.filename, quote=True)
        return (
            f'<{tag} src="data:{content.metadata.mime_type};base64,{encoded}" '
            f'name="{name}"/>'
        )
    raise ValueError(f"Satori outbound segment is unsupported: {segment.type}")


async def send_message(
    client: SatoriClient,
    endpoint: str,
    message: IMOutboundMessage,
    media: MediaStore,
) -> str | None:
    login, channel_id = parse_endpoint(endpoint)
    parts = []
    if message.reply_to:
        reply_id = html.escape(message.reply_to, quote=True)
        parts.append(f'<quote id="{reply_id}"/>')
    for segment in message.segments:
        parts.append(await _segment(segment, media))
    result = await client.call(
        "POST",
        "/message.create",
        {"channel_id": channel_id, "content": "".join(parts)},
        login,
    )
    message_id = result.get("id")
    return str(message_id) if isinstance(message_id, str | int) else None
