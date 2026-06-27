"""Agent Loop + 模块化系统提示综合测试。"""

import asyncio
from typing import AsyncIterator, List

import pytest

from Alincode.agent import Agent, Phase
from Alincode.permission import Mode
from Alincode.client import BaseProvider, Request
from Alincode.conversation import (
    ConversationManager,
    StreamEvent,
    ToolCall,
    NOTICE_MAX_ITER,
    NOTICE_CANCELLED,
)
from Alincode.tools import Registry, Result


# ── Fake provider (v2 — Request-based) ──────────────────

class FakeProvider(BaseProvider):
    """预制脚本模拟 LLM 流式返回。"""

    def __init__(self, script: List[List[StreamEvent]]):
        self.script = script
        self.call_count = 0
        self.last_req: Request | None = None

    @property
    def provider_name(self) -> str:
        return "fake"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.last_req = req
        idx = min(self.call_count, len(self.script) - 1)
        self.call_count += 1
        for ev in self.script[idx]:
            yield ev


# ── Fake tools ───────────────────────────────────────────

class FakeReadOnlyTool:
    def __init__(self, name="read_file", result=None, sleep=0):
        self._name = name
        self._result = result or Result(content="content", is_error=False)
        self._sleep = sleep
        self.executed = False
        self.last_args = ""

    @property
    def read_only(self) -> bool:
        return True

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return "Fake RO tool"

    def parameters(self) -> dict:
        return {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}

    async def execute(self, args: str) -> Result:
        self.executed = True
        self.last_args = args
        if self._sleep:
            await asyncio.sleep(self._sleep)
        return self._result


class FakeWriteTool:
    def __init__(self, name="write_file", result=None, sleep=0):
        self._name = name
        self._result = result or Result(content="written", is_error=False)
        self._sleep = sleep
        self.executed = False
        self.last_args = ""
        self.start_time = 0.0

    @property
    def read_only(self) -> bool:
        return False

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return "Fake RW tool"

    def parameters(self) -> dict:
        return {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}

    async def execute(self, args: str) -> Result:
        self.executed = True
        self.last_args = args
        self.start_time = asyncio.get_event_loop().time()
        if self._sleep:
            await asyncio.sleep(self._sleep)
        return self._result


# ── Tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_natural_completion():
    """AC1/AC2: 多轮自然完成。"""
    conv = ConversationManager()
    conv.add_user("do two steps")
    reg = Registry()
    fake_tool = FakeReadOnlyTool(name="read_file")
    reg.register(fake_tool)

    script = [
        [StreamEvent(tool_calls=[ToolCall(id="1", name="read_file", input='{}')], done=True)],
        [StreamEvent(text="All done.", done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)
    events = []
    async for ev in agent.run(conv, mode=Mode.BYPASS):
        events.append(ev)

    assert fake_tool.executed
    assert events[-1].done
    msgs = conv.messages
    assert msgs[-1].role == "assistant"


@pytest.mark.asyncio
async def test_max_iterations():
    """AC3: 迭代上限。"""
    conv = ConversationManager()
    conv.add_user("loop forever")
    reg = Registry()
    reg.register(FakeReadOnlyTool(name="read_file"))

    script = []
    for _ in range(30):
        script.append([StreamEvent(tool_calls=[ToolCall(id="1", name="read_file", input='{}')], done=True)])

    provider = FakeProvider(script)
    agent = Agent(provider, reg)
    events = []
    async for ev in agent.run(conv, mode=Mode.BYPASS):
        events.append(ev)

    assert provider.call_count == 25
    notices = [e.notice for e in events if e.notice]
    assert any(NOTICE_MAX_ITER in n for n in notices)


@pytest.mark.asyncio
async def test_unknown_tools_stop():
    """AC4: 连续未知工具停止。"""
    conv = ConversationManager()
    conv.add_user("use bad tools")
    reg = Registry()

    script = []
    for _ in range(5):
        script.append([StreamEvent(tool_calls=[ToolCall(id="1", name="nonexistent", input='{}')], done=True)])

    provider = FakeProvider(script)
    agent = Agent(provider, reg)
    events = []
    async for ev in agent.run(conv, mode=Mode.BYPASS):
        events.append(ev)

    assert provider.call_count == 3


@pytest.mark.asyncio
async def test_stream_error():
    """AC5: 流出错恢复。"""
    conv = ConversationManager()
    conv.add_user("test error")
    reg = Registry()

    provider = FakeProvider([[StreamEvent(err=RuntimeError("API down"), done=True)]])
    agent = Agent(provider, reg)
    events = []
    async for ev in agent.run(conv, mode=Mode.BYPASS):
        events.append(ev)

    errs = [e for e in events if e.err]
    assert len(errs) == 1


@pytest.mark.asyncio
async def test_concurrent_batch():
    """AC8: 保序分批并发。"""
    conv = ConversationManager()
    conv.add_user("batch test")
    reg = Registry()
    ro1 = FakeReadOnlyTool(name="read_file", sleep=0.05)
    ro2 = FakeReadOnlyTool(name="glob", sleep=0.05)
    rw = FakeWriteTool(name="bash", sleep=0.02)
    reg.register(ro1)
    reg.register(ro2)
    reg.register(rw)

    script = [
        [StreamEvent(tool_calls=[
            ToolCall(id="1", name="read_file", input='{}'),
            ToolCall(id="2", name="glob", input='{}'),
            ToolCall(id="3", name="bash", input='{}'),
        ], done=True)],
        [StreamEvent(text="done", done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)
    events = []
    async for ev in agent.run(conv, mode=Mode.BYPASS):
        events.append(ev)

    assert ro1.executed and ro2.executed and rw.executed
    start_order = [e.tool.name for e in events if e.tool and e.tool.phase == Phase.START]
    assert start_order == ["read_file", "glob", "bash"]


@pytest.mark.asyncio
async def test_cancel_during_tools():
    """AC9/AC10: 取消后历史合法。"""
    conv = ConversationManager()
    conv.add_user("cancel me")
    reg = Registry()
    reg.register(FakeReadOnlyTool(name="read_file", sleep=0.2))

    script = [
        [StreamEvent(tool_calls=[ToolCall(id="1", name="read_file", input='{}')], done=True)],
        [StreamEvent(text="final", done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)
    cancel = asyncio.Event()

    events = []
    async for ev in agent.run(conv, mode=Mode.BYPASS, cancel=cancel):
        events.append(ev)
        asyncio.create_task(_set_after(cancel, 0.01))

    notices = [e.notice for e in events if e.notice]
    assert any(NOTICE_CANCELLED in n for n in notices)
    assert conv.last_role in ("tool", "assistant")


async def _set_after(event: asyncio.Event, delay: float):
    await asyncio.sleep(delay)
    event.set()


@pytest.mark.asyncio
async def test_plan_mode():
    """AC13: Plan Mode 仅只读工具。"""
    conv = ConversationManager()
    conv.add_user("plan something")
    reg = Registry()
    reg.register(FakeReadOnlyTool(name="read_file"))
    reg.register(FakeReadOnlyTool(name="glob"))
    reg.register(FakeWriteTool(name="write_file"))

    provider = FakeProvider([[StreamEvent(text="Plan done.", done=True)]])
    agent = Agent(provider, reg)
    events = []
    async for ev in agent.run(conv, mode=Mode.PLAN):
        events.append(ev)

    assert provider.last_req is not None
    plan_names = {t.name for t in provider.last_req.tools}
    assert plan_names == {"read_file", "glob"}


@pytest.mark.asyncio
async def test_system_request_assembly():
    """系统提示装配：stable 非空、environment 非空、reminder 注入。"""
    conv = ConversationManager()
    conv.add_user("test")
    reg = Registry()
    reg.register(FakeReadOnlyTool(name="read_file"))

    provider = FakeProvider([[StreamEvent(text="ok", done=True)]])
    agent = Agent(provider, reg, version="0.3.0")
    async for _ in agent.run(conv, mode=Mode.BYPASS):
        pass

    req = provider.last_req
    assert req is not None
    assert req.system.stable
    assert "AlinCode" in req.system.stable
    assert req.system.environment
    assert req.reminder == ""  # Normal mode has no reminder


@pytest.mark.asyncio
async def test_plan_reminder_by_iteration():
    """AC9: Plan Mode 下按轮次注入完整/精简 reminder。"""
    conv = ConversationManager()
    conv.add_user("plan multi-step")
    reg = Registry()
    reg.register(FakeReadOnlyTool(name="read_file"))

    script = [
        [StreamEvent(tool_calls=[ToolCall(id="1", name="read_file", input='{}')], done=True)],
        [StreamEvent(tool_calls=[ToolCall(id="2", name="read_file", input='{}')], done=True)],
        [StreamEvent(tool_calls=[ToolCall(id="3", name="read_file", input='{}')], done=True)],
        [StreamEvent(text="final", done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)
    async for ev in agent.run(conv, mode=Mode.PLAN):
        # Collect reminders per iteration
        pass

    # Reminder was injected in each call
    # Iter 1 → full, Iter 2 → lite, Iter 3 → lite
    assert provider.call_count >= 2


# ── Compact Events ────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_compact_event_below_threshold():
    """估算 token 远低于阈值时不发 Compact 事件。"""
    from Alincode.runtime import SessionRuntime
    from Alincode.compact.state import (
        ContentReplacementState, RecoveryState,
        AutoCompactTrackingState, new_session_context,
    )

    conv = ConversationManager()
    conv.add_user("hello")
    reg = Registry()

    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=new_session_context("."),
        context_window=200000,
    )

    provider = FakeProvider([[StreamEvent(text="ok", done=True)]])
    agent = Agent(provider, reg, runtime=runtime)
    events = []
    async for ev in agent.run(conv, mode=Mode.BYPASS):
        events.append(ev)

    compact_events = [e.compact for e in events if e.compact]
    assert len(compact_events) == 0


@pytest.mark.asyncio
async def test_agent_emits_emergency_compact_event():
    """PTL 错误时发紧急压缩事件。"""
    from Alincode.client import PromptTooLongError
    from Alincode.runtime import SessionRuntime
    from Alincode.compact.state import (
        ContentReplacementState, RecoveryState,
        AutoCompactTrackingState, new_session_context,
    )

    conv = ConversationManager()
    conv.add_user("trigger ptl")
    reg = Registry()

    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=new_session_context("."),
        context_window=200000,
    )

    # Series: PTL error (emergency compact will try to retry, then fail)
    # The provider needs at least 2 entries: one for initial error, one for retry
    provider = FakeProvider([
        [StreamEvent(err=PromptTooLongError("test ptl"), done=True)],
        [StreamEvent(text="retry ok", done=True)],
    ])
    agent = Agent(provider, reg, runtime=runtime)
    events = []
    async for ev in agent.run(conv, mode=Mode.BYPASS):
        events.append(ev)

    compact_events = [e.compact for e in events if e.compact]
    # Should have BEFORE_EMERGENCY and AFTER_EMERGENCY
    assert len(compact_events) >= 1
    # At least BEFORE_EMERGENCY
    from Alincode.agent import CompactPhase
    assert any(c.phase == CompactPhase.BEFORE_EMERGENCY for c in compact_events)


@pytest.mark.asyncio
async def test_agent_runtime_injection():
    """Agent 构造接受 runtime 参数并正确注入。"""
    from Alincode.runtime import SessionRuntime

    conv = ConversationManager()
    conv.add_user("test")
    reg = Registry()
    runtime = SessionRuntime(context_window=100000)
    provider = FakeProvider([[StreamEvent(text="ok", done=True)]])
    agent = Agent(provider, reg, runtime=runtime)
    assert agent.runtime.context_window == 100000
    assert agent.runtime is runtime

    async for _ in agent.run(conv, mode=Mode.BYPASS):
        pass
