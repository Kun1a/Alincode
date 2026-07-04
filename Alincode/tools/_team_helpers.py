"""Team 工具共享辅助函数。

_get_team: 按 team_name 绑定 → TeammateContext → list_ 首个 顺序解析 Team。
_json_result: 快速构造 JSON Result。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from Alincode.tools import Result

if TYPE_CHECKING:
    from Alincode.team.manager import Manager
    from Alincode.team.types import Team


def get_team(team_manager: "Manager", team_name: str = "") -> "Team | None":
    """获取 Team：优先用绑定的 team_name，否则从 TeammateContext 取，最后取首个。"""
    if team_name:
        team = team_manager.get(team_name)
        if team is not None:
            return team
    # fallback: 从 TeammateContext 取
    from Alincode.team_hook import teammate_context

    tc = teammate_context()
    if tc is not None:
        team = team_manager.get(tc.team_name)
        if team is not None:
            return team
    teams = team_manager.list_()
    if teams:
        return teams[0]
    return None


def json_result(d: dict[str, Any]) -> Result:
    """快速构造 JSON Result。"""
    return Result(content=json.dumps(d, ensure_ascii=False))
