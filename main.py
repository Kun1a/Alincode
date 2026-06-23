"""MewCode v0.2 — 终端 AI 编程助手入口。

启动流程：加载配置 → 创建 Provider → 启动 TUI 对话。
"""

import asyncio
import sys

from config import ConfigLoader
from provider import create_provider
from tui.app import run


async def main() -> None:
    """MewCode 主入口。"""
    config_path = "config.yaml"

    # 加载配置
    try:
        config = ConfigLoader.load(config_path)
    except FileNotFoundError as e:
        print(f"错误: {e}")
        print("请创建 config.yaml 配置文件（参考 config.example.yaml）")
        sys.exit(1)
    except ValueError as e:
        print(f"配置错误: {e}")
        sys.exit(1)

    # 创建 provider
    try:
        provider = create_provider(config)
    except Exception as e:
        print(f"创建 Provider 失败: {e}")
        sys.exit(1)

    # 启动 TUI
    try:
        await run(provider, config.model)
    except Exception as e:
        print(f"运行错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
