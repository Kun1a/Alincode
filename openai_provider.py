"""OpenAI Provider：封装 openai SDK 的异步流式对话。"""

from typing import AsyncIterator, List

from openai import AsyncOpenAI

from config import ProviderConfig
from provider import BaseProvider, Message


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
