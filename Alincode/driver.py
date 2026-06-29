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
            print("请复制 config.example.yaml 为 config.yaml 或 .Alincode/skills/config.yaml")
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
    mcp_mgr = await mcp_new_manager(mcp_cfg, version="0.3.0")
    try:
        mcp_count = len(mcp_mgr.tools())
        for t in mcp_mgr.tools():
            registry.register(t)
        if mcp_count > 0:
            print(f"[mcp] registered {mcp_count} MCP tools from {len(mcp_cfg.servers)} server(s)",
                  file=sys.stderr)
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
            f"\"{iss.tool_name}\" not registered, skipped",
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

    app = AlinCodeApp(
        provider=provider, model=provider_cfg.model, registry=registry, engine=engine,
        runtime=runtime,
        instruction_text=instruction_text,
        memory_text=memory_text,
        writer=writer,
        memory_manager=mem_mgr,
        workspace=workspace,
        catalog=catalog,
    )
    try:
        await app.run_async()
    finally:
        writer.close()
        await mcp_mgr.close()


def run(config_path: str | None = None) -> None:
    """同步入口。"""
    asyncio.run(_amain(config_path))
