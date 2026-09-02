# tests/web/test_session.py
"""WebSession：事件消费 + 审批闭环（FakeProvider 驱动真实 Agent 循环）。"""

import asyncio

import pytest

from Alincode.bootstrap import AppContext
from Alincode.config import AppConfig, ProviderConfig
from Alincode.conversation import StreamEvent, ToolCall, Usage
from Alincode.permission.engine import new_engine
from Alincode.profile.service import ProfileService
from Alincode.profile.store import ProfileStore
from Alincode.tools import Registry
from Alincode.web.session import WebSession
from Alincode.session.list import list_sessions

# 复用 tests/test_agent.py 的 Fake 设施
from tests.test_agent import FakeProvider, FakeWriteTool


def _ctx(tmp_path, provider, registry) -> AppContext:
    engine, _ = new_engine(str(tmp_path))
    return AppContext(
        app_cfg=AppConfig(),
        provider_cfg=ProviderConfig(name="fake", protocol="anthropic",
                                    model="m", base_url="", api_key=""),
        provider=provider, registry=registry, engine=engine,
        instruction_text="", memory_text="", memory_manager=None,
        workspace=str(tmp_path), catalog=None, hook_engine=None,
        subagent_catalog=None, task_mgr=None, wt_mgr=None, team_mgr=None,
        agent_tool=None, team_commands=[], mcp_mgr=None,
    )


async def _collect_until(ws: WebSession, stop_type: str, timeout=5.0) -> list[dict]:
    got = []

    async def _pump():
        while True:
            m = await ws.outbox.get()
            got.append(m)
            if m["type"] == stop_type:
                return

    await asyncio.wait_for(_pump(), timeout)
    return got


async def _next_of(ws: WebSession, want: str) -> dict:
    while True:
        m = await ws.outbox.get()
        if m["type"] == want:
            return m


@pytest.mark.asyncio
async def test_plain_text_turn(tmp_path):
    provider = FakeProvider([[StreamEvent(text="你好！"), StreamEvent(done=True)]])
    ws = WebSession(_ctx(tmp_path, provider, Registry()))
    await ws.open()
    await ws.send_user("在吗")
    msgs = await _collect_until(ws, "turn.done")
    types = [m["type"] for m in msgs]
    assert "text.delta" in types and types[-1] == "turn.done"
    assert not ws.busy


@pytest.mark.asyncio
async def test_approval_roundtrip_deny(tmp_path):
    # 第一轮：模型要求调用写工具（DEFAULT 模式下写操作触发 ASK）；
    # 第二轮：拒绝后模型收到错误结果并收尾。
    provider = FakeProvider([
        [StreamEvent(tool_calls=[ToolCall(id="t1", name="write_file", input='{"x":"1"}')])],
        [StreamEvent(text="已取消"), StreamEvent(done=True)],
    ])
    registry = Registry()
    registry.register(FakeWriteTool())
    ws = WebSession(_ctx(tmp_path, provider, registry))
    await ws.open()
    await ws.send_user("写个文件")

    req = await asyncio.wait_for(_next_of(ws, "approval.request"), 5.0)
    assert req["tool_name"] == "write_file"
    await ws.respond_approval(req["request_id"], "deny_once")

    msgs = await _collect_until(ws, "turn.done")
    resolved = [m for m in msgs if m["type"] == "approval.resolved"]
    assert resolved and resolved[0]["outcome"] == "deny_once"
    tool_ends = [m for m in msgs if m["type"] == "tool.end"]
    assert tool_ends and tool_ends[0]["is_error"] is True


@pytest.mark.asyncio
async def test_profile_usage_is_recorded_and_budget_blocks_new_turns(tmp_path):
    profile = ProfileStore(tmp_path / "profiles").create("Alin", "secret")
    service = ProfileService(ProfileStore(tmp_path / "profiles"))
    service.set_budget(profile.id, 5)
    provider = FakeProvider([[
        StreamEvent(usage=Usage(input_tokens=3, output_tokens=2)),
        StreamEvent(done=True),
    ]])
    ws = WebSession(
        _ctx(tmp_path, provider, Registry()), profile_service=service, profile_id=profile.id,
    )
    await ws.open()
    await ws.send_user("在吗")
    messages = await _collect_until(ws, "turn.done")

    status = next(message for message in messages if message["type"] == "budget.status")
    assert status["budget"] == 5
    assert status["used_tokens"] == 5
    assert status["blocked"] is True
    await ws.send_user("再问一次")
    assert (await _next_of(ws, "notice"))["text"] == "本地 token 预算已用尽，请在设置中提高预算。"
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_mode_change_is_emitted_and_applies_to_the_session(tmp_path):
    ws = WebSession(_ctx(tmp_path, FakeProvider([]), Registry()))
    await ws.open()
    await _next_of(ws, "session.info")

    await ws.handle({"type": "mode.set", "mode": "plan"})

    info = await _next_of(ws, "session.info")
    assert info["mode"] == "plan"
    assert ws._mode.value == "plan"


