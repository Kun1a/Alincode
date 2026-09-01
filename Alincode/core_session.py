# Alincode/core_session.py
"""会话级组件构造（TUI/Web 共享）：Agent + Conversation + Runtime + Writer。

注意：不注入 system prompt——TUI 在 on_mount 注入（app.py），
WebSession 在 open() 时注入，避免双份。
"""

from __future__ import annotations

from dataclasses import dataclass

from Alincode.agent import Agent
from Alincode.bootstrap import AppContext
from Alincode.compact.state import (
    AutoCompactTrackingState,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
    open_session_context,
)
from Alincode.config import effective_context_window
from Alincode.conversation import ConversationManager
from Alincode.runtime import SessionRuntime
from Alincode.session import Writer as SessionWriter
from Alincode.session.load import load_session


@dataclass
class SessionBundle:
    agent: Agent
    conv: ConversationManager
    runtime: SessionRuntime
    writer: SessionWriter

    @property
    def session_id(self) -> str:
        return self.runtime.session.session_id


def make_replace_handler(writer: SessionWriter):
    """Conversation 替换回调：compact 标记 + 全量重写（搬自 app.py 的 _on_conv_replace）。"""

    def _on_conv_replace(msgs: list) -> None:
        writer.write_compact_marker()
        writer.append_all(msgs)

    return _on_conv_replace


def create_session(
    ctx: AppContext,
    resume_id: str | None = None,
    session_root: str | None = None,
) -> SessionBundle:
    """构造一个会话的全部组件。resume_id 非空时从 JSONL 恢复消息。"""
    if resume_id:
        session_ctx = open_session_context(ctx.workspace, resume_id, session_root)
    else:
        session_ctx = new_session_context(ctx.workspace, session_root)

    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=session_ctx,
        context_window=effective_context_window(ctx.provider_cfg),
    )
    if ctx.hook_engine:
        runtime.hook_engine = ctx.hook_engine

    writer = SessionWriter(session_ctx.session_dir)

    msgs = load_session(session_ctx.session_dir) if resume_id else []
    if msgs:
        conv = ConversationManager.from_messages(
            msgs,
            on_append=writer.append,
            on_replace=make_replace_handler(writer),
        )
    else:
        conv = ConversationManager(
            on_append=writer.append,
            on_replace=make_replace_handler(writer),
        )

    agent = Agent(
        provider=ctx.provider, registry=ctx.registry, model=ctx.provider_cfg.model,
        version="0.3.0", engine=ctx.engine,
        runtime=runtime,
        memory_manager=ctx.memory_manager,
        instruction_text=ctx.instruction_text,
        memory_text=ctx.memory_text,
        skills_catalog=ctx.catalog,
        hook_engine=ctx.hook_engine,
        workspace=ctx.workspace,
    )

    # 子 Agent 工具回填（对应 driver 原来的 per-agent wire）
    if ctx.agent_tool is not None:
        ctx.agent_tool.set_parent(agent)
        ctx.agent_tool.set_conv_getter(lambda: conv.messages)

    # LoadSkill 重绑：把共享 registry 中 load_skill 的 active_skills
    # 指向当前会话 runtime（MVP 单活跃会话语义；多会话并发为已知限制）
    ls_tool = ctx.registry.get("load_skill")
    if ls_tool is not None:
        ls_tool._active = runtime.active_skills

    return SessionBundle(agent=agent, conv=conv, runtime=runtime, writer=writer)
