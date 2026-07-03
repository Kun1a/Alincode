"""Worktree 生命周期：enter / exit / remove / auto_cleanup（F11-F14/T6）。"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from Alincode.worktree.session import WorktreeSession, save_session, clear_session
from Alincode.worktree.git import _run_git, _has_worktree_changes


class ExitAction(str, Enum):
    KEEP = "keep"
    REMOVE = "remove"


@dataclass
class ExitOptions:
    discard_changes: bool = False


@dataclass
class ExitReport:
    removed: bool
    path: str
    branch: str


@dataclass
class AutoCleanupReport:
    kept: bool
    path: str = ""
    branch: str = ""


class WorktreeHasChangesError(Exception):
    """Worktree 有未提交修改，拒绝删除。"""
    def __init__(self, name: str) -> None:
        super().__init__(f"Worktree '{name}' 有未提交修改，拒绝删除。加 --discard 强制删除。")
        self.name = name


async def enter(mgr, name: str) -> WorktreeSession:
    """进入 Worktree：不调 chdir，只记录 session。"""
    async with mgr.lock:
        wt = mgr.active.get(name)
        if wt is None:
            raise ValueError(f"worktree '{name}' 不存在")

        original_cwd = str(Path.cwd())
        session = WorktreeSession(
            original_cwd=original_cwd,
            worktree_path=wt.path,
            worktree_name=name,
            original_branch="",
            original_head_commit="",
            session_id=secrets.token_hex(8),
        )

        # 取当前分支/commit 信息（best-effort）
        try:
            session.original_branch = await _run_git(mgr.repo_root, "rev-parse", "--abbrev-ref", "HEAD")
        except Exception:
            pass
        try:
            session.original_head_commit = await _run_git(mgr.repo_root, "rev-parse", "HEAD")
        except Exception:
            pass

        mgr.current_session = session
        save_session(mgr.session_file, session)
        return session


async def exit_wt(
    mgr, name: str, action: ExitAction, opts: ExitOptions | None = None,
) -> ExitReport:
    """退出 Worktree。"""
    if opts is None:
        opts = ExitOptions()

    async with mgr.lock:
        wt = mgr.active.get(name)
        if wt is None:
            raise ValueError(f"worktree '{name}' 不存在")

        if mgr.current_session is None or mgr.current_session.worktree_name != name:
            raise ValueError(f"worktree '{name}' 不是当前 session，无法退出")

        # 变更检查
        if action == ExitAction.REMOVE and not opts.discard_changes:
            if await _has_worktree_changes(wt.path, wt.head_commit):
                raise WorktreeHasChangesError(name)

        # 兜底切回原 cwd
        if mgr.current_session and mgr.current_session.original_cwd:
            try:
                os.chdir(mgr.current_session.original_cwd)
            except OSError:
                pass

        # 清空 session
        mgr.current_session = None
        clear_session(mgr.session_file)

        # 删除
        removed = False
        if action == ExitAction.REMOVE:
            try:
                await _run_git(mgr.repo_root, "worktree", "remove", "--force", wt.path)
            except RuntimeError:
                pass
            # 短暂等待解决 lockfile 竞态
            import asyncio as _asyncio
            await _asyncio.sleep(0.1)
            try:
                await _run_git(mgr.repo_root, "branch", "-D", wt.branch)
            except RuntimeError:
                pass
            del mgr.active[name]
            removed = True

        return ExitReport(removed=removed, path=wt.path, branch=wt.branch)


async def remove_wt(mgr, name: str, opts: ExitOptions | None = None) -> ExitReport:
    """独立 remove 入口——允许删除非当前 session 的 Worktree。"""
    if opts is None:
        opts = ExitOptions()

    async with mgr.lock:
        wt = mgr.active.get(name)
        if wt is None:
            raise ValueError(f"worktree '{name}' 不存在")

        if not opts.discard_changes:
            if await _has_worktree_changes(wt.path, wt.head_commit):
                raise WorktreeHasChangesError(name)

        try:
            await _run_git(mgr.repo_root, "worktree", "remove", "--force", wt.path)
        except RuntimeError:
            pass
        import asyncio as _asyncio
        await _asyncio.sleep(0.1)
        try:
            await _run_git(mgr.repo_root, "branch", "-D", wt.branch)
        except RuntimeError:
            pass

        del mgr.active[name]
        return ExitReport(removed=True, path=wt.path, branch=wt.branch)


async def auto_cleanup(mgr, name: str) -> AutoCleanupReport:
    """自动清理：manual 跳过，无变更删除，有变更保留。"""
    async with mgr.lock:
        wt = mgr.active.get(name)
        if wt is None:
            return AutoCleanupReport(kept=False)

        if wt.manual:
            return AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)

        has_changes = await _has_worktree_changes(wt.path, wt.head_commit)
        if not has_changes:
            await remove_wt(mgr, name, ExitOptions(discard_changes=True))
            return AutoCleanupReport(kept=False)

        return AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)
