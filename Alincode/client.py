"""Client 模块：LLM Provider 抽象层与具体实现（Anthropic / OpenAI）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, List
import json

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from Alincode.config import ProviderConfig
from Alincode.conversation import (
    Message,
    StreamEvent,
    ToolCall,
    ToolDefinition,
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_SYSTEM,
)


# ── Provider 接口 ─────────────────────────────────────

class BaseProvider(ABC):
    """LLM Provider 抽象基类。"""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 标识名，如 "anthropic"、"openai"。"""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: List[Message],
        model: str,
        tools: List[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        """发送对话历史给 LLM，异步流式返回 StreamEvent。

        Args:
            messages: 完整对话历史（含本次 user 消息）
            model: 模型名
            tools: 工具定义列表（空列表表示不带工具）
        """
        ...


# ── Anthropic provider ────────────────────────────────────────────

THINKING_CONFIG = {
    "type": "enabled",
    "budget_tokens": 4000,
}


class AnthropicProvider(BaseProvider):
    """Anthropic 协议实现，支持工具调用与 extended thinking。"""

    def __init__(self, config: ProviderConfig) -> None:
        self._client = AsyncAnthropic(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def stream(
        self,
        messages: List[Message],
        model: str,
        tools: List[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        """调用 Anthropic Messages API，流式返回 StreamEvent。"""
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": 8192,
            "system": _extract_system_prompt(messages),
            "messages": _to_anthropic_messages(messages),
        }

        # 注入工具定义
        if tools:
            params["tools"] = _to_anthropic_tools(tools)

        # 含工具历史的请求关闭 thinking（避免 400）
        if not _has_tool_history(messages):
            params["thinking"] = THINKING_CONFIG

        try:
            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield StreamEvent(text=delta.text)
                        # thinking_delta / input_json_delta 跳过
                        # （SDK 内部累加器保留完整 input JSON）

                # 流结束后取汇总，检查是否有 tool_use
                final_message = await stream.get_final_message()
                if final_message.stop_reason == "tool_use":
                    calls = []
                    for block in final_message.content:
                        if block.type == "tool_use":
                            calls.append(ToolCall(
                                id=block.id,
                                name=block.name,
                                input=_safe_json_dumps(block.input),
                            ))
                    if calls:
                        yield StreamEvent(tool_calls=calls)

                yield StreamEvent(done=True)

        except Exception as e:
            yield StreamEvent(err=e)
            yield StreamEvent(done=True)


class OpenAIProvider(BaseProvider):
    """OpenAI 协议实现，支持工具调用。"""

    def __init__(self, config: ProviderConfig) -> None:
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    async def stream(
        self,
        messages: List[Message],
        model: str,
        tools: List[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        """调用 OpenAI Chat Completions API，流式返回 StreamEvent。"""
        params: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(messages),
            "stream": True,
        }

        # 注入工具定义
        if tools:
            params["tools"] = _to_openai_tools(tools)

        try:
            tool_calls_buf: dict[int, dict[str, str]] = {}
            async for chunk in await self._client.chat.completions.create(**params):
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # 正文增量
                if delta.content:
                    yield StreamEvent(text=delta.content)

                # 工具调用增量
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_buf:
                            tool_calls_buf[idx] = {"id": "", "name": "", "args": ""}
                        if tc.id:
                            tool_calls_buf[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_buf[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_buf[idx]["args"] += tc.function.arguments

            # 流结束后组装 tool_calls
            if tool_calls_buf:
                calls = []
                for idx in sorted(tool_calls_buf.keys()):
                    v = tool_calls_buf[idx]
                    args = v.get("args", "") or "{}"
                    calls.append(ToolCall(
                        id=v.get("id", ""),
                        name=v.get("name", ""),
                        input=args,
                    ))
                yield StreamEvent(tool_calls=calls)

            yield StreamEvent(done=True)

        except Exception as e:
            yield StreamEvent(err=e)
            yield StreamEvent(done=True)


# ── 工具辅助函数 ──────────────────────────────────────────

def _to_anthropic_tools(tools: List[ToolDefinition]) -> List[dict]:
    """将 ToolDefinition 列表转为 Anthropic 工具格式。"""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


def _to_openai_tools(tools: List[ToolDefinition]) -> List[dict]:
    """将 ToolDefinition 列表转为 OpenAI 工具格式。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _safe_json_dumps(obj: Any) -> str:
    """安全序列化为 JSON 字符串，失败时返回空对象字符串。"""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"


def _extract_system_prompt(messages: List[Message]) -> str:
    """提取 system 角色的消息内容作为 system prompt。"""
    parts = [msg.content for msg in messages if msg.role == ROLE_SYSTEM]
    return "\n".join(parts) if parts else ""


def _has_tool_history(messages: List[Message]) -> bool:
    """检查消息历史中是否包含工具交互——有则对续答请求关闭 thinking。"""
    for msg in messages:
        if msg.role == ROLE_TOOL:
            return True
        if msg.role == ROLE_ASSISTANT and msg.tool_calls:
            return True
    return False


def _to_anthropic_messages(messages: List[Message]) -> List[dict]:
    """将内部 Message 列表转换为 Anthropic API 格式。"""
    result = []
    for msg in messages:
        if msg.role == ROLE_SYSTEM:
            continue
        elif msg.role == ROLE_USER:
            result.append({"role": "user", "content": msg.content or ""})
        elif msg.role == ROLE_ASSISTANT:
            if msg.tool_calls:
                content_blocks: list[dict[str, Any]] = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for c in msg.tool_calls:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": c.id,
                        "name": c.name,
                        "input": json.loads(c.input),
                    })
                result.append({"role": "assistant", "content": content_blocks})
            else:
                result.append({"role": "assistant", "content": msg.content or ""})
        elif msg.role == ROLE_TOOL:
            tool_result_blocks = []
            for r in (msg.tool_results or []):
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": r.tool_call_id,
                    "content": r.content,
                    "is_error": r.is_error,
                })
            result.append({"role": "user", "content": tool_result_blocks})
    return result


def _to_openai_messages(messages: List[Message]) -> List[dict]:
    """将内部 Message 列表转换为 OpenAI API 格式。"""
    result = []
    for msg in messages:
        if msg.role == ROLE_USER:
            result.append({"role": "user", "content": msg.content or ""})
        elif msg.role == ROLE_ASSISTANT:
            entry: dict[str, Any] = {"role": "assistant", "content": msg.content or None}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": c.input or "{}",
                        },
                    }
                    for c in msg.tool_calls
                ]
            result.append(entry)
        elif msg.role == ROLE_SYSTEM:
            result.append({"role": "system", "content": msg.content or ""})
        elif msg.role == ROLE_TOOL:
            for r in (msg.tool_results or []):
                result.append({
                    "role": "tool",
                    "tool_call_id": r.tool_call_id,
                    "content": r.content,
                })
    return result


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
