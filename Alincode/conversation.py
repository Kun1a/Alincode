"""对话管理模块：数据类型 + 对话状态管理器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

# ── 角色常量 ─────────────────────────────────────────────

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_TOOL = "tool"  # 携带工具执行结果的回合


# ── 停止 / 提示常量 ────────────────────────────────────────

NOTICE_MAX_ITER = "已达到最大迭代轮数，本轮停止。"
NOTICE_UNKNOWN_TOOLS = "连续请求未知工具，本轮停止。"
NOTICE_CANCELLED = "本轮已被取消。"
NOTICE_PROVIDER_ERROR = "LLM 请求出错，本轮停止。"


# ── 工具相关类型 ──────────────────────────────────────────

@dataclass
class ToolCall:
    """协议无关地承载模型发起的一次工具调用（流式拼接完成后）。"""
    id: str            # provider 侧调用 id；回灌结果时配对
    name: str          # 工具名（注册中心按名查找）
    input: str         # 拼接完成的 JSON 参数字符串（raw JSON）


@dataclass
class ToolResult:
    """协议无关地承载一次工具执行结果。"""
    tool_call_id: str  # 对应 ToolCall.id
    content: str       # 执行产出（成功内容或结构化错误文本）
    is_error: bool = False  # 是否为错误结果


@dataclass
class ToolDefinition:
    """注册中心导出的协议无关工具定义。"""
    name: str
    description: str
    input_schema: dict[str, Any]  # 完整 JSON Schema：type/properties/required


@dataclass
class Usage:
    """单次 LLM 请求的 token 用量。"""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamEvent:
    """流式事件——text / tool_calls / usage / done / err 多态语义。"""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None  # 本轮 token 用量（流结束后上抛一次）
    done: bool = False
    err: Exception | None = None


# ── 对话消息 ────────────────────────────────────────────

@dataclass
class Message:
    """对话消息，兼容 Anthropic 和 OpenAI 两种格式。"""
    role: Literal["user", "assistant", "system", "tool"] = "user"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


# ── 对话管理器 ──────────────────────────────────────────

class ConversationManager:
    """对话状态管理器：维护消息历史、上下文窗口、轮次统计。"""

    def __init__(self) -> None:
        self._messages: List[Message] = []

    @property
    def messages(self) -> List[Message]:
        """返回完整对话历史（只读副本）。"""
        return list(self._messages)

    @property
    def turn_count(self) -> int:
        """返回 user 消息轮数。"""
        return len([m for m in self._messages if m.role == ROLE_USER])

    @property
    def last_role(self) -> str:
        """返回最后一条消息的角色，无消息时返回空字符串。"""
        if not self._messages:
            return ""
        return self._messages[-1].role

    def add_user(self, text: str) -> None:
        """追加用户消息。"""
        self._messages.append(Message(role=ROLE_USER, content=text))

    def add_assistant(self, text: str) -> None:
        """追加 AI 回复。"""
        self._messages.append(Message(role=ROLE_ASSISTANT, content=text))

    def add_assistant_with_tool_calls(self, text: str, calls: list[ToolCall]) -> None:
        """assistant 工具调用回合——preamble 文本 + 工具调用列表。"""
        self._messages.append(Message(
            role=ROLE_ASSISTANT,
            content=text,
            tool_calls=list(calls),
        ))

    def add_tool_results(self, calls: list[ToolCall], results: list[ToolResult]) -> None:
        """工具结果回合——同时存储 tool_calls 和 results，保证历史完整性。

        Args:
            calls: 本轮的原始工具调用列表（用于 assistant 端配对）
            results: 执行结果列表（一一对应 calls）
        """
        self._messages.append(Message(
            role=ROLE_TOOL,
            tool_calls=list(calls),
            tool_results=list(results),
        ))

    def ensure_assistant_tail(self, text: str = "") -> None:
        """确保历史以 assistant 消息结尾，必要时补一条。

        取消 / 出错 / 上限停止后调用，防止下一轮请求因角色不对齐被 API 拒（400）。

        规则：
        - 最后是 user → 加 assistant(text)
        - 最后是 assistant 有 tool_calls 但后面无 tool_result → 补齐
        - 最后是 assistant 无 tool_calls → 不动
        - 最后是 tool → 已是合法状态，不动
        """
        if not self._messages:
            self._messages.append(Message(role=ROLE_ASSISTANT, content=text))
            return

        last = self._messages[-1]
        if last.role == ROLE_USER:
            self._messages.append(Message(role=ROLE_ASSISTANT, content=text))
        elif last.role == ROLE_ASSISTANT and last.tool_calls:
            # 有悬空 tool_use 无 tool_result——补齐空结果
            empty_results = [
                ToolResult(tool_call_id=c.id, content=NOTICE_CANCELLED, is_error=True)
                for c in last.tool_calls
            ]
            self._messages.append(Message(
                role=ROLE_TOOL,
                tool_calls=list(last.tool_calls),
                tool_results=empty_results,
            ))
            if text:
                self._messages.append(Message(role=ROLE_ASSISTANT, content=text))

    def add_system(self, text: str) -> None:
        """追加系统消息。"""
        self._messages.append(Message(role=ROLE_SYSTEM, content=text))

    def clear(self) -> None:
        """清空对话历史。"""
        self._messages.clear()

    def get_context(self, max_turns: Optional[int] = None) -> List[Message]:
        """获取最近 N 轮对话（用于上下文窗口裁剪）。"""
        if max_turns is None:
            return list(self._messages)

        result = []
        user_count = 0
        for msg in reversed(self._messages):
            result.insert(0, msg)
            if msg.role == ROLE_USER:
                user_count += 1
            if user_count >= max_turns:
                break
        return result


__all__ = [
    "Message",
    "ConversationManager",
    "ToolCall",
    "ToolResult",
    "ToolDefinition",
    "Usage",
    "StreamEvent",
    "ROLE_USER",
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "ROLE_TOOL",
    "NOTICE_MAX_ITER",
    "NOTICE_UNKNOWN_TOOLS",
    "NOTICE_CANCELLED",
    "NOTICE_PROVIDER_ERROR",
]
