"""4 个后台任务工具：TaskList / TaskGet / TaskStop / SendMessage（T23）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from Alincode.tools import Result

if TYPE_CHECKING:
    from Alincode.task.manager import Manager


class TaskListTool:
    def __init__(self, manager: "Manager") -> None:
        self._mgr = manager

    def name(self) -> str:
        return "TaskList"

    @property
    def read_only(self) -> bool:
        return True

    def description(self) -> str:
        return "列出所有后台任务（running/completed/failed/cancelled）"

    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: str) -> Result:
        tasks = self._mgr.list()
        items = [{
            "id": bt.id, "name": bt.name,
            "status": bt.status.name.lower(),
            "tool_count": bt.tool_count,
            "last_activity": bt.last_activity,
        } for bt in tasks]
        return Result(content=json.dumps(items, ensure_ascii=False))


class TaskGetTool:
    def __init__(self, manager: "Manager") -> None:
        self._mgr = manager

    def name(self) -> str:
        return "TaskGet"

    @property
    def read_only(self) -> bool:
        return True

    def description(self) -> str:
        return "获取指定后台任务的完整状态"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "任务 ID"}},
            "required": ["task_id"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            return Result(content="invalid JSON args", is_error=True)
        task_id = data.get("task_id", "")
        bt = self._mgr.get(task_id)
        if bt is None:
            return Result(content=f"task {task_id} not found", is_error=True)
        return Result(content=json.dumps({
            "id": bt.id, "name": bt.name, "status": bt.status.name.lower(),
            "task": bt.task, "result": bt.result,
            "tool_count": bt.tool_count, "last_activity": bt.last_activity,
            "usage": {"input": bt.usage.input, "output": bt.usage.output},
            "err": str(bt.err) if bt.err else None,
        }, ensure_ascii=False))


class TaskStopTool:
    def __init__(self, manager: "Manager") -> None:
        self._mgr = manager

    def name(self) -> str:
        return "TaskStop"

    @property
    def read_only(self) -> bool:
        return False

    def description(self) -> str:
        return "取消指定的后台任务"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "任务 ID"}},
            "required": ["task_id"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            return Result(content="invalid JSON args", is_error=True)
        task_id = data.get("task_id", "")
        ok = await self._mgr.stop(task_id)
        if not ok:
            return Result(content=f"task {task_id} not found", is_error=True)
        return Result(content=json.dumps({"status": "cancellation_requested"}))


class SendMessageTool:
    def __init__(self, manager: "Manager") -> None:
        self._mgr = manager

    def name(self) -> str:
        return "SendMessage"

    @property
    def read_only(self) -> bool:
        return False

    def description(self) -> str:
        return "给已完成的 Agent 续派新任务（按 name 查找）"

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent 名称"},
                "message": {"type": "string", "description": "新任务消息"},
            },
            "required": ["name", "message"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            return Result(content="invalid JSON args", is_error=True)
        name = data.get("name", "")
        message = data.get("message", "")
        if not name or not message:
            return Result(content="name and message are required", is_error=True)
        try:
            task_id = await self._mgr.send_message(name, message)
            return Result(content=json.dumps({"task_id": task_id, "status": "resumed"}))
        except Exception as e:
            return Result(content=str(e), is_error=True)
