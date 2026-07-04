"""TeamHook / TeammateContext 单测(T16)。"""

from __future__ import annotations


from Alincode.team_hook import (
    IncomingMessage,
    TeamSpawnRequest,
    TeammateContext,
    reset_teammate_context,
    set_teammate_context,
    teammate_context,
)


class TestTeammateContext:
    def test_defaults(self):
        tc = TeammateContext(team_name="demo", member_name="alice", agent_id="agent-1")
        assert tc.team_name == "demo"
        assert tc.member_name == "alice"
        assert tc.agent_id == "agent-1"
        assert tc.backend_type == "in-process"
        assert tc.read_unread is not None
        assert tc.mark_read is not None

    async def test_noop_closures(self):
        tc = TeammateContext(team_name="demo", member_name="alice", agent_id="agent-1")
        indices, msgs = await tc.read_unread()
        assert indices == []
        assert msgs == []
        await tc.mark_read([0, 1])  # no-op,不抛错


class TestContextVar:
    def test_set_get_reset(self):
        tc = TeammateContext(team_name="demo", member_name="alice", agent_id="agent-1")
        assert teammate_context() is None
        token = set_teammate_context(tc)
        assert teammate_context() is tc
        reset_teammate_context(token)
        assert teammate_context() is None

    def test_isolation_per_task(self):
        """contextvars 在不同 asyncio task 间隔离。"""
        import asyncio

        tc = TeammateContext(team_name="demo", member_name="alice", agent_id="agent-1")

        async def child():
            # 子 task 默认看不到父的 set(如果 set 在父的 context copy 之后)
            return teammate_context()

        async def main():
            set_teammate_context(tc)
            # 子 task 继承父的 context(含 set)
            result = await asyncio.create_task(child())
            return result

        result = asyncio.run(main())
        assert result is tc


class TestIncomingMessage:
    def test_dataclass(self):
        msg = IncomingMessage(from_="lead", summary="hi", content="hello")
        assert msg.from_ == "lead"
        assert msg.type == "text"
        assert msg.summary == "hi"
        assert msg.content == "hello"
        assert msg.timestamp == 0
        assert msg.payload is None


class TestTeamSpawnRequest:
    def test_defaults(self):
        req = TeamSpawnRequest(team_name="demo", member_name="alice", prompt="do work")
        assert req.team_name == "demo"
        assert req.member_name == "alice"
        assert req.prompt == "do work"
        assert req.subagent_type == ""
        assert req.model == ""
        assert req.plan_mode_required is False
