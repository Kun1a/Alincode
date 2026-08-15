# Alincode/web/server.py
"""FastAPI 应用工厂 + WebSocket 端点 + 静态前端挂载。"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from Alincode.bootstrap import AppContext, build_context, shutdown_context
from Alincode.session.list import list_sessions
from Alincode.session.load import load_session
from Alincode.web.protocol import project_messages
from Alincode.web.session import WebSession

WEBUI_DIST = Path(__file__).resolve().parents[2] / "webui" / "dist"


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="AlinCode WebUI")
    sessions_dir = os.path.join(ctx.workspace, ".Alincode", "sessions")

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/api/sessions")
    async def sessions() -> list[dict]:
        return [
            {"id": s.id, "title": s.title, "model": s.model, "size": s.size,
             "modified_at": s.modified_at.isoformat()}
            for s in list_sessions(sessions_dir)
        ]

    @app.get("/api/sessions/{session_id}/messages")
    async def session_messages(session_id: str) -> list[dict]:
        sdir = os.path.join(sessions_dir, session_id)
        if not os.path.isdir(sdir):
            return []
        return project_messages(load_session(sdir))

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        session = WebSession(ctx)

        async def _pump() -> None:
            """唯一写 socket 的协程：outbox → 浏览器。"""
            while True:
                msg = await session.outbox.get()
                await ws.send_json(msg)

        pump = asyncio.create_task(_pump())
        await session.open()
        try:
            while True:
                data = await ws.receive_json()
                await session.handle(data)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await session.close()
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump

    # 静态前端（构建后）。dist 不存在时给提示页，避免 404 困惑。
    if WEBUI_DIST.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(WEBUI_DIST), html=True), name="ui")
    else:
        @app.get("/")
        async def index_hint() -> str:
            return ("AlinCode 后端已启动，但前端尚未构建。"
                    "请执行 cd webui && npm install && npm run build，"
                    "或使用 npm run dev 走 Vite 开发服务器（代理已配置）。")

    return app


def serve(config_path: str | None = None,
          host: str = "127.0.0.1", port: int = 8765) -> None:
    """同步入口：python -m Alincode --web。"""
    if host not in ("127.0.0.1", "localhost"):
        print("警告: WebUI 可驱动真实工具执行且 MVP 无鉴权，"
              "绑定非本机地址有安全风险！")

    async def _main() -> None:
        ctx = await build_context(config_path)
        app = create_app(ctx)
        cfg = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(cfg)
        try:
            await server.serve()
        finally:
            await shutdown_context(ctx)

    asyncio.run(_main())
