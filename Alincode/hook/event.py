"""Hook 生命周期事件枚举（snake_case）。"""

from __future__ import annotations

from enum import Enum


class Event(str, Enum):
    """11 个生命周期事件。值对应 YAML 字面量（snake_case）。"""

    SESSION_START = "session_start"
    SESSION_END = "session_end"
    SESSION_RESUME = "session_resume"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    STOP = "stop"
    PRE_USER_MESSAGE = "pre_user_message"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"
    NOTIFICATION = "notification"


# 拦截类事件
BLOCKING_EVENTS: frozenset[Event] = frozenset({
    Event.PRE_TOOL_USE,
    Event.USER_PROMPT_SUBMIT,
})


def is_blocking(e: Event) -> bool:
    return e in BLOCKING_EVENTS


def parse_event(s: str) -> Event | None:
    """从字符串解析 Event，兼容旧 PascalCase。"""
    # 旧格式兼容映射
    compat = {
        "SessionStart": "session_start",
        "SessionEnd": "session_end",
        "SessionResume": "session_resume",
        "UserPromptSubmit": "user_prompt_submit",
        "Stop": "stop",
        "PreUserMessage": "pre_user_message",
        "PreToolUse": "pre_tool_use",
        "PostToolUse": "post_tool_use",
        "PreCompact": "pre_compact",
        "PostCompact": "post_compact",
        "Notification": "notification",
    }
    s = compat.get(s, s)
    try:
        return Event(s)
    except ValueError:
        return None
