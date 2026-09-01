"""Team 核心数据结构:Team / TeammateInfo / BackendType 与异常类。

对应 spec F1-F2、F11、F63;plan.md「核心数据结构」段。
所有字段命名与 config.json 的 json key 对齐(下划线命名),
序列化通过手写 to_dict / from_dict 控制 is_active 的 None 语义(F19c)。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BackendType(str, Enum):
    """队员执行后端类型。"""

    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"


@dataclass
class TeammateInfo:
    """队员信息(F2)。

    is_active: None/True 表活跃,False 表空闲;终止后直接从 members 移除。
    """

    name: str
    agent_id: str
    agent_type: str = ""  # "" 表 Fork 路径
    model: str = ""  # "" 表 inherit
    worktree_path: str = ""  # 绝对路径
    branch: str = ""
    backend_type: BackendType = BackendType.IN_PROCESS
    pane_id: str = ""  # tmux pane id / iterm2 split id / "" for in-process
    is_active: bool | None = None  # None/True 活跃,False 空闲
    plan_mode_required: bool = False
    session_dir: str = ""  # 绝对路径

    def to_dict(self) -> dict[str, Any]:
        """序列化为 config.json 的 member 条目。"""
        return {
            "name": self.name,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "model": self.model,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "backend_type": self.backend_type.value,
            "pane_id": self.pane_id,
            "is_active": self.is_active,  # 保留 None 语义
            "plan_mode_required": self.plan_mode_required,
            "session_dir": self.session_dir,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TeammateInfo:
        """从 config.json 的 member 条目反序列化。"""
        bt = d.get("backend_type", "in-process")
        # 兼容字符串与枚举
        try:
            backend_type = BackendType(bt)
        except ValueError:
            backend_type = BackendType.IN_PROCESS
        return cls(
            name=d.get("name", ""),
            agent_id=d.get("agent_id", ""),
            agent_type=d.get("agent_type", ""),
            model=d.get("model", ""),
            worktree_path=d.get("worktree_path", ""),
            branch=d.get("branch", ""),
            backend_type=backend_type,
            pane_id=d.get("pane_id", ""),
            is_active=d.get("is_active", None),
            plan_mode_required=d.get("plan_mode_required", False),
            session_dir=d.get("session_dir", ""),
        )


@dataclass
class Team:
    """Team 小组对象(F1)。

    持久化字段(name/sanitized_name/lead_agent_id/backend/description/created_at/members)
    落 config.json;派生路径字段(config_dir 等)不持久化,由 Manager 填充。
    _lock 保护 members 的 read-modify-write,不参与序列化与比较。
    """

    name: str  # 用户给的原始名
    sanitized_name: str  # 经 sanitize 后用于路径,Team 主键
    lead_agent_id: str  # 固定 "lead"(本期 Lead = 主 Agent)
    backend: BackendType = BackendType.IN_PROCESS  # 全 team 默认后端
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    members: list[TeammateInfo] = field(default_factory=list)

    # 派生路径(不持久化,由 Manager 填充)
    config_dir: str = ""
    config_path: str = ""  # <config_dir>/config.json
    tasks_path: str = ""  # <config_dir>/tasks.json
    mailbox_dir: str = ""  # <config_dir>/mailbox/

    # 并发锁:保护 members 的 read-modify-write(跨进程需配合 reload_from_disk_locked)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 config.json(F63)。派生路径字段不写入。"""
        return {
            "name": self.name,
            "sanitized_name": self.sanitized_name,
            "lead_agent_id": self.lead_agent_id,
            "backend": self.backend.value,
            "description": self.description,
            "created_at": int(self.created_at.timestamp()),
            "members": [m.to_dict() for m in self.members],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Team:
        """从 config.json 反序列化。派生路径字段留空,由 Manager 填充。"""
        bt = d.get("backend", "in-process")
        try:
            backend = BackendType(bt)
        except ValueError:
            backend = BackendType.IN_PROCESS
        # created_at 可能是 timestamp(int)或 ISO 字符串
        ca = d.get("created_at", 0)
        if isinstance(ca, (int, float)):
            created_at = datetime.fromtimestamp(ca)
        elif isinstance(ca, str):
            try:
                created_at = datetime.fromisoformat(ca)
            except ValueError:
                created_at = datetime.now()
        else:
            created_at = datetime.now()
        return cls(
            name=d.get("name", ""),
            sanitized_name=d.get("sanitized_name", ""),
            lead_agent_id=d.get("lead_agent_id", "lead"),
            backend=backend,
            description=d.get("description", ""),
            created_at=created_at,
            members=[TeammateInfo.from_dict(m) for m in d.get("members", [])],
        )

    def fill_derived_paths(self, config_dir: str) -> None:
        """根据 config_dir 填充派生路径字段。"""
        import os

        self.config_dir = config_dir
        self.config_path = os.path.join(config_dir, "config.json")
        self.tasks_path = os.path.join(config_dir, "tasks.json")
        self.mailbox_dir = os.path.join(config_dir, "mailbox")

    def member_by_name(self, name: str) -> TeammateInfo | None:
        """按队员名查成员。"""
        for m in self.members:
            if m.name == name:
                return m
        return None

    def member_by_agent_id(self, agent_id: str) -> TeammateInfo | None:
        """按 agent_id 查成员。"""
        for m in self.members:
            if m.agent_id == agent_id:
                return m
        return None


# ---- 异常类 ----


class TeamError(Exception):
    """Team 相关错误基类。"""


class TeamNotFoundError(TeamError):
    """Team 不存在。"""


class TeamHasActiveMembersError(TeamError):
    """Team 仍有活跃成员,不能删除。"""


class MemberExistsError(TeamError):
    """队员名在 Team 内已存在。"""


class MemberNotFoundError(TeamError):
    """队员不存在。"""


class InProcessTeammateNoSpawnError(TeamError):
    """in-process 后端队员不许再 spawn 队员(避免无限递归)。"""
