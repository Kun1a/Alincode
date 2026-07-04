"""邮箱消息类型(T6)。

对应 spec F32 的 mailbox 消息结构与 F34 的消息类型。
Message.from_ 对应 json key "from"(from 是 Python 关键字)。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    """消息类型(F34)。"""

    TEXT = "text"  # 纯文本(必带 5-10 词 summary)
    SHUTDOWN_REQUEST = "shutdown_request"  # 优雅退出协商
    SHUTDOWN_RESPONSE = "shutdown_response"  # 只能发给 Lead
    PLAN_APPROVAL_RESPONSE = "plan_approval_response"  # 只允许 Lead 发送
    IDLE_NOTIFICATION = "idle_notification"  # 队员空闲通知(T45)


@dataclass
class Message:
    """邮箱消息(F32)。

    from_ 对应 json key "from"(Python 关键字避让)。
    timestamp=0 时由 Box.write 自动补 int(time.time())。
    read 默认 False(未读)。
    """

    from_: str
    to: str
    type: MessageType = MessageType.TEXT
    summary: str = ""
    content: str = ""
    payload: dict[str, Any] | None = None
    timestamp: int = 0
    read: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_,
            "to": self.to,
            "type": str(self.type),
            "summary": self.summary,
            "content": self.content,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "read": self.read,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Message":
        t = d.get("type", "text")
        try:
            mtype = MessageType(t)
        except ValueError:
            mtype = MessageType.TEXT
        return cls(
            from_=d.get("from", ""),
            to=d.get("to", ""),
            type=mtype,
            summary=d.get("summary", ""),
            content=d.get("content", ""),
            payload=d.get("payload"),
            timestamp=d.get("timestamp", 0),
            read=d.get("read", False),
        )
