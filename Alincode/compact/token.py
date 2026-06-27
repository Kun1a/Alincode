"""Token 估算：锚定真实 usage + 字符增量（T5）。"""

from __future__ import annotations

import json
import math

from Alincode.compact.const import ESTIMATE_CHARS_PER_TOKEN
from Alincode.conversation import Message, Usage


def usage_anchor(u: Usage) -> int:
    """把 stream 尾事件中的 usage 合并成单一锚点值。

    等价于 input_tokens + output_tokens + cache_read + cache_write。
    """
    return u.input_tokens + u.output_tokens + u.cache_read + u.cache_write


def message_chars(msgs: list[Message]) -> int:
    """计算消息列表的 UTF-8 字节总量。

    累加 content 字节 + tool_calls input 序列化字节 + tool_results content 字节。
    """
    total = 0
    for msg in msgs:
        if msg.content:
            total += len(msg.content.encode("utf-8"))
        for tc in (msg.tool_calls or []):
            # input 是 JSON 字符串，直接算字节
            if isinstance(tc.input, str):
                total += len(tc.input.encode("utf-8"))
            else:
                total += len(json.dumps(tc.input, ensure_ascii=False).encode("utf-8"))
        for tr in (msg.tool_results or []):
            if tr.content:
                total += len(tr.content.encode("utf-8"))
    return total


def estimate_tokens(
    anchor: int,
    all_msgs: list[Message],
    anchor_msg_len: int,
) -> int:
    """锚定最近一次 provider usage + 之后新增消息的字符增量。

    入参：
      - anchor: 上一次主对话路径 stream 真实 usage 之和
      - all_msgs: 当前 conv.messages 完整列表（必须已过 layer1）
      - anchor_msg_len: anchor 被记录时 conv.messages 的长度

    只对 anchor_msg_len 之后的消息做字符增量估算。
    锚点为 0 且 anchor_msg_len 为 0 时退化为纯字符估算。
    """
    start = max(0, min(anchor_msg_len, len(all_msgs)))
    tail = all_msgs[start:]
    chars = message_chars(tail)
    return anchor + math.ceil(chars / ESTIMATE_CHARS_PER_TOKEN)
