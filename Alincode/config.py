"""配置模块：ProviderConfig 数据类 + ConfigLoader 配置加载器。"""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ProviderConfig:
    """LLM 供应商配置。

    四个必填字段，由 ConfigLoader 从 YAML 文件加载。
    """
    protocol: str   # "anthropic" | "openai"
    model: str      # 模型名，如 "claude-opus-4-8"
    base_url: str   # API 端点地址
    api_key: str    # 认证密钥


class ConfigLoader:
    """YAML 配置文件加载与校验。

    用静态方法 load 读取指定路径的 YAML 文件，校验字段完整性后返回 ProviderConfig。
    """

    VALID_PROTOCOLS = {"anthropic", "openai"}
    REQUIRED_FIELDS = ("protocol", "model", "base_url", "api_key")

    @staticmethod
    def load(path: str) -> ProviderConfig:
        """读取并校验 YAML 配置，返回 ProviderConfig。

        Args:
            path: YAML 配置文件路径

        Returns:
            校验通过的 ProviderConfig 实例

        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 必填字段缺失或 protocol 值不合法
        """
        config_path = Path(path)
        if not config_path.is_file():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            raise ValueError("配置文件内容为空")

        # 校验必填字段
        missing = [field for field in ConfigLoader.REQUIRED_FIELDS if not data.get(field)]
        if missing:
            raise ValueError(
                f"配置文件缺少必填字段: {', '.join(missing)}\n"
                f"必填字段: {', '.join(ConfigLoader.REQUIRED_FIELDS)}"
            )

        # 校验 protocol 值
        protocol = str(data["protocol"]).strip().lower()
        if protocol not in ConfigLoader.VALID_PROTOCOLS:
            raise ValueError(
                f"protocol 值不合法: '{protocol}'，"
                f"必须是 {' 或 '.join(sorted(ConfigLoader.VALID_PROTOCOLS))}"
            )

        return ProviderConfig(
            protocol=protocol,
            model=str(data["model"]).strip(),
            base_url=str(data["base_url"]).strip(),
            api_key=str(data["api_key"]).strip(),
        )
