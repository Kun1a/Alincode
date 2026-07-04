"""Backend Protocol + SpawnRequest + new_backend 工厂(T10)。

对应 spec F12-F13。三种后端(tmux/iterm2/in-process)各一个子模块,
通过 new_backend 工厂按 BackendType 分发。
sub_agent/conv/task_mgr 字段类型为 Any,避免 backend 反向依赖 agent 包。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from Alincode.team.types import BackendType


@dataclass
class SpawnRequest:
    """spawn 请求(F13)。

    Pane 后端(tmux/iterm2)用 team_name/member_name/agent_id/worktree_path 等
    构造 CLI 命令;initial_prompt 不走命令行,由 spawn 前预写入 mailbox。
    in-process 后端用 sub_agent/conv/task_mgr 直接起 asyncio task。
    """

    team_name: str
    member_name: str
    agent_id: str
    worktree_path: str
    session_dir: str
    agent_type: str = ""
    model: str = ""
    initial_prompt: str = ""
    plan_mode_required: bool = False
    # in-process 专用——同进程后端直接复用这三个对象
    sub_agent: Any = None  # agent.Agent
    conv: Any = None  # conversation.Conversation
    task_mgr: Any = None  # task.Manager


class Backend(Protocol):
    """后端抽象(F12)。三方法:spawn / wake / kill。"""

    def type(self) -> BackendType: ...
    # spawn 在后端启动一个新队员;返回 (pane_id, agent_id)
    async def spawn(self, req: SpawnRequest) -> tuple[str, str]: ...
    # wake 用于消息到达时唤醒目标 pane。in-process 后端为 no-op
    async def wake(self, pane_id: str, agent_id: str) -> None: ...
    # kill 终止 pane(Pane 后端)或 cancel task(in-process)
    async def kill(self, pane_id: str, agent_id: str) -> None: ...


def new_backend(t: BackendType, **deps: Any) -> Backend:
    """按 BackendType 分发到具体后端(T12-T14 实现后补全)。"""
    if t == BackendType.IN_PROCESS:
        from Alincode.team.backend.inprocess import InProcessBackend

        return InProcessBackend(deps.get("task_mgr"))
    if t == BackendType.TMUX:
        from Alincode.team.backend.tmux import TmuxBackend

        return TmuxBackend()
    if t == BackendType.ITERM2:
        from Alincode.team.backend.iterm2 import Iterm2Backend

        return Iterm2Backend()
    raise ValueError(f"未知后端类型: {t}")
