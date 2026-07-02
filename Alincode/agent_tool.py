"""Agent 工具实现：主 Agent 通过此工具委派子 Agent（T17/F1-F3）。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from Alincode.tools import Result
from Alincode.tool.filter import apply_agent_tool_filter, FilterParams
from Alincode.fork import build_forked_messages, FORK_BOILERPLATE_TAG
from Alincode.agent import AUTO_BACKGROUND_SECONDS


def is_fork_context_str(s: str) -> bool:
    """检查字符串中是否含 fork boilerplate 标记。"""
    return FORK_BOILERPLATE_TAG in s

if TYPE_CHECKING:
    from Alincode.agent import Agent
    from Alincode.subagent.catalog import Catalog as SubagentCatalog
    from Alincode.task.manager import Manager as TaskManager


class AgentTool:
    """统一 Agent 工具——subagent_type 分流定义式/Fork 式。

    subagent_type 非空 → 定义式（预定义角色）
    subagent_type 为空 → Fork 式（继承父对话）
    """

    def __init__(
        self,
        catalog: "SubagentCatalog",
        task_mgr: "TaskManager",
        parent: "Agent | None" = None,
        bg_enabled: bool = True,
        conv_getter: "object | None" = None,  # callable → list[Message]
    ) -> None:
        self._catalog = catalog
        self._task_mgr = task_mgr
        self._parent = parent
        self._bg_enabled = bg_enabled
        self._conv_getter = conv_getter

    def set_parent(self, ag: "Agent") -> None:
        self._parent = ag

    def set_conv_getter(self, getter: object) -> None:
        """设置父对话消息获取回调（Fork 路径需要）。"""
        self._conv_getter = getter

    def name(self) -> str:
        return "Agent"

    @property
    def read_only(self) -> bool:
        return False

    @property
    def timeout(self) -> float:
        """Agent 工具需要更长超时：120s（与自动切后台阈值一致）。"""
        return AUTO_BACKGROUND_SECONDS

    def description(self) -> str:
        names = [d.name for d in self._catalog.list()]
        base = (
            "启动一个子 Agent 独立完成任务。"
            "subagent_type 可选值: " + ", ".join(names) + "。"
            + "留空走 Fork 路径（继承父对话历史）。"
        )
        return base

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "交给子 Agent 的任务指令",
                },
                "description": {
                    "type": "string",
                    "description": "一句话描述任务（UI 展示用）",
                },
                "subagent_type": {
                    "type": "string",
                    "description": "预定义角色名，留空走 Fork 路径",
                },
                "model": {
                    "type": "string",
                    "description": "模型覆盖：haiku/sonnet/opus/inherit",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "true 时后台启动",
                },
                "name": {
                    "type": "string",
                    "description": "给子 Agent 命名（供 SendMessage 查找）",
                },
            },
            "required": ["prompt", "description"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            return Result(content="invalid JSON args", is_error=True)

        prompt = data.get("prompt", "")
        description = data.get("description", "")
        subagent_type = data.get("subagent_type", "")
        run_in_background = bool(data.get("run_in_background", False))
        agent_name = data.get("name", "")

        if not prompt:
            return Result(content="prompt is required", is_error=True)
        if not description:
            return Result(content="description is required", is_error=True)

        if self._parent is None:
            return Result(content="Agent tool not wired to parent", is_error=True)

        parent = self._parent

        # ── 防嵌套：提示词中检测 fork boilerplate ────
        if prompt and is_fork_context_str(prompt):
            return Result(content="Fork subagent cannot spawn Agent (boilerplate detected)", is_error=True)

        # ── Resolve 定义 ─────────────────────────────
        if subagent_type:
            defi = self._catalog.resolve(subagent_type)
            if defi is None:
                return Result(content=f"unknown subagent_type: {subagent_type}", is_error=True)
        else:
            defi = self._catalog.fork_definition()

        is_fork = defi.is_fork()
        background = defi.background or run_in_background or is_fork

        if background and not self._bg_enabled:
            return Result(content="background mode is disabled by config", is_error=True)

        # ── 工具过滤 ─────────────────────────────────
        all_names = [d.name for d in parent._registry.definitions()]
        allowed = apply_agent_tool_filter(FilterParams(
            all_tools=all_names,
            source=int(defi.source),
            background=background,
            allowed=defi.tools,
            disallowed=defi.disallowed_tools,
        ))

        # ── 构造子 Agent ─────────────────────────────
        from Alincode.runtime import SessionRuntime as SR
        from Alincode.agent import Agent
        from Alincode.conversation import ConversationManager

        sub_runtime = SR(context_window=200000)
        sub_agent = Agent(
            provider=parent._provider,
            registry=parent._registry,
            model=parent._model,
            version=parent._version,
            engine=parent._engine,
            runtime=sub_runtime,
            system_prompt=defi.system_prompt if defi.system_prompt else None,
            max_turns=defi.max_turns,
            permission_mode=defi.permission_mode,
            dont_ask=defi.dont_ask,
            hook_engine=parent._hook_engine,
            allowed_tools=allowed,
        )

        # ── 子对话 ───────────────────────────────────
        if is_fork:
            if self._conv_getter is not None:
                parent_msgs = self._conv_getter()  # type: ignore[misc]
            else:
                parent_msgs = []
            forked = build_forked_messages(parent_msgs, prompt)
            sub_conv = ConversationManager.from_messages(forked)
        else:
            sub_conv = ConversationManager()

        # ── 后台路径 ─────────────────────────────────
        if background:
            task_id = await self._task_mgr.launch(
                sub_agent, sub_conv, agent_name,
                "" if is_fork else prompt  # Fork conv 已含 prompt，不重复追加
            )
            return Result(content=json.dumps({"task_id": task_id, "status": "async_launched"}))

        # ── 前台路径 ─────────────────────────────────
        events: asyncio.Queue = asyncio.Queue(maxsize=32)
        try:
            final_text = await asyncio.wait_for(
                sub_agent.run_to_completion(sub_conv, prompt, events),
                timeout=AUTO_BACKGROUND_SECONDS,
            )
            return Result(content=final_text)
        except asyncio.TimeoutError:
            running = asyncio.create_task(sub_agent.run_to_completion(sub_conv, "", events))
            from Alincode.task.manager import PartialState
            task_id = await self._task_mgr.adopt_running(
                sub_agent, sub_conv, agent_name, events, running, PartialState(),
            )
            return Result(content=json.dumps({"task_id": task_id, "status": "timed_out_to_background"}))
        except Exception as e:
            return Result(content=f"subagent error: {e}", is_error=True)
