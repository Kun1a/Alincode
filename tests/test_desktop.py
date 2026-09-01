"""Windows 桌面入口的无 GUI 单元测试。"""

import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from Alincode import desktop
from Alincode.desktop import DesktopConfig, desktop_url
from Alincode.web import server


def test_desktop_uses_a_random_loopback_port_and_one_time_token():
    config = DesktopConfig()

    assert config.host == "127.0.0.1"
    assert config.port == 0
    assert desktop_url(43123, "launch-token") == "http://127.0.0.1:43123/?token=launch-token"


def test_frozen_app_reads_the_bundled_webui_dist(tmp_path, monkeypatch):
    monkeypatch.setattr(server.sys, "frozen", True, raising=False)
    monkeypatch.setattr(server.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert server.webui_dist() == tmp_path / "webui" / "dist"


def test_loopback_server_releases_its_port_after_stop():
    app = FastAPI()
    app.get("/api/health")(lambda: {"ok": True})
    loopback = desktop.LoopbackServer(app)
    port = loopback.start()

    assert b"ok" in urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health").read()
    loopback.stop()

    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)


def test_desktop_window_close_stops_the_loopback_server(monkeypatch):
    events: list[str] = []

    class FakeServer:
        def __init__(self, app):
            events.append("server-created")

        def start(self):
            events.append("server-started")
            return 43123

        def stop(self):
            events.append("server-stopped")

    webview = SimpleNamespace(
        create_window=lambda title, url, **kwargs: events.append(f"window:{url}"),
        start=lambda: events.append("window-closed"),
    )
    monkeypatch.setattr(desktop, "LoopbackServer", FakeServer)
    monkeypatch.setitem(sys.modules, "webview", webview)

    desktop.run_desktop()

    assert events[-2:] == ["window-closed", "server-stopped"]
