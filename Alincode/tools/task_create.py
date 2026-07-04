"""TaskCreate 工具：在当前 Team 的共享任务列表里创建任务。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from Alincode.tools import Result, Tool
from Alincode.tools._team_helpers import get_team, json_result
from Alincode.team.tasks import Patch, Store, Task

if TYPE_CHECKING:
    from Alincode.team.manager import Manager


class TaskCreateTool(Tool):
    """在 Team 共享任务列表里创建任务。

    team_name 为空时从 TeammateContext 解析（全局注册场景）。
    build_teammate_tools 构造时绑 team_name（per-team 实例化）。
    """

    def __init__(self, team_manager: "Manager", team_name: str = ""):
        self._mgr = team_manager
        self._team_name = team_name

    def name(self) -> str:
        return "TaskCreate"

    @property
    def read_only(self) -> bool:
        return True

    def description(self) -> str:
        return "在当前 Team 的共享任务列表里创建任务。"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "任务标题"},
                "description": {"type": "string", "description": "任务详情"},
                "assignee": {"type": "string", "description": "指派队员名"},
                "blocked_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "依赖的任务 id 列表",
                },
            },
            "required": ["title"],
        }

    async def execute(self, args: str) -> Result:
        data = json.loads(args) if args.strip() else {}
        team = get_team(self._mgr, self._team_name)
        if team is None:
            return Result(content="不在 Team 上下文中", is_error=True)
        store = Store(team.tasks_path)
        t = Task(
            title=data.get("title", ""),
            description=data.get("description", ""),
            assignee=data.get("assignee", ""),
        )
        tid = await store.create(t)
        blocked_by = data.get("blocked_by", [])
        if blocked_by:
            await store.update(tid, Patch(add_blocked_by=blocked_by))
        return json_result({"task_id": tid})
