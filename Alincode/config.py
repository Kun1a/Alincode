"""配置模块：ProviderConfig / AppConfig + ConfigLoader 统一加载。"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from Alincode.config_protocol import (
    DEFAULT_ANTHROPIC_CONTEXT_WINDOW,
    DEFAULT_OPENAI_CONTEXT_WINDOW,
)


# ── 数据类 ──────────────────────────────────────────

@dataclass
class ProviderConfig:
    """LLM 供应商配置。"""
    name: str = "default"
    protocol: str = ""      # "anthropic" | "openai"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    context_window: int = 0  # 0 表示走协议默认


def effective_context_window(p: ProviderConfig) -> int:
    """返回 provider 的有效上下文窗口大小。"""
    if p.context_window > 0:
        return p.context_window
    if p.protocol == "anthropic":
        return DEFAULT_ANTHROPIC_CONTEXT_WINDOW
    if p.protocol == "openai":
        return DEFAULT_OPENAI_CONTEXT_WINDOW
    return DEFAULT_ANTHROPIC_CONTEXT_WINDOW


@dataclass
class AppConfig:
    """应用级配置：providers 列表 + MCP servers + Hooks。"""
    providers: list[ProviderConfig] = field(default_factory=list)
    mcp_servers: dict = field(default_factory=dict)  # raw dict，由 mcp 层进一步校验
    hooks: list[dict] = field(default_factory=list)   # raw list，由 hook 层进一步校验


# ── 加载器 ──────────────────────────────────────────

class ConfigLoader:
    """统一 YAML 配置文件加载。

    支持两种格式：
    - 新格式：顶层 providers 列表 + mcp_servers 字典
    - 旧格式：顶层扁平字段（protocol/model/base_url/api_key）
    """

    VALID_PROTOCOLS = {"anthropic", "openai"}
    PROVIDER_FIELDS = ("protocol", "model", "base_url", "api_key")

    @staticmethod
    def load(path: str) -> AppConfig:
        """读取 YAML 配置，返回 AppConfig。"""
        config_path = Path(path)
        if not config_path.is_file():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            raise ValueError("配置文件内容为空")

        providers = ConfigLoader._parse_providers(data)
        mcp_servers = data.get("mcp_servers")
        if mcp_servers is None:
            mcp_servers = {}
        elif not isinstance(mcp_servers, dict):
            mcp_servers = {}

        hooks_raw = data.get("hooks")
        hooks: list[dict] = []
        if isinstance(hooks_raw, list):
            hooks = hooks_raw

        return AppConfig(providers=providers, mcp_servers=mcp_servers, hooks=hooks)

    @staticmethod
    def _parse_providers(data: dict) -> list[ProviderConfig]:
        """从 YAML 数据中解析 providers 列表。"""
        raw_providers = data.get("providers")

        if raw_providers is None:
            # 旧格式：顶层扁平字段
            return [ConfigLoader._parse_single_provider(data, name="default")]

        if not isinstance(raw_providers, list):
            raise ValueError("providers 必须是列表")

        result = []
        for i, entry in enumerate(raw_providers):
            if not isinstance(entry, dict):
                print(f"[config] warn: providers[{i}] 不是字典，跳过", file=sys.stderr)
                continue
            name = str(entry.get("name", f"provider-{i}")).strip()
            result.append(ConfigLoader._parse_single_provider(entry, name=name))

        if not result:
            raise ValueError("providers 列表为空或全部校验失败")

        return result

    @staticmethod
    def _parse_single_provider(data: dict, name: str = "default") -> ProviderConfig:
        """解析单个 provider 配置。"""
        missing = [f for f in ConfigLoader.PROVIDER_FIELDS if not data.get(f)]
        if missing:
            raise ValueError(
                f"provider '{name}' 缺少必填字段: {', '.join(missing)}"
            )

        protocol = str(data["protocol"]).strip().lower()
        if protocol not in ConfigLoader.VALID_PROTOCOLS:
            raise ValueError(
                f"provider '{name}' protocol 值不合法: '{protocol}'，"
                f"必须是 {' 或 '.join(sorted(ConfigLoader.VALID_PROTOCOLS))}"
            )

        return ProviderConfig(
            name=name,
            protocol=protocol,
            model=str(data["model"]).strip(),
            base_url=str(data["base_url"]).strip(),
            api_key=str(data["api_key"]).strip(),
            context_window=int(data.get("context_window", 0)),
        )
