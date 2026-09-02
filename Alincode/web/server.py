# Alincode/web/server.py
"""FastAPI 应用工厂 + WebSocket 端点 + 静态前端挂载。"""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from Alincode.bootstrap import AppContext, build_context, shutdown_context
from Alincode.session.list import list_sessions
from Alincode.session.load import load_session
from Alincode.profile.store import ProfileStore
from Alincode.profile.service import ProfileService
from Alincode.web.auth import LocalAuth
from Alincode.web.protocol import project_messages
from Alincode.web.session import WebSession

def webui_dist() -> Path:
    """返回源码或 PyInstaller onedir 包中的前端构建产物目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "webui" / "dist"
    return Path(__file__).resolve().parents[2] / "webui" / "dist"


def create_app(
    ctx: AppContext | None,
    *,
    auth: LocalAuth | None = None,
    profile_store: ProfileStore | None = None,
) -> FastAPI:
    app = FastAPI(title="AlinCode WebUI")
    sessions_dir = os.path.join(ctx.workspace, ".Alincode", "sessions") if ctx else None

    if (auth is None) != (profile_store is None):
        raise ValueError("桌面认证需要同时提供 auth 和 profile_store")
    profile_service = ProfileService(profile_store) if profile_store else None

    def _local_session(request: Request) -> str:
        session_id = request.cookies.get("alincode_session")
        if auth is None or not session_id or not auth.has_session(session_id):
            raise HTTPException(status_code=401, detail="请先完成本机启动验证")
        return session_id

    def _profile_for_session(session_id: str) -> str:
        if auth is None or not auth.has_session(session_id):
            raise HTTPException(status_code=401, detail="请先完成本机启动验证")
        profile_id = auth.profile_for(session_id)
        if profile_id is None:
            raise HTTPException(status_code=403, detail="请先解锁 Profile")
        return profile_id

    def _unlocked_profile(request: Request) -> tuple[str, str]:
        session_id = _local_session(request)
        return session_id, _profile_for_session(session_id)

    def _history_dir(request: Request) -> str:
        if auth is None:
            assert sessions_dir is not None
            return sessions_dir
        _, profile_id = _unlocked_profile(request)
        assert profile_store is not None
        return str(profile_store.sessions_dir(profile_id))

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True}

    @app.post("/api/auth/exchange", status_code=204)
    async def exchange_launch_token(request: Request, response: Response) -> None:
        if auth is None:
            raise HTTPException(status_code=404, detail="当前入口不需要本机认证")
        data = await request.json()
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str):
            raise HTTPException(status_code=400, detail="启动令牌格式错误")
        session_id = auth.exchange_launch_token(token)
        if session_id is None:
            raise HTTPException(status_code=401, detail="启动令牌无效或已使用")
        response.set_cookie(
            "alincode_session", session_id, httponly=True, samesite="strict",
        )

    @app.get("/api/profiles")
    async def profiles(request: Request) -> list[dict[str, str]]:
        _local_session(request)
        assert profile_store is not None
        return [_profile_data(profile) for profile in profile_store.list_profiles()]

    @app.post("/api/profiles", status_code=201)
    async def create_profile(request: Request) -> dict[str, str]:
        session_id = _local_session(request)
        assert profile_store is not None and auth is not None
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Profile 数据格式错误")
        name = data.get("name")
        password = data.get("password")
        if not isinstance(name, str) or not isinstance(password, str):
            raise HTTPException(status_code=400, detail="Profile 名称和密码不能为空")
        try:
            profile = profile_store.create(name, password)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        auth.unlock(session_id, profile.id)
        return _profile_data(profile)

    @app.get("/api/profile")
    async def current_profile(request: Request) -> dict[str, str]:
        _, profile_id = _unlocked_profile(request)
        assert profile_store is not None
        return _profile_data(profile_store.get(profile_id))

    @app.post("/api/profiles/{profile_id}/unlock")
    async def unlock_profile(profile_id: str, request: Request) -> dict[str, str]:
        session_id = _local_session(request)
        assert profile_store is not None and auth is not None
        data = await request.json()
        password = data.get("password") if isinstance(data, dict) else None
        if not isinstance(password, str):
            raise HTTPException(status_code=400, detail="Profile 密码不能为空")
        try:
            matched = profile_store.verify_password(profile_id, password)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Profile 不存在") from error
        if not matched:
            raise HTTPException(status_code=401, detail="Profile 密码错误")
        auth.unlock(session_id, profile_id)
        return _profile_data(profile_store.get(profile_id))

    @app.post("/api/profile/lock", status_code=204)
    async def lock_profile(request: Request) -> None:
        session_id, _ = _unlocked_profile(request)
        assert auth is not None
        auth.lock(session_id)

    @app.put("/api/profile/provider")
    async def save_provider(request: Request) -> dict[str, str]:
        _, profile_id = _unlocked_profile(request)
        assert profile_service is not None
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Provider 配置格式错误")
        fields = ("protocol", "model", "base_url", "api_key")
        if any(not isinstance(data.get(field), str) for field in fields):
            raise HTTPException(status_code=400, detail="Provider 配置字段格式错误")
        if not all(data[field].strip() for field in ("protocol", "model")):
            raise HTTPException(status_code=400, detail="Provider 和模型不能为空")
        api_key = data["api_key"].strip()
        if not api_key:
            try:
                api_key = profile_service.provider_key(profile_id)
            except FileNotFoundError as error:
                raise HTTPException(status_code=400, detail="首次保存时 API Key 不能为空") from error
        profile_service.save_provider(
            profile_id,
            protocol=data["protocol"].strip(),
            model=data["model"].strip(),
            base_url=data["base_url"].strip(),
            api_key=api_key,
        )
        return profile_service.provider_summary(profile_id)

    @app.get("/api/profile/provider")
    async def provider_summary(request: Request) -> dict[str, str]:
        _, profile_id = _unlocked_profile(request)
        assert profile_service is not None
        try:
            return profile_service.provider_summary(profile_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail="尚未配置 Provider") from error

    @app.put("/api/profile/budget")
    async def set_budget(request: Request) -> dict[str, int | bool]:
        _, profile_id = _unlocked_profile(request)
        assert profile_service is not None
        data = await request.json()
        budget = data.get("budget") if isinstance(data, dict) else None
        if not isinstance(budget, int) or isinstance(budget, bool):
            raise HTTPException(status_code=400, detail="预算必须是非负整数")
        try:
            profile_service.set_budget(profile_id, budget)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return profile_service.budget_status(profile_id)

    @app.get("/api/profile/budget")
    async def budget_status(request: Request) -> dict[str, int | bool]:
        _, profile_id = _unlocked_profile(request)
        assert profile_service is not None
        return profile_service.budget_status(profile_id)

    @app.put("/api/profile/workspace")
    async def set_workspace(request: Request) -> dict[str, str]:
        _, profile_id = _unlocked_profile(request)
        assert profile_service is not None
        data = await request.json()
        workspace = data.get("path") if isinstance(data, dict) else None
        if not isinstance(workspace, str) or not workspace.strip():
            raise HTTPException(status_code=400, detail="项目目录不能为空")
        try:
            profile_service.set_workspace(profile_id, workspace)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"path": profile_service.workspace(profile_id) or ""}

    @app.get("/api/profile/workspace")
    async def workspace(request: Request) -> dict[str, str]:
        _, profile_id = _unlocked_profile(request)
        assert profile_service is not None
        return {"path": profile_service.workspace(profile_id) or ""}

    @app.put("/api/profile/workspaces")
    async def save_workspaces(request: Request) -> dict[str, list[str] | str]:
        _, profile_id = _unlocked_profile(request)
        assert profile_service is not None
        data = await request.json()
        paths = data.get("paths") if isinstance(data, dict) else None
        active_path = data.get("active_path") if isinstance(data, dict) else None
        if not isinstance(paths, list) or not paths or not all(isinstance(path, str) for path in paths):
            raise HTTPException(status_code=400, detail="项目目录列表不能为空")
        if not isinstance(active_path, str) or not active_path.strip():
            raise HTTPException(status_code=400, detail="当前项目目录不能为空")
        try:
            return profile_service.save_workspaces(profile_id, paths, active_path=active_path)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/profile/workspaces")
    async def workspaces(request: Request) -> dict[str, list[str] | str]:
        _, profile_id = _unlocked_profile(request)
        assert profile_service is not None
        return profile_service.workspaces(profile_id)

    @app.put("/api/profile/mcp")
    async def save_mcp_servers(request: Request) -> dict:
        _, profile_id = _unlocked_profile(request)
        assert profile_service is not None
        data = await request.json()
        if not isinstance(data, dict) or not isinstance(data.get("servers"), dict):
            raise HTTPException(status_code=400, detail="MCP Server 配置格式错误")
        try:
            profile_service.save_mcp_servers(profile_id, data["servers"])
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"servers": profile_service.mcp_servers(profile_id)}

    @app.get("/api/profile/mcp")
    async def mcp_servers(request: Request) -> dict:
        _, profile_id = _unlocked_profile(request)
        assert profile_service is not None
        return {"servers": profile_service.mcp_servers(profile_id)}

    @app.get("/api/sessions")
    async def sessions(request: Request) -> list[dict]:
        return [
            {"id": s.id, "title": s.title, "model": s.model, "size": s.size,
             "modified_at": s.modified_at.isoformat()}
            for s in list_sessions(_history_dir(request))
        ]

    @app.get("/api/sessions/{session_id}/messages")
    async def session_messages(session_id: str, request: Request) -> list[dict]:
        sdir = os.path.join(_history_dir(request), session_id)
        if not os.path.isdir(sdir):
            return []
        return project_messages(load_session(sdir))

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        session_root = None
        profile_id = None
        session_ctx = ctx
        owns_context = False
        if auth is not None:
            try:
                profile_id = _profile_for_session(ws.cookies.get("alincode_session", ""))
                assert profile_service is not None
                workspace = profile_service.workspace(profile_id)
                if workspace is None:
                    raise ValueError("请先选择项目目录")
                session_ctx = await build_context(
                    workspace=workspace,
                    provider_override=profile_service.provider_config(profile_id),
                    mcp_servers_override=profile_service.mcp_servers(profile_id),
                )
                owns_context = True
            except HTTPException:
                await ws.close(code=1008)
                return
            except (FileNotFoundError, ValueError):
                await ws.close(code=1008)
                return
            assert profile_store is not None
            session_root = str(profile_store.sessions_dir(profile_id))
        if session_ctx is None:
            await ws.close(code=1011)
            return
        assert session_ctx is not None
        await ws.accept()
        session = WebSession(
            session_ctx,
            session_root=session_root,
            profile_service=profile_service,
            profile_id=profile_id,
        )

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
            if owns_context:
                await shutdown_context(session_ctx)

    # 静态前端（构建后）。dist 不存在时给提示页，避免 404 困惑。
    frontend_dist = webui_dist()
    if frontend_dist.is_dir():
        # PyInstaller 环境可能缺失 Windows MIME 注册表，导致 ES module 被当作 text/plain。
        mimetypes.add_type("application/javascript", ".js", strict=True)
        mimetypes.add_type("application/javascript", ".mjs", strict=True)
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="ui")
    else:
        @app.get("/")
        async def index_hint() -> str:
            return ("AlinCode 后端已启动，但前端尚未构建。"
                    "请执行 cd webui && npm install && npm run build，"
                    "或使用 npm run dev 走 Vite 开发服务器（代理已配置）。")

    return app


def _profile_data(profile) -> dict[str, str]:
    return {"id": profile.id, "name": profile.name}


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
