"""共享任务列表 Store(T8)。

对应 spec F26-F30。CRUD + 依赖图(blocks/blocked_by 双向维护)。
文件:<team_config_dir>/tasks.json,read-modify-write + filelock。
is_ready 不存盘,list_ 输出时计算(blocked_by 全 completed 则 ready)。
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Alincode.team.filelock import acquire
from Alincode.team.persistence import atomic_write_json, read_json


class Status(str, Enum):
    """任务状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class Task:
    """任务(F30)。"""

    id: str = ""
    title: str = ""
    description: str = ""
    status: Status = Status.PENDING
    assignee: str = ""
    blocked_by: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0
    # 派生字段,不存盘
    is_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": str(self.status),
            "assignee": self.assignee,
            "blocked_by": list(self.blocked_by),
            "blocks": list(self.blocks),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        s = d.get("status", "pending")
        try:
            status = Status(s)
        except ValueError:
            status = Status.PENDING
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            status=status,
            assignee=d.get("assignee", ""),
            blocked_by=list(d.get("blocked_by", [])),
            blocks=list(d.get("blocks", [])),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
        )


@dataclass
class Filter:
    """查询过滤。"""

    status: Status | None = None


@dataclass
class Patch:
    """更新补丁(F29)。"""

    title: str | None = None
    description: str | None = None
    status: Status | None = None
    assignee: str | None = None
    add_blocks: list[str] | None = None
    add_blocked_by: list[str] | None = None
    remove_blocks: list[str] | None = None
    remove_blocked_by: list[str] | None = None


class TaskNotFoundError(Exception):
    """任务不存在。"""


class Store:
    """共享任务列表(F26-F30)。"""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock_path = path + ".lock"

    def _read_raw(self) -> dict[str, Any]:
        """读 tasks.json,不存在返回空结构。"""
        try:
            data = read_json(self._path)
            if not isinstance(data, dict):
                return {"tasks": []}
            return data
        except FileNotFoundError:
            return {"tasks": []}

    async def create(self, t: Task) -> str:
        """创建任务,返回 task_<6位hex> ID(F26)。"""
        async with acquire(self._lock_path):
            data = self._read_raw()
            t.id = f"task_{secrets.token_hex(3)}"
            now = int(time.time())
            t.created_at = now
            t.updated_at = now
            data.setdefault("tasks", []).append(t.to_dict())
            atomic_write_json(self._path, data)
            return t.id

    async def get(self, id_: str) -> Task:
        """按 id 查任务(F27)。"""
        async with acquire(self._lock_path):
            data = self._read_raw()
            for t in data.get("tasks", []):
                if isinstance(t, dict) and t.get("id") == id_:
                    return Task.from_dict(t)
        raise TaskNotFoundError(f"任务 '{id_}' 不存在")

    async def list_(self, filter_: Filter | None = None) -> list[Task]:
        """列任务,按 status 过滤,附加 is_ready(F28)。"""
        async with acquire(self._lock_path):
            data = self._read_raw()
            all_tasks = [
                Task.from_dict(t) for t in data.get("tasks", []) if isinstance(t, dict)
            ]
        completed_ids = {t.id for t in all_tasks if t.status == Status.COMPLETED}
        # 过滤
        if filter_ and filter_.status is not None:
            result = [t for t in all_tasks if t.status == filter_.status]
        else:
            result = all_tasks
        # 附加 is_ready
        for t in result:
            t.is_ready = all(bid in completed_ids for bid in t.blocked_by)
        return result

    async def update(self, id_: str, patch: Patch) -> None:
        """更新任务,双向维护 blocks/blocked_by(F29)。"""
        async with acquire(self._lock_path):
            data = self._read_raw()
            tasks = data.get("tasks", [])
            target: dict[str, Any] | None = None
            for t in tasks:
                if isinstance(t, dict) and t.get("id") == id_:
                    target = t
                    break
            if target is None:
                raise TaskNotFoundError(f"任务 '{id_}' 不存在")

            # 基本字段
            if patch.title is not None:
                target["title"] = patch.title
            if patch.description is not None:
                target["description"] = patch.description
            if patch.status is not None:
                target["status"] = str(patch.status)
            if patch.assignee is not None:
                target["assignee"] = patch.assignee

            target.setdefault("blocked_by", [])
            target.setdefault("blocks", [])

            # add_blocked_by:当前任务 blocked_by 加 X,X 的 blocks 加当前
            if patch.add_blocked_by:
                for bid in patch.add_blocked_by:
                    if bid not in target["blocked_by"]:
                        target["blocked_by"].append(bid)
                    for other in tasks:
                        if (
                            isinstance(other, dict)
                            and other.get("id") == bid
                            and id_ not in other.setdefault("blocks", [])
                        ):
                            other["blocks"].append(id_)

            # remove_blocked_by:当前任务 blocked_by 删 X,X 的 blocks 删当前
            if patch.remove_blocked_by:
                for bid in patch.remove_blocked_by:
                    if bid in target["blocked_by"]:
                        target["blocked_by"].remove(bid)
                    for other in tasks:
                        if (
                            isinstance(other, dict)
                            and other.get("id") == bid
                            and id_ in other.get("blocks", [])
                        ):
                            other["blocks"].remove(id_)

            # add_blocks:当前任务 blocks 加 X,X 的 blocked_by 加当前
            if patch.add_blocks:
                for bid in patch.add_blocks:
                    if bid not in target["blocks"]:
                        target["blocks"].append(bid)
                    for other in tasks:
                        if (
                            isinstance(other, dict)
                            and other.get("id") == bid
                            and id_ not in other.setdefault("blocked_by", [])
                        ):
                            other["blocked_by"].append(id_)

            # remove_blocks:当前任务 blocks 删 X,X 的 blocked_by 删当前
            if patch.remove_blocks:
                for bid in patch.remove_blocks:
                    if bid in target["blocks"]:
                        target["blocks"].remove(bid)
                    for other in tasks:
                        if (
                            isinstance(other, dict)
                            and other.get("id") == bid
                            and id_ in other.get("blocked_by", [])
                        ):
                            other["blocked_by"].remove(id_)

            target["updated_at"] = int(time.time())
            atomic_write_json(self._path, data)
