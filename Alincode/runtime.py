"""SessionRuntime：跨 Agent run 持有的长生命周期状态容器（T26）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from Alincode.compact.state import (
    ContentReplacementState,
    RecoveryState,
    AutoCompactTrackingState,
    SessionContext,
    new_session_context,
)
from Alincode.skills.active import ActiveSkills


@dataclass
class SessionRuntime:
    """TUI Model 跨 run 持有的长生命周期状态。

    compact 是逻辑层，对状态零持有、可重入。
    """
    replacement: ContentReplacementState = field(default_factory=ContentReplacementState)
    recovery: RecoveryState = field(default_factory=RecoveryState)
    auto_tracking: AutoCompactTrackingState = field(default_factory=AutoCompactTrackingState)
    session: SessionContext = field(default_factory=lambda: new_session_context("."))
    context_window: int = 200000
    usage_anchor: int = 0       # 上一次主对话路径 stream 真实 usage 之和
    anchor_msg_len: int = 0     # anchor 当时 conv.length()
    active_skills: ActiveSkills = field(default_factory=ActiveSkills)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def new_default_runtime(workspace: str = ".") -> SessionRuntime:
    """构造默认 SessionRuntime（测试用）。"""
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=new_session_context(workspace),
    )
