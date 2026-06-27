"""Client 模块：LLM Provider 抽象层、请求结构、缓存感知用量。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
    Usage,
    ROLE_USER,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_SYSTEM,
)


# ── 哨兵异常 ──────────────────────────────────────

class PromptTooLongError(Exception):
    """Provider 上报上下文超出窗口时统一抛出的哨兵异常。"""


# ── 请求结构 ──────────────────────────────────────

@dataclass
class System:
    """系统提示分为稳定块（可缓存）和环境块（动态）。"""
    stable: str = ""       # 模块化系统提示，可缓存（N1）
    environment: str = ""  # 环境信息，不缓存（F2）


@dataclass
class Request:
    """一次 LLM 请求的完整入参（替代分散传参）。"""
    system: System = field(default_factory=System)
    messages: list[Message] = field(default_factory=list)
    model: str = ""
    tools: list[ToolDefinition] = field(default_factory=list)
    reminder: str = ""  # 本轮补充消息（plan mode reminder 等）


# ── Provider 接口 ─────────────────────────────────────

class BaseProvider(ABC):
    """LLM Provider 抽象基类。"""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 标识名，如 "anthropic"、"openai"。"""
        ...

    @abstractmethod
    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        """流式请求 LLM，返回 StreamEvent 序列。"""
        ...


# ── Anthropic provider ────────────────────────────────────────────

THINKING_CONFIG = {
    "type": "enabled",
    "budget_tokens": 4000,
}


