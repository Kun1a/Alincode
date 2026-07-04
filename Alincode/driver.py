"""主驱动模块：编排配置加载、Provider 创建、工具注册、MCP 连接、权限引擎、应用启动。"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import datetime as _dt
import os

from Alincode.config import ConfigLoader, effective_context_window
from Alincode.client import create_provider
from Alincode.compact.state import (
    ContentReplacementState,
    RecoveryState,
    AutoCompactTrackingState,
    new_session_context,
)
from Alincode.instructions import Loader as InstructionsLoader
from Alincode.memory import Manager as MemoryManager
from Alincode.runtime import SessionRuntime
from Alincode.session import Writer as SessionWriter, clean_expired
from Alincode.skills.catalog import Catalog
from Alincode.tools import new_default_registry
from Alincode.permission.engine import new_engine
from Alincode.mcp import load_from_dict as mcp_from_dict, new_manager as mcp_new_manager
from Alincode.app import AlinCodeApp


DEFAULT_CONFIG_PATHS = [
    Path(".Alincode/config.yaml"),
    Path(".Alincode/skills/config.yaml"),
    Path("config.yaml"),
]


async def _amain(config_path: str | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(message)s",
        stream=sys.stderr,
    )
    if config_path is None:
        for p in DEFAULT_CONFIG_PATHS:
            if p.is_file():
                config_path = str(p)
                break
        if config_path is None:
            print("错误: 找不到 config.yaml 配置文件")
            print(
                "请复制 config.example.yaml 为 config.yaml 或 .Alincode/skills/config.yaml"
            )
            raise SystemExit(1)

    app_cfg = ConfigLoader.load(config_path)
    if not app_cfg.providers:
        print("错误: 配置文件中没有有效的 provider")
        raise SystemExit(1)

    # 取第一个 provider（未来可选）
    provider_cfg = app_cfg.providers[0]
    provider = create_provider(provider_cfg)
    registry = new_default_registry()

    # ── MCP 工具发现与注册 ────────────────────────
    root = str(Path.cwd().resolve())
    mcp_cfg = mcp_from_dict(app_cfg.mcp_servers)
    mcp_mgr = None
    try:
        mcp_mgr = await mcp_new_manager(mcp_cfg, version="0.3.0")
    except Exception as e:
        print(f"[mcp] manager init failed: {e}", file=sys.stderr)
    if mcp_mgr is not None:
        try:
            mcp_count = len(mcp_mgr.tools())
            for t in mcp_mgr.tools():
                registry.register(t)
            if mcp_count > 0:
                print(
                    f"[mcp] registered {mcp_count} MCP tools from {len(mcp_cfg.servers)} server(s)",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[mcp] register error: {e}", file=sys.stderr)

    # ── 权限引擎 ──────────────────────────────────
    engine, err = new_engine(root)
    if err:
        print(f"权限引擎降级: {err}", file=sys.stderr)

    # ── 项目指令加载 ──────────────────────────────
    workspace = str(Path.cwd().resolve())
    user_home = os.path.expanduser("~")
    loader = InstructionsLoader(project_root=workspace, user_home=user_home)
    instruction_text = loader.load()

    # ── 记忆初始化 ────────────────────────────────
    mem_mgr = MemoryManager(
        project_dir=os.path.join(workspace, ".Alincode", "memory"),
        user_dir=os.path.join(user_home, ".Alincode", "memory"),
        provider=provider,
        model=provider_cfg.model,
    )
    memory_text = mem_mgr.load_index()

    # ── 会话运行时 ─────────────────────────────────
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=new_session_context(workspace),
        context_window=effective_context_window(provider_cfg),
    )

    # ── 会话写入器 ─────────────────────────────────
    writer = SessionWriter(runtime.session.session_dir)

    # ── 后台清理过期会话 ────────────────────────────
    sessions_dir = os.path.join(workspace, ".Alincode", "sessions")
    asyncio.create_task(
        asyncio.to_thread(clean_expired, sessions_dir, _dt.timedelta(days=30))
    )

    # ── Skills 加载 ────────────────────────────────
    catalog = Catalog.load(workspace)
    # fail-fast 工具白名单检查
    issues = catalog.validate_tools(registry)
    for iss in issues:
        print(
            f"[skills] skill {iss.skill_name}: allowed_tool "
            f'"{iss.tool_name}" not registered, skipped',
            file=sys.stderr,
        )
    for iss in issues:
        # 从 catalog 中移除有问题的 skill
        catalog._by_name.pop(iss.skill_name, None)
        if iss.skill_name in catalog._order:
            catalog._order.remove(iss.skill_name)

    # 注册 LoadSkill 工具
    from Alincode.skills.load_skill import LoadSkillTool

    load_skill = LoadSkillTool(catalog, runtime.active_skills, registry)
    registry.register(load_skill)

    # ── Hook 加载 ────────────────────────────────────
    from Alincode.hook import load_from_dict, Event as HookEvent

    hook_engine = load_from_dict(app_cfg.hooks)

    # ── SubAgent Catalog ─────────────────────────────
    from Alincode.subagent import load_catalog as subagent_load_catalog

    subagent_catalog = subagent_load_catalog(workspace)

    # ── Task Manager ─────────────────────────────────
    from Alincode.task import Manager as TaskManager

    task_mgr = TaskManager()

    # ── Worktree Manager ────────────────────────────
    wt_mgr = None
    try:
        from Alincode.worktree import Manager as WorktreeManager

        wt_mgr = WorktreeManager(workspace)
    except ValueError as e:
        print(f"worktree: init skipped: {e}", file=sys.stderr)

    # ── Agent 工具注册 ──────────────────────────────
    from Alincode.tools.agent_tool import AgentTool

    agent_tool = AgentTool(
        subagent_catalog, task_mgr, parent=None, bg_enabled=True, worktree_mgr=wt_mgr
    )
    registry.register(agent_tool)

    # ── 过期 Worktree 清理 ───────────────────────────
    if wt_mgr is not None:
        from datetime import datetime, timedelta

        asyncio.create_task(wt_mgr.sweep_stale(datetime.now() - timedelta(hours=24)))

    # ── Team 集成 wire(T28) ───────────────────────────
    from Alincode.team import Manager as TeamManager
    from Alincode.team.registry import AgentNameRegistry
    from Alincode.team.spawn import SpawnDeps

    name_reg = AgentNameRegistry()
    task_mgr.set_name_registry(name_reg)
    team_mgr = TeamManager(
        home_dir=user_home,
        project_root=workspace,
        wt_mgr=wt_mgr,
        task_mgr=task_mgr,
        reg=name_reg,
    )

    # 注册 TeamCreate / TeamDelete（全局工具，其余 Team 工具由 build_teammate_tools per-team 构造）
    from Alincode.tools.team_create import TeamCreateTool
    from Alincode.tools.team_delete import TeamDeleteTool

    registry.register(TeamCreateTool(team_mgr))
    registry.register(TeamDeleteTool(team_mgr))

    # 注入 Team Manager 到 AgentTool（team_name 分支直接处理 spawn）
    agent_tool.set_team_manager(team_mgr)

    # 注入 spawn deps
    team_mgr.set_spawn_deps(
        SpawnDeps(
            provider=provider,
            registry=registry,
            catalog=subagent_catalog,
            engine=engine,
            hook_engine=hook_engine,
            model=provider_cfg.model,
            version="0.3.0",
        )
    )

    # 注入 kill 回调
    async def _kill_member(member_info):
        from Alincode.team.backend import new_backend

        backend = new_backend(member_info.backend_type, task_mgr=task_mgr)
        await backend.kill(member_info.pane_id, member_info.agent_id)

    team_mgr.set_kill_member(_kill_member)

    # T30: 注册 on_task_done 回调(队员 idle 通知)
    task_mgr.on_task_done(team_mgr.handle_task_done)

    # /team 命令注册
    from Alincode.commands.builtin_team import register as register_team_cmds

    team_commands = register_team_cmds(team_mgr)

    # ── Coordinator Mode 应用(T24) ──
    from Alincode import coordinator

    coordinator_enabled = coordinator.is_enabled(app_cfg)

    app = AlinCodeApp(
        provider=provider,
        model=provider_cfg.model,
        registry=registry,
        engine=engine,
        runtime=runtime,
        instruction_text=instruction_text,
        memory_text=memory_text,
        writer=writer,
        memory_manager=mem_mgr,
        workspace=workspace,
        catalog=catalog,
        hook_engine=hook_engine,
        task_mgr=task_mgr,
    )
    # 回填 parent 引用
    agent_tool.set_parent(app.agent)
    agent_tool.set_conv_getter(lambda: app._conv.messages)

    # ── T28: 注入 team_mgr + 命令到 App ──
    app.team_mgr = team_mgr
    app._team_commands = team_commands

    # ── T24: Coordinator Mode 应用 ──
    if coordinator_enabled:
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
        await hook_engine.dispatch(
            HookEvent.SESSION_END,
            {
                "event": "session_end",
                "session_id": runtime.session.session_id,
                "cwd": workspace,
                "mode": "default",
            },
        )
        writer.close()
        if mcp_mgr is not None:
            await mcp_mgr.close()


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
