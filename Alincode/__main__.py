# Alincode/__main__.py
"""AlinCode 入口 — 使用 `python -m Alincode` 启动。

默认进入 TUI；`--web` 启动浏览器端（FastAPI + WebSocket）：
    python -m Alincode --web [--host 127.0.0.1] [--port 8765] [config.yaml]
"""

import sys


def main() -> None:
    if "--web" in sys.argv:
        argv = [a for a in sys.argv[1:] if a != "--web"]
        host, port, config_path = "127.0.0.1", 8765, None
        i = 0
        while i < len(argv):
            if argv[i] == "--host":
                host = argv[i + 1]
                i += 2
            elif argv[i] == "--port":
                port = int(argv[i + 1])
                i += 2
            else:
                config_path = argv[i]
                i += 1
        from Alincode.web.server import serve
        serve(config_path=config_path, host=host, port=port)
        return
    from Alincode.driver import run
    run()


if __name__ == "__main__":
    main()
