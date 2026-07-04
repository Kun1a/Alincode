"""backend detect + Protocol 单测(T10-T11)。覆盖 AC6。"""

from __future__ import annotations

import pytest

from Alincode.team.backend import SpawnRequest, new_backend
from Alincode.team.backend.detect import detect
from Alincode.team.types import BackendType


class TestDetect:
    """AC6:detect() 的 4 种组合。"""

    def test_tmux_env(self, monkeypatch):
        # $TMUX 设置 → tmux
        monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1234,0")
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.setattr("shutil.which", lambda x: None)
        assert detect() == BackendType.TMUX

    def test_iterm2(self, monkeypatch):
        # $TERM_PROGRAM == "iTerm.app" 且 it2 可执行 → iterm2
        monkeypatch.delenv("TMUX", raising=False)
        monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
        monkeypatch.setattr(
            "shutil.which",
            lambda x: "/usr/local/bin/it2" if x == "it2" else None,
        )
        assert detect() == BackendType.ITERM2

    def test_tmux_binary(self, monkeypatch):
        # 都无 env 但 tmux 二进制在 PATH → tmux
        monkeypatch.delenv("TMUX", raising=False)
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.setattr(
            "shutil.which",
            lambda x: "/usr/bin/tmux" if x == "tmux" else None,
        )
        assert detect() == BackendType.TMUX

    def test_in_process_fallback(self, monkeypatch):
        # 都无 → in-process
        monkeypatch.delenv("TMUX", raising=False)
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.setattr("shutil.which", lambda x: None)
        assert detect() == BackendType.IN_PROCESS

    def test_iterm2_without_it2_falls_through(self, monkeypatch):
        # $TERM_PROGRAM == "iTerm.app" 但 it2 不可执行 → 继续找 tmux
        monkeypatch.delenv("TMUX", raising=False)
        monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
        monkeypatch.setattr("shutil.which", lambda x: None)
        assert detect() == BackendType.IN_PROCESS


class TestSpawnRequest:
    def test_defaults(self):
        req = SpawnRequest(
            team_name="demo",
            member_name="alice",
            agent_id="agent-1",
            worktree_path="/tmp/wt",
            session_dir="/tmp/sess",
        )
        assert req.team_name == "demo"
        assert req.agent_id == "agent-1"
        assert req.agent_type == ""
        assert req.model == ""
        assert req.initial_prompt == ""
        assert req.plan_mode_required is False
        assert req.sub_agent is None
        assert req.conv is None
        assert req.task_mgr is None


class TestNewBackend:
    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            new_backend("unknown")  # type: ignore[arg-type]
