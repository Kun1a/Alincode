# tests/web/test_protocol.py
"""Event→JSON 投影与历史消息投影的纯函数测试。"""

from Alincode.agent import CompactEvent, CompactPhase, Event, Phase, ToolEvent
from Alincode.conversation import Message, ToolCall, ToolResult, Usage
from Alincode.permission import ApprovalRequest, Verdict
from Alincode.web.protocol import project_event, project_messages


def test_text_delta():
    assert project_event(Event(text="你好"), {}) == [
        {"type": "text.delta", "delta": "你好"}
    ]


def test_tool_start_end():
    start = Event(tool=ToolEvent(name="bash", args='{"cmd":"ls"}', phase=Phase.START))
    end = Event(tool=ToolEvent(name="bash", phase=Phase.END, result="ok", is_error=False,
                               duration_ms=125))
    assert project_event(start, {}) == [
        {"type": "tool.start", "name": "bash", "args": '{"cmd":"ls"}'}
    ]
    assert project_event(end, {}) == [
        {"type": "tool.end", "name": "bash", "result": "ok", "is_error": False,
         "duration_ms": 125}
    ]


def test_approval_registers_future_and_is_not_serialized():
    import asyncio

    async def _run():
        fut = asyncio.get_event_loop().create_future()
        req = ApprovalRequest(tool_name="write_file", tool_args='{"path":"x"}',
                              reason="write outside root", verdict=Verdict.ASK, respond=fut)
        registry: dict = {}
        msgs = project_event(Event(approval=req), registry)
        assert len(msgs) == 1
        m = msgs[0]
        assert m["type"] == "approval.request"
        assert m["tool_name"] == "write_file"
        assert "respond" not in str(m)          # Future 绝不进入 JSON
        assert registry[m["request_id"]] is req

    asyncio.run(_run())


def test_err_and_done_project_to_strings():
    ev = Event(err=RuntimeError("boom"), notice="出错", done=True)
    msgs = project_event(ev, {})
    types = [m["type"] for m in msgs]
    assert types == ["turn.error", "notice", "turn.done"]
    assert msgs[0]["message"] == "boom"


def test_usage_iter_compact():
    ev = Event(usage=Usage(input_tokens=10, output_tokens=5, cache_write=1, cache_read=2),
               iter=3,
               compact=CompactEvent(phase=CompactPhase.AFTER_AUTO, before=100, after=40))
    msgs = project_event(ev, {})
    assert {"type": "compact", "phase": "after_auto", "before": 100, "after": 40,
            "error": ""} in msgs
    assert {"type": "usage", "input_tokens": 10, "output_tokens": 5,
            "cache_write": 1, "cache_read": 2} in msgs
    assert {"type": "iter", "value": 3} in msgs


def test_project_messages_pairs_tool_calls_with_results():
    msgs = [
        Message(role="user", content="写个文件"),
        Message(role="assistant", content="",
                tool_calls=[ToolCall(id="t1", name="write_file", input='{"path":"a.txt"}')]),
        Message(role="tool",
                tool_results=[ToolResult(tool_call_id="t1", content="written", is_error=False)]),
        Message(role="assistant", content="完成了"),
    ]
    blocks = project_messages(msgs)
    assert blocks[0] == {"kind": "user", "content": "写个文件"}
    assert blocks[1]["kind"] == "tool"
    assert blocks[1]["state"] == "done"
    assert blocks[1]["result"] == "written"
    assert blocks[2] == {"kind": "assistant", "content": "完成了"}


def test_project_messages_restores_persisted_tool_duration():
    msgs = [
        Message(role="assistant", tool_calls=[ToolCall(id="t1", name="read_file", input="{}")]),
        Message(role="tool", tool_results=[ToolResult(tool_call_id="t1", content="text", duration_ms=125)]),
    ]

    assert project_messages(msgs)[0]["durationMs"] == 125
