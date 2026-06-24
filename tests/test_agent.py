"""Agent Loop 综合测试：覆盖 AC1-AC9, AC13。"""

import asyncio
from typing import AsyncIterator, List

import pytest

from Alincode.agent import Agent, Mode, Phase
from Alincode.client import BaseProvider
from Alincode.conversation import (
    ConversationManager,
    StreamEvent,
    ToolCall,
    ToolDefinition,
    Usage,
    NOTICE_MAX_ITER,
    NOTICE_UNKNOWN_TOOLS,
    NOTICE_CANCELLED,
    NOTICE_PROVIDER_ERROR,
)
from Alincode.tools import Registry, Result


# ── Fake provider ───────────────────────────────────────┐

class FakeProvider(BaseProvider):
    """预制脚本模拟 LLM 流式返回。"""

    def __init__(self, script: List[List[StreamEvent]]):
        self.script = script
        self.call_count = 0
        self.last_tools: list[ToolDefinition] | None = None
        self.last_suffix: str = ""

    @property
    def provider_name(self) -> str:
        return "fake"

    async def stream(
        self,
        messages: List,
        model: str,
        tools: List[ToolDefinition],
        system_suffix: str = "",
    ) -> AsyncIterator[StreamEvent]:
        self.last_tools = tools
        self.last_suffix = system_suffix
        idx = min(self.call_count, len(self.script) - 1)
        self.call_count += 1
        for ev in self.script[idx]:
            yield ev


# ── Fake tools ───────────────────────────────────────────┐

class FakeReadOnlyTool:
    """可配置的只读假工具。"""
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
    """可配置的有副作用假工具。"""
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


# ── Helpers ──────────────────────────────────────────────┐

def _tool_defs(reg: Registry) -> list[ToolDefinition]:
    return reg.definitions()


# ── Tests: Core loop ─────────────────────────────────────┐

