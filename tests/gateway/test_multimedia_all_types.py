"""Comprehensive test for all multimedia types and QQ special message types in the gateway.

Tests:
- Outbound serialization of all 20+ component types (Image, Record, Video, File, Plain, At, AtAll, Face, Reply, Forward, Node, Nodes, Poke, RPS, Dice, Shake, Share, Location, Music, Json, Unknown)
- Inbound round-trip for plain, image, record, video, file, reply, at, at_all
- Negative tests for unsupported QQ-specific inbound types (face, forward, node, poke, rps, dice, shake)
- Validation that internal fields (path, _type, file_) are not leaked in outbound envelopes
"""

import sys, types, asyncio
from unittest.mock import MagicMock
from pathlib import Path

project_root = Path(r"E:\test\astriminfra\astr-IM infra\astrbot-analysis-gitee")
sys.path.insert(0, str(project_root))

# 1. Mock pydantic
pydantic = types.ModuleType('pydantic')
pydantic.v1 = types.ModuleType('pydantic.v1')
class FakeBaseModel:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    def __setattr__(self, name, value):
        self.__dict__[name] = value
pydantic.BaseModel = FakeBaseModel
pydantic.v1.BaseModel = FakeBaseModel
sys.modules['pydantic'] = pydantic
sys.modules['pydantic.v1'] = pydantic.v1

# 2. Build astrbot package tree
astrbot = types.ModuleType('astrbot')
astrbot.__path__ = [str(project_root / 'astrbot')]
sys.modules['astrbot'] = astrbot

astrbot_core = types.ModuleType('astrbot.core')
astrbot_core.__path__ = [str(project_root / 'astrbot' / 'core')]
astrbot_core.astrbot_config = MagicMock()
astrbot_core.astrbot_config.get = MagicMock(return_value=None)
astrbot_core.file_token_service = MagicMock()
astrbot_core.file_token_service.register_file = MagicMock(return_value="mock_token")
astrbot_core.logger = MagicMock()
sys.modules['astrbot.core'] = astrbot_core

astrbot_core.config = types.ModuleType('astrbot.core.config')
class FakeAstrBotConfig:
    pass
astrbot_core.config.AstrBotConfig = FakeAstrBotConfig
astrbot_core.config.default = types.ModuleType('astrbot.core.config.default')
astrbot_core.config.default.DB_PATH = ":memory:"
sys.modules['astrbot.core.config'] = astrbot_core.config
sys.modules['astrbot.core.config.default'] = astrbot_core.config.default

astrbot_core.log = types.ModuleType('astrbot.core.log')
astrbot_core.log.LogBroker = MagicMock
astrbot_core.log.LogManager = MagicMock()
astrbot_core.log.LogManager.GetLogger = MagicMock(return_value=MagicMock())
astrbot_core.log.LogManager.configure_logger = MagicMock()
astrbot_core.log.LogManager.configure_trace_logger = MagicMock()
sys.modules['astrbot.core.log'] = astrbot_core.log

