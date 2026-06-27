"""摘要 Prompt 单测：结构断言 + 对话序列化 + <summary> 解析（T22 子集）。"""

from Alincode.compact.summary_prompt import (
    build_summary_prompt,
    serialize_conversation,
    extract_summary,
)
from Alincode.conversation import Message, ToolCall, ToolResult


def test_build_summary_prompt_shape():
    """返回 1 条 user 消息，包含 9 部分标题 + <analysis>/<summary> 标签。"""
    msgs = [Message(role="user", content="hello")]
    result = build_summary_prompt(msgs)
    assert len(result) == 1
    assert result[0].role == "user"
    content = result[0].content
    assert "<analysis>" in content
    assert "</analysis>" in content
    assert "<summary>" in content
    assert "</summary>" in content
    assert "不要调用任何工具" in content
    # 9 部分标题逐个检查
    for title in [
        "主要请求和意图",
        "关键技术概念",
        "文件和代码段",
        "错误和修复",
        "问题解决过程",
        "所有用户消息原文",
        "待办任务",
        "当前工作",
        "可能的下一步",
    ]:
        assert title in content


def test_serialize_conversation_deterministic():
    """相同 msgs 两次序列化返回逐字节相等。"""
    msgs = [
        Message(role="user", content="hello"),
        Message(
            role="assistant",
            content="response",
            tool_calls=[ToolCall(id="1", name="read", input='{"path":"f"}')],
        ),
        Message(
            role="tool",
            tool_results=[ToolResult(tool_call_id="1", content="file content", is_error=False)],
        ),
    ]
    s1 = serialize_conversation(msgs)
    s2 = serialize_conversation(msgs)
    assert s1 == s2
    assert "user: hello" in s1
    assert "[call read id=1" in s1
    assert "[result id=1" in s1


def test_extract_summary_standard():
    """标准场景：取 <summary> 正文。"""
    raw = "前言<summary>这是摘要内容</summary>后语"
    assert extract_summary(raw) == "这是摘要内容"


def test_extract_summary_missing():
    """缺失标签时返回原文。"""
    raw = "没有标签的纯文本"
    result = extract_summary(raw)
    assert result == "没有标签的纯文本"


def test_extract_summary_nested():
    """多个 <summary> 时取最后一个。"""
    raw = "<summary>旧</summary>中间<summary>新</summary>尾"
    assert extract_summary(raw) == "新"


def test_extract_summary_unclosed():
    """只有开标签无闭标签时取尾部。"""
    raw = "开头<summary>没有闭标签"
    result = extract_summary(raw)
    assert "没有闭标签" in result
