"""后端检测(T11)。

对应 spec F14。按优先级一次性决定,不做运行时回退:
1. $TMUX → tmux(当前在 tmux 会话内)
2. $TERM_PROGRAM == "iTerm.app" && it2 可执行 → iterm2
3. tmux 二进制在 PATH → tmux(外部 spawn 新 session)
4. 否则 → in-process
"""

from __future__ import annotations

import os
import shutil

from Alincode.team.types import BackendType


def detect() -> BackendType:
    """检测当前环境可用的后端类型(F14)。"""
    # 1. 当前在 tmux 会话内
    if os.environ.get("TMUX"):
        return BackendType.TMUX
    # 2. iTerm2 + it2 CLI
    if os.environ.get("TERM_PROGRAM") == "iTerm.app" and shutil.which("it2"):
        return BackendType.ITERM2
    # 3. tmux 二进制在 PATH(外部 spawn 新 session)
    if shutil.which("tmux"):
        return BackendType.TMUX
    # 4. 兜底:同进程
    return BackendType.IN_PROCESS
