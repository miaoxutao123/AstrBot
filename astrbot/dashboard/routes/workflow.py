"""Workflow management routes for visual Agent orchestration."""

import traceback
import uuid

from quart import request

from astrbot.core import logger
from astrbot.core.core_lifecycle import AstrBotCoreLifecycle
from astrbot.core.db import BaseDatabase

from .route import Response


class WorkflowRoute:
    def __init__(self, core_lifecycle: AstrBotCoreLifecycle, db_helper: BaseDatabase):
        self.core_lifecycle = core_lifecycle
        self.db_helper = db_helper
        self.routes = {
            "/workflow/list": ("GET", self.list_workflows),
            "/workflow/get/<workflow_id>": ("GET", self.get_workflow),
            "/workflow/save": ("POST", self.save_workflow),
            "/workflow/delete/<workflow_id>": ("DELETE", self.delete_workflow),
            "/workflow/test": ("POST", self.test_workflow),
            "/workflow/tools/available": ("GET", self.get_available_tools),
            "/workflow/providers/available": ("GET", self.get_available_providers),
            "/workflow/knowledge-bases/available": (
                "GET",
                self.get_available_knowledge_bases,
            ),
            "/workflow/plugin-commands/available": (
                "GET",
                self.get_available_plugin_commands,
            ),
            "/workflow/platforms/available": ("GET", self.get_available_platforms),
            "/workflow/deploy/<workflow_id>": (
                "POST",
                self.deploy_workflow_as_provider,
            ),
            "/workflow/undeploy/<workflow_id>": (
                "POST",
                self.undeploy_workflow_provider,
            ),
        }

    def get_routes(self):
        return self.routes

    async def list_workflows(self):
        """List all workflows."""
        try:
            workflows = await self.db_helper.get_all_workflows()
            return Response().ok(workflows).__dict__
        except Exception as e:
            logger.error(f"获取工作流列表失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"获取工作流列表失败: {e!s}").__dict__

    async def get_workflow(self, workflow_id: str):
        """Get a specific workflow by ID."""
        try:
            workflow = await self.db_helper.get_workflow(workflow_id)
            if not workflow:
                return Response().error("工作流不存在").__dict__
            return Response().ok(workflow).__dict__
        except Exception as e:
            logger.error(f"获取工作流失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"获取工作流失败: {e!s}").__dict__

    async def save_workflow(self):
        """Save a workflow (create or update)."""
        try:
            data = await request.get_json()
            workflow_id = data.get("workflow_id")
            name = data.get("name", "Untitled Workflow")
            description = data.get("description", "")
            workflow_data = data.get("data", {})

            if not workflow_id:
                workflow_id = str(uuid.uuid4())

            workflow = {
                "workflow_id": workflow_id,
                "name": name,
                "description": description,
                "data": workflow_data,
            }

            await self.db_helper.save_workflow(workflow)
            return Response().ok({"workflow": workflow}).__dict__
        except Exception as e:
            logger.error(f"保存工作流失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"保存工作流失败: {e!s}").__dict__

    async def delete_workflow(self, workflow_id: str):
        """Delete a workflow."""
        try:
            # 先检查并取消部署已部署的 provider
            provider_id = f"workflow_{workflow_id}"
            provider_manager = self.core_lifecycle.provider_manager
            if provider_id in provider_manager.inst_map:
                await provider_manager.delete_provider(provider_id)
                logger.info(f"已移除工作流 Provider: {provider_id}")

            await self.db_helper.delete_workflow(workflow_id)
            return Response().ok(None).__dict__
        except Exception as e:
            logger.error(f"删除工作流失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"删除工作流失败: {e!s}").__dict__

    async def test_workflow(self):
        """Test run a workflow with given input.

        Supports multimodal input with images:
        {
            "workflow_data": {...},
            "input": "text input",
            "image_urls": ["http://...", "data:image/..."]  // optional
        }
        """
        try:
            data = await request.get_json()
            workflow_data = data.get("workflow_data", {})
            test_input = data.get("input", "")
            image_urls = data.get("image_urls", [])

            from astrbot.core.agent.runners.workflow_agent_runner import (
                WorkflowAgentRunner,
            )

            from astrbot.core.message.components import Image, Plain

            runner = WorkflowAgentRunner(
                workflow_data=workflow_data,
                provider_manager=self.core_lifecycle.provider_manager,
                kb_manager=self.core_lifecycle.kb_manager,
            )

            # Build input components if images are provided
            input_components = None
            if image_urls:
                input_components = []
                if test_input:
                    input_components.append(Plain(test_input))
                for url in image_urls:
                    input_components.append(
                        Image.fromURL(url)
                        if url.startswith("http")
                        else Image(file=url)
                    )

            result = await runner.run(test_input, input_components=input_components)

            # Serialize result components for frontend
            result_components_data = []
            for comp in result.result_components:
                comp_data = {
                    "type": comp.type.value
                    if hasattr(comp.type, "value")
                    else str(comp.type)
                }
                if hasattr(comp, "text"):
                    comp_data["text"] = comp.text
                if hasattr(comp, "file"):
                    comp_data["file"] = comp.file
                if hasattr(comp, "url"):
                    comp_data["url"] = comp.url
                result_components_data.append(comp_data)

            # Serialize structured logs for frontend
            structured_logs_data = []
            if hasattr(result, "structured_logs") and result.structured_logs:
                for log_entry in result.structured_logs:
                    structured_logs_data.append(log_entry.to_dict())

            return (
                Response()
                .ok(
                    {
                        "result": result.result_text,
                        "result_components": result_components_data,
                        "logs": result.execution_logs
                        if hasattr(result, "execution_logs")
                        else [],
                        "structured_logs": structured_logs_data,
                        "success": result.success,
                        "error": result.error,
                    }
                )
                .__dict__
            )
        except Exception as e:
            logger.error(f"测试工作流失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"测试工作流失败: {e!s}").__dict__

    async def get_available_tools(self):
        """Get all available tools for workflow nodes."""
        try:
            llm_tools = self.core_lifecycle.provider_manager.llm_tools
            tools = []

            for tool in llm_tools.func_list:
                tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                        "active": tool.active,
                    }
                )

            return Response().ok(tools).__dict__
        except Exception as e:
            logger.error(f"获取可用工具列表失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"获取可用工具列表失败: {e!s}").__dict__

    async def get_available_providers(self):
        """Get all available LLM providers for workflow nodes."""
        try:
            provider_manager = self.core_lifecycle.provider_manager
            providers = []

            for provider in provider_manager.provider_insts:
                meta = provider.meta()
                providers.append(
                    {
                        "id": meta.id,
                        "model": meta.model,
                        "type": meta.type,
                        "provider_type": meta.provider_type.value
                        if meta.provider_type
                        else None,
                    }
                )

            return Response().ok(providers).__dict__
        except Exception as e:
            logger.error(f"获取可用模型列表失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"获取可用模型列表失败: {e!s}").__dict__

    async def get_available_knowledge_bases(self):
        """Get all available knowledge bases for workflow nodes."""
        try:
            kb_manager = self.core_lifecycle.kb_manager
            knowledge_bases = await kb_manager.list_kbs()

            result = []
            for kb in knowledge_bases:
                result.append(
                    {
                        "kb_id": kb.kb_id,
                        "name": kb.kb_name,
                        "description": kb.description,
                    }
                )

            return Response().ok(result).__dict__
        except Exception as e:
            logger.error(f"获取可用知识库列表失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"获取可用知识库列表失败: {e!s}").__dict__

    async def get_available_plugin_commands(self):
        """Get all available plugin command handlers for workflow nodes."""
        try:
            from astrbot.core.star.star import star_map
            from astrbot.core.star.star_handler import EventType, star_handlers_registry

            commands = []

            # Get all AdapterMessageEvent handlers (which are typically commands)
            handlers = star_handlers_registry.get_handlers_by_event_type(
                EventType.AdapterMessageEvent,
                only_activated=True,
            )

            for handler in handlers:
                # Get plugin info
                plugin = star_map.get(handler.handler_module_path)
                plugin_name = plugin.name if plugin else "Unknown"

                # Get command info from filters
                command_name = ""
                for filter_ in handler.event_filters:
                    if hasattr(filter_, "command_name"):
                        command_name = getattr(filter_, "command_name", "")
                        break
                    elif hasattr(filter_, "regex"):
                        command_name = f"[regex] {getattr(filter_, 'regex', '')}"
                        break

                commands.append(
                    {
                        "handler_full_name": handler.handler_full_name,
                        "handler_name": handler.handler_name,
                        "plugin_name": plugin_name,
                        "command_name": command_name,
                        "description": handler.desc or "",
                        "enabled": handler.enabled,
                    }
                )

            return Response().ok(commands).__dict__
        except Exception as e:
            logger.error(f"获取可用插件命令列表失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"获取可用插件命令列表失败: {e!s}").__dict__

    async def get_available_platforms(self):
        """Get all available platforms for workflow nodes."""
        try:
            platform_manager = self.core_lifecycle.platform_manager
            platforms = []

            for platform in platform_manager.platform_insts:
                meta = platform.meta()
                platforms.append(
                    {
                        "id": meta.id,
                        "name": meta.name,
                        "display_name": meta.adapter_display_name or meta.name,
                        "status": platform.status.value
                        if hasattr(platform, "status")
                        else "unknown",
                    }
                )

            return Response().ok(platforms).__dict__
        except Exception as e:
            logger.error(f"获取可用平台列表失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"获取可用平台列表失败: {e!s}").__dict__

    async def deploy_workflow_as_provider(self, workflow_id: str):
        """Deploy a workflow as a provider that can be selected for conversations."""
        try:
            # Get the workflow
            workflow = await self.db_helper.get_workflow(workflow_id)
            if not workflow:
                return Response().error("工作流不存在").__dict__

            # Create provider config
            provider_id = f"workflow_{workflow_id}"
            provider_config = {
                "id": provider_id,
                "type": "workflow",
                "enable": True,
                "provider_type": "chat_completion",  # Required for frontend filtering
                "workflow_id": workflow_id,
                "workflow_name": workflow.get("name", "Workflow"),
                "workflow_data": workflow.get("data", {}),
            }

            # Check if already exists
            provider_manager = self.core_lifecycle.provider_manager
            if provider_id in provider_manager.inst_map:
                # Already deployed, just reload
                await provider_manager.reload(provider_config)
            else:
                # Create new provider
                await provider_manager.create_provider(provider_config)

            # Inject kb_manager
            if provider_id in provider_manager.inst_map:
                provider = provider_manager.inst_map[provider_id]
                if hasattr(provider, "set_managers"):
                    provider.set_managers(  # type: ignore[union-attr]
                        provider_manager, self.core_lifecycle.kb_manager
                    )

            # Update workflow's deployed status in database
            workflow["deployed"] = True
            await self.db_helper.save_workflow(workflow)

            return (
                Response()
                .ok({"provider_id": provider_id, "message": "工作流已部署为 Provider"})
                .__dict__
            )
        except Exception as e:
            logger.error(f"部署工作流失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"部署工作流失败: {e!s}").__dict__

    async def undeploy_workflow_provider(self, workflow_id: str):
        """Remove a workflow provider deployment."""
        try:
            provider_id = f"workflow_{workflow_id}"
            provider_manager = self.core_lifecycle.provider_manager

            if provider_id in provider_manager.inst_map:
                await provider_manager.delete_provider(provider_id)

            # Update workflow's deployed status in database
            workflow = await self.db_helper.get_workflow(workflow_id)
            if workflow:
                workflow["deployed"] = False
                await self.db_helper.save_workflow(workflow)

            return Response().ok({"message": "工作流 Provider 已移除"}).__dict__
        except Exception as e:
            logger.error(f"移除工作流 Provider 失败: {e!s}\n{traceback.format_exc()}")
            return Response().error(f"移除工作流 Provider 失败: {e!s}").__dict__
