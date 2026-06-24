"""Agent 单轮闭环单元测试：fake provider 驱动 AC8/AC9 链路。"""

from typing import AsyncIterator, List

import pytest

from Alincode.client import BaseProvider
from Alincode.conversation import (
    ConversationManager,
    StreamEvent,
    ToolCall,
    ToolDefinition,
)
from Alincode.agent import Agent, Phase, EMPTY_FINAL_PROMPT
from Alincode.tools import Registry, Result


# ── fake provider ───────────────────────────────────────┐

class FakeProvider(BaseProvider):
    """用预制脚本来模拟 LLM 流式返回，无需真实 API。"""

    def __init__(self, script: List[List[StreamEvent]]):
        """
        script: 每次 stream() 调用返回的事件序列列表。
        script[0] = 请求#1 的返回序列
        script[1] = 请求#2 的返回序列（可选）
        """
        self.script = script
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return "fake"

    async def stream(
        self,
        messages: List,
        model: str,
        tools: List[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        idx = min(self.call_count, len(self.script) - 1)
        self.call_count += 1
        for ev in self.script[idx]:
            yield ev


# ── fake tool ───────────────────────────────────────────┐

class FakeTool:
    """可配置执行结果的假工具。"""

    def __init__(self, name: str = "read_file", result: Result | None = None):
        self._name = name
        self._result = result or Result(content="fake file content", is_error=False)
        self.executed = False
        self.last_args = ""

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return "A fake tool for testing"

    def parameters(self) -> dict:
        return {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}

    async def execute(self, args: str) -> Result:
        self.executed = True
        self.last_args = args
        return self._result


# ── tests ──────────────────────────────────────────────┐

@pytest.mark.asyncio
async def test_single_round_text_only():
    """纯文本回合（无工具调用）→ 直接返回文本，无工具事件。"""
    conv = ConversationManager()
    conv.add_user("Hello")
    reg = Registry()

    script = [
        [StreamEvent(text="Hi"), StreamEvent(text=" there!"), StreamEvent(done=True)],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)

    events = []
    async for ev in agent.run(conv):
        events.append(ev)

    # 没有工具事件
    tools = [e for e in events if e.tool is not None]
    assert len(tools) == 0

    # 有文本 + done
    assert any(e.done for e in events)
    texts = "".join(e.text for e in events)
    assert "Hi there!" in texts

    # 最终文本已写入对话
    msgs = conv.messages
    assert len(msgs) == 2  # user + assistant


@pytest.mark.asyncio
async def test_tool_round_single(AC8: str = "AC8"):
    """AC8: 请求#1 返回工具调用 → 执行 → 请求#2 返回文本总结。"""
    conv = ConversationManager()
    conv.add_user("read pyproject.toml")
    reg = Registry()
    fake_tool = FakeTool(name="read_file", result=Result(content="[project]\nname = alincode"))
    reg.register(fake_tool)

    script = [
        # 请求#1：preamble 文本 + 工具调用
        [
            StreamEvent(text="让我读取文件..."),
            StreamEvent(tool_calls=[
                ToolCall(id="call_1", name="read_file", input='{"path":"pyproject.toml"}'),
            ]),
            StreamEvent(done=True),
        ],
        # 请求#2：最终文本答复
        [
            StreamEvent(text="文件内容是 [project] name = alincode，这是 AlinCode 项目配置。"),
            StreamEvent(done=True),
        ],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)

    events = []
    async for ev in agent.run(conv):
        events.append(ev)

    # 工具执行被正确触发
    assert fake_tool.executed
    assert "pyproject.toml" in fake_tool.last_args

    # 事件序列：preamble text → tool START → tool END → final text → done
    tool_starts = [e for e in events if e.tool and e.tool.phase == Phase.START]
    tool_ends = [e for e in events if e.tool and e.tool.phase == Phase.END]
    assert len(tool_starts) == 1
    assert len(tool_ends) == 1
    assert tool_starts[0].tool.name == "read_file"
    assert tool_ends[0].tool.is_error is False

    # 对话历史结构正确：user → assistant(tool_call) → tool_result → assistant(final)
    msgs = conv.messages
    assert len(msgs) == 4
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"
    assert len(msgs[1].tool_calls) == 1
    assert msgs[1].tool_calls[0].name == "read_file"
    assert msgs[2].role == "tool"
    assert len(msgs[2].tool_results) == 1
    assert msgs[2].tool_results[0].tool_call_id == "call_1"
    assert msgs[3].role == "assistant"
    assert "alincode" in msgs[3].content

    assert any(e.done for e in events)


@pytest.mark.asyncio
async def test_single_round_limit(AC9: str = "AC9"):
    """AC9: 请求#2 仍请求工具 → 不再执行，以占位提示结束。"""
    conv = ConversationManager()
    conv.add_user("do two things")
    reg = Registry()
    fake_tool = FakeTool(name="read_file")
    reg.register(fake_tool)

    script = [
        # 请求#1：工具调用
        [
            StreamEvent(text="读文件..."),
            StreamEvent(tool_calls=[
                ToolCall(id="call_1", name="read_file", input='{"x":"first"}'),
            ]),
            StreamEvent(done=True),
        ],
        # 请求#2：又请求工具（触发单轮上限）
        [
            StreamEvent(tool_calls=[
                ToolCall(id="call_2", name="read_file", input='{"x":"ignored"}'),
            ]),
            StreamEvent(done=True),
        ],
    ]
    provider = FakeProvider(script)
    agent = Agent(provider, reg)

    events = []
    async for ev in agent.run(conv):
        events.append(ev)

    # 只执行了一次工具（请求#2 的 tool_calls 被忽略）
    assert fake_tool.executed
    assert provider.call_count == 2

    # 应该输出单轮上限占位提示
    final_text = "".join(e.text for e in events)
    assert EMPTY_FINAL_PROMPT in final_text or "单轮" in final_text
