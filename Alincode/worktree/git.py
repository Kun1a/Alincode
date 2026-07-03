"""Git 子进程包装 + 变更检测（T3）。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


async def _run_git(work_dir: str, *args: str) -> str:
    """在 work_dir 中执行 git 命令，返回 stdout 去尾换行文本。失败抛 RuntimeError。"""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""

    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=work_dir,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {err}")

    return stdout.decode("utf-8", errors="replace").rstrip("\n")


async def _has_worktree_changes(wt_path: str, base_commit: str) -> bool:
    """检测 Worktree 是否有未提交修改或新增 commit。git 出错返回 True（fail-closed）。"""
    try:
        out = await _run_git(wt_path, "status", "--porcelain")
        if out.strip():
            return True
    except RuntimeError:
        return True  # fail-closed

    if base_commit:
        try:
            count = await _run_git(wt_path, "rev-list", "--count", f"{base_commit}..HEAD")
            if int(count.strip()) > 0:
                return True
        except (RuntimeError, ValueError):
            return True

    return False


def _resolve_head_sha_from_fs(wt_path: str) -> str | None:
    """纯文件系统读 HEAD SHA（不调 git 子进程），失败返回 None。"""
    wt = Path(wt_path)
    git_file = wt / ".git"
    if not git_file.exists():
        return None

    try:
        content = git_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    # .git 是文件（worktree 指针）：gitdir: <repo>/.git/worktrees/<name>
    is_worktree_ptr = content.startswith("gitdir:")
    if is_worktree_ptr:
        git_dir = content[7:].strip()
        head_file = Path(git_dir) / "HEAD"
    else:
        git_dir = str(wt / ".git")
        head_file = Path(git_dir) / "HEAD"

    if not head_file.exists():
        return None

    try:
        head_content = head_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    # ref: refs/heads/<branch>
    if head_content.startswith("ref: "):
        ref_path = head_content[5:].strip()
        ref_file = Path(git_dir) / ref_path
        try:
            return ref_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    # detached HEAD：直接就是 SHA
    return head_content
