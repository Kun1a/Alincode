"""会话恢复：从 JSONL 加载消息列表（T6）。"""

from __future__ import annotations

import json
import logging
import os

from Alincode.conversation import Message, ToolCall, ToolResult

logger = logging.getLogger(__name__)


def load_session(session_dir: str) -> list[Message]:
    """从 conversation.jsonl 恢复消息列表。

    - 从最后一个 compact 标记之后开始加载
    - 跳过 JSON 解析失败的坏行
    - 截断孤立工具调用
    """
    jsonl = os.path.join(session_dir, "conversation.jsonl")
    if not os.path.isfile(jsonl):
        return []

    all_lines: list[dict] = []
    with open(jsonl, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("session load: skipping bad line in %s", jsonl)
                continue
            all_lines.append(data)

    # 从最后 compact 标记之后开始
    last_compact = -1
    for i, d in enumerate(all_lines):
        if d.get("type") == "compact":
            last_compact = i

    lines = all_lines[last_compact + 1:] if last_compact >= 0 else all_lines

    msgs = _lines_to_messages(lines)
    return _truncate_orphaned_tool_calls(msgs)


def _lines_to_messages(lines: list[dict]) -> list[Message]:
    """JSONL 记录 → Message 列表。"""
    msgs: list[Message] = []
    for d in lines:
        role = d.get("role", "")
        content = d.get("content", "")
        tcs = d.get("tool_calls")
        trs = d.get("tool_results")

        tool_calls = None
        if isinstance(tcs, list):
            tool_calls = [
                ToolCall(id=tc.get("id", ""), name=tc.get("name", ""),
                         input=tc.get("input", "{}"))
                for tc in tcs
            ]

        tool_results = None
        if isinstance(trs, list):
            tool_results = [
                ToolResult(
                    tool_call_id=tr.get("tool_call_id", ""),
                    content=tr.get("content", ""),
                    is_error=tr.get("is_error", False),
                )
                for tr in trs
            ]

        msgs.append(Message(
            role=role,
            content=content,
            tool_calls=tool_calls or [],
            tool_results=tool_results or [],
        ))
    return msgs


def _truncate_orphaned_tool_calls(msgs: list[Message]) -> list[Message]:
    """如果最后一条是 assistant 且有 tool_calls，截断掉。"""
    if not msgs:
        return msgs
    last = msgs[-1]
    if last.role == "assistant" and last.tool_calls:
        return msgs[:-1]
    return msgs
