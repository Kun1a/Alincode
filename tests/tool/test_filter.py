"""工具过滤测试（T9）。"""

from Alincode.tool.filter import apply_agent_tool_filter, FilterParams


def test_default_removes_agent():
    result = apply_agent_tool_filter(FilterParams(
        all_tools=["read_file", "write_file", "bash", "Agent"],
    ))
    assert "Agent" not in result
    assert "read_file" in result
    assert "bash" in result


def test_background_intersection():
    result = apply_agent_tool_filter(FilterParams(
        all_tools=["read_file", "write_file", "edit_file", "Agent", "TaskList", "bash", "mcp__test"],
        background=True,
    ))
    assert "read_file" in result
    assert "bash" in result
    assert "mcp__test" in result
    assert "Agent" not in result
    assert "TaskList" not in result


def test_disallowed_removes():
    result = apply_agent_tool_filter(FilterParams(
        all_tools=["read_file", "write_file", "grep"],
        disallowed=["write_file"],
    ))
    assert "read_file" in result
    assert "write_file" not in result


def test_allowed_narrows():
    result = apply_agent_tool_filter(FilterParams(
        all_tools=["read_file", "write_file", "grep", "bash"],
        allowed=["read_file", "grep"],
    ))
    assert result == ["read_file", "grep"]


def test_allowed_plus_disallowed():
    result = apply_agent_tool_filter(FilterParams(
        all_tools=["read_file", "write_file", "grep", "bash"],
        allowed=["read_file", "grep", "write_file"],
        disallowed=["write_file"],
    ))
    assert "read_file" in result
    assert "grep" in result
    assert "write_file" not in result
