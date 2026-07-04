"""TeamCreate 工具：创建一个 Team，Lead 自动成为第一个成员。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from Alincode.tools import Result, Tool

if TYPE_CHECKING:
    from Alincode.team.manager import Manager


class TeamCreateTool(Tool):
    """创建 Team 的全局工具（注册到主 registry）。"""

    def __init__(self, team_manager: "Manager"):
        self._mgr = team_manager

    def name(self) -> str:
        return "TeamCreate"

    @property
    def read_only(self) -> bool:
        return True

    def description(self) -> str:
        return "创建一个 Team,Lead 自动成为第一个成员。"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "team_name": {"type": "string", "description": "团队名"},
                "description": {"type": "string", "description": "团队描述"},
            },
            "required": ["team_name"],
        }

    async def execute(self, args: str) -> Result:
        data = json.loads(args) if args.strip() else {}
        try:
            team = await self._mgr.create(
                data.get("team_name", ""), data.get("description", "")
            )
            self._mgr.active_team = team.sanitized_name
            return Result(
                content=json.dumps(
                    {
                        "team_name": team.sanitized_name,
                        "backend": str(team.backend),
                        "config_path": team.config_path,
                    },
                    ensure_ascii=False,
                )
            )
        except Exception as e:
            return Result(content=f"创建团队失败: {e}", is_error=True)