@pytest.mark.asyncio
async def test_invalid_mode_keeps_the_current_mode(tmp_path):
    ws = WebSession(_ctx(tmp_path, FakeProvider([]), Registry()))
    await ws.open()
    await _next_of(ws, "session.info")

    await ws.handle({"type": "mode.set", "mode": "danger"})

    assert (await _next_of(ws, "notice"))["text"] == "不支持的执行模式。"
    assert ws._mode.value == "default"


@pytest.mark.asyncio
async def test_new_session_keeps_the_unlocked_profile_context(tmp_path):
    ws = WebSession(_ctx(tmp_path, FakeProvider([]), Registry()))
    await ws.open()
    original = await _next_of(ws, "session.info")

    await ws.handle({"type": "session.new"})

    info = await asyncio.wait_for(ws.outbox.get(), 1.0)
    assert info["type"] == "session.info"
    history = await _next_of(ws, "history")
    assert info["session_id"] != original["session_id"]
    assert info["workspace"] == str(tmp_path)
    assert history == {"type": "history", "session_id": info["session_id"], "blocks": []}


@pytest.mark.asyncio
async def test_new_session_can_bind_to_the_selected_workspace(tmp_path):
    """新对话应使用用户在项目选择器中选择的目录，而非旧的默认目录。"""
    project_b = tmp_path / "project-b"
    project_b.mkdir()
    initial = _ctx(tmp_path, FakeProvider([]), Registry())
    selected = _ctx(project_b, FakeProvider([]), Registry())

    async def context_for_workspace(path: str) -> AppContext:
        assert path == str(project_b)
        return selected

    ws = WebSession(initial, context_factory=context_for_workspace)
    await ws.open()
    await _next_of(ws, "session.info")

    await ws.handle({"type": "session.new", "workspace": str(project_b)})

    info = await _next_of(ws, "session.info")
    assert info["workspace"] == str(project_b)
    assert ws._ctx is selected


@pytest.mark.asyncio
async def test_resumed_session_restores_its_saved_workspace(tmp_path):
    """历史会话回到创建时的项目目录，不能被当前默认项目覆盖。"""
    project_b = tmp_path / "project-b"
    project_b.mkdir()
    session_root = tmp_path / "sessions"
    initial = _ctx(tmp_path, FakeProvider([]), Registry())
    selected = _ctx(project_b, FakeProvider([]), Registry())

    async def context_for_workspace(path: str) -> AppContext:
        assert path == str(project_b)
        return selected

    ws = WebSession(initial, session_root=str(session_root), context_factory=context_for_workspace)
    await ws.open()
    await _next_of(ws, "session.info")
    await ws.handle({"type": "session.new", "workspace": str(project_b)})
    info = await _next_of(ws, "session.info")
    await _next_of(ws, "history")
    await ws.send_user("保存这个项目目录")
    await _collect_until(ws, "turn.done")
    await ws.close()

    resumed = WebSession(initial, session_root=str(session_root), context_factory=context_for_workspace)
    await resumed.open()
    await _next_of(resumed, "session.info")
    await resumed.resume(info["session_id"])

    history = await _next_of(resumed, "history")
    assert history["session_id"] == info["session_id"]
    assert resumed._ctx is selected


@pytest.mark.asyncio
async def test_opening_and_closing_an_empty_web_session_does_not_create_history(tmp_path):
    """仅打开应用而不发送消息时，不应持久化空会话。"""
    session_root = tmp_path / "sessions"
    ws = WebSession(_ctx(tmp_path, FakeProvider([]), Registry()), session_root=str(session_root))

    await ws.open()
    await ws.close()

    assert list_sessions(str(session_root)) == []