astrbot_utils = types.ModuleType('astrbot.core.utils')
astrbot_utils.__path__ = [str(project_root / 'astrbot' / 'core' / 'utils')]
astrbot_utils.astrbot_path = types.ModuleType('astrbot.core.utils.astrbot_path')
astrbot_utils.astrbot_path.get_astrbot_temp_path = MagicMock(return_value=str(project_root / "temp"))
astrbot_utils.astrbot_path.get_astrbot_data_path = MagicMock(return_value=str(project_root / "data"))
astrbot_utils.io = types.ModuleType('astrbot.core.utils.io')
astrbot_utils.io.download_file = MagicMock(return_value=None)
astrbot_utils.io.download_image_by_url = MagicMock(return_value="/tmp/fake.jpg")
astrbot_utils.io.file_to_base64 = MagicMock(return_value="base64://fake")
astrbot_utils.shared_preferences = types.ModuleType('astrbot.core.utils.shared_preferences')
astrbot_utils.shared_preferences.SharedPreferences = MagicMock
astrbot_utils.pip_installer = types.ModuleType('astrbot.core.utils.pip_installer')
astrbot_utils.pip_installer.DependencyConflictError = Exception
astrbot_utils.pip_installer.PipInstaller = MagicMock
astrbot_utils.requirements_utils = types.ModuleType('astrbot.core.utils.requirements_utils')
astrbot_utils.requirements_utils.RequirementsPrecheckFailed = Exception
astrbot_utils.requirements_utils.find_missing_requirements = MagicMock(return_value=[])
astrbot_utils.requirements_utils.find_missing_requirements_or_raise = MagicMock()
astrbot_utils.t2i = types.ModuleType('astrbot.core.utils.t2i')
astrbot_utils.t2i.renderer = types.ModuleType('astrbot.core.utils.t2i.renderer')
astrbot_utils.t2i.renderer.HtmlRenderer = MagicMock
astrbot_utils.metrics = types.ModuleType('astrbot.core.utils.metrics')
astrbot_utils.metrics.Metric = MagicMock()
astrbot_utils.trace = types.ModuleType('astrbot.core.utils.trace')
astrbot_utils.trace.TraceSpan = MagicMock
sys.modules['astrbot.core.utils'] = astrbot_utils
sys.modules['astrbot.core.utils.astrbot_path'] = astrbot_utils.astrbot_path
sys.modules['astrbot.core.utils.io'] = astrbot_utils.io
sys.modules['astrbot.core.utils.shared_preferences'] = astrbot_utils.shared_preferences
sys.modules['astrbot.core.utils.pip_installer'] = astrbot_utils.pip_installer
sys.modules['astrbot.core.utils.requirements_utils'] = astrbot_utils.requirements_utils
sys.modules['astrbot.core.utils.t2i'] = astrbot_utils.t2i
sys.modules['astrbot.core.utils.t2i.renderer'] = astrbot_utils.t2i.renderer
sys.modules['astrbot.core.utils.metrics'] = astrbot_utils.metrics
sys.modules['astrbot.core.utils.trace'] = astrbot_utils.trace

astrbot_db = types.ModuleType('astrbot.core.db')
astrbot_db.__path__ = [str(project_root / 'astrbot' / 'core' / 'db')]
astrbot_db.po = types.ModuleType('astrbot.core.db.po')
class FakeAttachment:
    pass
astrbot_db.po.Attachment = FakeAttachment
astrbot_db.sqlite = types.ModuleType('astrbot.core.db.sqlite')
astrbot_db.sqlite.SQLiteDatabase = MagicMock
sys.modules['astrbot.core.db'] = astrbot_db
sys.modules['astrbot.core.db.po'] = astrbot_db.po
sys.modules['astrbot.core.db.sqlite'] = astrbot_db.sqlite

astrbot_agent = types.ModuleType('astrbot.core.agent')
astrbot_agent.__path__ = [str(project_root / 'astrbot' / 'core' / 'agent')]
astrbot_agent.tool = types.ModuleType('astrbot.core.agent.tool')
astrbot_agent.tool.ToolSet = MagicMock
sys.modules['astrbot.core.agent'] = astrbot_agent
sys.modules['astrbot.core.agent.tool'] = astrbot_agent.tool

astrbot_provider = types.ModuleType('astrbot.core.provider')
astrbot_provider.__path__ = [str(project_root / 'astrbot' / 'core' / 'provider')]
astrbot_provider.entities = types.ModuleType('astrbot.core.provider.entities')
astrbot_provider.entities.ProviderRequest = MagicMock
sys.modules['astrbot.core.provider'] = astrbot_provider
sys.modules['astrbot.core.provider.entities'] = astrbot_provider.entities

