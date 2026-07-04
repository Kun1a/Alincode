"""三种后端单测(T12/T13/T14)。命令构造 + mock subprocess + mock task_mgr。"""

from __future__ import annotations

import asyncio

import pytest

from Alincode.team.backend import SpawnRequest
from Alincode.team.backend.inprocess import InProcessBackend
from Alincode.team.backend.iterm2 import Iterm2Backend
from Alincode.team.backend.tmux import TmuxBackend, build_member_cmd
from Alincode.team.types import BackendType


# ---- Fake 对象 ----


class FakeProc:
    """模拟 asyncio.subprocess.Process。"""

    def __init__(self, stdout=b"%5\n", returncode=0):
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, b""

    async def wait(self):
        return self.returncode


def make_req(**kw) -> SpawnRequest:
    """构造测试用 SpawnRequest。"""
    defaults = dict(
        team_name="demo",
        member_name="alice",
        agent_id="agent-1",
        worktree_path="/tmp/wt",
        session_dir="/tmp/sess",
    )
    defaults.update(kw)
    return SpawnRequest(**defaults)


# ---- T12: TmuxBackend ----


class TestBuildMemberCmd:
    def test_basic_fields(self):
        cmd = build_member_cmd(make_req())
        assert "--team" in cmd
        assert "demo" in cmd
        assert "--member" in cmd
        assert "alice" in cmd
        assert "--agent-id" in cmd
        assert "agent-1" in cmd
        assert "--session-dir" in cmd
        assert "--worktree" in cmd

    def test_optional_fields(self):
        cmd = build_member_cmd(
            make_req(
                agent_type="general-purpose", model="gpt-4", plan_mode_required=True
            )
        )
        assert "--agent-type" in cmd
        assert "general-purpose" in cmd
        assert "--model" in cmd
        assert "gpt-4" in cmd
        assert "--plan-mode" in cmd

    def test_no_optional_fields(self):
        cmd = build_member_cmd(make_req())
        assert "--agent-type" not in cmd
        assert "--model" not in cmd
        assert "--plan-mode" not in cmd


class TestTmuxBackend:
    def test_type(self):
        assert TmuxBackend().type() == BackendType.TMUX

    async def test_spawn_in_tmux(self, monkeypatch):
        """$TMUX 设置时走 split-window。"""
        monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1234,0")
        captured = []

        async def fake_exec(*args, **kwargs):
            captured.append(args)
            return FakeProc(stdout=b"%5\n")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        pane_id, agent_id = await TmuxBackend().spawn(make_req())
        assert pane_id == "%5"
        assert agent_id == "agent-1"
        assert "tmux" in captured[0]
        assert "split-window" in captured[0]

    async def test_spawn_outside_tmux(self, monkeypatch):
        """$TMUX 未设时走 new-session -d(F16)。"""
        monkeypatch.delenv("TMUX", raising=False)
        captured = []

        async def fake_exec(*args, **kwargs):
            captured.append(args)
            return FakeProc(stdout=b"%7\n")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        pane_id, _ = await TmuxBackend().spawn(make_req())
        assert pane_id == "%7"
        assert "new-session" in captured[0]

    async def test_spawn_failure_raises(self, monkeypatch):
        monkeypatch.setenv("TMUX", "x")

        async def fake_exec(*a, **k):
            return FakeProc(returncode=1, stdout=b"")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        with pytest.raises(RuntimeError, match="tmux spawn 失败"):
            await TmuxBackend().spawn(make_req())

    async def test_wake(self, monkeypatch):
        captured = []

        async def fake_exec(*args, **kwargs):
            captured.append(args)
            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        await TmuxBackend().wake("%5", "agent-1")
        assert "send-keys" in captured[0]
        assert "%5" in captured[0]

    async def test_kill(self, monkeypatch):
        captured = []

        async def fake_exec(*args, **kwargs):
            captured.append(args)
            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        await TmuxBackend().kill("%5", "agent-1")
        assert "kill-pane" in captured[0]


# ---- T13: Iterm2Backend ----


class TestIterm2Backend:
    def test_type(self):
        assert Iterm2Backend().type() == BackendType.ITERM2

    async def test_spawn(self, monkeypatch):
        captured = []

        async def fake_exec(*args, **kwargs):
            captured.append(args)
            return FakeProc(stdout=b"split-1\n")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        pane_id, agent_id = await Iterm2Backend().spawn(make_req())
        assert pane_id == "split-1"
        assert agent_id == "agent-1"
        args = captured[0]
        assert "it2" in args
        assert "split" in args

    async def test_wake(self, monkeypatch):
        captured = []

        async def fake_exec(*args, **kwargs):
            captured.append(args)
            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        await Iterm2Backend().wake("split-1", "agent-1")
        assert "send-text" in captured[0]

    async def test_kill(self, monkeypatch):
        captured = []

        async def fake_exec(*args, **kwargs):
            captured.append(args)
            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        await Iterm2Backend().kill("split-1", "agent-1")
        assert "close-pane" in captured[0]


# ---- T14: InProcessBackend ----


class FakeTaskMgr:
    """模拟 task.Manager。"""

    def __init__(self):
        self.launch_args = None
        self.stop_args = None

    async def launch(self, ag, conv, name, task_text):
        self.launch_args = (ag, conv, name, task_text)
        return "task-123"

    async def stop(self, task_id):
        self.stop_args = (task_id,)
        return True


class TestInProcessBackend:
    def test_type(self):
        assert InProcessBackend().type() == BackendType.IN_PROCESS

    async def test_spawn(self):
        tm = FakeTaskMgr()
        backend = InProcessBackend(tm)
        req = make_req(
            sub_agent="fake_agent",
            conv="fake_conv",
            initial_prompt="do something",
        )
        pane_id, agent_id = await backend.spawn(req)
        assert pane_id == ""  # in-process 无 pane
        assert agent_id == "task-123"  # in-process 用 task_id 作为 agent_id(F18)
        assert tm.launch_args == ("fake_agent", "fake_conv", "alice", "do something")

    async def test_spawn_no_task_mgr_raises(self):
        backend = InProcessBackend()
        with pytest.raises(RuntimeError, match="task_mgr"):
            await backend.spawn(make_req(sub_agent="x", conv="y"))

    async def test_spawn_no_sub_agent_raises(self):
        backend = InProcessBackend(FakeTaskMgr())
        with pytest.raises(RuntimeError, match="sub_agent"):
            await backend.spawn(make_req())

    async def test_wake_noop(self):
        backend = InProcessBackend(FakeTaskMgr())
        await backend.wake("", "agent-1")  # 不抛错

    async def test_kill(self):
        tm = FakeTaskMgr()
        backend = InProcessBackend(tm)
        await backend.kill("", "agent-1")
        assert tm.stop_args == ("agent-1",)
