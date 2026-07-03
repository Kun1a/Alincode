"""Worktree 过期清理（F33-F34/T7）。"""

from __future__ import annotations

import re
from datetime import datetime

from Alincode.worktree.git import _has_worktree_changes, _run_git
from Alincode.worktree.lifecycle import ExitOptions, remove_wt

# 只识别 SubAgent 临时 Worktree 命名模式
_TEMP_PATTERN = re.compile(r"^agent-a[0-9a-f]{7}$")


async def sweep_stale(mgr, cutoff: datetime) -> list[str]:
    """清理过期的临时 Worktree。三层过滤后删除。"""
    removed: list[str] = []

    for child in sorted(mgr.worktree_dir.iterdir()):
        if not child.is_dir():
            continue

        # 第一层：名字匹配临时模式
        if not _TEMP_PATTERN.match(child.name):
            continue

        # 第二层：时间过滤 + 跳过当前 session
        mtime = datetime.fromtimestamp(child.stat().st_mtime)
        if mtime > cutoff:
            continue
        if mgr.current_session and mgr.current_session.worktree_path == str(child):
            continue

        # 还原 slug
        name = child.name.replace("+", "/")

        # 第三层：变更检查
        wt = mgr.active.get(name)
        base_commit = wt.head_commit if wt else ""
        if await _has_worktree_changes(str(child), base_commit):
            continue

        # 额外检查：未推送 commit
        try:
            result = await _run_git(str(child), "rev-list", "--max-count=1", "HEAD", "--not", "--remotes")
            if result.strip():
                continue  # 有未推送 commit
        except RuntimeError:
            continue  # fail-closed

        # 通过三层：删除
        try:
            await remove_wt(mgr, name, ExitOptions(discard_changes=True))
            removed.append(name)
        except Exception:
            pass

    return removed
