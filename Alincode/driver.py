"""主驱动模块：编排配置加载、共享装配（bootstrap）、TUI 会话启动。"""

from __future__ import annotations

import asyncio
import logging
import sys

from Alincode.bootstrap import build_context, shutdown_context
from Alincode.compact.state import (
    ContentReplacementState,
    RecoveryState,
    AutoCompactTrackingState,
    new_session_context,
)
from Alincode.config import effective_context_window
from Alincode.hook.event import Event as HookEvent
from Alincode.runtime import SessionRuntime
from Alincode.session import Writer as SessionWriter
from Alincode.app import AlinCodeApp


async def _amain(config_path: str | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(message)s",
        stream=sys.stderr,
    )

    ctx = await build_context(config_path)

    # ── 会话运行时（TUI 单会话）─────────────────────
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=new_session_context(ctx.workspace),
        context_window=effective_context_window(ctx.provider_cfg),
    )

    # ── 会话写入器 ─────────────────────────────────
    writer = SessionWriter(runtime.session.session_dir)

    app = AlinCodeApp(
        provider=ctx.provider,
        model=ctx.provider_cfg.model,
        registry=ctx.registry,
        engine=ctx.engine,
        runtime=runtime,
        instruction_text=ctx.instruction_text,
        memory_text=ctx.memory_text,
        writer=writer,
        memory_manager=ctx.memory_manager,
        workspace=ctx.workspace,
        catalog=ctx.catalog,
        hook_engine=ctx.hook_engine,
        task_mgr=ctx.task_mgr,
    )
    # 回填 parent 引用
    ctx.agent_tool.set_parent(app.agent)
    ctx.agent_tool.set_conv_getter(lambda: app._conv.messages)

    # ── T28: 注入 team_mgr + 命令到 App ──
    app.team_mgr = ctx.team_mgr
    app._team_commands = ctx.team_commands

    # ── T24: Coordinator Mode 应用 ──
    if ctx.coordinator_enabled:
        from Alincode import coordinator

        app.agent._allowed_tools = coordinator.allowed_tools()
        if app.agent.system_prompt:
            app.agent.system_prompt += coordinator.system_prompt_suffix()
        else:
            app.agent.system_prompt = coordinator.system_prompt_suffix()
        app.coordinator_mode = True

    try:
        await app.run_async()
    finally:
        # ── Hook: SessionEnd 兜底 ──
        if ctx.hook_engine is not None:
            await ctx.hook_engine.dispatch(
                HookEvent.SESSION_END,
                {
                    "event": "session_end",
                    "session_id": runtime.session.session_id,
                    "cwd": ctx.workspace,
                    "mode": "default",
                },
            )
        writer.close()
        await shutdown_context(ctx)


def run(config_path: str | None = None) -> None:
    """同步入口。"""
    # ── T29: --team-member 自治循环 ──
    from Alincode.team_member import (
        is_team_member_mode,
        parse_team_member_args,
        run_team_member,
    )

    if is_team_member_mode(sys.argv):
        args = parse_team_member_args(
            [a for a in sys.argv[1:] if a != config_path]
            if config_path
            else sys.argv[1:]
        )
        asyncio.run(run_team_member(args))
        return

    asyncio.run(_amain(config_path))
