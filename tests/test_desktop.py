"""Windows 桌面入口的无 GUI 单元测试。"""

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
