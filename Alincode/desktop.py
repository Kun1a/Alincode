"""Windows 本地桌面入口：pywebview + 临时回环 Web 服务。"""

from __future__ import annotations

import asyncio
import os
import secrets
import socket
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote

import uvicorn

from Alincode.profile.store import ProfileStore
from Alincode.web.auth import LocalAuth
from Alincode.web.server import create_app


@dataclass(frozen=True)
class DesktopConfig:
    """桌面服务只能绑定本机，端口交给系统分配。"""

    host: str = "127.0.0.1"
    port: int = 0


def desktop_url(port: int, launch_token: str) -> str:
    """生成窗口首开 URL；令牌会由前端立即兑换并从地址栏移除。"""
    return f"http://127.0.0.1:{port}/?token={quote(launch_token)}"


class LoopbackServer:
    """在后台线程运行 Uvicorn，并保留关闭时所需的服务句柄。"""

    def __init__(self, app, config: DesktopConfig = DesktopConfig()) -> None:
        self._app = app
        self._config = config
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    def start(self) -> int:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self._config.host, self._config.port))
        listener.listen()
        self._socket = listener
        self.port = listener.getsockname()[1]
        self._server = uvicorn.Server(uvicorn.Config(self._app, log_level="warning"))
        self._thread = threading.Thread(target=self._serve, daemon=True, name="alincode-web")
        self._thread.start()
        deadline = time.monotonic() + 5
        while not self._server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        if not self._server.started:
            self.stop()
            raise RuntimeError("本机 Web 服务启动超时")
        return self.port

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._socket is not None:
            self._socket.close()

    def _serve(self) -> None:
        assert self._server is not None and self._socket is not None
        asyncio.run(self._server.serve(sockets=[self._socket]))


def pick_folder() -> str | None:
    """使用 Windows 原生目录选择框；取消时保持当前项目不变。"""
    from tkinter import Tk, filedialog

    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(title="选择项目目录") or None
    finally:
        root.destroy()


def pick_files() -> tuple[str, ...]:
    """使用 Windows 原生多文件选择器，取消时返回空元组。"""
    from tkinter import Tk, filedialog

    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return tuple(filedialog.askopenfilenames(title="选择文件作为上下文"))
    finally:
        root.destroy()


def open_directory(path: str) -> None:
    """让用户用资源管理器添加或编辑项目级 Skill。"""
    os.startfile(path)


def run_desktop() -> None:
    """启动桌面窗口；关闭窗口后同步关闭临时回环服务。"""
    launch_token = secrets.token_urlsafe(32)
    app = create_app(
        None,
        auth=LocalAuth(launch_token),
        profile_store=ProfileStore(),
        directory_picker=pick_folder,
        directory_opener=open_directory,
        file_picker=pick_files,
    )
    server = LoopbackServer(app)
    port = server.start()
    try:
        import webview

        webview.create_window("AlinCode", desktop_url(port, launch_token), width=1280, height=820)
        webview.start()
    finally:
        server.stop()
