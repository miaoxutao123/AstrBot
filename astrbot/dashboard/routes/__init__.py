from .api_key import ApiKeyRoute
from .auth import AuthRoute
from .background_task import BackgroundTaskRoute
from .backup import BackupRoute
from .chat import ChatRoute
from .chatui_project import ChatUIProjectRoute
from .command import CommandRoute
from .config import ConfigRoute
from .conversation import ConversationRoute
from .cron import CronRoute
from .file import FileRoute
from .knowledge_base import KnowledgeBaseRoute
from .log import LogRoute
from .open_api import OpenApiRoute
from .long_term_memory import LongTermMemoryRoute
from .persona import PersonaRoute
from .platform import PlatformRoute
from .plugin import PluginRoute
from .project_context import ProjectContextRoute
from .session_management import SessionManagementRoute
from .skills import SkillsRoute
from .stat import StatRoute
from .static_file import StaticFileRoute
from .subagent import SubAgentRoute
from .tool_evolution import ToolEvolutionRoute
from .tools import ToolsRoute
from .update import UpdateRoute
from .workflow import WorkflowRoute

__all__ = [
    "ApiKeyRoute",
    "AuthRoute",
    "BackupRoute",
    "ChatRoute",
    "ChatUIProjectRoute",
    "CommandRoute",
    "ConfigRoute",
    "ConversationRoute",
    "CronRoute",
    "BackgroundTaskRoute",
    "FileRoute",
    "KnowledgeBaseRoute",
    "LogRoute",
    "OpenApiRoute",
    "LongTermMemoryRoute",
    "PersonaRoute",
    "ProjectContextRoute",
    "PlatformRoute",
    "PluginRoute",
    "SessionManagementRoute",
    "StatRoute",
    "StaticFileRoute",
    "SubAgentRoute",
    "ToolEvolutionRoute",
    "ToolsRoute",
    "SkillsRoute",
    "UpdateRoute",
    "WorkflowRoute",
]
