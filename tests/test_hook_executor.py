"""Hook Executor 测试（新格式：command + reject）。"""

import asyncio
import pytest

from Alincode.hook.event import Event
from Alincode.hook.rule import (
    Rule, Action, ActionType, CommandAction, PromptAction, HttpAction, SubagentAction,
)
from Alincode.hook.executor import Executor


# ── Command ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_command_exit_0():
    rule = _rule("t", Event.STOP, Action(type=ActionType.COMMAND, command=CommandAction(command="exit 0")))
    r = await Executor().run(rule, {"event": "stop"}, blocking=False)
    assert r.blocked is False
    assert r.err is None


@pytest.mark.asyncio
async def test_command_exit_2_block():
    """兼容旧语义：exit 2 表达拦截。"""
    rule = _rule("t", Event.PRE_TOOL_USE, Action(type=ActionType.COMMAND,
        command=CommandAction(command='python -c "import sys; sys.stderr.write(\'blocked\'); sys.exit(2)"')))
    r = await Executor().run(rule, {"event": "pre_tool_use"}, blocking=True)
    assert r.blocked is True
    assert "blocked" in r.reason


@pytest.mark.asyncio
async def test_reject_mode_blocked():
    """reject=True：stdout 作为拒绝原因。"""
    rule = _rule("t", Event.PRE_TOOL_USE, Action(type=ActionType.COMMAND,
        command=CommandAction(command="echo rejected by policy")), reject=True)
    r = await Executor().run(rule, {"event": "pre_tool_use"}, blocking=True)
    assert r.blocked is True
    assert "rejected by policy" in r.reason


@pytest.mark.asyncio
async def test_command_exit_1_no_block():
    rule = _rule("t", Event.PRE_TOOL_USE, Action(type=ActionType.COMMAND,
        command=CommandAction(command='python -c "import sys; sys.exit(1)"')))
    r = await Executor().run(rule, {"event": "pre_tool_use"}, blocking=True)
    assert r.blocked is False
    assert r.err is not None


@pytest.mark.asyncio
async def test_command_exit_2_non_blocking():
    rule = _rule("t", Event.STOP, Action(type=ActionType.COMMAND, command=CommandAction(command="exit 2")))
    r = await Executor().run(rule, {"event": "stop"}, blocking=False)
    assert r.blocked is False
    assert r.err is not None


@pytest.mark.asyncio
async def test_command_timeout():
    rule = _rule("t", Event.STOP, Action(type=ActionType.COMMAND,
        command=CommandAction(command="python -c \"import time; time.sleep(5)\"")))
    rule.timeout_s = 0.1
    r = await Executor().run(rule, {"event": "stop"}, blocking=False)
    assert isinstance(r.err, (TimeoutError, asyncio.TimeoutError))


# ── Prompt ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prompt_return():
    rule = _rule("t", Event.SESSION_START, Action(type=ActionType.PROMPT, prompt=PromptAction(text="用 zh-CN")))
    r = await Executor().run(rule, {"event": "session_start"}, blocking=False)
    assert r.prompt == "用 zh-CN"
    assert r.blocked is False


# ── HTTP ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_http_block():
    from unittest.mock import MagicMock

    rule = _rule("t", Event.PRE_TOOL_USE, Action(type=ActionType.HTTP,
        http=HttpAction(url="http://localhost/check")))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"decision": "block", "reason": "network policy"}

    mock_client = MagicMock()
    async def _req(*a, **kw):
        return mock_resp
    mock_client.request = _req

    ex = Executor()
    ex._http_client = mock_client
    r = await ex.run(rule, {"event": "pre_tool_use"}, blocking=True)
    assert r.blocked is True
    assert r.reason == "network policy"


@pytest.mark.asyncio
async def test_http_non_2xx():
    from unittest.mock import MagicMock

    rule = _rule("t", Event.PRE_TOOL_USE, Action(type=ActionType.HTTP,
        http=HttpAction(url="http://localhost/check")))

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_client = MagicMock()
    async def _req(*a, **kw):
        return mock_resp
    mock_client.request = _req

    ex = Executor()
    ex._http_client = mock_client
    r = await ex.run(rule, {"event": "pre_tool_use"}, blocking=True)
    assert r.blocked is False


# ── Subagent ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_subagent_stub(capsys):
    rule = _rule("t", Event.SESSION_START, Action(type=ActionType.SUBAGENT,
        subagent=SubagentAction(agent_name="foo", prompt="test")))
    r = await Executor().run(rule, {"event": "session_start"}, blocking=False)
    assert r.blocked is False
    captured = capsys.readouterr()
    assert "not yet implemented" in captured.err


# ── reject + 命令失败 ──────────────────────────────────

@pytest.mark.asyncio
async def test_reject_command_failure_still_blocks():
    """reject=true 时命令失败仍拦截，但 reason 包含异常信息。"""
    rule = _rule("t", Event.PRE_TOOL_USE, Action(type=ActionType.COMMAND,
        command=CommandAction(command="nonexistent_command_xyz")), reject=True)
    r = await Executor().run(rule, {"event": "pre_tool_use"}, blocking=True)
    assert r.blocked is True
    assert "命令异常" in r.reason


# ── 辅助 ───────────────────────────────────────────────

def _rule(id: str, event: Event, action: Action, reject: bool = False) -> Rule:
    return Rule(id=id, event=event, action=action, reject=reject)
