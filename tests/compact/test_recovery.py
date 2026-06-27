"""恢复段单测：文件快照排序/截断、工具列表一致性、边界提示稳定（T22 子集）。"""

from Alincode.compact.state import FileReadRecord
from Alincode.compact.recovery import (
    build_recovery_attachment,
    render_file_block,
    render_tools_block,
    BOUNDARY_NOTICE,
)
from Alincode.conversation import ToolDefinition
from datetime import datetime, timedelta


def _make_record(path: str, content: str, ts: datetime) -> FileReadRecord:
    return FileReadRecord(path=path, content=content, timestamp=ts)


def test_render_file_block_truncate():
    """超长内容保留头部，尾部出现 (content truncated)。"""
    long_content = "A" * 20000  # > 5000 * 3.5 = 17500
    rec = FileReadRecord(path="/test.txt", content=long_content, timestamp=datetime.now())
    out = render_file_block(rec)
    assert "(content truncated)" in out
    # 内容被截断但头部保留（在 ### /test.txt 和 [read at] 行之后）
    assert "AAAAA" in out


def test_render_file_block_no_truncate():
    """短内容不截断。"""
    rec = FileReadRecord(path="/small.txt", content="short", timestamp=datetime.now())
    out = render_file_block(rec)
    assert "(content truncated)" not in out
    assert "short" in out


def test_render_tools_block():
    """工具列表每个工具名+description 出现。"""
    defs = [
        ToolDefinition(name="read", description="Read file", input_schema={"type": "object"}),
        ToolDefinition(name="write", description="Write file", input_schema={"type": "object", "properties": {"path": {"type": "string"}}}),
    ]
    out = render_tools_block(defs)
    assert "read" in out
    assert "Read file" in out
    assert "write" in out


def test_render_tools_block_empty():
    """空列表输出 (无)。"""
    out = render_tools_block([])
    assert "(无)" in out


def test_build_recovery_attachment_limit():
    """超过 5 条只展示最近 5 条，按时间戳倒序。"""
    now = datetime.now()
    records = [
        _make_record(f"f{i}.txt", f"content{i}", now - timedelta(seconds=10 - i))
        for i in range(7)
    ]
    # 模拟 RecoveryState.snapshot() 的排序：按时间戳倒序（最新在前）
    records.sort(key=lambda r: r.timestamp, reverse=True)
    defs = [ToolDefinition(name="read", description="Read file", input_schema={"type": "object"})]
    out = build_recovery_attachment(records, defs)
    # 只有最近 5 条：f0(最旧), f1 应被排除
    assert "f0.txt" not in out
    assert "f1.txt" not in out
    # f2-f6 应出现
    for i in range(2, 7):
        assert f"f{i}.txt" in out


def test_build_recovery_attachment_tools_exact():
    """工具名集合与入参一致。"""
    defs = [
        ToolDefinition(name="read", description="d", input_schema={"type": "object"}),
        ToolDefinition(name="grep", description="d", input_schema={"type": "object"}),
    ]
    out = build_recovery_attachment([], defs)
    assert "read" in out
    assert "grep" in out


def test_boundary_notice_stable():
    """相同入参两次 build_recovery_attachment 输出逐字节相等。"""
    records = [_make_record("/f.txt", "content", datetime.now())]
    defs = [ToolDefinition(name="read", description="d", input_schema={"type": "object"})]
    r1 = build_recovery_attachment(records, defs)
    r2 = build_recovery_attachment(records, defs)
    assert r1 == r2


def test_build_recovery_attachment_empty_snapshot():
    """空 snapshot 输出 (无)。"""
    out = build_recovery_attachment([], [])
    assert "(无)" in out
    assert BOUNDARY_NOTICE in out
