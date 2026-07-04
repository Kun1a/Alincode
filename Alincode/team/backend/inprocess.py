"""In-process 后端(T14)。

对应 spec F18-F19。同进程 asyncio task 跑 run_to_completion,
复用 task.Manager.launch。wake 为 no-op(同进程下一轮 Loop 自动读邮箱)。
in-process 队员只允许同步子 Agent,不能再 spawn Team 队员(F19)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Alincode.team.backend import SpawnRequest
from Alincode.team.types import BackendType

if TYPE_CHECKING:
    from Alincode.task.manager import Manager as TaskManager


class InProcessBackend:
    """同进程后端:在事件循环里起 asyncio task 跑队员。"""

    def __init__(self, task_mgr: "TaskManager | None" = None) -> None:
        self._task_mgr = task_mgr

    def type(self) -> BackendType:
        return BackendType.IN_PROCESS

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        """spawn 队员:调 task_mgr.launch 起 asyncio task(F18)。

        返回 ("", task_id)——in-process 用 agent_id 作为目标 id,pane_id 为空。
        """
        if self._task_mgr is None:
            raise RuntimeError("InProcessBackend 需要 task_mgr 依赖")
        if req.sub_agent is None or req.conv is None:
            raise RuntimeError(
                "InProcessBackend.spawn 需要 SpawnRequest.sub_agent 和 conv"
            )
        task_id = await self._task_mgr.launch(
            req.sub_agent,
            req.conv,
            req.member_name,
            req.initial_prompt,
        )
        return ("", task_id)

    async def wake(self, pane_id: str, agent_id: str) -> None:
        """no-op:同进程,下一轮 Loop 自动读邮箱(F18)。"""
        pass

    async def kill(self, pane_id: str, agent_id: str) -> None:
        """cancel asyncio task(F18)。"""
        if self._task_mgr is not None:
            await self._task_mgr.stop(agent_id)
