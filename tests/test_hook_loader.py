"""Hook Loader 测试（新格式：snake_case + 字符串条件表达式 + reject）。"""

import pytest

from Alincode.hook.loader import load_from_dict, _parse_duration
from Alincode.hook.event import Event


# ── _parse_duration ────────────────────────────────────

@pytest.mark.parametrize("s, expected", [
    ("30s", 30), ("5m", 300), ("1h", 3600), ("10", 10),
    ("1.5s", 1.5), (30, 30), (30.0, 30.0),
], ids=["30s", "5m", "1h", "bare", "float-s", "int", "float"])
def test_parse_duration_valid(s, expected):
    assert _parse_duration(s) == expected


def test_parse_duration_invalid():
    assert _parse_duration("abc") is None
    assert _parse_duration("") is None
    assert _parse_duration(None) is None


# ── 合法加载 ───────────────────────────────────────────

def test_load_valid():
    engine = load_from_dict([
        {
            "id": "first",
            "event": "session_start",
            "action": {"type": "prompt", "text": "hello"},
        },
        {
            "id": "second",
            "event": "stop",
            "action": {"type": "command", "command": "echo done"},
        },
    ])
    assert len(engine.rules) == 2
    assert engine.rules[0].id == "first"
    assert engine.rules[0].event == Event.SESSION_START
    assert engine.rules[1].id == "second"
    assert engine.rules[1].event == Event.STOP


# ── reject 字段 ────────────────────────────────────────

def test_load_with_reject():
    engine = load_from_dict([
        {
            "id": "blocker",
            "event": "pre_tool_use",
            "if": 'tool == "write_file"',
            "action": {"type": "command", "command": "echo blocked"},
            "reject": True,
        },
    ])
    assert len(engine.rules) == 1
    assert engine.rules[0].reject is True


# ── 字符串条件表达式 ───────────────────────────────────

def test_load_condition_expression():
    engine = load_from_dict([
        {
            "id": "cond-hook",
            "event": "pre_tool_use",
            "if": 'tool == "write_file" && args.file_path =~ /\\.py$/',
            "action": {"type": "command", "command": "ruff format"},
        },
    ])
    assert len(engine.rules) == 1
    c = engine.rules[0].condition
    assert c is not None
    assert len(c.atoms) == 2
    assert c.atoms[0].field == "tool"
    assert c.atoms[0].op == "=="
    assert c.atoms[0].value == "write_file"
    assert c.atoms[1].field == "args.file_path"
    assert c.atoms[1].op == "=~"
    assert c.atoms[1].value == r"\.py$"


def test_load_single_atom():
    engine = load_from_dict([
        {
            "id": "single",
            "event": "pre_tool_use",
            "if": 'tool != "read_file"',
            "action": {"type": "command", "command": "echo x"},
        },
    ])
    assert engine.rules[0].condition is not None
    assert engine.rules[0].condition.atoms[0].op == "!="


# ── 错误处理 ──────────────────────────────────────────

def test_missing_id(capsys):
    engine = load_from_dict([
        {"event": "stop", "action": {"type": "command", "command": "x"}},
        {"id": "valid", "event": "stop", "action": {"type": "command", "command": "ok"}},
    ])
    assert len(engine.rules) == 1
    assert engine.rules[0].id == "valid"


def test_unknown_event(capsys):
    engine = load_from_dict([
        {"id": "bad", "event": "unknown_event", "action": {"type": "command", "command": "x"}},
        {"id": "good", "event": "stop", "action": {"type": "command", "command": "ok"}},
    ])
    assert len(engine.rules) == 1


def test_async_on_blocking(capsys):
    engine = load_from_dict([
        {"id": "bad", "event": "pre_tool_use", "async": True, "action": {"type": "command", "command": "x"}},
        {"id": "ok", "event": "stop", "action": {"type": "command", "command": "ok"}},
    ])
    assert len(engine.rules) == 1
    assert engine.rules[0].id == "ok"


def test_duplicate_id(capsys):
    """重复 id 跳过后续。"""
    engine = load_from_dict([
        {"id": "dup", "event": "stop", "action": {"type": "command", "command": "first"}},
        {"id": "dup", "event": "stop", "action": {"type": "command", "command": "second"}},
    ])
    assert len(engine.rules) == 1


# ── only_once ─────────────────────────────────────────

def test_only_once():
    engine = load_from_dict([
        {"id": "once", "event": "pre_user_message", "only_once": True,
         "action": {"type": "command", "command": "echo once"}},
    ])
    assert engine.rules[0].only_once is True


# ── 空列表 ────────────────────────────────────────────

def test_empty_hooks():
    engine = load_from_dict([])
    assert len(engine.rules) == 0


# ── 正则内含运算符 ─────────────────────────────────────

def test_regex_contains_op():
    """正则内包含 && / || 不应被误切分。"""
    from Alincode.hook.matcher import parse_condition
    c = parse_condition('tool =~ /write_file && read_file/')
    assert c is not None
    assert len(c.atoms) == 1
    assert c.atoms[0].value == "write_file && read_file"


def test_regex_contains_pipe():
    """正则内包含 || 不应被误切分。"""
    from Alincode.hook.matcher import parse_condition
    c = parse_condition('tool =~ /install|test/')
    assert c is not None
    assert len(c.atoms) == 1
    assert c.atoms[0].value == "install|test"


# ── 空字符串条件 ───────────────────────────────────────

def test_empty_if_string():
    """空字符串条件 → 无条件触发（None condition）。"""
    engine = load_from_dict([
        {"id": "empty-if", "event": "stop",
         "if": "",
         "action": {"type": "command", "command": "echo x"}},
    ])
    assert len(engine.rules) == 1
    assert engine.rules[0].condition is None


def test_whitespace_if_string():
    """纯空格条件 → 无条件触发。"""
    engine = load_from_dict([
        {"id": "ws-if", "event": "stop",
         "if": "   ",
         "action": {"type": "command", "command": "echo x"}},
    ])
    assert engine.rules[0].condition is None
