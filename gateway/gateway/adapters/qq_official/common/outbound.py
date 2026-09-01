"""Gateway IM to QQ Official REST conversion."""

from gateway.media import MediaStore
from gateway.profiles.im import IMOutboundMessage

from .api import QQOfficialAPI
from .media import upload_image
from .models import QQOfficialEndpoint


async def send_message(
    endpoint_value: str,
    message: IMOutboundMessage,
    api: QQOfficialAPI,
    media: MediaStore,
) -> str | None:
    endpoint = QQOfficialEndpoint.decode(endpoint_value)
    texts: list[str] = []
    image = None
    for segment in message.segments:
        if segment.type == "text":
            texts.append(str(segment.data["text"]))
        elif segment.type == "reply":
            continue
        elif segment.type == "image" and image is None:
            image = await upload_image(endpoint, segment, api, media)
        else:
            raise ValueError(
                f"QQ Official outbound segment is unsupported: {segment.type}"
            )
    payload: dict[str, object] = {"content": "".join(texts), "msg_type": 0}
    if message.reply_to:
        payload["msg_id"] = message.reply_to
    if image is not None:
        payload.update({"media": image, "msg_type": 7})
    if endpoint.scene == "c2c":
        path = f"/v2/users/{endpoint.destination_id}/messages"
        payload["msg_seq"] = 1
    elif endpoint.scene == "group":
        path = f"/v2/groups/{endpoint.destination_id}/messages"
        payload["msg_seq"] = 1
    else:
        path = f"/channels/{endpoint.destination_id}/messages"
    result = await api.request("POST", path, payload)
    message_id = result.get("id")
    return str(message_id) if isinstance(message_id, str | int) else None
