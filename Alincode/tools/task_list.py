"""TaskList 工具：列任务，可按 status 过滤，带 is_ready 字段。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from Alincode.tools import Result, Tool
from Alincode.tools._team_helpers import get_team, json_result
from Alincode.team.tasks import Filter, Status, Store

if TYPE_CHECKING:
    from Alincode.team.manager import Manager


class TaskListTool(Tool):
    """列任务，可按 status 过滤。

    name 为 "TaskList"（去掉 Team 前缀）。
    """

    def __init__(self, team_manager: "Manager", team_name: str = ""):
        self._mgr = team_manager
        self._team_name = team_name

    def name(self) -> str:
        return "TaskList"

    @property
    def read_only(self) -> bool:
        return True

    def description(self) -> str:
        return "列任务,可按 status 过滤,带 is_ready 字段。"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "过滤状态:pending/in_progress/completed/blocked",
                },
            },
        }

    async def execute(self, args: str) -> Result:
        data = json.loads(args) if args.strip() else {}
        team = get_team(self._mgr, self._team_name)
        if team is None:
            return Result(content="不在 Team 上下文中", is_error=True)
        store = Store(team.tasks_path)
        status_str = data.get("status", "")
        filt = None
        if status_str:
            try:
                filt = Filter(status=Status(status_str))
            except ValueError:
                return Result(content=f"未知状态: {status_str}", is_error=True)
        tasks = await store.list_(filt)
        return json_result({"tasks": [t.to_dict() for t in tasks]})
