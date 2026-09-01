"""Windows 便携包专用入口，不影响默认 TUI 与 ``--web`` 调试入口。"""

from Alincode.desktop import run_desktop


if __name__ == "__main__":
    run_desktop()
