"""主驱动模块：编排配置加载、Provider 创建、工具注册、应用启动。"""

from pathlib import Path

from Alincode.config import ConfigLoader
from Alincode.client import create_provider
from Alincode.tools import new_default_registry
from Alincode.app import AlinCodeApp


# 配置搜索路径，按优先级排列
DEFAULT_CONFIG_PATHS = [
    Path(".Alincode/skills/config.yaml"),
    Path("config.yaml"),
]


def run(config_path: str | None = None) -> None:
    """加载配置、创建 Provider、注册工具、启动 TUI。

    Args:
        config_path: 配置文件路径，为 None 时按 DEFAULT_CONFIG_PATHS 搜索。
    """
    if config_path is None:
        for p in DEFAULT_CONFIG_PATHS:
            if p.is_file():
                config_path = str(p)
                break
        if config_path is None:
            print("错误: 找不到 config.yaml 配置文件")
            print("请复制 config.example.yaml 为 config.yaml 或 .Alincode/skills/config.yaml")
            raise SystemExit(1)

    # 加载配置
    config = ConfigLoader.load(config_path)

    # 创建 provider
    provider = create_provider(config)

    # 构造工具注册中心
    registry = new_default_registry()

    # 启动 Textual TUI
    app = AlinCodeApp(provider=provider, model=config.model, registry=registry)
    app.run()
