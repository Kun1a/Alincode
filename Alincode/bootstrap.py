# Alincode/bootstrap.py
"""应用装配工厂：provider/工具/权限/记忆/团队等共享装配（TUI 与 Web 共用）。

会话级组件（SessionRuntime / Writer / Agent / ConversationManager）
不在此处构造——它们由 core_session.create_session 按会话创建。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from Alincode.client import BaseProvider, create_provider
from Alincode.config import AppConfig, ConfigLoader, ProviderConfig
from Alincode.instructions import Loader as InstructionsLoader
from Alincode.mcp import load_from_dict as mcp_from_dict, new_manager as mcp_new_manager
from Alincode.memory import Manager as MemoryManager
from Alincode.permission.engine import PermissionEngine, new_engine
from Alincode.skills.catalog import Catalog
from Alincode.tools import Registry, new_default_registry

DEFAULT_CONFIG_PATHS = [
    Path(".Alincode/config.yaml"),
    Path(".Alincode/skills/config.yaml"),
    Path("config.yaml"),
]


@dataclass
class AppContext:
    """共享装配产物。会话级组件（runtime/writer/agent/conv）由 core_session 构造。"""

    app_cfg: AppConfig
    provider_cfg: ProviderConfig
    provider: BaseProvider
    registry: Registry
    engine: PermissionEngine
    instruction_text: str
    memory_text: str
    memory_manager: MemoryManager | None
    workspace: str
    catalog: Catalog | None
    hook_engine: object          # hook.engine.Engine | None
    subagent_catalog: object | None
    task_mgr: object | None      # task.Manager
    wt_mgr: object | None        # worktree.Manager | None
    team_mgr: object | None      # team.Manager
    agent_tool: object | None    # tools.agent_tool.AgentTool
    team_commands: list = field(default_factory=list)
    mcp_mgr: object | None = None
    coordinator_enabled: bool = False


def resolve_config_path(config_path: str | None) -> str:
    """配置文件发现；找不到时打印指引并 SystemExit(1)。"""
    if config_path is not None:
        return config_path
    for p in DEFAULT_CONFIG_PATHS:
        if p.is_file():
            return str(p)
    print("错误: 找不到 config.yaml 配置文件")
    print("请复制 config.example.yaml 为 config.yaml 或 .Alincode/skills/config.yaml")
    raise SystemExit(1)


async def build_context(
    config_path: str | None = None,
    *,
    workspace: str | None = None,
    provider_override: ProviderConfig | None = None,
) -> AppContext:
    """执行全部共享装配，返回 AppContext。主体逻辑搬自 driver._amain，语义不变。"""
    if config_path is None and provider_override is not None:
        app_cfg = AppConfig()
    else:
        config_path = resolve_config_path(config_path)
        app_cfg = ConfigLoader.load(config_path)
    if not app_cfg.providers and provider_override is None:
        print("错误: 配置文件中没有有效的 provider")
        raise SystemExit(1)

    # 桌面 Profile 可覆盖模型配置；TUI/Web 仍使用配置文件第一个 provider。
    provider_cfg = provider_override or app_cfg.providers[0]
    provider = create_provider(provider_cfg)
    registry = new_default_registry()
    workspace_path = str(Path(workspace).resolve()) if workspace else str(Path.cwd().resolve())

    # ── MCP 工具发现与注册 ────────────────────────
    root = workspace_path
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
    user_home = os.path.expanduser("~")
    loader = InstructionsLoader(project_root=workspace_path, user_home=user_home)
    instruction_text = loader.load()

    # ── 记忆初始化 ────────────────────────────────
    mem_mgr = MemoryManager(
        project_dir=os.path.join(workspace_path, ".Alincode", "memory"),
        user_dir=os.path.join(user_home, ".Alincode", "memory"),
        provider=provider,
        model=provider_cfg.model,
    )
    memory_text = mem_mgr.load_index()

    # ── 后台清理过期会话 ────────────────────────────
    from Alincode.session import clean_expired

    sessions_dir = os.path.join(workspace_path, ".Alincode", "sessions")
    asyncio.create_task(
        asyncio.to_thread(clean_expired, sessions_dir, _dt.timedelta(days=30))
    )

    # ── Skills 加载 ────────────────────────────────
    catalog = Catalog.load(workspace_path)
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

    # 注册 LoadSkill 工具。
    # 注意：原 driver 传入 runtime.active_skills（会话级），此处无 runtime，
    # 用占位 ActiveSkills 注册；core_session.create_session 会在每个会话
    # 创建时把 _active 重绑到该会话 runtime.active_skills。
    from Alincode.skills.active import ActiveSkills
    from Alincode.skills.load_skill import LoadSkillTool

    load_skill = LoadSkillTool(catalog, ActiveSkills(), registry)
    registry.register(load_skill)

    # ── Hook 加载 ────────────────────────────────────
    from Alincode.hook import load_from_dict

    hook_engine = load_from_dict(app_cfg.hooks)

    # ── SubAgent Catalog ─────────────────────────────
    from Alincode.subagent import load_catalog as subagent_load_catalog

    subagent_catalog = subagent_load_catalog(workspace_path)

    # ── Task Manager ─────────────────────────────────
    from Alincode.task import Manager as TaskManager

    task_mgr = TaskManager()

    # ── Worktree Manager ────────────────────────────
    wt_mgr = None
    try:
        from Alincode.worktree import Manager as WorktreeManager

        wt_mgr = WorktreeManager(workspace_path)
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
        project_root=workspace_path,
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

    # ── Coordinator Mode 判定(T24) ──
    from Alincode import coordinator

    coordinator_enabled = coordinator.is_enabled(app_cfg)

    return AppContext(
        app_cfg=app_cfg,
        provider_cfg=provider_cfg,
        provider=provider,
        registry=registry,
        engine=engine,
        instruction_text=instruction_text,
        memory_text=memory_text,
        memory_manager=mem_mgr,
        workspace=workspace_path,
        catalog=catalog,
        hook_engine=hook_engine,
        subagent_catalog=subagent_catalog,
        task_mgr=task_mgr,
        wt_mgr=wt_mgr,
        team_mgr=team_mgr,
        agent_tool=agent_tool,
        team_commands=team_commands,
        mcp_mgr=mcp_mgr,
        coordinator_enabled=coordinator_enabled,
    )


async def shutdown_context(ctx: AppContext) -> None:
    """关闭共享资源（目前仅 MCP 连接）。"""
    if ctx.mcp_mgr is not None:
        await ctx.mcp_mgr.close()
