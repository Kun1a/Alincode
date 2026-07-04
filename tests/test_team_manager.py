"""Team Manager / persistence / types 单测(T1-T4 + T3b)。

覆盖 AC1-AC5、T2 sanitize/atomic_write、T3b reload_from_disk_locked、T4 成员操作。
"""

from __future__ import annotations

import os

import pytest

from Alincode.team import (
    BackendType,
    Manager,
    Team,
    TeammateInfo,
    TeamHasActiveMembersError,
    MemberExistsError,
    MemberNotFoundError,
)
from Alincode.team.persistence import (
    atomic_write_json,
    read_json,
    reload_from_disk_locked,
    sanitize,
)


# ---- T2: sanitize / atomic_write_json / read_json ----


class TestSanitize:
    def test_basic(self):
        assert sanitize("foo bar/baz") == "foo-bar-baz"

    def test_strip(self):
        assert sanitize("  hello  ") == "hello"

    def test_non_ascii_returns_empty(self):
        # 中文字符全部非法,替换为 - 后首尾去掉 = 空
        assert sanitize("团队") == ""

    def test_keep_valid_chars(self):
        assert sanitize("a.b-c_d") == "a.b-c_d"

    def test_all_dashes(self):
        assert sanitize("---") == ""

    def test_preserves_inner_dashes(self):
        # - 是合法字符,连续的 - 保留不折叠
        assert sanitize("a---b") == "a---b"


class TestAtomicWriteJson:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "test.json"
        data = {"name": "test", "members": [], "num": 42}
        atomic_write_json(p, data)
        assert read_json(p) == data

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "sub" / "deep" / "test.json"
        atomic_write_json(p, {"x": 1})
        assert read_json(p) == {"x": 1}

    def test_read_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_json(tmp_path / "nope.json")

    def test_overwrite(self, tmp_path):
        p = tmp_path / "f.json"
        atomic_write_json(p, {"v": 1})
        atomic_write_json(p, {"v": 2})
        assert read_json(p) == {"v": 2}


# ---- T1: types 序列化 ----


class TestSerialization:
    def test_teammate_is_active_none_preserved(self):
        """is_active=None 语义要保留(F2)。"""
        info = TeammateInfo(name="alice", agent_id="agent-1", is_active=None)
        d = info.to_dict()
        assert d["is_active"] is None
        info2 = TeammateInfo.from_dict(d)
        assert info2.is_active is None

    def test_teammate_backend_type_roundtrip(self):
        info = TeammateInfo(name="alice", agent_id="a1", backend_type=BackendType.TMUX)
        d = info.to_dict()
        assert d["backend_type"] == "tmux"
        info2 = TeammateInfo.from_dict(d)
        assert info2.backend_type == BackendType.TMUX

    def test_team_roundtrip(self):
        from datetime import datetime

        team = Team(
            name="demo",
            sanitized_name="demo",
            lead_agent_id="lead",
            backend=BackendType.IN_PROCESS,
            created_at=datetime.now(),
        )
        team.members.append(TeammateInfo(name="lead", agent_id="lead"))
        team.members.append(
            TeammateInfo(name="alice", agent_id="agent-1", is_active=False)
        )
        d = team.to_dict()
        assert "config_dir" not in d  # 派生路径不持久化
        assert "config_path" not in d
        team2 = Team.from_dict(d)
        assert team2.name == "demo"
        assert len(team2.members) == 2
        assert team2.members[1].is_active is False


# ---- T3: Manager 创建/获取/删除 ----


