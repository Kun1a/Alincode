"""TeamHook Protocol + TeammateContext(T16)。

对应 spec F25、plan.md「agent 包扩展」段。
agent.py 是单文件(非包),本模块放 Alincode/ 根下,与 agent.py 同级。
TeammateContext 用 contextvars.ContextVar 注入,每个 asyncio task 独立。
read_unread / mark_read 走闭包注入(避免 agent 包反向依赖 mailbox)。
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


@dataclass
class IncomingMessage:
    """队员收到的消息(轻量,独立于 mailbox.Message)。

    agent 包不直接 import mailbox(避免循环);由 team 包在闭包里转换。
    """

    from_: str
    type: str = "text"
    summary: str = ""
    content: str = ""
    timestamp: int = 0
    payload: dict[str, Any] | None = None


@dataclass
class TeamSpawnRequest:
    """Agent 工具 → TeamHook.spawn_teammate 的请求(F25)。"""

    team_name: str
    member_name: str
    subagent_type: str = ""
    model: str = ""
    prompt: str = ""
    plan_mode_required: bool = False


@dataclass
class TeammateContext:
    """队员执行上下文(T16)。

    由 team 包在 spawn 时构造闭包注入,避免 agent 包反向依赖 mailbox。
    read_unread 返回 (indices, list[IncomingMessage])。
    """

    team_name: str
    member_name: str
    agent_id: str
    worktree_path: str = ""
    backend_type: str = "in-process"
    # 闭包:读未读消息
    read_unread: Callable[[], Awaitable[tuple[list[int], list[IncomingMessage]]]] = (
        field(default_factory=lambda: _noop_read_unread)
    )
    # 闭包:标记已读
    mark_read: Callable[[list[int]], Awaitable[None]] = field(
        default_factory=lambda: _noop_mark_read
    )
    # 闭包:切换权限模式(Plan 审批用,T32)
    set_permission_mode: Callable[[str], None] | None = None


async def _noop_read_unread() -> tuple[list[int], list[IncomingMessage]]:
    return [], []


async def _noop_mark_read(indices: list[int]) -> None:
    pass


# ---- ContextVar 注入 ----

_TEAMMATE_CTX: contextvars.ContextVar[TeammateContext | None] = contextvars.ContextVar(
    "alincode_teammate_ctx", default=None
)


def set_teammate_context(tc: TeammateContext) -> contextvars.Token:
    """设置当前 asyncio task 的 TeammateContext。返回 token 用于 reset。"""
    return _TEAMMATE_CTX.set(tc)


def teammate_context() -> TeammateContext | None:
    """取当前 TeammateContext(无则 None)。"""
    return _TEAMMATE_CTX.get()


def reset_teammate_context(token: contextvars.Token) -> None:
    """恢复到之前的 TeammateContext。"""
    _TEAMMATE_CTX.reset(token)


class TeamHook(Protocol):
    """Agent 工具委托给 Team Manager 的接口(plan.md)。"""

    # spawn_teammate:把 Agent 工具的 team_name 分支委托给 Team Manager。
    # 返回 final_text(立即返回 JSON 描述)。
    async def spawn_teammate(self, req: TeamSpawnRequest) -> str: ...

    # is_teammate_context:判断当前上下文是否在某队员的执行上下文中。
    # 返回 (team_name, member_name, is_in_process)。
    # 不在队员上下文时返回 ("", "", False)。
    def is_teammate_context(self) -> tuple[str, str, bool]: ...
