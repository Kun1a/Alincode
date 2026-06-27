"""第 1 层单测：单条落盘、聚合、幂等、决策冻结、落盘失败降级（T22 子集）。"""

import os
import time

from Alincode.compact.state import ContentReplacementState, new_session_context
from Alincode.compact.layer1 import offload_and_snip, spill_single, build_preview
from Alincode.conversation import Message, ToolResult


def _make_tool_msg(results: list[tuple[str, str]]) -> Message:
    """辅助：构造一条 tool 消息。"""
    trs = [ToolResult(tool_call_id=tid, content=content) for tid, content in results]
    return Message(role="tool", tool_results=trs)


def test_spill_single_idempotent(tmp_path):
    """连续两次 spill_single，文件 st_mtime_ns 不变。"""
    ctx = new_session_context(str(tmp_path))
    tid = "test_id_1"
    content = "hello world"
    spill_single(ctx, tid, content)
    path = os.path.join(ctx.spill_dir, tid)
    assert os.path.isfile(path)
    mtime1 = os.stat(path).st_mtime_ns
    time.sleep(0.01)
    spill_single(ctx, tid, content)
    mtime2 = os.stat(path).st_mtime_ns
    assert mtime1 == mtime2


def test_offload_single_result(tmp_path):
    """单条 60000 字节 → 被替换；预览体包含四项信息。"""
    content = "x" * 60000
    msgs = [_make_tool_msg([("id_big", content)])]
    state = ContentReplacementState()
    ctx = new_session_context(str(tmp_path))
    out = offload_and_snip(msgs, state, ctx)
    out_content = out[0].tool_results[0].content
    # 已被替换
    assert "[content offloaded]" in out_content
    assert "original size: 60000 bytes" in out_content
    assert "[saved to]" in out_content
    assert "[head preview]" in out_content
    assert "文件读取工具" in out_content
    assert "不要凭头部预览猜测" in out_content
    # 落盘文件存在
    assert os.path.isfile(os.path.join(ctx.spill_dir, "id_big"))


def test_offload_aggregate(tmp_path):
    """3 条 80000 字节工具结果 → 至少 2 条被替换，聚合 ≤ 200000。"""
    content = "y" * 80000
    results = [("a", content), ("b", content), ("c", content)]
    msgs = [_make_tool_msg(results)]
    state = ContentReplacementState()
    ctx = new_session_context(str(tmp_path))
    out = offload_and_snip(msgs, state, ctx)
    trs = out[0].tool_results
    replaced = sum(1 for tr in trs if "[content offloaded]" in tr.content)
    assert replaced >= 2
    # 聚合字节 ≤ 200000
    remaining = sum(
        len(tr.content.encode("utf-8"))
        for tr in trs
        if "[content offloaded]" not in tr.content
    )
    assert remaining <= 200000


def test_offload_decision_freeze(tmp_path):
    """同一 id 跑两次 offload_and_snip，第二次结果逐字节一致。"""
    content = "z" * 60000
    msgs = [_make_tool_msg([("id_freeze", content)])]
    state = ContentReplacementState()
    ctx = new_session_context(str(tmp_path))
    out1 = offload_and_snip(msgs, state, ctx)
    out2 = offload_and_snip(msgs, state, ctx)
    assert out1[0].tool_results[0].content == out2[0].tool_results[0].content


def test_offload_spill_failure_retryable(tmp_path):
    """落盘失败时该条不被替换，账本未标记。"""
    import errno
    content = "x" * 60000
    msgs = [_make_tool_msg([("id_fail", content)])]
    state = ContentReplacementState()
    ctx = new_session_context(str(tmp_path))

    # 把 spill 目录设为不可写：先建目录，再 monkeypatch spill_single 使其抛 OSError
    orig_spill = spill_single

    def _failing_spill(session, tid, c):
        raise OSError(errno.EACCES, "Permission denied")
    import Alincode.compact.layer1 as l1mod
    l1mod.spill_single = _failing_spill
    try:
        out = offload_and_snip(msgs, state, ctx)
        tr_content = out[0].tool_results[0].content
        assert "[content offloaded]" not in tr_content
    finally:
        l1mod.spill_single = orig_spill


def test_preview_stable_across_rounds():
    """同一入参连续两次 build_preview 返回逐字节相等。"""
    p1 = build_preview(1000, "head content", "/tmp/spill/test_id")
    p2 = build_preview(1000, "head content", "/tmp/spill/test_id")
    assert p1 == p2


def test_offload_preserves_non_tool_messages():
    """非 tool 消息原样保留。"""
    msgs = [
        Message(role="user", content="hello"),
        _make_tool_msg([("id", "x" * 100)]),
    ]
    state = ContentReplacementState()
    ctx = new_session_context(".")
    out = offload_and_snip(msgs, state, ctx)
    assert out[0].role == "user"
    assert out[0].content == "hello"