astrbot_star = types.ModuleType('astrbot.core.star')
astrbot_star.__path__ = [str(project_root / 'astrbot' / 'core' / 'star')]
astrbot_star.star = types.ModuleType('astrbot.core.star.star')
astrbot_star.star.star_map = {}
astrbot_star.star_handler = types.ModuleType('astrbot.core.star.star_handler')
astrbot_star.star_handler.star_handlers_registry = MagicMock()
astrbot_star.filter = types.ModuleType('astrbot.core.star.filter')
astrbot_star.filter.command = types.ModuleType('astrbot.core.star.filter.command')
astrbot_star.filter.command.CommandFilter = MagicMock
astrbot_star.filter.command_group = types.ModuleType('astrbot.core.star.filter.command_group')
astrbot_star.filter.command_group.CommandGroupFilter = MagicMock
sys.modules['astrbot.core.star'] = astrbot_star
sys.modules['astrbot.core.star.star'] = astrbot_star.star
sys.modules['astrbot.core.star.star_handler'] = astrbot_star.star_handler
sys.modules['astrbot.core.star.filter'] = astrbot_star.filter
sys.modules['astrbot.core.star.filter.command'] = astrbot_star.filter.command
sys.modules['astrbot.core.star.filter.command_group'] = astrbot_star.filter.command_group

# --- Fixed FakeMessageType (Enum-like with .name and .value) ---
class FakeMessageType:
    def __init__(self, val):
        if isinstance(val, FakeMessageType):
            self.name = val.name
            self.value = val.value
        elif isinstance(val, str):
            mapping = {
                'FriendMessage': 'FRIEND_MESSAGE',
                'GroupMessage': 'GROUP_MESSAGE',
                'OtherMessage': 'OTHER_MESSAGE',
            }
            self.name = mapping.get(val, val)
            self.value = val
        else:
            self.name = str(val)
            self.value = str(val)
    def __str__(self):
        return self.value

FakeMessageType.FRIEND_MESSAGE = FakeMessageType('FriendMessage')
FakeMessageType.GROUP_MESSAGE = FakeMessageType('GroupMessage')
FakeMessageType.OTHER_MESSAGE = FakeMessageType('OtherMessage')

astrbot_platform = types.ModuleType('astrbot.core.platform')
astrbot_platform.__path__ = [str(project_root / 'astrbot' / 'core' / 'platform')]
astrbot_platform.astrbot_message = types.ModuleType('astrbot.core.platform.astrbot_message')
class FakeGroup:
    pass
class FakeAstrBotMessage:
    pass
class FakeMessageMember:
    def __init__(self, user_id="", nickname=""):
        self.user_id = user_id
        self.nickname = nickname
astrbot_platform.astrbot_message.Group = FakeGroup
astrbot_platform.astrbot_message.AstrBotMessage = FakeAstrBotMessage
astrbot_platform.astrbot_message.MessageMember = FakeMessageMember
astrbot_platform.astrbot_message.MessageType = FakeMessageType
sys.modules['astrbot.core.platform.astrbot_message'] = astrbot_platform.astrbot_message

astrbot_platform.message_session = types.ModuleType('astrbot.core.platform.message_session')
class FakeMessageSession:
    def __init__(self, platform_name, message_type, session_id):
        self.platform_name = platform_name
        self.message_type = message_type
        self.session_id = session_id
    def __str__(self):
        return f"{self.platform_name}:{self.message_type}:{self.session_id}"
class FakeMessageSesion:
    @classmethod
    def from_str(cls, s):
        parts = s.split(":")
        return FakeMessageSession(parts[0], parts[1], parts[2])
astrbot_platform.message_session.MessageSession = FakeMessageSession
astrbot_platform.message_session.MessageSesion = FakeMessageSesion
sys.modules['astrbot.core.platform.message_session'] = astrbot_platform.message_session

astrbot_platform.message_type = types.ModuleType('astrbot.core.platform.message_type')
astrbot_platform.message_type.MessageType = FakeMessageType
sys.modules['astrbot.core.platform.message_type'] = astrbot_platform.message_type

astrbot_platform.platform_metadata = types.ModuleType('astrbot.core.platform.platform_metadata')
class FakePlatformMetadata:
    def __init__(self, name, id, description):
        self.name = name
        self.id = id
        self.description = description
astrbot_platform.platform_metadata.PlatformMetadata = FakePlatformMetadata
sys.modules['astrbot.core.platform.platform_metadata'] = astrbot_platform.platform_metadata

astrbot_platform.register = types.ModuleType('astrbot.core.platform.register')
astrbot_platform.register.register_platform_adapter = lambda *a, **k: (lambda cls: cls)
sys.modules['astrbot.core.platform.register'] = astrbot_platform.register