class AnthropicProvider(BaseProvider):
    """Anthropic 协议实现——双 system 块 + 缓存断点 + reminder 并入用户消息。"""

    def __init__(self, config: ProviderConfig) -> None:
        self._client = AsyncAnthropic(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        """调用 Anthropic Messages API。

        system 通过双文本块发送：稳定块 + 环境块。
        稳定块末尾标 cache_control（N1），环境块不标。
        """
        # 构建 system 参数（双文本块）
        system_blocks = []
        if req.system.stable:
            system_blocks.append({
                "type": "text",
                "text": req.system.stable,
                "cache_control": {"type": "ephemeral"},
            })
        if req.system.environment:
            system_blocks.append({
                "type": "text",
                "text": req.system.environment,
            })

        # 构建消息列表，reminder 并入末条 user 消息
        messages = _to_anthropic_messages(req.messages, req.reminder)

        params: dict[str, Any] = {
            "model": req.model,
            "max_tokens": 8192,
            "messages": messages,
        }
        if system_blocks:
            params["system"] = system_blocks
        if req.tools:
            params["tools"] = _to_anthropic_tools(req.tools)
        if not _has_tool_history(req.messages):
            params["thinking"] = THINKING_CONFIG

        try:
            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield StreamEvent(text=delta.text)

                final_message = await stream.get_final_message()

                # 缓存用量
                usage_ = _extract_anthropic_usage(final_message)
                if usage_:
                    yield StreamEvent(usage=usage_)

                if final_message.stop_reason == "tool_use":
                    calls = []
                    for block in final_message.content:
                        if block.type == "tool_use":
                            calls.append(ToolCall(
                                id=block.id, name=block.name,
                                input=_safe_json_dumps(block.input),
                            ))
                    if calls:
                        yield StreamEvent(tool_calls=calls)

                yield StreamEvent(done=True)

        except Exception as e:
            err = _wrap_anthropic_ptl(e)
            yield StreamEvent(err=err)
            yield StreamEvent(done=True)


class OpenAIProvider(BaseProvider):
    """OpenAI 协议实现——单条 system（stable+env），reminder 尾部追加。"""

    def __init__(self, config: ProviderConfig) -> None:
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        """调用 OpenAI Chat Completions API。"""
        openai_msgs = _to_openai_messages(req)

        params: dict[str, Any] = {
            "model": req.model,
            "messages": openai_msgs,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if req.tools:
            params["tools"] = _to_openai_tools(req.tools)

        try:
            tool_calls_buf: dict[int, dict[str, str]] = {}
            async for chunk in await self._client.chat.completions.create(**params):
                delta = chunk.choices[0].delta if chunk.choices else None

                if hasattr(chunk, "usage") and chunk.usage:
                    yield StreamEvent(usage=_extract_openai_usage(chunk.usage))

                if delta is None:
                    continue
                if delta.content:
                    yield StreamEvent(text=delta.content)
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

            if tool_calls_buf:
                calls = []
                for idx in sorted(tool_calls_buf.keys()):
                    v = tool_calls_buf[idx]
                    calls.append(ToolCall(
                        id=v.get("id", ""), name=v.get("name", ""),
                        input=v.get("args", "") or "{}",
                    ))
                yield StreamEvent(tool_calls=calls)

            yield StreamEvent(done=True)

        except Exception as e:
            err = _wrap_openai_ptl(e)
            yield StreamEvent(err=err)
            yield StreamEvent(done=True)


# ── PTL 错误包装 ──────────────────────────────────────

def _wrap_anthropic_ptl(orig: Exception) -> Exception:
    """若是 Anthropic prompt_too_long 错误则包装为 PromptTooLongError。"""
    cls = type(orig).__name__
    msg = str(orig).lower()
    if "bad_request" in cls.lower() or "badrequest" in cls.lower():
        if "prompt is too long" in msg or "context_length" in msg:
            wrapped = PromptTooLongError("anthropic prompt too long")
            wrapped.__cause__ = orig
            return wrapped
    return orig


def _wrap_openai_ptl(orig: Exception) -> Exception:
    """若是 OpenAI context_length_exceeded 错误则包装为 PromptTooLongError。"""
    cls = type(orig).__name__
    msg = str(orig).lower()
    if "bad_request" in cls.lower() or "badrequest" in cls.lower():
        if "context_length_exceeded" in msg:
            wrapped = PromptTooLongError("openai context too long")
            wrapped.__cause__ = orig
            return wrapped
    return orig


# ── 辅助函数 ──────────────────────────────────────────

def _to_anthropic_tools(tools: List[ToolDefinition]) -> List[dict]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def _to_openai_tools(tools: List[ToolDefinition]) -> List[dict]:
    return [
        {"type": "function", "function": {
            "name": t.name, "description": t.description,
            "parameters": t.input_schema,
        }}
        for t in tools
    ]


def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"


def _has_tool_history(messages: List[Message]) -> bool:
    for msg in messages:
        if msg.role == ROLE_TOOL:
            return True
        if msg.role == ROLE_ASSISTANT and msg.tool_calls:
            return True
    return False


def _extract_anthropic_usage(final_message) -> Usage | None:
    try:
        u = final_message.usage
        return Usage(
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
        )
    except Exception:
        return None


def _extract_openai_usage(u) -> Usage:
    details = getattr(u, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details else 0
    return Usage(
        input_tokens=getattr(u, "prompt_tokens", 0) or 0,
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
        cache_read=cached or 0,
    )


def _to_anthropic_messages(messages: List[Message], reminder: str = "") -> List[dict]:
    """转换为 Anthropic 格式，reminder 织入末条 user 消息的 content 块。"""
    result = []
    for msg in messages:
        if msg.role == ROLE_SYSTEM:
            continue
        elif msg.role == ROLE_USER:
            result.append({"role": "user", "content": msg.content or ""})
        elif msg.role == ROLE_ASSISTANT:
            if msg.tool_calls:
                blocks: list[dict] = []
                if msg.content:
                    blocks.append({"type": "text", "text": msg.content})
                for c in msg.tool_calls:
                    blocks.append({
                        "type": "tool_use", "id": c.id, "name": c.name,
                        "input": json.loads(c.input),
                    })
                result.append({"role": "assistant", "content": blocks})
            else:
                result.append({"role": "assistant", "content": msg.content or ""})
        elif msg.role == ROLE_TOOL:
            blocks = []
            for r in (msg.tool_results or []):
                blocks.append({
                    "type": "tool_result", "tool_use_id": r.tool_call_id,
                    "content": r.content, "is_error": r.is_error,
                })
            result.append({"role": "user", "content": blocks})

    # reminder 织入末条 user 消息
    if reminder and result:
        last = result[-1]
        if last["role"] == "user":
            content = last["content"]
            if isinstance(content, str):
                result[-1]["content"] = [{"type": "text", "text": content}]
                content = result[-1]["content"]
            content.append({"type": "text", "text": reminder})
        else:
            result.append({"role": "user", "content": [{"type": "text", "text": reminder}]})

    return result


def _to_openai_messages(req: Request) -> List[dict]:
    """转换为 OpenAI 格式——单条 system（stable+env），reminder 尾部 user。"""
    result = []

    # 单条 system：stable 在前，env 在后
    sys_content = req.system.stable
    if req.system.environment:
        sys_content = (sys_content + "\n\n" + req.system.environment).strip()
    if sys_content:
        result.append({"role": "system", "content": sys_content})

    for msg in req.messages:
        if msg.role == ROLE_USER:
            result.append({"role": "user", "content": msg.content or ""})
        elif msg.role == ROLE_ASSISTANT:
            entry: dict = {"role": "assistant", "content": msg.content or None}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {"id": c.id, "type": "function", "function": {
                        "name": c.name, "arguments": c.input or "{}",
                    }} for c in msg.tool_calls
                ]
            result.append(entry)
        elif msg.role == ROLE_SYSTEM:
            pass  # 已用 req.system 替代
        elif msg.role == ROLE_TOOL:
            for r in (msg.tool_results or []):
                result.append({
                    "role": "tool", "tool_call_id": r.tool_call_id,
                    "content": r.content,
                })

    # reminder 作为尾部 user 消息追加
    if req.reminder:
        result.append({"role": "user", "content": req.reminder})

    return result


# ── Factory ───────────────────────────────────────────────────────

def create_provider(config: ProviderConfig) -> BaseProvider:
    if config.protocol == "openai":
        return OpenAIProvider(config)
    elif config.protocol == "anthropic":
        return AnthropicProvider(config)
    else:
        raise ValueError(f"未知的 protocol: '{config.protocol}'")


__all__ = [
    "BaseProvider", "AnthropicProvider", "OpenAIProvider", "create_provider",
    "Request", "System",
]
