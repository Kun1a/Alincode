"""Token 估算单测：锚点 + 字符增量 + usage 合并（T22 子集）。"""

import math

from Alincode.compact.token import estimate_tokens, usage_anchor, message_chars
from Alincode.conversation import Message, Usage


def test_usage_anchor_sum():
    """四个字段相加返回 int。"""
    u = Usage(input_tokens=100, output_tokens=50, cache_read=10, cache_write=5)
    assert usage_anchor(u) == 165


def test_usage_anchor_zero():
    """零 usage 返回 0。"""
    u = Usage()
    assert usage_anchor(u) == 0


def test_message_chars_empty():
    """空列表返回 0。"""
    assert message_chars([]) == 0


def test_message_chars_basic():
    """content 字节累加正确。"""
    msgs = [
        Message(role="user", content="hello"),        # 5 bytes
        Message(role="assistant", content="世界"),     # 6 bytes (2*3)
    ]
    assert message_chars(msgs) == 11


def test_message_chars_with_tool_calls():
    """含 tool_calls input 与 tool_results content。"""
    from Alincode.conversation import ToolCall, ToolResult
    msgs = [
        Message(role="tool",
                tool_calls=[ToolCall(id="1", name="read", input='{"path":"f"}')],
                tool_results=[ToolResult(tool_call_id="1", content="file content")]),
    ]
    # input: 12 bytes ("{\"path\":\"f\"}"), content: 12 bytes ("file content")
    expected = 12 + 12
    assert message_chars(msgs) == expected


def test_estimate_tokens_anchor_zero():
    """anchor=0, anchor_msg_len=0 退化为纯字符估算。"""
    msgs = [Message(role="user", content="abc")]  # 3 bytes
    result = estimate_tokens(0, msgs, 0)
    assert result == math.ceil(3 / 3.5)


def test_estimate_tokens_with_anchor():
    """anchor=1000, anchor_msg_len=1 只算第 2 条消息。"""
    m1 = Message(role="user", content="first")
    m2 = Message(role="assistant", content="second")
    # m2: "second" = 6 bytes, 6/3.5 = 1.71 → ceil=2
    result = estimate_tokens(1000, [m1, m2], 1)
    assert result == 1002


def test_estimate_tokens_anchor_len_beyond():
    """anchor_msg_len 超出列表长度时安全处理。"""
    msgs = [Message(role="user", content="x")]
    result = estimate_tokens(500, msgs, 10)
    assert result == 500


def test_estimate_tokens_large():
    """大值不溢出（Python int）。"""
    msgs = [Message(role="user", content="x" * 1000)]
    result = estimate_tokens(2_000_000_000, msgs, 0)
    assert result > 2_000_000_000
