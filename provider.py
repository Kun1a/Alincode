"""Provider 抽象层：定义统一 LLM 接口，Anthropic 和 OpenAI 各自实现。

子类只需实现 chat() 方法和 provider_name 属性即可接入。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, List, Optional

from config import ProviderConfig


@dataclass
class Message:
    """对话消息，兼容 Anthropic 和 OpenAI 两种格式。

    extra 字段为 extended thinking 等扩展能力预留，纯文本对话时为 None。
    """
    role: str           # "user" | "assistant" | "system"
    content: str        # 消息正文
    extra: Optional[dict] = None   # 扩展字段（thinking blocks 等）


class BaseProvider(ABC):
    """LLM Provider 抽象基类。

    所有 LLM 后端通过继承此类来接入，核心是 chat() 方法返回异步 token 迭代器。
    """

    @abstractmethod
    async def chat(self, messages: List[Message], model: str) -> AsyncIterator[str]:
        """发送对话历史给 LLM，异步流式返回 token。

        Args:
            messages: 完整对话历史（含本次 user 消息）
            model: 模型名，可由调用方覆盖配置中的值

        Yields:
            每个 token 字符串（可能包含特殊标记如 [THINKING]）
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 标识名，如 "anthropic"、"openai"。"""
        ...


def create_provider(config: ProviderConfig) -> BaseProvider:
    """根据配置创建对应的 Provider 实例。

    Args:
        config: 已校验的 ProviderConfig

    Returns:
        对应协议的 BaseProvider 子类实例

    Raises:
        ValueError: protocol 值不匹配任何已知 provider
    """
    if config.protocol == "openai":
        from openai_provider import OpenAIProvider
        return OpenAIProvider(config)
    elif config.protocol == "anthropic":
        from anthropic_provider import AnthropicProvider
        return AnthropicProvider(config)
    else:
        raise ValueError(f"未知的 protocol: '{config.protocol}'")
