"""Skill 执行器：inline / fork 分支（T17）。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from Alincode.skills.render import render_body

if TYPE_CHECKING:
    from Alincode.skills.catalog import Catalog
    from Alincode.conversation import ConversationManager
    from Alincode.client import BaseProvider
    from Alincode.tools import Registry
    from Alincode.runtime import SessionRuntime
    from Alincode.permission.engine import PermissionEngine


class Executor:
    """Skill 执行器：inline（注入主对话）/ fork（子 Agent 隔离执行）。"""

    def __init__(
        self,
        catalog: "Catalog",
        provider: "BaseProvider",
        registry: "Registry",
        runtime: "SessionRuntime",
        engine: "PermissionEngine",
        model: str = "",
        version: str = "0.3.0",
    ) -> None:
        self._catalog = catalog
        self._provider = provider
        self._registry = registry
        self._runtime = runtime
        self._engine = engine
        self._model = model
        self._version = version

    async def execute(
        self,
        name: str,
        args: str = "",
        conv: "ConversationManager | None" = None,
    ) -> str | None:
        """执行 Skill，返回 assistant 文本（fork 模式）或 None（inline 模式）。

        inline：注入主对话 → 返回 None（由对话循环处理）
        fork：子 Agent 跑完 → 返回 final_text
        """
        skill = self._catalog.get(name)
        if skill is None:
            return f"[skill {name} failed: unknown skill]"

        # 重读最新 SKILL.md
        try:
            skill_md = skill.source_dir / "SKILL.md"
            if skill_md.is_file():
                from Alincode.skills.parser import _parse_frontmatter_and_body
                _, body = _parse_frontmatter_and_body(skill_md.read_text(encoding="utf-8"))
                skill.prompt_body = body
        except Exception:
            pass

        rendered = render_body(skill, args)

        if skill.meta.is_fork():
            return await self._execute_fork(skill, rendered, conv)
        else:
            return await self._execute_inline(skill, rendered, conv)

    async def _execute_inline(
        self, skill, rendered: str, conv: "ConversationManager | None",
    ) -> str | None:
        """inline：把渲染文本作为 user 消息注入主对话。"""
        if conv is None:
            return f"[skill {skill.meta.name}: no conversation to inject]"
        conv.add_user(rendered)
        return None  # 对话循环会继续处理

    async def _execute_fork(
        self, skill, rendered: str, conv: "ConversationManager | None",
    ) -> str:
        """fork：起子 Agent 独立跑完，返回 final_text。"""
        try:
            from Alincode.agent import Agent
            from Alincode.conversation import ConversationManager, Message
            from Alincode.runtime import SessionRuntime
            from Alincode.permission import Mode

            # 构造子对话
            sub_msgs = []
            fork_ctx = skill.meta.fork_context

            if fork_ctx == "full" and conv is not None:
                # 摘要主对话
                main_msgs = conv.messages
                req = await _summarize(main_msgs, self._provider, self._model)
                if req:
                    sub_msgs.append(req)
                sub_msgs.append(Message(role="user", content=rendered))
            elif fork_ctx == "recent" and conv is not None:
                main_msgs = conv.messages
                sub_msgs = list(main_msgs[-5:]) if len(main_msgs) > 5 else list(main_msgs)
                sub_msgs.append(Message(role="user", content=rendered))
            else:
                sub_msgs = [Message(role="user", content=rendered)]

            sub_conv = ConversationManager.from_messages(sub_msgs)
            sub_runtime = SessionRuntime(context_window=self._runtime.context_window)

            # 过滤工具集
            from Alincode.tools import Registry as ToolRegistry
            sub_reg = ToolRegistry()
            if skill.meta.allowed_tools:
                for t_name in skill.meta.allowed_tools:
                    tool = self._registry.get(t_name)
                    if tool:
                        sub_reg.register(tool)
            else:
                sub_reg = self._registry

            # 确保 LoadSkill 可用
            sub_agent = Agent(
                provider=self._provider,
                registry=sub_reg,
                model=skill.meta.model or self._model,
                version=self._version,
                engine=self._engine,
                runtime=sub_runtime,
            )

            final_text = ""
            fork_usage = 0
            async for ev in sub_agent.run(sub_conv, mode=Mode.DEFAULT):
                if ev.text:
                    final_text += ev.text
                if ev.usage:
                    fork_usage += ev.usage.input_tokens + ev.usage.output_tokens
                if ev.err:
                    return f"[skill {skill.meta.name} failed: {ev.err}]"

            # 回写 token 用量到主 runtime
            if fork_usage:
                async with self._runtime._lock:
                    self._runtime.usage_anchor += fork_usage

            return final_text.strip() or f"[skill {skill.meta.name}: no output]"

        except asyncio.CancelledError:
            return f"[skill {skill.meta.name} failed: cancelled]"
        except Exception as e:
            return f"[skill {skill.meta.name} failed: {e}]"


async def _summarize(msgs, provider, model):
    """生成主对话摘要。"""
    from Alincode.compact.summary_prompt import build_summary_prompt, extract_summary
    from Alincode.client import Request, System
    from Alincode.conversation import Message

    try:
        prompt_msgs = build_summary_prompt(msgs)
        req = Request(
            system=System(stable="", environment=""),
            messages=prompt_msgs,
            model=model,
            tools=[],
        )
        text = ""
        async for ev in provider.stream(req):
            if ev.err:
                break
            if ev.text:
                text += ev.text
        summary = extract_summary(text)
        if summary:
            return Message(role="user", content=f"## 对话摘要\n\n{summary}")
    except Exception:
        pass
    return None
