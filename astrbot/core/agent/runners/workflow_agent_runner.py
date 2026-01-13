"""
Workflow Agent Runner
Executes visual workflow graphs with nodes like LLM, Tool, Knowledge Base, etc.
"""

import json
import re
import traceback
from dataclasses import dataclass, field
from typing import Any

from astrbot import logger
from astrbot.core.agent.message import (
    AssistantMessageSegment,
    ToolCall,
    ToolCallMessageSegment,
)
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.knowledge_base.kb_mgr import KnowledgeBaseManager
from astrbot.core.provider.entities import ProviderRequest, ToolCallsResult
from astrbot.core.provider.manager import ProviderManager


@dataclass
class WorkflowResult:
    """Result of workflow execution."""

    result_text: str
    execution_logs: list[str] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str | None = None


class WorkflowAgentRunner:
    """
    Executes workflow graphs defined in the visual workflow editor.
    Supports node types: start, end, llm, tool, knowledgeBase, condition
    """

    def __init__(
        self,
        workflow_data: dict[str, Any],
        provider_manager: ProviderManager,
        kb_manager: KnowledgeBaseManager | None = None,
    ):
        self.workflow_data = workflow_data
        self.provider_manager = provider_manager
        self.kb_manager = kb_manager

        self.nodes: list[dict] = workflow_data.get("nodes", [])
        self.edges: list[dict] = workflow_data.get("edges", [])

        # Build adjacency map for traversal
        self.adjacency: dict[str, list[str]] = {}
        for edge in self.edges:
            source = edge.get("source", "")
            target = edge.get("target", "")
            if source:
                if source not in self.adjacency:
                    self.adjacency[source] = []
                self.adjacency[source].append(target)

        # Node lookup by ID
        self.node_map: dict[str, dict] = {n["id"]: n for n in self.nodes}

        # Execution context
        self.variables: dict[str, Any] = {}
        self.logs: list[str] = []

    def _log(self, message: str) -> None:
        """Add execution log."""
        self.logs.append(message)
        logger.debug(f"[Workflow] {message}")

    def _substitute_variables(self, text: str) -> str:
        """
        Replace {{variable}} placeholders with actual values.
        Supports: {{input}}, {{output}}, {{_kb_result}}, {{custom_var}}
        """
        if not text:
            return text

        def replacer(match: re.Match) -> str:
            var_name = match.group(1).strip()
            if var_name in self.variables:
                val = self.variables[var_name]
                return str(val) if val is not None else ""
            # Return empty string if variable not found (instead of keeping placeholder)
            self._log(f"Warning: Variable '{var_name}' not found, replacing with empty string")
            return ""

        # Pattern supports variables like {{input}}, {{_kb_result}}, {{var_name}}
        # \w+ matches word characters including underscore
        return re.sub(r"\{\{([_a-zA-Z][_a-zA-Z0-9]*)\}\}", replacer, text)

    def _find_start_node(self) -> dict | None:
        """Find the start node in the workflow."""
        for node in self.nodes:
            if node.get("type") == "start":
                return node
        return None

    def _get_next_nodes(self, node_id: str) -> list[dict]:
        """Get all nodes connected from the given node."""
        next_ids = self.adjacency.get(node_id, [])
        return [self.node_map[nid] for nid in next_ids if nid in self.node_map]

    async def _execute_llm_node(self, node: dict) -> str:
        """Execute an LLM node with optional tool calling support."""
        data = node.get("data", {})
        provider_id = data.get("provider_id", "")
        raw_prompt = data.get("prompt", "{{input}}")
        raw_system_prompt = data.get("system_prompt", "")
        output_var = data.get("output_variable", "output")
        enable_tools = data.get("enable_tools", False)
        allowed_tools = data.get("allowed_tools", [])

        self._log(f"LLM node raw prompt: {raw_prompt[:200]}...")
        self._log(f"Current variables: {list(self.variables.keys())}")

        prompt = self._substitute_variables(raw_prompt)
        system_prompt = self._substitute_variables(raw_system_prompt)

        self._log(f"LLM node substituted prompt: {prompt[:200]}...")
        self._log(f"Executing LLM node with provider: {provider_id or 'default'}")

        # Find provider
        provider = None
        if provider_id:
            for p in self.provider_manager.provider_insts:
                if p.meta().id == provider_id:
                    provider = p
                    break

        if not provider:
            # Use first available provider
            if self.provider_manager.provider_insts:
                provider = self.provider_manager.provider_insts[0]
            else:
                raise ValueError("No LLM provider available")

        # Build tool set if tools are enabled
        func_tool = None
        tool_map: dict[str, FunctionTool] = {}
        if enable_tools and allowed_tools:
            llm_tools = self.provider_manager.llm_tools
            func_tool = ToolSet(tools=[])
            for tool in llm_tools.func_list:
                if tool.name in allowed_tools and tool.active:
                    func_tool.add_tool(tool)
                    tool_map[tool.name] = tool
            self._log(f"LLM node enabled tools: {[t.name for t in func_tool.tools]}")

        # Build initial request
        request = ProviderRequest(prompt=prompt, system_prompt=system_prompt)
        contexts = await request.assemble_context()

        # Tool calling loop
        max_iterations = 10  # Prevent infinite loops
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            self._log(f"LLM call iteration {iteration}")

            # Call LLM with or without tools
            if func_tool and not func_tool.empty():
                response = await provider.text_chat(
                    contexts=[contexts],
                    func_tool=func_tool,
                    system_prompt=system_prompt,
                )
            else:
                response = await provider.text_chat(
                    contexts=[contexts],
                    system_prompt=system_prompt,
                )

            # Check if LLM wants to call tools
            if response.tools_call_name and response.tools_call_args:
                self._log(f"LLM requested tool calls: {response.tools_call_name}")

                # Execute each tool call
                tool_results: list[ToolCallMessageSegment] = []
                for i, tool_name in enumerate(response.tools_call_name):
                    tool_args = response.tools_call_args[i] if i < len(response.tools_call_args) else {}
                    tool_id = response.tools_call_ids[i] if i < len(response.tools_call_ids) else f"call_{i}"

                    self._log(f"Executing tool: {tool_name} with args: {tool_args}")

                    if tool_name in tool_map:
                        try:
                            tool_func = tool_map[tool_name]
                            result = await tool_func.handler(**tool_args)
                            result_str = str(result) if result is not None else ""
                            self._log(f"Tool {tool_name} result: {result_str[:100]}...")
                        except Exception as e:
                            result_str = f"Error executing tool: {e}"
                            self._log(f"Tool {tool_name} error: {e}")
                    else:
                        result_str = f"Tool '{tool_name}' not found in allowed tools"
                        self._log(result_str)

                    tool_results.append(ToolCallMessageSegment(
                        role="tool",
                        tool_call_id=tool_id,
                        content=result_str,
                    ))

                # Build tool calls result for next iteration
                assistant_msg = AssistantMessageSegment(
                    role="assistant",
                    content=response.completion_text or "",
                    tool_calls=[
                        ToolCall(
                            id=response.tools_call_ids[i] if i < len(response.tools_call_ids) else f"call_{i}",
                            function=ToolCall.FunctionBody(
                                name=response.tools_call_name[i],
                                arguments=json.dumps(response.tools_call_args[i]) if i < len(response.tools_call_args) else "{}",
                            ),
                        )
                        for i in range(len(response.tools_call_name))
                    ],
                )

                tool_calls_result = ToolCallsResult(
                    tool_calls_info=assistant_msg,
                    tool_calls_result=tool_results,
                )

                # Update request with tool results for next iteration
                request = ProviderRequest(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    tool_calls_result=tool_calls_result,
                )
                contexts = await request.assemble_context()
            else:
                # No more tool calls, we have the final response
                break

        result = response.completion_text or ""
        self.variables[output_var] = result
        self._log(f"LLM output stored in '{output_var}': {result[:100]}...")

        return result

    async def _execute_tool_node(self, node: dict) -> str:
        """Execute a tool node."""
        data = node.get("data", {})
        tool_name = data.get("tool_name", "")
        arguments = data.get("arguments", {})
        output_var = data.get("output_variable", "_tool_result")

        if not tool_name:
            raise ValueError("Tool name not specified")

        self._log(f"Executing tool: {tool_name}")

        # Substitute variables in arguments
        resolved_args = {}
        for key, value in arguments.items():
            if isinstance(value, str):
                resolved_args[key] = self._substitute_variables(value)
            else:
                resolved_args[key] = value

        # Find and execute tool
        llm_tools = self.provider_manager.llm_tools
        tool_func = None

        for tool in llm_tools.func_list:
            if tool.name == tool_name and tool.active:
                tool_func = tool
                break

        if not tool_func:
            raise ValueError(f"Tool '{tool_name}' not found or not active")

        # Execute the tool
        try:
            result = await tool_func.handler(**resolved_args)
            result_str = str(result) if result is not None else ""
            self.variables[output_var] = result_str
            self._log(f"Tool result stored in '{output_var}': {result_str[:100]}...")
            return result_str
        except Exception as e:
            error_msg = f"Tool execution failed: {e}"
            self._log(error_msg)
            self.variables[output_var] = error_msg
            return error_msg

    async def _execute_kb_node(self, node: dict) -> str:
        """Execute a knowledge base retrieval node."""
        data = node.get("data", {})
        kb_id = data.get("kb_id", "")
        query = self._substitute_variables(data.get("query", "{{input}}"))
        top_k = data.get("top_k", 5)
        output_var = data.get("output_variable", "_kb_result")

        self._log(f"KB node output_var: {output_var}")

        if not kb_id:
            raise ValueError("Knowledge base not specified")

        if not self.kb_manager:
            raise ValueError("Knowledge base manager not available")

        self._log(f"Querying knowledge base: {kb_id} with query: {query[:100]}...")

        # Retrieve from knowledge base
        try:
            # Get kb_name from kb_id
            kb_helper = await self.kb_manager.get_kb(kb_id)
            if not kb_helper:
                raise ValueError(f"Knowledge base '{kb_id}' not found")

            kb_name = kb_helper.kb.kb_name
            self._log(f"Found KB name: {kb_name}")

            # Call retrieve with kb_names list
            results = await self.kb_manager.retrieve(
                query=query,
                kb_names=[kb_name],
                top_m_final=top_k,
            )

            if not results:
                self.variables[output_var] = ""
                self._log(f"KB retrieval found no results, stored empty string in '{output_var}'")
                return ""

            # Extract context_text from results
            result_str = results.get("context_text", "")
            self.variables[output_var] = result_str
            result_count = len(results.get("results", []))
            self._log(
                f"KB retrieval found {result_count} results, stored in '{output_var}'"
            )
            self._log(f"KB result preview: {result_str[:200]}...")
            self._log(f"Variables after KB: {list(self.variables.keys())}")
            return result_str
        except Exception as e:
            error_msg = f"Knowledge base retrieval failed: {e}"
            self._log(error_msg)
            self.variables[output_var] = error_msg
            return error_msg

    async def _execute_condition_node(self, node: dict) -> bool:
        """
        Execute a condition node.
        Returns True if condition passes, False otherwise.
        """
        data = node.get("data", {})
        condition = data.get("condition", "True")

        self._log(f"Evaluating condition: {condition}")

        # Create safe evaluation context with variables
        eval_context = {"len": len, "str": str, "int": int, "float": float, "bool": bool}
        eval_context.update(self.variables)

        try:
            result = eval(condition, {"__builtins__": {}}, eval_context)
            self._log(f"Condition result: {result}")
            return bool(result)
        except Exception as e:
            self._log(f"Condition evaluation failed: {e}")
            return False

    async def _execute_llm_judge_node(self, node: dict) -> bool:
        """
        Execute an LLM judge node.
        Uses LLM to evaluate a question and returns True/False based on response.
        """
        data = node.get("data", {})
        provider_id = data.get("provider_id", "")
        raw_judge_prompt = data.get("judge_prompt", "")
        true_keywords = data.get("true_keywords", "是,yes,true,正确")

        if not raw_judge_prompt:
            self._log("LLM Judge node: No judge prompt specified")
            return False

        judge_prompt = self._substitute_variables(raw_judge_prompt)
        self._log(f"LLM Judge node prompt: {judge_prompt[:200]}...")

        # Parse true keywords
        keywords = [k.strip().lower() for k in true_keywords.split(",") if k.strip()]
        self._log(f"LLM Judge true keywords: {keywords}")

        # Find provider
        provider = None
        if provider_id:
            for p in self.provider_manager.provider_insts:
                if p.meta().id == provider_id:
                    provider = p
                    break

        if not provider:
            if self.provider_manager.provider_insts:
                provider = self.provider_manager.provider_insts[0]
            else:
                raise ValueError("No LLM provider available for judge node")

        # Build request with clear instruction
        system_prompt = "你是一个判断助手。请根据问题内容，用简短的词语回答'是'或'否'。只需回答一个词。"
        request = ProviderRequest(prompt=judge_prompt, system_prompt=system_prompt)
        contexts = await request.assemble_context()

        # Call LLM
        response = await provider.text_chat(contexts=[contexts], system_prompt=system_prompt)
        result_text = (response.completion_text or "").strip().lower()

        self._log(f"LLM Judge response: {result_text}")

        # Check if response contains any true keyword
        is_true = any(keyword in result_text for keyword in keywords)
        self._log(f"LLM Judge result: {is_true}")

        return is_true

    async def _execute_node(self, node: dict) -> Any:
        """Execute a single node based on its type."""
        node_type = node.get("type", "")
        node_id = node.get("id", "")

        self._log(f"Executing node: {node_id} (type: {node_type})")

        if node_type == "start":
            # Start node just passes through
            return self.variables.get("input", "")

        elif node_type == "end":
            # End node returns the current output
            return self.variables.get("output", self.variables.get("input", ""))

        elif node_type == "llm":
            return await self._execute_llm_node(node)

        elif node_type == "tool":
            return await self._execute_tool_node(node)

        elif node_type == "knowledgeBase":
            return await self._execute_kb_node(node)

        elif node_type == "condition":
            return await self._execute_condition_node(node)

        elif node_type == "llmJudge":
            return await self._execute_llm_judge_node(node)

        else:
            self._log(f"Unknown node type: {node_type}")
            return None

    async def run(self, user_input: str) -> WorkflowResult:
        """
        Execute the workflow with the given user input.
        Uses topological sort to ensure proper execution order.
        Returns the final result.
        """
        self.variables = {"input": user_input}
        self.logs = []

        try:
            # Find start node
            start_node = self._find_start_node()
            if not start_node:
                return WorkflowResult(
                    result_text="",
                    execution_logs=self.logs,
                    success=False,
                    error="No start node found in workflow",
                )

            self._log(f"Starting workflow execution with input: {user_input[:100]}...")

            # Build reverse adjacency (incoming edges) for topological sort
            in_degree: dict[str, int] = {n["id"]: 0 for n in self.nodes}
            for edge in self.edges:
                target = edge.get("target", "")
                if target in in_degree:
                    in_degree[target] += 1

            # Topological sort using Kahn's algorithm
            # Start with nodes that have no incoming edges
            queue: list[dict] = []
            for node in self.nodes:
                if in_degree[node["id"]] == 0:
                    queue.append(node)

            execution_order: list[dict] = []
            while queue:
                current_node = queue.pop(0)
                execution_order.append(current_node)

                # Reduce in-degree for all neighbors
                for next_node_id in self.adjacency.get(current_node["id"], []):
                    in_degree[next_node_id] -= 1
                    if in_degree[next_node_id] == 0:
                        if next_node_id in self.node_map:
                            queue.append(self.node_map[next_node_id])

            self._log(f"Execution order: {[n.get('type', 'unknown') for n in execution_order]}")

            # Execute nodes in topological order
            final_result = user_input
            for current_node in execution_order:
                node_type = current_node.get("type", "")

                # Execute the node
                result = await self._execute_node(current_node)

                # Handle condition nodes specially
                if node_type == "condition":
                    if not result:
                        # Skip downstream nodes if condition is False
                        # Mark all reachable nodes as "skipped" by removing them
                        self._log(f"Condition failed, skipping downstream nodes")
                        # For simplicity, we continue but don't update output
                        continue

                # Handle LLM judge nodes similarly to condition nodes
                if node_type == "llmJudge":
                    if not result:
                        self._log(f"LLM Judge returned False, skipping downstream nodes")
                        continue

                # Update output variable if we have a result
                if result is not None and node_type not in ["start", "condition", "llmJudge"]:
                    self.variables["output"] = result
                    final_result = result

            self._log("Workflow execution completed")

            return WorkflowResult(
                result_text=str(final_result),
                execution_logs=self.logs,
                variables=self.variables,
                success=True,
            )

        except Exception as e:
            error_msg = f"Workflow execution failed: {e}\n{traceback.format_exc()}"
            self._log(error_msg)
            logger.error(error_msg)

            return WorkflowResult(
                result_text="",
                execution_logs=self.logs,
                variables=self.variables,
                success=False,
                error=str(e),
            )
