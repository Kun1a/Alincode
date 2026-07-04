"""TaskGet 工具：按 id 查询任务详情。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from Alincode.tools import Result, Tool
from Alincode.tools._team_helpers import get_team, json_result
from Alincode.team.tasks import Store, TaskNotFoundError

if TYPE_CHECKING:
    from Alincode.team.manager import Manager


class TaskGetTool(Tool):
    """按 id 查询任务详情。

    name 为 "TaskGet"（去掉 Team 前缀）。
    """

    def __init__(self, team_manager: "Manager", team_name: str = ""):
        self._mgr = team_manager
        self._team_name = team_name

    def name(self) -> str:
        return "TaskGet"

    @property
    def read_only(self) -> bool:
        return True

    def description(self) -> str:
        return "按 id 查询任务详情。"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 id"},
            },
            "required": ["task_id"],
        }

    async def execute(self, args: str) -> Result:
        data = json.loads(args) if args.strip() else {}
        team = get_team(self._mgr, self._team_name)
        if team is None:
            return Result(content="不在 Team 上下文中", is_error=True)
        store = Store(team.tasks_path)
        try:
            t = await store.get(data.get("task_id", ""))
            return json_result(t.to_dict())
        except TaskNotFoundError as e:
            return Result(content=str(e), is_error=True)
