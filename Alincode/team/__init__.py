"""Team 包:把 ch13 SubAgent 扩展为 Team 队员,实现网状协作。

数据模型层(Team / TeammateInfo / BackendType)+ Manager 持久化协调入口。
依赖方向:agent ──→ team ──→ {backend, mailbox, registry, tasks, tools}
"""

from __future__ import annotations

from Alincode.team.types import (
    BackendType,
    Team,
    TeammateInfo,
    TeamError,
    TeamNotFoundError,
    TeamHasActiveMembersError,
    MemberExistsError,
    MemberNotFoundError,
    InProcessTeammateNoSpawnError,
)
from Alincode.team.manager import Manager, LeadMessage

__all__ = [
    "BackendType",
    "Team",
    "TeammateInfo",
    "TeamError",
    "TeamNotFoundError",
    "TeamHasActiveMembersError",
    "MemberExistsError",
    "MemberNotFoundError",
    "InProcessTeammateNoSpawnError",
    "Manager",
    "LeadMessage",
]
