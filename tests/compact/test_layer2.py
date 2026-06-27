"""第 2 层单测：近期原文边界、配对修正、分组（T22 子集）。"""

from Alincode.compact.layer2 import pick_recent_tail, group_by_user_turn, _join_after_summary
from Alincode.conversation import Message


def _make_msgs(*roles):
    """辅助：按 role 序列构造消息列表。"""
    msgs = []
    for r in roles:
        msgs.append(Message(role=r, content=f"{r} message"))
    return msgs


def test_group_by_user_turn():
    """标准分组：每遇 user 开新组。"""
    msgs = _make_msgs("user", "assistant", "tool", "user", "assistant")
    groups = group_by_user_turn(msgs)
    assert len(groups) == 2
    assert len(groups[0]) == 3
    assert len(groups[1]) == 2


def test_group_by_user_turn_starts_non_user():
    """第一条非 user → 塞进第 0 组。"""
    msgs = _make_msgs("system", "user", "assistant")
    groups = group_by_user_turn(msgs)
    assert len(groups) == 2
    assert groups[0][0].role == "system"


def test_pick_recent_tail_empty():
    """空列表返回 []。"""
    assert pick_recent_tail([]) == []


def test_pick_recent_tail_short():
    """短对话原样返回。"""
    msgs = _make_msgs("user", "assistant")
    result = pick_recent_tail(msgs)
    assert len(result) == len(msgs)


def test_join_after_summary_no_consecutive_user():
    """recent 首条是 user → 插入 assistant 衔接占位。"""
    s_msg = Message(role="user", content="summary")
    recent = [Message(role="user", content="hello")]
    result = _join_after_summary(s_msg, recent)
    assert result[0].role == "user"  # summary
    assert result[1].role == "assistant"  # 衔接占位
    assert "已加载上下文摘要" in result[1].content
    assert result[2].role == "user"


def test_join_after_summary_recent_starts_assistant():
    """recent 首条是 assistant → 正常拼接无占位。"""
    s_msg = Message(role="user", content="summary")
    recent = [Message(role="assistant", content="response")]
    result = _join_after_summary(s_msg, recent)
    assert len(result) == 2
    assert result[0].role == "user"
    assert result[1].role == "assistant"


def test_join_after_summary_drops_leading_tool():
    """recent 首条是 tool → 防御性丢弃。"""
    s_msg = Message(role="user", content="summary")
    recent = [
        Message(role="tool", content="tool result"),
        Message(role="assistant", content="response"),
    ]
    result = _join_after_summary(s_msg, recent)
    assert result[0].role == "user"
    assert result[1].role == "assistant"


def test_join_after_summary_empty_recent():
    """空 recent → 只返回 summary。"""
    s_msg = Message(role="user", content="summary")
    result = _join_after_summary(s_msg, [])
    assert len(result) == 1
    assert result[0].role == "user"
