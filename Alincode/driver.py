"""主驱动模块：编排配置加载、Provider 创建、工具注册、权限引擎、应用启动。"""

from pathlib import Path

from Alincode.config import ConfigLoader
from Alincode.client import create_provider
from Alincode.tools import new_default_registry
from Alincode.permission.engine import new_engine
from Alincode.app import AlinCodeApp


DEFAULT_CONFIG_PATHS = [
    Path(".Alincode/skills/config.yaml"),
    Path("config.yaml"),
]


def run(config_path: str | None = None) -> None:
    if config_path is None:
        for p in DEFAULT_CONFIG_PATHS:
            if p.is_file():
                config_path = str(p)
                break
        if config_path is None:
            print("错误: 找不到 config.yaml 配置文件")
            print("请复制 config.example.yaml 为 config.yaml 或 .Alincode/skills/config.yaml")
            raise SystemExit(1)

    config = ConfigLoader.load(config_path)
    provider = create_provider(config)
    registry = new_default_registry()

    # 构造权限引擎
    root = str(Path.cwd().resolve())
    engine, err = new_engine(root)
    if err:
        import sys
        print(f"权限引擎降级: {err}", file=sys.stderr)

    app = AlinCodeApp(provider=provider, model=config.model, registry=registry, engine=engine)
    app.run()
