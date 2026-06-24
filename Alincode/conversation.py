"""对话管理模块：数据类型 + 对话状态管理器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

# ── 角色常量 ─────────────────────────────────────────────

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_TOOL = "tool"  # 携带工具执行结果的回合


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
class StreamEvent:
    """流式事件——text 增量 / tool_calls / done / err 四态语义。

    一次 LLM 回复依次产出 0-N 个 text 事件，
    随后可能产出 1 个 tool_calls 事件（非空列表），
    最后 1 个 done 事件。出错时产出 err 事件。
    """
    text: str = ""                        # 文本增量
    tool_calls: list[ToolCall] = field(default_factory=list)  # 非空：模型请求执行这些工具
    done: bool = False
    err: Exception | None = None


# ── 对话消息 ────────────────────────────────────────────

@dataclass
class Message:
    """对话消息，兼容 Anthropic 和 OpenAI 两种格式。

    role: "user" | "assistant" | "system" | "tool"
    tool_calls: assistant 回合可携带的工具调用列表（流式拼接后）
    tool_results: tool 回合携带的工具执行结果列表
    """
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

    def add_tool_results(self, results: list[ToolResult]) -> None:
        """工具结果回合（ROLE_TOOL）。"""
        self._messages.append(Message(
            role=ROLE_TOOL,
            tool_results=list(results),
        ))

    def add_system(self, text: str) -> None:
        """追加系统消息。"""
        self._messages.append(Message(role=ROLE_SYSTEM, content=text))

    def clear(self) -> None:
        """清空对话历史。"""
        self._messages.clear()

    def get_context(self, max_turns: Optional[int] = None) -> List[Message]:
        """获取最近 N 轮对话（用于上下文窗口裁剪）。

        Args:
            max_turns: 最大轮数，为 None 时返回全部。
        """
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
    "StreamEvent",
    "ROLE_USER",
    "ROLE_ASSISTANT",
    "ROLE_SYSTEM",
    "ROLE_TOOL",
]
