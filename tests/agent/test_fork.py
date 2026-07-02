"""Fork 辅助测试（T13）。"""

from Alincode.fork import build_forked_messages, is_fork_context, FORK_BOILERPLATE_TAG
from Alincode.conversation import Message, ToolResult


def test_build_forked_empty():
    msgs = build_forked_messages([], "do something")
    assert len(msgs) == 1
    assert FORK_BOILERPLATE_TAG in msgs[0].content
    assert "do something" in msgs[0].content


def test_is_fork_context_true():
    msgs = [Message(role="user", content=f"{FORK_BOILERPLATE_TAG} do x")]
    assert is_fork_context(msgs) is True


def test_is_fork_context_false():
    msgs = [Message(role="user", content="normal message")]
    assert is_fork_context(msgs) is False


def test_build_forked_preserves_parent():
    parent = [Message(role="user", content="hello")]
    msgs = build_forked_messages(parent, "do task")
    assert len(msgs) == 2
    assert msgs[0].content == "hello"
    assert FORK_BOILERPLATE_TAG in msgs[1].content


def test_build_forked_unpaired_tool_calls():
    """末条 assistant 有未配对的 tool_call，应生成 placeholder。"""
    from Alincode.conversation import Message as M, ToolCall as TC
    parent = [
        M(role="assistant", content="", tool_calls=[
            TC(id="tc1", name="read_file", input='{"path":"x"}'),
            TC(id="tc2", name="bash", input='{}'),
        ]),
        M(role="tool", tool_results=[
            ToolResult(tool_call_id="tc1", content="file content"),
        ]),
    ]
    msgs = build_forked_messages(parent, "task")
    # 应该有: assistant, original tool result, placeholder tool, user
    assert len(msgs) == 4
    # 第三条是 placeholder tool 消息
    tool_msg = msgs[2]
    assert tool_msg.role == "tool"
    assert any(tr.content == "[forked, skipped]" for tr in tool_msg.tool_results)
