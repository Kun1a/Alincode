"""三种启动入口的参数路由测试。"""

import sys

from Alincode import __main__ as entry


def test_default_entry_keeps_tui_path(monkeypatch):
    called: list[bool] = []
    monkeypatch.setattr("Alincode.driver.run", lambda: called.append(True))
    monkeypatch.setattr(sys, "argv", ["AlinCode"])

    entry.main()

    assert called == [True]


def test_web_entry_preserves_web_arguments(monkeypatch):
    called: list[tuple[str | None, str, int]] = []
    monkeypatch.setattr(
        "Alincode.web.server.serve",
        lambda *, config_path, host, port: called.append((config_path, host, port)),
    )
    monkeypatch.setattr(sys, "argv", ["AlinCode", "--web", "--host", "0.0.0.0", "--port", "9123", "user.yaml"])

    entry.main()

    assert called == [("user.yaml", "0.0.0.0", 9123)]


def test_desktop_entry_does_not_change_tui_or_web_options(monkeypatch):
    called: list[bool] = []
    monkeypatch.setattr("Alincode.desktop.run_desktop", lambda: called.append(True))
    monkeypatch.setattr(sys, "argv", ["AlinCode", "--desktop"])

    entry.main()

    assert called == [True]
