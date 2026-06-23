"""Client 模块：LLM Provider 抽象层与具体实现（Anthropic / OpenAI）。"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, List

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from Alincode.config import ProviderConfig
from Alincode.conversation import Message


# ── Abstract base ─────────────────────────────────────────────────

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


# ── Anthropic provider ────────────────────────────────────────────

# 启用 extended thinking 的请求参数，budget_tokens 设为 4000
THINKING_CONFIG = {
    "type": "enabled",
    "budget_tokens": 4000,
}


class AnthropicProvider(BaseProvider):
    """Anthropic 协议实现，使用 AsyncAnthropic 客户端进行流式对话。

    extended thinking 默认启用，思考过程以 [THINKING]...[/THINKING] 包裹输出。
    """

    def __init__(self, config: ProviderConfig) -> None:
        self._client = AsyncAnthropic(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def chat(self, messages: List[Message], model: str) -> AsyncIterator[str]:
        """调用 Anthropic Messages API，流式返回 token。

        Args:
            messages: 对话历史
            model: 模型名

        Yields:
            文本 token 字符串；思考过程以 [THINKING] 和 [/THINKING] 包裹。
        """
        try:
            async with self._client.messages.stream(
                model=model,
                max_tokens=8192,
                system=self._extract_system_prompt(messages),
                messages=self._to_anthropic_messages(messages),
                thinking=THINKING_CONFIG,
            ) as stream:
                in_thinking = False
                async for event in stream:
                    if event.type == "text":
                        if in_thinking:
                            yield "[/THINKING]"
                            in_thinking = False
                        yield event.text
                    elif event.type == "thinking_delta":
                        if not in_thinking:
                            yield "[THINKING]"
                            in_thinking = True
                        yield event.thinking
                    elif event.type == "thinking_done":
                        if in_thinking:
                            yield "[/THINKING]"
                            in_thinking = False

                if in_thinking:
                    yield "[/THINKING]"

        except Exception as e:
            print(f"\n[Anthropic 错误] {e}")

    def _to_anthropic_messages(self, messages: List[Message]) -> List[dict]:
        """将内部 Message 列表转换为 Anthropic API 格式。"""
        result = []
        for msg in messages:
            if msg.role == "system":
                continue
            result.append({"role": msg.role, "content": msg.content})
        return result

    def _extract_system_prompt(self, messages: List[Message]) -> str:
        """提取 system 角色的消息内容作为 system prompt。"""
        parts = [msg.content for msg in messages if msg.role == "system"]
        return "\n".join(parts) if parts else ""


# ── OpenAI provider ───────────────────────────────────────────────

class OpenAIProvider(BaseProvider):
    """OpenAI 协议实现，使用 AsyncOpenAI 客户端进行流式对话。"""

    def __init__(self, config: ProviderConfig) -> None:
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    async def chat(self, messages: List[Message], model: str) -> AsyncIterator[str]:
        """调用 OpenAI Chat Completions API，流式返回 token。

        Args:
            messages: 对话历史
            model: 模型名

        Yields:
            每个内容 token 字符串
        """
        try:
            async with self._client.chat.completions.stream(
                model=model,
                messages=self._to_openai_messages(messages),
            ) as stream:
                async for event in stream:
                    if event.type == "content.delta":
                        yield event.delta
        except Exception as e:
            print(f"\n[OpenAI 错误] {e}")

    def _to_openai_messages(self, messages: List[Message]) -> List[dict]:
        """将内部 Message 列表转换为 OpenAI API 格式。"""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]


# ── Factory ───────────────────────────────────────────────────────

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
        return OpenAIProvider(config)
    elif config.protocol == "anthropic":
        return AnthropicProvider(config)
    else:
        raise ValueError(f"未知的 protocol: '{config.protocol}'")


__all__ = [
    "BaseProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "create_provider",
]
