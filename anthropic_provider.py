"""Anthropic Provider：封装 anthropic SDK 的异步流式对话，支持 extended thinking。"""

from typing import AsyncIterator, List

from anthropic import AsyncAnthropic

from config import ProviderConfig
from provider import BaseProvider, Message


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
                        # 切换出 thinking 块时关闭标记
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

                # 流结束时确保关闭
                if in_thinking:
                    yield "[/THINKING]"

        except Exception as e:
            print(f"\n[Anthropic 错误] {e}")

    def _to_anthropic_messages(self, messages: List[Message]) -> List[dict]:
        """将内部 Message 列表转换为 Anthropic API 格式。

        提取 system 消息单独处理（Anthropic 用顶级 system 参数），
        其余按 user/assistant 转换。
        """
        result = []
        for msg in messages:
            if msg.role == "system":
                # system 消息将作为 stream() 的 system 参数传递
                continue
            result.append({"role": msg.role, "content": msg.content})
        return result

    def _extract_system_prompt(self, messages: List[Message]) -> str:
        """提取 system 角色的消息内容作为 system prompt。"""
        parts = [msg.content for msg in messages if msg.role == "system"]
        return "\n".join(parts) if parts else ""
