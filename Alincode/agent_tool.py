"""Agent 工具实现：主 Agent 通过此工具委派子 Agent（T17/F1-F3）。"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import TYPE_CHECKING

from Alincode.tools import Result
from Alincode.tool.filter import apply_agent_tool_filter, FilterParams
from Alincode.fork import build_forked_messages, FORK_BOILERPLATE_TAG
from Alincode.agent import AUTO_BACKGROUND_SECONDS


def is_fork_context_str(s: str) -> bool:
    """检查字符串中是否含 fork boilerplate 标记。"""
    return FORK_BOILERPLATE_TAG in s


def _build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    """构建 Worktree 上下文通知（F22）。"""
    return f"""<worktree-context>
你当前在一个独立的 Git Worktree 副本中工作，与父 Agent 隔离。
- 父目录: {parent_cwd}
- 你的工作目录: {wt_path}
- 父 Agent 提到的绝对路径基于父目录，你需要翻译成本地路径（替换前缀）再读写
- 编辑文件前，必须先在本地 Worktree 重新 read_file 一次，避免使用过时内容
</worktree-context>"""

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
        worktree_mgr: "object | None" = None,  # Worktree Manager
    ) -> None:
        self._catalog = catalog
        self._task_mgr = task_mgr
        self._parent = parent
        self._bg_enabled = bg_enabled
        self._conv_getter = conv_getter
        self._worktree_mgr = worktree_mgr

    def set_parent(self, ag: "Agent") -> None:
        self._parent = ag

    def set_conv_getter(self, getter: object) -> None:
        """设置父对话消息获取回调（Fork 路径需要）。"""
        self._conv_getter = getter

    def set_worktree_mgr(self, mgr: object) -> None:
        """设置 Worktree Manager（isolation 需要）。"""
        self._worktree_mgr = mgr

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
                "isolation": {
                    "type": "string",
                    "description": "文件系统隔离模式：留空 / worktree",
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
        isolation_override = data.get("isolation", "") or ""  # 空 → 用 definition 的 isolation

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

        # isolation 参数覆盖 definition 的值（copy 避免污染 catalog 缓存）
        if isolation_override:
            import copy
            defi = copy.copy(defi)
            defi.isolation = isolation_override

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

        # ── Worktree isolation ───────────────────────
        wt_path = ""
        worktree_name = ""
        if defi.isolation == "worktree" and self._worktree_mgr is not None:
            wt_mgr = self._worktree_mgr
            worktree_name = f"agent-a{secrets.token_hex(4)}"  # 8 hex chars
            try:
                wt = await wt_mgr.create(worktree_name, "HEAD", manual=False)  # type: ignore[union-attr]
                wt_path = wt.path  # type: ignore[union-attr]
            except Exception as e:
                return Result(content=f"worktree create failed: {e}", is_error=True)

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

        # ── Worktree notice 注入 ──────────────────────
        task_text = "" if is_fork else prompt
        if wt_path:
            import os as _os
            parent_cwd = _os.getcwd()
            notice = _build_worktree_notice(parent_cwd, wt_path)
            task_text = notice + "\n\n" + task_text if task_text else notice

        # ── 后台路径 ─────────────────────────────────
        if background:
            task_id = await self._task_mgr.launch(
                sub_agent, sub_conv, agent_name, task_text,
            )
            return Result(content=json.dumps({"task_id": task_id, "status": "async_launched"}))

        # ── 前台路径（含 worktree cwd 注入）──────────
        events: asyncio.Queue = asyncio.Queue(maxsize=32)
        final_text = ""

        async def _run_in_ctx():
            from Alincode.tool.ctx import with_cwd
            if wt_path:
                with with_cwd(wt_path):
                    return await asyncio.wait_for(
                        sub_agent.run_to_completion(sub_conv, task_text, events),
                        timeout=AUTO_BACKGROUND_SECONDS,
                    )
            else:
                return await asyncio.wait_for(
                    sub_agent.run_to_completion(sub_conv, task_text, events),
                    timeout=AUTO_BACKGROUND_SECONDS,
                )

        try:
            final_text = await _run_in_ctx()
        except asyncio.TimeoutError:
            # ── Worktree auto cleanup (timeout) ───
            if wt_path and self._worktree_mgr is not None:
                try:
                    await self._worktree_mgr.auto_cleanup(worktree_name)  # type: ignore[union-attr]
                except Exception:
                    pass
            running = asyncio.create_task(sub_agent.run_to_completion(sub_conv, "", events))
            from Alincode.task.manager import PartialState
            task_id = await self._task_mgr.adopt_running(
                sub_agent, sub_conv, agent_name, events, running, PartialState(),
            )
            return Result(content=json.dumps({"task_id": task_id, "status": "timed_out_to_background"}))
        except Exception as e:
            # ── Worktree auto cleanup (error) ─────
            if wt_path and self._worktree_mgr is not None:
                try:
                    await self._worktree_mgr.auto_cleanup(worktree_name)  # type: ignore[union-attr]
                except Exception:
                    pass
            return Result(content=f"subagent error: {e}", is_error=True)

        # ── Worktree auto cleanup (success) ──────
        if wt_path and self._worktree_mgr is not None:
            try:
                report = await self._worktree_mgr.auto_cleanup(worktree_name)  # type: ignore[union-attr]
                if report.kept:
                    final_text = final_text + f"\n[Worktree 保留在 {report.path}, 分支 {report.branch}]"
            except Exception:
                pass

        return Result(content=final_text)
