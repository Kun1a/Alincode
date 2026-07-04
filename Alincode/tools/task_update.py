"""TaskUpdate 工具：更新任务，支持 add_blocks/add_blocked_by 双向依赖。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from Alincode.tools import Result, Tool
from Alincode.tools._team_helpers import get_team, json_result
from Alincode.team.tasks import Patch, Status, Store, TaskNotFoundError

if TYPE_CHECKING:
    from Alincode.team.manager import Manager


class TaskUpdateTool(Tool):
    """更新任务，支持 add_blocks/add_blocked_by 双向依赖。"""

    def __init__(self, team_manager: "Manager", team_name: str = ""):
        self._mgr = team_manager
        self._team_name = team_name

    def name(self) -> str:
        return "TaskUpdate"

    @property
    def read_only(self) -> bool:
        return True

    def description(self) -> str:
        return "更新任务,支持 add_blocks/add_blocked_by 双向依赖。"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务 id"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {"type": "string"},
                "assignee": {"type": "string"},
                "add_blocks": {"type": "array", "items": {"type": "string"}},
                "add_blocked_by": {"type": "array", "items": {"type": "string"}},
                "remove_blocks": {"type": "array", "items": {"type": "string"}},
                "remove_blocked_by": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task_id"],
        }

    async def execute(self, args: str) -> Result:
        data = json.loads(args) if args.strip() else {}
        team = get_team(self._mgr, self._team_name)
        if team is None:
            return Result(content="不在 Team 上下文中", is_error=True)
        store = Store(team.tasks_path)
        tid = data.get("task_id", "")
        patch_kwargs: dict[str, Any] = {}
        for key in (
            "title",
            "description",
            "assignee",
            "add_blocks",
            "add_blocked_by",
            "remove_blocks",
            "remove_blocked_by",
        ):
            if key in data:
                patch_kwargs[key] = data[key]
        if "status" in data:
            try:
                patch_kwargs["status"] = Status(data["status"])
            except ValueError:
                return Result(content=f"未知状态: {data['status']}", is_error=True)
        try:
            await store.update(tid, Patch(**patch_kwargs))
            return json_result({"updated": True})
        except TaskNotFoundError as e:
            return Result(content=str(e), is_error=True)
