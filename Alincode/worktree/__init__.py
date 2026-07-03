"""Worktree 隔离：Git Worktree 管理 + explicit cwd 工具改造。"""

from Alincode.worktree.slug import validate_slug, flat_slug
from Alincode.worktree.session import WorktreeSession
from Alincode.worktree.manager import Manager, Worktree
from Alincode.worktree.create import create as _create_wt
from Alincode.worktree.lifecycle import (
    enter, exit_wt, remove_wt, auto_cleanup,
    ExitAction, ExitOptions, ExitReport, AutoCleanupReport,
    WorktreeHasChangesError,
)
from Alincode.worktree.sweep import sweep_stale

# 首次 import 时绑定方法到 Manager（幂等，重复 import 不重新绑定）
if getattr(Manager, "_methods_bound", False) is False:
    Manager.create = _create_wt  # type: ignore[assignment]
    Manager.enter = enter  # type: ignore[assignment]
    Manager.exit = exit_wt  # type: ignore[assignment]
    Manager.remove = remove_wt  # type: ignore[assignment]
    Manager.auto_cleanup = auto_cleanup  # type: ignore[assignment]
    Manager.sweep_stale = sweep_stale  # type: ignore[assignment]
    Manager._methods_bound = True  # type: ignore[attr-defined]

__all__ = [
    "validate_slug", "flat_slug",
    "WorktreeSession",
    "Manager", "Worktree",
    "ExitAction", "ExitOptions", "ExitReport", "AutoCleanupReport",
    "WorktreeHasChangesError",
]
