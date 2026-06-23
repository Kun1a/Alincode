"""对话管理模块：Message 数据结构 + ConversationManager 对话状态管理。"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Message:
    """对话消息，兼容 Anthropic 和 OpenAI 两种格式。

    extra 字段为 extended thinking 等扩展能力预留，纯文本对话时为 None。
    """
    role: str                     # "user" | "assistant" | "system"
    content: str                  # 消息正文
    extra: Optional[dict] = None  # 扩展字段（thinking blocks 等）


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
        return len([m for m in self._messages if m.role == "user"])

    def add_user(self, text: str) -> None:
        """追加用户消息。"""
        self._messages.append(Message(role="user", content=text))

    def add_assistant(self, text: str) -> None:
        """追加 AI 回复。"""
        self._messages.append(Message(role="assistant", content=text))

    def add_system(self, text: str) -> None:
        """追加系统消息。"""
        self._messages.append(Message(role="system", content=text))

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
            if msg.role == "user":
                user_count += 1
            if user_count >= max_turns:
                break
        return result


__all__ = ["Message", "ConversationManager"]
