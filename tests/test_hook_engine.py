"""Hook Engine 测试（新格式：snake_case + 字符串条件表达式 + reject）。"""

import pytest

from Alincode.hook.event import Event
from Alincode.hook.rule import (
    Rule, Condition, AtomCondition, Action, ActionType, CommandAction, PromptAction,
)
from Alincode.hook.engine import Engine
from Alincode.hook.executor import Executor


@pytest.mark.asyncio
async def test_dispatch_no_rules():
    engine = Engine([], [])
    result = await engine.dispatch(Event.STOP, {"event": "stop"})
    assert result.blocked is False
    assert result.injected_prompts == []


@pytest.mark.asyncio
async def test_dispatch_prompt():
    rules = [
        _rule("h1", Event.SESSION_START, Action(type=ActionType.PROMPT, prompt=PromptAction(text="用 zh-CN 回复"))),
        _rule("h2", Event.SESSION_START, Action(type=ActionType.PROMPT, prompt=PromptAction(text="简洁回复"))),
    ]
    engine = Engine(rules, [])
    result = await engine.dispatch(Event.SESSION_START, {"event": "session_start"})
    assert len(result.injected_prompts) == 2


@pytest.mark.asyncio
async def test_dispatch_blocking_stops_further():
    rules = [
        _rule("blocker", Event.PRE_TOOL_USE, Action(
            type=ActionType.COMMAND,
            command=CommandAction(command='python -c "import sys; sys.stderr.write(\'blocked\'); sys.exit(2)"'),
        )),
        _rule("never-run", Event.PRE_TOOL_USE, Action(
            type=ActionType.PROMPT, prompt=PromptAction(text="should not appear"),
        )),
    ]
    engine = Engine(rules, [])
    result = await engine.dispatch(Event.PRE_TOOL_USE, {"event": "pre_tool_use", "tool": "write_file"})
    assert result.blocked is True
    assert result.blocking_hook_id == "blocker"
    assert len(result.injected_prompts) == 0


@pytest.mark.asyncio
async def test_reject_mode():
    """reject=True 时直接拦截，不使用 exit 2。"""
    rules = [
        _rule("rejector", Event.PRE_TOOL_USE, Action(
            type=ActionType.COMMAND,
            command=CommandAction(command='echo "rejected by policy"'),
        ), reject=True),
    ]
    engine = Engine(rules, [])
    result = await engine.dispatch(Event.PRE_TOOL_USE, {"event": "pre_tool_use", "tool": "write_file"})
    assert result.blocked is True
    assert "rejected by policy" in result.reason


@pytest.mark.asyncio
async def test_dispatch_non_blocking_no_break():
    rules = [
        _rule("err-one", Event.STOP, Action(type=ActionType.COMMAND, command=CommandAction(command="exit 2"))),
        _rule("still-run", Event.STOP, Action(type=ActionType.PROMPT, prompt=PromptAction(text="still here"))),
    ]
    engine = Engine(rules, [])
    result = await engine.dispatch(Event.STOP, {"event": "stop"})
    assert result.blocked is False
    assert len(result.injected_prompts) == 1


@pytest.mark.asyncio
async def test_only_once():
    rules = [
        _rule("once-hook", Event.PRE_USER_MESSAGE, Action(
            type=ActionType.COMMAND, command=CommandAction(command="echo first"),
        ), only_once=True),
    ]
    engine = Engine(rules, [])
    await engine.dispatch(Event.PRE_USER_MESSAGE, {"event": "pre_user_message"})
    r2 = await engine.dispatch(Event.PRE_USER_MESSAGE, {"event": "pre_user_message"})
    assert r2.blocked is False


@pytest.mark.asyncio
async def test_only_once_reset():
    rules = [
        _rule("once-hook", Event.PRE_USER_MESSAGE, Action(
            type=ActionType.PROMPT, prompt=PromptAction(text="first-turn"),
        ), only_once=True),
    ]
    engine = Engine(rules, [])
    r1 = await engine.dispatch(Event.PRE_USER_MESSAGE, {"event": "pre_user_message"})
    assert len(r1.injected_prompts) == 1
    r2 = await engine.dispatch(Event.PRE_USER_MESSAGE, {"event": "pre_user_message"})
    assert len(r2.injected_prompts) == 0
    await engine.reset_for_new_session()
    r3 = await engine.dispatch(Event.PRE_USER_MESSAGE, {"event": "pre_user_message"})
    assert len(r3.injected_prompts) == 1


@pytest.mark.asyncio
async def test_condition_exact_match():
    rules = [
        Rule(
            id="cond-hook", event=Event.PRE_TOOL_USE,
            condition=Condition.all_of([AtomCondition(field="tool", op="==", value="write_file")]),
            action=Action(type=ActionType.COMMAND, command=CommandAction(command="exit 2")),
        ),
    ]
    engine = Engine(rules, [])
    r1 = await engine.dispatch(Event.PRE_TOOL_USE, {"event": "pre_tool_use", "tool": "write_file"})
    assert r1.blocked is True
    r2 = await engine.dispatch(Event.PRE_TOOL_USE, {"event": "pre_tool_use", "tool": "read_file"})
    assert r2.blocked is False


@pytest.mark.asyncio
async def test_dispatch_respects_order():
    order = []
    class SpyExecutor(Executor):
        async def run(self, rule, payload, *, blocking):
            order.append(rule.id)
            return await super().run(rule, payload, blocking=blocking)

    rules = [
        _rule("a", Event.STOP, Action(type=ActionType.PROMPT, prompt=PromptAction(text="a"))),
        _rule("b", Event.STOP, Action(type=ActionType.PROMPT, prompt=PromptAction(text="b"))),
        _rule("c", Event.STOP, Action(type=ActionType.PROMPT, prompt=PromptAction(text="c"))),
    ]
    engine = Engine(rules, [])
    engine._executor = SpyExecutor()
    await engine.dispatch(Event.STOP, {"event": "stop"})
    assert order == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_skipped_event():
    rules = [_rule("only-stop", Event.STOP, Action(type=ActionType.COMMAND, command=CommandAction(command="exit 2")))]
    engine = Engine(rules, [])
    result = await engine.dispatch(Event.SESSION_START, {"event": "session_start"})
    assert result.blocked is False


# ── 辅助 ───────────────────────────────────────────────

def _rule(id: str, event: Event, action: Action, only_once: bool = False, reject: bool = False) -> Rule:
    return Rule(id=id, event=event, action=action, only_once=only_once, reject=reject)
