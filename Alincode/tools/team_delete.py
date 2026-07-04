"""TeamDelete 工具：删除一个 Team（需所有成员空闲或 force=True）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from Alincode.tools import Result, Tool

if TYPE_CHECKING:
    from Alincode.team.manager import Manager


class TeamDeleteTool(Tool):
    """删除 Team 的全局工具（注册到主 registry）。"""

    def __init__(self, team_manager: "Manager"):
        self._mgr = team_manager

    def name(self) -> str:
        return "TeamDelete"

    @property
    def read_only(self) -> bool:
        return True

    def description(self) -> str:
        return "删除一个 Team(需所有成员空闲或 force=True)。"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "team_name": {"type": "string", "description": "团队名"},
                "force": {"type": "boolean", "description": "强制删除(忽略活跃成员)"},
            },
            "required": ["team_name"],
        }

    async def execute(self, args: str) -> Result:
        data = json.loads(args) if args.strip() else {}
        try:
            await self._mgr.delete(
                data.get("team_name", ""), bool(data.get("force", False))
            )
            return Result(content=json.dumps({"deleted": True}, ensure_ascii=False))
        except Exception as e:
            return Result(content=f"删除团队失败: {e}", is_error=True)
