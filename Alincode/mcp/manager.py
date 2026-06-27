"""MCP 连接管理器：并发连接、生命周期、工具注册（F4/F5/F6/F9/F10/F11）。"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AsyncExitStack

from Alincode.mcp.config import Config, ServerConfig
from Alincode.mcp.tool import McpTool, adapt_tool

# 超时常量（包级变量，单测可临时修改）
connect_timeout: float = 30.0
close_timeout: float = 5.0


class Manager:
    """MCP server 连接生命周期管理器。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: list[_Session] = []
        self._tools: list[McpTool] = []
        self._stack = AsyncExitStack()

    def tools(self) -> list[McpTool]:
        """返回适配好的工具列表（只读副本）。"""
        return list(self._tools)

    async def close(self) -> None:
        """关闭所有会话，5s 超时兜底。忽略清理阶段的协议错误。"""
        try:
            await asyncio.wait_for(self._stack.aclose(), timeout=close_timeout)
        except asyncio.TimeoutError:
            print(
                f"[mcp] warn: close timeout ({close_timeout}s), "
                f"some sessions may leak",
                file=sys.stderr,
            )
        except (RuntimeError, BaseExceptionGroup):
            # MCP SDK 在退出时的 async generator 清理可能抛 RuntimeError
            # （cancel scope 跨 task）或 BaseExceptionGroup，不影响功能
            pass
        except Exception:
            print(
                "[mcp] warn: unexpected error during close",
                file=sys.stderr,
            )


class _Session:
    """内部会话记录。"""
    def __init__(self, name: str, session: object) -> None:
        self.name = name
        self.session = session


async def new_manager(cfg: Config, version: str) -> Manager:
    """并发连接所有 server，每 server 30s 超时，失败跳过不阻塞。"""
    mgr = Manager()

    async def _connect_one(name: str, srv: ServerConfig) -> None:
        try:
            await asyncio.wait_for(
                _do_connect(mgr, name, srv, version),
                timeout=connect_timeout,
            )
        except asyncio.TimeoutError:
            print(
                f"[mcp] warn: connect server {name} timeout after {connect_timeout}s",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"[mcp] warn: connect server {name} failed: {e}", file=sys.stderr)

    tasks = [
        asyncio.create_task(_connect_one(name, srv))
        for name, srv in cfg.servers.items()
    ]
    if tasks:
        # _connect_one 内部已 try/except，但 gather 确保不抛 aggregate 异常
        await asyncio.gather(*tasks)

    # 稳定排序工具
    mgr._tools.sort(key=lambda t: t.name())
    return mgr


async def _do_connect(
    mgr: Manager, name: str, srv: ServerConfig, version: str,
) -> None:
    """建立单个 server 连接：transport → session → initialize → list_tools → adapt。"""
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError:
        print(
            "[mcp] warn: mcp SDK not installed. Install with: pip install mcp",
            file=sys.stderr,
        )
        return

    # 构造 transport
    if srv.type == "stdio":
        params = StdioServerParameters(
            command=srv.command,
            args=srv.args,
            env={**os.environ, **srv.env},
        )
        ctx = stdio_client(params)
    else:
        ctx = streamablehttp_client(srv.url, headers=srv.headers or None)

    transport = await mgr._stack.enter_async_context(ctx)
    read, write = transport[0], transport[1]
    session = await mgr._stack.enter_async_context(
        ClientSession(read, write)
    )
    await session.initialize()
    listed = await session.list_tools()

    adapted = []
    for t in (listed.tools or []):
        tool = adapt_tool(name, t, session)
        if tool:
            adapted.append(tool)

    async with mgr._lock:
        mgr._sessions.append(_Session(name, session))
        mgr._tools.extend(adapted)
