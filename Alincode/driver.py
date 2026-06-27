"""主驱动模块：编排配置加载、Provider 创建、工具注册、MCP 连接、权限引擎、应用启动。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from Alincode.config import ConfigLoader
from Alincode.client import create_provider
from Alincode.tools import new_default_registry
from Alincode.permission.engine import new_engine
from Alincode.mcp import load_config as mcp_load_config, new_manager as mcp_new_manager
from Alincode.app import AlinCodeApp


DEFAULT_CONFIG_PATHS = [
    Path(".Alincode/skills/config.yaml"),
    Path("config.yaml"),
]


async def _amain(config_path: str | None = None) -> None:
    if config_path is None:
        for p in DEFAULT_CONFIG_PATHS:
            if p.is_file():
                config_path = str(p)
                break
        if config_path is None:
            print("错误: 找不到 config.yaml 配置文件")
            print("请复制 config.example.yaml 为 config.yaml 或 .Alincode/skills/config.yaml")
            raise SystemExit(1)

    config = ConfigLoader.load(config_path)
    provider = create_provider(config)
    registry = new_default_registry()

    # ── MCP 工具发现与注册 ────────────────────────
    root = str(Path.cwd().resolve())
    mcp_cfg = mcp_load_config(root)
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

    app = AlinCodeApp(provider=provider, model=config.model, registry=registry, engine=engine)
    try:
        await app.run_async()
    finally:
        await mcp_mgr.close()


def run(config_path: str | None = None) -> None:
    """同步入口。"""
    asyncio.run(_amain(config_path))
