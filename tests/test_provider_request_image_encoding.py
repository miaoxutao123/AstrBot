import os
import sys
import json

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial


@pytest.mark.asyncio
async def test_provider_request_normalizes_base64_scheme_payload():
    req = ProviderRequest()
    result = await req._encode_image_bs64("base64://aGVs\nbG8")
    assert result == "data:image/jpeg;base64,aGVsbG8="


@pytest.mark.asyncio
async def test_provider_request_normalizes_data_url_payload():
    req = ProviderRequest()
    result = await req._encode_image_bs64("data:image/png;base64,aGVs\nbG8")
    assert result == "data:image/png;base64,aGVsbG8="


@pytest.mark.asyncio
async def test_provider_request_ignores_invalid_base64_image():
    req = ProviderRequest(prompt=None, image_urls=["base64://not_base64@@@"])
    message = await req.assemble_context()
    assert isinstance(message["content"], list)
    assert message["content"][0]["type"] == "text"
    assert message["content"][0]["text"] == "[图片]"
    assert all(block.get("type") != "image_url" for block in message["content"])


@pytest.mark.asyncio
async def test_openai_payload_normalizes_context_base64_image():
    provider = ProviderOpenAIOfficial(
        provider_config={
            "key": ["test-key"],
            "model": "gpt-4o-mini",
            "type": "openai_chat_completion",
        },
        provider_settings={},
    )
    contexts = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "base64://aGVs\nbG8"},
                }
            ],
        }
    ]

    payload, _ = await provider._prepare_chat_payload(prompt=None, contexts=contexts)
    message_content = payload["messages"][0]["content"]
    assert isinstance(message_content, list)
    image_blocks = [
        block for block in message_content if isinstance(block, dict) and block.get("type") == "image_url"
    ]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"] == "data:image/jpeg;base64,aGVsbG8="


@pytest.mark.asyncio
async def test_openai_payload_drops_invalid_context_base64_image():
    provider = ProviderOpenAIOfficial(
        provider_config={
            "key": ["test-key"],
            "model": "gpt-4o-mini",
            "type": "openai_chat_completion",
        },
        provider_settings={},
    )
    contexts = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "base64://not_base64@@@"},
                }
            ],
        }
    ]

    payload, _ = await provider._prepare_chat_payload(prompt=None, contexts=contexts)
    message_content = payload["messages"][0]["content"]
    assert isinstance(message_content, list)
    assert message_content[0]["type"] == "text"
    assert message_content[0]["text"] == "[图片]"
    assert all(block.get("type") != "image_url" for block in message_content if isinstance(block, dict))


@pytest.mark.asyncio
async def test_openai_payload_sanitizes_invalid_tool_call_arguments():
    provider = ProviderOpenAIOfficial(
        provider_config={
            "key": ["test-key"],
            "model": "gpt-4o-mini",
            "type": "openai_chat_completion",
        },
        provider_settings={},
    )
    contexts = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": '{"q":"abc"\n...[truncated 100 chars]...\n',
                    },
                }
            ],
        }
    ]

    payload, _ = await provider._prepare_chat_payload(prompt=None, contexts=contexts)
    arguments = payload["messages"][0]["tool_calls"][0]["function"]["arguments"]
    assert isinstance(arguments, str)
    parsed = json.loads(arguments)
    assert parsed.get("_astrbot_notice")


@pytest.mark.asyncio
async def test_openai_payload_converts_dict_tool_call_arguments_to_json_string():
    provider = ProviderOpenAIOfficial(
        provider_config={
            "key": ["test-key"],
            "model": "gpt-4o-mini",
            "type": "openai_chat_completion",
        },
        provider_settings={},
    )
    contexts = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": {"q": "astrbot"},
                    },
                }
            ],
        }
    ]

    payload, _ = await provider._prepare_chat_payload(prompt=None, contexts=contexts)
    arguments = payload["messages"][0]["tool_calls"][0]["function"]["arguments"]
    assert isinstance(arguments, str)
    assert json.loads(arguments) == {"q": "astrbot"}