class TestManagerCreate:
    async def test_create_basic(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        assert team.sanitized_name == "demo"
        assert team.lead_agent_id == "lead"
        assert os.path.exists(team.config_path)
        assert os.path.isdir(team.mailbox_dir)
        data = read_json(team.config_path)
        assert data["name"] == "demo"
        assert data["backend"] == "in-process"  # Windows 无 tmux
        assert len(data["members"]) == 1
        assert data["members"][0]["name"] == "lead"

    async def test_create_sanitizes_name(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("refactor auth", "")
        assert team.sanitized_name == "refactor-auth"
        assert os.path.basename(team.config_dir) == "refactor-auth"

    async def test_create_duplicate_suffix(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        t1 = await mgr.create("demo", "")
        t2 = await mgr.create("demo", "")
        t3 = await mgr.create("demo", "")
        assert t1.sanitized_name == "demo"
        assert t2.sanitized_name == "demo-2"
        assert t3.sanitized_name == "demo-3"
        assert os.path.isdir(t1.config_dir)
        assert os.path.isdir(t2.config_dir)

    async def test_create_empty_name_rejected(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        from Alincode.team import TeamError

        with pytest.raises(TeamError):
            await mgr.create("---", "")  # sanitize 后为空

    async def test_get(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        await mgr.create("demo", "")
        assert mgr.get("demo") is not None
        assert mgr.get("nonexistent") is None

    async def test_list_sorted(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        await mgr.create("beta", "")
        await mgr.create("alpha", "")
        teams = mgr.list_()
        assert len(teams) == 2


class TestManagerDelete:
    async def test_force_false_with_active(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        await mgr.add_member(
            team, TeammateInfo(name="alice", agent_id="a1", is_active=None)
        )
        with pytest.raises(TeamHasActiveMembersError):
            await mgr.delete("demo", force=False)
        # 目录仍在
        assert os.path.isdir(team.config_dir)

    async def test_force_true_deletes(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        await mgr.add_member(
            team, TeammateInfo(name="alice", agent_id="a1", is_active=None)
        )
        await mgr.delete("demo", force=True)
        assert mgr.get("demo") is None
        assert not os.path.exists(team.config_dir)

    async def test_no_active_non_force_ok(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        await mgr.add_member(
            team, TeammateInfo(name="alice", agent_id="a1", is_active=False)
        )
        await mgr.delete("demo", force=False)
        assert mgr.get("demo") is None


class TestManagerRestore:
    async def test_restore_from_disk(self, tmp_path):
        mgr1 = Manager(project_root=tmp_path)
        await mgr1.create("demo", "test desc")
        # 新实例从磁盘恢复
        mgr2 = Manager(project_root=tmp_path)
        team = mgr2.get("demo")
        assert team is not None
        assert team.name == "demo"
        assert team.description == "test desc"
        assert len(team.members) == 1

    def test_restore_skips_corrupt(self, tmp_path, capsys):
        # 先建一个正常的
        Manager(project_root=tmp_path)
        # 手动写损坏的 config.json
        bad_dir = tmp_path / ".Alincode" / "team" / "corrupt"
        bad_dir.mkdir(parents=True)
        (bad_dir / "config.json").write_text("{invalid json", encoding="utf-8")
        mgr2 = Manager(project_root=tmp_path)
        assert mgr2.get("corrupt") is None
        captured = capsys.readouterr()
        assert "corrupt" in captured.err


# ---- T4: Team 成员操作 ----


class TestMemberOps:
    async def test_add_member(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        await mgr.add_member(
            team, TeammateInfo(name="alice", agent_id="a1", worktree_path="/tmp/wt")
        )
        assert team.member_by_name("alice") is not None
        data = read_json(team.config_path)
        names = [m["name"] for m in data["members"]]
        assert "alice" in names

    async def test_add_member_duplicate(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        await mgr.add_member(team, TeammateInfo(name="alice", agent_id="a1"))
        with pytest.raises(MemberExistsError):
            await mgr.add_member(team, TeammateInfo(name="alice", agent_id="a2"))

    async def test_set_member_active(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        await mgr.add_member(
            team, TeammateInfo(name="alice", agent_id="a1", is_active=None)
        )
        await mgr.set_member_active(team, "alice", False)
        assert team.member_by_name("alice").is_active is False
        data = read_json(team.config_path)
        for m in data["members"]:
            if m["name"] == "alice":
                assert m["is_active"] is False

    async def test_set_member_active_not_found(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        with pytest.raises(MemberNotFoundError):
            await mgr.set_member_active(team, "alice", False)

    async def test_remove_member(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        await mgr.add_member(team, TeammateInfo(name="alice", agent_id="a1"))
        await mgr.remove_member(team, "alice")
        assert team.member_by_name("alice") is None

    async def test_member_by_agent_id(self, tmp_path):
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        await mgr.add_member(team, TeammateInfo(name="alice", agent_id="agent-xyz"))
        m = team.member_by_agent_id("agent-xyz")
        assert m is not None
        assert m.name == "alice"
        assert team.member_by_agent_id("nope") is None


# ---- T3b: reload_from_disk_locked 跨进程兜底 ----


class TestReloadFromDisk:
    async def test_reload_finds_disk_member(self, tmp_path):
        """跨进程兜底:磁盘上有 alice,内存中没有,reload 后能看到。"""
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        assert team.member_by_name("alice") is None

        # 模拟另一个进程在磁盘上写了带 alice 的 config.json
        data = read_json(team.config_path)
        data["members"].append(
            {
                "name": "alice",
                "agent_id": "agent-1",
                "agent_type": "",
                "model": "",
                "worktree_path": "/tmp/wt",
                "branch": "",
                "backend_type": "in-process",
                "pane_id": "",
                "is_active": None,
                "plan_mode_required": False,
                "session_dir": "",
            }
        )
        atomic_write_json(team.config_path, data)

        # 内存中仍没有 alice(reload 前)
        assert team.member_by_name("alice") is None

        # set_member_active 应该走 reload 路径,找到 alice 并更新
        await mgr.set_member_active(team, "alice", False)
        assert team.member_by_name("alice").is_active is False

    async def test_reload_silent_on_missing_file(self, tmp_path):
        """config.json 不存在时 reload 静默回退。"""
        mgr = Manager(project_root=tmp_path)
        team = await mgr.create("demo", "")
        # 删掉 config.json
        os.unlink(team.config_path)
        async with team._lock:
            await reload_from_disk_locked(team)
        # 不抛错,内存现状不变
        assert len(team.members) == 1  # lead 还在