astrbot_platform.sources = types.ModuleType('astrbot.core.platform.sources')
astrbot_platform.sources.__path__ = [str(project_root / 'astrbot' / 'core' / 'platform' / 'sources')]
astrbot_platform.sources.webchat = types.ModuleType('astrbot.core.platform.sources.webchat')
astrbot_platform.sources.webchat.__path__ = [str(project_root / 'astrbot' / 'core' / 'platform' / 'sources' / 'webchat')]
astrbot_platform.sources.webchat.webchat_queue_mgr = MagicMock()
astrbot_platform.sources.webchat.webchat_adapter = MagicMock()
astrbot_platform.sources.webchat.webchat_event = MagicMock()
sys.modules['astrbot.core.platform.sources'] = astrbot_platform.sources
sys.modules['astrbot.core.platform.sources.webchat'] = astrbot_platform.sources.webchat
sys.modules['astrbot.core.platform.sources.webchat.webchat_queue_mgr'] = astrbot_platform.sources.webchat.webchat_queue_mgr
sys.modules['astrbot.core.platform.sources.webchat.webchat_adapter'] = astrbot_platform.sources.webchat.webchat_adapter
sys.modules['astrbot.core.platform.sources.webchat.webchat_event'] = astrbot_platform.sources.webchat.webchat_event

# Fixed FakeAstrMessageEvent with proper MessageType conversion
astrbot_platform_ame = types.ModuleType('astrbot.core.platform.astr_message_event')
class FakeAstrMessageEvent:
    def __init__(self, message_str, message_obj, platform_meta, session_id):
        self.message_str = message_str
        self.message_obj = message_obj
        self.platform_meta = platform_meta
        self.role = "member"
        self.is_wake = False
        self.is_at_or_wake_command = False
        self._extras = {}
        self._force_stopped = False
        self._result = None
        self._has_send_oper = False
        self.call_llm = False
        self._temporary_local_files = []
        self.plugins_name = None
        self.created_at = 0
        # Convert message_type like real AstrMessageEvent does
        message_type = getattr(message_obj, "type", None)
        if not isinstance(message_type, FakeMessageType):
            try:
                message_type = FakeMessageType(str(message_type))
            except Exception:
                message_type = FakeMessageType.FRIEND_MESSAGE
        self.session = FakeMessageSession(platform_meta.id, message_type, session_id)
    @property
    def unified_msg_origin(self):
        return str(self.session)
    @unified_msg_origin.setter
    def unified_msg_origin(self, value):
        pass
    @property
    def session_id(self):
        return self.session.session_id
    @session_id.setter
    def session_id(self, value):
        self.session.session_id = value
    def get_platform_name(self):
        return self.platform_meta.name
    def get_platform_id(self):
        return self.platform_meta.id
    def get_message_str(self):
        return self.message_str
    def get_messages(self):
        return getattr(self.message_obj, "message", [])
    def get_message_type(self):
        message_type = getattr(self.message_obj, "type", None)
        if isinstance(message_type, FakeMessageType):
            return message_type
        return self.session.message_type
    def get_group_id(self):
        return ""
    def get_self_id(self):
        return getattr(self.message_obj, "self_id", "")
    def get_sender_id(self):
        sender = getattr(self.message_obj, "sender", None)
        if sender:
            return getattr(sender, "user_id", "")
        return ""
    def get_sender_name(self):
        sender = getattr(self.message_obj, "sender", None)
        if sender:
            return getattr(sender, "nickname", "")
        return ""
    def set_extra(self, key, value):
        self._extras[key] = value
    def get_extra(self, key=None, default=None):
        if key is None:
            return self._extras
        return self._extras.get(key, default)
    def clear_extra(self):
        self._extras.clear()
    def track_temporary_local_file(self, path):
        if path and path not in self._temporary_local_files:
            self._temporary_local_files.append(path)
    def cleanup_temporary_local_files(self):
        self._temporary_local_files.clear()
    def is_private_chat(self):
        return self.get_message_type().name == 'FRIEND_MESSAGE'
    def is_wake_up(self):
        return self.is_wake
    def is_admin(self):
        return self.role == "admin"
    def stop_event(self):
        self._force_stopped = True
    def is_stopped(self):
        return self._force_stopped
    def get_result(self):
        return self._result

