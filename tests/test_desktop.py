"""Windows 桌面入口的无 GUI 单元测试。"""

from Alincode.desktop import DesktopConfig, desktop_url


def test_desktop_uses_a_random_loopback_port_and_one_time_token():
    config = DesktopConfig()

    assert config.host == "127.0.0.1"
    assert config.port == 0
    assert desktop_url(43123, "launch-token") == "http://127.0.0.1:43123/?token=launch-token"