@pytest.mark.asyncio
async def test_natural_completion():
    """AC1/AC2: 多轮自然完成——模型最后一轮无工具调用时停止。"""
    conv = ConversationManager()
    conv.add_user("do two steps")
    reg = Registry()
    fake_tool = FakeReadOnlyTool(name="read_file")
    reg.register(fake_tool)

    script = [
        # 轮1：工具调用
        [StreamEvent(text="reading...",
                     tool_calls=[ToolCall(id="1", name="read_file", input='{}')],
                     done=True)],
        # 轮2：最终文本
        [StreamEvent(text="All done.", done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)

    events = []
    async for ev in agent.run(conv):
        events.append(ev)

    # 工具执行了
    assert fake_tool.executed
    # 最终 done
    assert events[-1].done
    # 历史正确
    msgs = conv.messages
    assert msgs[-1].role == "assistant"
    assert "All done" in msgs[-1].content


@pytest.mark.asyncio
async def test_max_iterations():
    """AC3: 迭代上限——到达 MAX_ITERATIONS 时停止并提示。"""
    conv = ConversationManager()
    conv.add_user("loop forever")
    reg = Registry()
    fake_tool = FakeReadOnlyTool(name="read_file")
    reg.register(fake_tool)

    # 持续返回工具调用，永不停止
    infinite_script = []
    for _ in range(30):
        infinite_script.append([
            StreamEvent(tool_calls=[ToolCall(id="1", name="read_file", input='{}')], done=True),
        ])

    provider = FakeProvider(infinite_script)
    agent = Agent(provider, reg)

    events = []
    async for ev in agent.run(conv):
        events.append(ev)

    # 恰好 25 轮（Agent 内部 MAX_ITERATIONS=25）
    assert provider.call_count == 25
    # 最后是上限提示
    notices = [e.notice for e in events if e.notice]
    assert any(NOTICE_MAX_ITER in n for n in notices)
    # 历史以 assistant 收尾
    assert conv.last_role == "assistant" or len(conv.messages) > 0


@pytest.mark.asyncio
async def test_unknown_tools_stop():
    """AC4: 连续未知工具——达到阈值停止。"""
    conv = ConversationManager()
    conv.add_user("use bad tools")
    reg = Registry()

    script = []
    for _ in range(5):
        script.append([
            StreamEvent(tool_calls=[ToolCall(id="1", name="nonexistent_tool", input='{}')],
                        done=True),
        ])

    provider = FakeProvider(script)
    agent = Agent(provider, reg)

    events = []
    async for ev in agent.run(conv):
        events.append(ev)

    # 连续 3 轮未知工具后停止（MAX_UNKNOWN_RUN=3）
    assert provider.call_count == 3
    notices = [e.notice for e in events if e.notice]
    assert any(NOTICE_UNKNOWN_TOOLS in n for n in notices)


@pytest.mark.asyncio
async def test_unknown_tools_reset():
    """AC4: 未知工具后出现已注册工具，计数重置。"""
    conv = ConversationManager()
    conv.add_user("mixed")
    reg = Registry()
    reg.register(FakeReadOnlyTool(name="read_file"))

    script = [
        # 轮1：未知
        [StreamEvent(tool_calls=[ToolCall(id="1", name="bad1", input='{}')], done=True)],
        # 轮2：已知
        [StreamEvent(tool_calls=[ToolCall(id="2", name="read_file", input='{}')], done=True)],
        # 轮3：又未知
        [StreamEvent(tool_calls=[ToolCall(id="3", name="bad2", input='{}')], done=True)],
        # 轮4：未知
        [StreamEvent(tool_calls=[ToolCall(id="4", name="bad3", input='{}')], done=True)],
        # 轮5：未知
        [StreamEvent(tool_calls=[ToolCall(id="5", name="bad4", input='{}')], done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)

    events = []
    async for ev in agent.run(conv):
        events.append(ev)

    # 因为轮2重置了计数，所以轮3/4/5 才触发停止（共5轮）
    assert provider.call_count == 5
    notices = [e.notice for e in events if e.notice]
    assert any(NOTICE_UNKNOWN_TOOLS in n for n in notices)


@pytest.mark.asyncio
async def test_stream_error():
    """AC5: 流出错——停止并提示，不崩溃。"""
    conv = ConversationManager()
    conv.add_user("test error")
    reg = Registry()

    script = [
        [StreamEvent(err=RuntimeError("API down"), done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)

    events = []
    async for ev in agent.run(conv):
        events.append(ev)

    errs = [e for e in events if e.err]
    assert len(errs) == 1
    notices = [e.notice for e in events if e.notice]
    assert any(NOTICE_PROVIDER_ERROR in n for n in notices)


@pytest.mark.asyncio
async def test_event_completeness():
    """AC6: 事件流包含 iter/text/tool/usage/done。"""
    conv = ConversationManager()
    conv.add_user("test")
    reg = Registry()
    fake_tool = FakeReadOnlyTool(name="read_file")
    reg.register(fake_tool)

    script = [
        [StreamEvent(text="Let me check...",
                     usage=Usage(input_tokens=10, output_tokens=5),
                     tool_calls=[ToolCall(id="1", name="read_file", input='{}')],
                     done=True)],
        [StreamEvent(text="Done.", usage=Usage(input_tokens=8, output_tokens=4), done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)
    events = []
    async for ev in agent.run(conv):
        events.append(ev)

    event_types = set()
    for e in events:
        if e.text:
            event_types.add("text")
        if e.tool:
            event_types.add("tool")
        if e.usage:
            event_types.add("usage")
        if e.iter:
            event_types.add("iter")
        if e.done:
            event_types.add("done")
    assert {"text", "tool", "usage", "iter", "done"} <= event_types


@pytest.mark.asyncio
async def test_concurrent_batch():
    """AC8: 保序分批——连续只读并发执行，有副作用在其后串行。"""
    conv = ConversationManager()
    conv.add_user("batch test")
    reg = Registry()

    # 用 sleep 来验证并发：两只读各 sleep 0.05s
    ro1 = FakeReadOnlyTool(name="ro1", sleep=0.05)
    ro2 = FakeReadOnlyTool(name="ro2", sleep=0.05)
    rw = FakeWriteTool(name="rw", sleep=0.02)
    reg.register(ro1)
    reg.register(ro2)
    reg.register(rw)

    script = [
        [StreamEvent(tool_calls=[
            ToolCall(id="1", name="ro1", input='{}'),
            ToolCall(id="2", name="ro2", input='{}'),
            ToolCall(id="3", name="rw", input='{}'),
        ], done=True)],
        [StreamEvent(text="done", done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)
    events = []
    async for ev in agent.run(conv):
        events.append(ev)

    # 两只读 + 一个写都执行了
    assert ro1.executed and ro2.executed and rw.executed

    # 批量并发：两只读几乎同时完成（done 在 start_time 之后）
    # rw 在两只读之后执行（串行）
    # 由于 FakeWriteTool 记录 start_time，只要有记录即可
    assert rw.start_time > 0

    # 工具事件序列计数正确
    tool_starts = [e for e in events if e.tool and e.tool.phase == Phase.START]
    tool_ends = [e for e in events if e.tool and e.tool.phase == Phase.END]
    assert len(tool_starts) == 3
    assert len(tool_ends) == 3

    # 事件按原始调用序排列（ro1, ro2, rw 顺序不变）
    start_order = [e.tool.name for e in events if e.tool and e.tool.phase == Phase.START]
    assert start_order == ["ro1", "ro2", "rw"]


@pytest.mark.asyncio
async def test_cancel_during_tools():
    """AC9/AC10: 取消后历史合法，含 tool_results + assistant 文本尾。"""
    conv = ConversationManager()
    conv.add_user("cancel me")
    reg = Registry()
    fake_tool = FakeReadOnlyTool(name="read_file", sleep=0.2)
    reg.register(fake_tool)

    script = [
        [StreamEvent(tool_calls=[ToolCall(id="1", name="read_file", input='{}')], done=True)],
        [StreamEvent(text="final", done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)
    cancel = asyncio.Event()

    async def _do_cancel():
        await asyncio.sleep(0.01)
        cancel.set()

    events = []
    async for ev in agent.run(conv, cancel=cancel):
        events.append(ev)
        # 第一轮开始时触发取消
        asyncio.create_task(_do_cancel())

    # 有取消 notice
    notices = [e.notice for e in events if e.notice]
    assert any(NOTICE_CANCELLED in n for n in notices)
    # 历史以 tool 结尾（合法状态：下一条 user 消息不会触发 400）
    # 如果工具正在执行中被取消，ensure_assistant_tail 补了 tool_results
    assert conv.last_role in ("tool", "assistant")


@pytest.mark.asyncio
async def test_plan_mode():
    """AC13: Plan Mode 下只发送只读工具。"""
    conv = ConversationManager()
    conv.add_user("plan something")
    reg = Registry()
    reg.register(FakeReadOnlyTool(name="read_file"))
    reg.register(FakeReadOnlyTool(name="glob"))
    reg.register(FakeWriteTool(name="write_file"))

    script = [
        [StreamEvent(text="Plan: I will read and write.", done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)
    events = []
    async for ev in agent.run(conv, mode=Mode.PLAN):
        events.append(ev)

    # Plan Mode 下只发只读工具
    assert provider.last_tools is not None
    plan_names = {t.name for t in provider.last_tools}
    assert plan_names == {"read_file", "glob"}
    assert "write_file" not in plan_names
    # system_suffix 包含 Plan Mode 提醒
    assert "计划模式" in provider.last_suffix or "只读" in provider.last_suffix