astrbot_platform_ame.AstrMessageEvent = FakeAstrMessageEvent
sys.modules['astrbot.core.platform.astr_message_event'] = astrbot_platform_ame

astrbot_api = types.ModuleType('astrbot.api')
astrbot_api.__path__ = [str(project_root / 'astrbot' / 'api')]
astrbot_api.event = types.ModuleType('astrbot.api.event')
astrbot_api.event.AstrMessageEvent = FakeAstrMessageEvent
astrbot_api.event.MessageChain = MagicMock
astrbot_api.message_components = types.ModuleType('astrbot.api.message_components')
astrbot_api.platform = types.ModuleType('astrbot.api.platform')
astrbot_api.platform.AstrBotMessage = FakeAstrBotMessage
astrbot_api.platform.MessageMember = FakeMessageMember
astrbot_api.platform.MessageType = FakeMessageType
astrbot_api.platform.Platform = MagicMock
astrbot_api.platform.PlatformMetadata = FakePlatformMetadata
astrbot_api.platform.register_platform_adapter = lambda *a, **k: (lambda cls: cls)
sys.modules['astrbot.api'] = astrbot_api
sys.modules['astrbot.api.event'] = astrbot_api.event
sys.modules['astrbot.api.message_components'] = astrbot_api.message_components
sys.modules['astrbot.api.platform'] = astrbot_api.platform

for mod_name in [
    'sqlalchemy', 'sqlalchemy.ext', 'sqlalchemy.ext.asyncio', 'sqlalchemy.orm',
    'sqlalchemy.future', 'sqlalchemy.sql', 'sqlalchemy.engine', 'sqlalchemy.dialects',
    'aiosqlite', 'quart', 'aiohttp', 'telegram', 'telegram.ext', 'telegram.error',
    'telegram.constants', 'telegram.helpers', 'aiocqhttp', 'discord', 'py_cord',
    'lark_oapi', 'dingtalk_stream', 'slack_sdk', 'websockets', 'wechatpy',
    'wechatpy.crypto', 'pillow', 'PIL', 'PIL.Image', 'pydub', 'silk', 'silk_python',
    'markitdown', 'jieba', 'faiss', 'faiss_cpu', 'mcp', 'anthropic', 'openai',
    'dashscope', 'google', 'google.genai', 'httpx', 'psutil', 'watchfiles', 'apscheduler',
    'apscheduler.schedulers', 'apscheduler.schedulers.asyncio', 'apscheduler.events',
    'aiofiles', 'deprecated', 'docstring_parser', 'filelock', 'cryptography',
    'qrcode', 'pyotp', 'python_ripgrep', 'packaging', 'tenacity', 'shipyard_python_sdk',
    'shipyard_neo_sdk', 'pypdf', 'pysocks', 'python_socks', 'click', 'certifi',
    'chardet', 'loguru', 'ormsgpack', 'pip', 'rank_bm25', 'xinference_client',
    'audioop_lts', 'telegramify_markdown', 'sqlmodel', 'asyncio_mqtt',
]:
    m = types.ModuleType(mod_name)
    m.__path__ = []
    sys.modules[mod_name] = m

print("Mock setup complete. Attempting imports...")

from astrbot.core.message.components import (
    Plain, Image, Record, Video, File, At, AtAll, Face, Reply,
    Forward, Node, Nodes, Poke, RPS, Dice, Shake, Share, Contact,
    Location, Music, Json, Unknown,
)
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.gateway.serializer import MessageSerializer
from astrbot.core.gateway.envelope import MessageEnvelope, EventType
from astrbot.core.platform.sources.webchat.message_parts_helper import (
    build_webchat_message_parts,
    parse_webchat_message_parts,
    build_message_chain_from_payload,
)

print("All imports successful!")

def _make_event(chain, text=""):
    msg = AstrBotMessage()
    msg.sender = MessageMember(user_id="123", nickname="Alice")
    msg.type = MessageType.FRIEND_MESSAGE
    msg.message_str = text
    msg.message = chain
    msg.self_id = "bot_1"
    meta = PlatformMetadata(name="aiocqhttp", id="qq_1", description="")
    return AstrMessageEvent(message_str=text, message_obj=msg, platform_meta=meta, session_id="123")

async def run_tests():
    errors = []
    passed = 0

    def test(name, cond, msg=""):
        nonlocal passed, errors
        if cond:
            passed += 1
            print(f"  PASSED: {name}")
        else:
            errors.append(f"FAILED: {name}: {msg}")
            print(f"  FAILED: {name}: {msg}")

    # --- Outbound Serialization ---
    print("\n[Outbound Serialization]")

    env = await MessageSerializer.to_envelope(_make_event([Image.fromURL("https://img.png")]))
    test("Image URL", env.message.chain[0]["type"] == "Image" and env.message.chain[0]["data"]["file"] == "https://img.png")

    env = await MessageSerializer.to_envelope(_make_event([Image.fromFileSystem("/tmp/test.jpg")]))
    test("Image local", env.message.chain[0]["type"] == "Image" and env.message.chain[0]["data"]["file"].startswith("file://"))

    env = await MessageSerializer.to_envelope(_make_event([Image.fromBase64("base64data")]))
    test("Image base64", env.message.chain[0]["type"] == "Image" and "base64://" in env.message.chain[0]["data"]["file"])

    env = await MessageSerializer.to_envelope(_make_event([Record.fromURL("https://voice.mp3")]))
    test("Record URL", env.message.chain[0]["type"] == "Record" and env.message.chain[0]["data"]["file"] == "https://voice.mp3")

    env = await MessageSerializer.to_envelope(_make_event([Record.fromFileSystem("/tmp/voice.amr")]))
    test("Record local", env.message.chain[0]["type"] == "Record" and env.message.chain[0]["data"]["file"].startswith("file://"))

    env = await MessageSerializer.to_envelope(_make_event([Record.fromBase64("base64data")]))
    test("Record base64", env.message.chain[0]["type"] == "Record" and "base64://" in env.message.chain[0]["data"]["file"])

    env = await MessageSerializer.to_envelope(_make_event([Record(file="https://voice.mp3", text="hello")]))
    test("Record with text", env.message.chain[0]["type"] == "Record" and env.message.chain[0]["data"].get("text") == "hello")

    env = await MessageSerializer.to_envelope(_make_event([Video.fromURL("https://video.mp4")]))
    test("Video URL", env.message.chain[0]["type"] == "Video" and env.message.chain[0]["data"]["file"] == "https://video.mp4")

    env = await MessageSerializer.to_envelope(_make_event([Video.fromFileSystem("/tmp/video.mp4")]))
    test("Video local", env.message.chain[0]["type"] == "Video" and env.message.chain[0]["data"]["file"].startswith("file://"))

    env = await MessageSerializer.to_envelope(_make_event([File(name="report.pdf", url="https://report.pdf")]))
    test("File URL", env.message.chain[0]["type"] == "File" and env.message.chain[0]["data"]["file"] == "https://report.pdf" and env.message.chain[0]["data"]["name"] == "report.pdf")

    env = await MessageSerializer.to_envelope(_make_event([File(name="report.pdf", file="/tmp/report.pdf")]))
    test("File local", env.message.chain[0]["type"] == "File" and env.message.chain[0]["data"]["file"] == "/tmp/report.pdf" and env.message.chain[0]["data"]["name"] == "report.pdf")

    env = await MessageSerializer.to_envelope(_make_event([Plain(text="hello")], "hello"))
    test("Plain", env.message.chain[0]["type"] == "text" and env.message.chain[0]["data"]["text"] == "hello")

    env = await MessageSerializer.to_envelope(_make_event([At(qq="123456", name="Bob")]))
    test("At", env.message.chain[0]["type"] == "at" and env.message.chain[0]["data"]["qq"] == "123456")

    env = await MessageSerializer.to_envelope(_make_event([AtAll()]))
    test("AtAll", env.message.chain[0]["type"] == "at" and env.message.chain[0]["data"]["qq"] == "all")

    env = await MessageSerializer.to_envelope(_make_event([Face(id=123)]))
    test("Face", env.message.chain[0]["type"] == "face" and env.message.chain[0]["data"]["id"] == 123)

    env = await MessageSerializer.to_envelope(_make_event([Reply(id="msg_123")]))
    test("Reply", env.message.chain[0]["type"] == "reply" and env.message.chain[0]["data"]["id"] == "msg_123")

    env = await MessageSerializer.to_envelope(_make_event([Forward(id="fwd_abc")]))
    test("Forward", env.message.chain[0]["type"] == "forward" and env.message.chain[0]["data"]["id"] == "fwd_abc")

    env = await MessageSerializer.to_envelope(_make_event([Node(content=[Plain(text="node")], uin="123", name="Alice")]))
    test("Node", env.message.chain[0]["type"] == "node" and env.message.chain[0]["data"]["user_id"] == "123" and "content" in env.message.chain[0]["data"])

    env = await MessageSerializer.to_envelope(_make_event([Nodes(nodes=[Node(content=[Plain(text="n1")], uin="1", name="A")])]))
    test("Nodes", env.message.chain[0]["type"] == "Nodes" and "messages" in env.message.chain[0]["data"])

    env = await MessageSerializer.to_envelope(_make_event([Poke(poke_type="126")]))
    test("Poke", env.message.chain[0]["type"] == "poke" and env.message.chain[0]["data"]["type"] == "126")

    env = await MessageSerializer.to_envelope(_make_event([RPS()]))
    test("RPS", env.message.chain[0]["type"] == "rps")

    env = await MessageSerializer.to_envelope(_make_event([Dice()]))
    test("Dice", env.message.chain[0]["type"] == "dice")

    env = await MessageSerializer.to_envelope(_make_event([Shake()]))
    test("Shake", env.message.chain[0]["type"] == "shake")

    env = await MessageSerializer.to_envelope(_make_event([Share(url="https://link.com", title="Link")]))
    test("Share", env.message.chain[0]["type"] == "share" and env.message.chain[0]["data"]["url"] == "https://link.com")

    env = await MessageSerializer.to_envelope(_make_event([Location(lat=39.9, lon=116.4, title="Beijing")]))
    test("Location", env.message.chain[0]["type"] == "location" and env.message.chain[0]["data"]["lat"] == 39.9)

    env = await MessageSerializer.to_envelope(_make_event([Music(_type="qq", id=12345)]))
    test("Music", env.message.chain[0]["type"] == "music" and env.message.chain[0]["data"].get("type") == "qq")

    env = await MessageSerializer.to_envelope(_make_event([Json(data={"key": "value"})]))
    test("Json", env.message.chain[0]["type"] == "json" and env.message.chain[0]["data"]["data"] == {"key": "value"})

    env = await MessageSerializer.to_envelope(_make_event([Unknown(text="something")]))
    test("Unknown", env.message.chain[0]["type"] == "unknown" and env.message.chain[0]["data"]["text"] == "something")

    env = await MessageSerializer.to_envelope(_make_event([
        Reply(id="msg_123"), At(qq="456", name="Bob"), Image.fromURL("https://img.png"),
        Plain(text="look"), Forward(id="fwd")
    ]))
    test("Mixed QQ chain", len(env.message.chain) == 5 and env.message.chain[0]["type"] == "reply" and env.message.chain[1]["type"] == "at" and env.message.chain[2]["type"] == "Image" and env.message.chain[3]["type"] == "text" and env.message.chain[4]["type"] == "forward")

    env = await MessageSerializer.to_envelope(_make_event([Image.fromURL("https://img.png")]))
    test("No internal fields leak", "path" not in env.message.chain[0]["data"] and "_type" not in env.message.chain[0]["data"])

    env = await MessageSerializer.to_envelope(_make_event([File(name="x.pdf", url="https://x.pdf")]))
    test("File hides file_", "file" in env.message.chain[0]["data"] and "file_" not in env.message.chain[0]["data"])

    # --- Inbound Round-Trip ---
    print("\n[Inbound Round-Trip]")

    chain = await build_message_chain_from_payload([{"type": "plain", "text": "hello"}], get_attachment_by_id=None, strict=True)
    test("Inbound plain", len(chain.chain) == 1 and isinstance(chain.chain[0], Plain))

    chain = await build_message_chain_from_payload([{"type": "image", "url": "https://img.png"}], get_attachment_by_id=None, strict=True)
    test("Inbound image URL", isinstance(chain.chain[0], Image) and chain.chain[0].file == "https://img.png")

    chain = await build_message_chain_from_payload([{"type": "record", "url": "https://voice.mp3"}], get_attachment_by_id=None, strict=True)
    test("Inbound record URL", isinstance(chain.chain[0], Record) and chain.chain[0].file == "https://voice.mp3")

    chain = await build_message_chain_from_payload([{"type": "video", "url": "https://video.mp4"}], get_attachment_by_id=None, strict=True)
    test("Inbound video URL", isinstance(chain.chain[0], Video) and chain.chain[0].file == "https://video.mp4")

    chain = await build_message_chain_from_payload([{"type": "file", "url": "https://doc.pdf", "filename": "doc.pdf"}], get_attachment_by_id=None, strict=True)
    test("Inbound file URL", isinstance(chain.chain[0], File) and chain.chain[0].url == "https://doc.pdf" and chain.chain[0].name == "doc.pdf")

    chain = await build_message_chain_from_payload([
        {"type": "reply", "message_id": "msg_123", "selected_text": "quoted"},
        {"type": "plain", "text": "hello"}
    ], get_attachment_by_id=None, strict=True)
    test("Inbound reply", isinstance(chain.chain[0], Reply) and chain.chain[0].id == "msg_123")

    chain = await build_message_chain_from_payload([{"type": "at", "qq": "123456", "name": "Bob"}], get_attachment_by_id=None, strict=True)
    test("Inbound at", isinstance(chain.chain[0], At) and chain.chain[0].qq == "123456" and chain.chain[0].name == "Bob")

    chain = await build_message_chain_from_payload([{"type": "at", "qq": "all"}], get_attachment_by_id=None, strict=True)
    test("Inbound at all", isinstance(chain.chain[0], AtAll))

    chain = await build_message_chain_from_payload([
        {"type": "plain", "text": "Hey "},
        {"type": "at", "qq": "123456", "name": "Bob"},
        {"type": "image", "url": "https://img.png"},
        {"type": "file", "url": "https://doc.pdf", "filename": "doc.pdf"},
    ], get_attachment_by_id=None, strict=True)
    test("Inbound mixed", len(chain.chain) == 4 and isinstance(chain.chain[0], Plain) and isinstance(chain.chain[1], At) and isinstance(chain.chain[2], Image) and isinstance(chain.chain[3], File))

    # QQ-specific inbound not supported
    for bad_type in ["face", "forward", "node", "poke", "rps", "dice", "shake"]:
        try:
            await build_message_chain_from_payload([{"type": bad_type}], get_attachment_by_id=None, strict=True)
            test(f"Inbound {bad_type} not supported", False, f"should have raised ValueError for {bad_type}")
        except ValueError as e:
            test(f"Inbound {bad_type} not supported", "unsupported" in str(e))

    # attachment_id without DB
    try:
        await build_message_chain_from_payload([{"type": "image", "attachment_id": "abc"}], get_attachment_by_id=None, strict=True)
        test("Inbound attachment_id no DB", False, "should have raised")
    except ValueError as e:
        test("Inbound attachment_id no DB", "get_attachment_by_id is not provided" in str(e))

    # --- Report ---
    if errors:
        print(f"\n{'='*60}")
        print(f"SUMMARY: {passed} passed, {len(errors)} failed")
        print(f"{'='*60}")
        for e in errors:
            print(f"  {e}")
        raise RuntimeError(f"{len(errors)} tests failed")

    print(f"\n{'='*60}")
    print(f"ALL {passed} TESTS PASSED")
    print(f"{'='*60}")
    return {"passed": passed, "errors": []}

async def main():
    result = await run_tests()
    return result

if __name__ == "__main__":
    asyncio.run(main())
