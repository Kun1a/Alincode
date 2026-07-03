"""Worktree Manager：生命周期管理 + session 持久化（F3-F5/T4）。"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from Alincode.worktree.session import load_session, clear_session, WorktreeSession
from Alincode.worktree.git import _resolve_head_sha_from_fs

DEFAULT_SYMLINK_DIRS = ["node_modules", ".venv", "vendor"]


@dataclass
class Worktree:
    """单个 Worktree 的元信息。"""
    name: str
    path: str
    branch: str
    based_on: str = ""
    head_commit: str = ""
    created: datetime = field(default_factory=datetime.now)
    manual: bool = False


class Manager:
    """Worktree 生命周期管理器。"""

    def __init__(self, repo_root: str) -> None:
        self.repo_root = str(Path(repo_root).resolve())
        _verify_repo_root(self.repo_root)

        self.worktree_dir = Path(self.repo_root) / ".Alincode" / "worktrees"
        self.session_file = Path(self.repo_root) / ".Alincode" / "worktree_session.json"
        self.lock = asyncio.Lock()
        self.active: dict[str, Worktree] = {}
        self.current_session: WorktreeSession | None = None
        self.symlink_dirs: list[str] = list(DEFAULT_SYMLINK_DIRS)

        # 初始化目录
        self.worktree_dir.mkdir(parents=True, exist_ok=True)

        # 恢复 session
        session = load_session(self.session_file)
        if session is not None:
            if not Path(session.worktree_path).exists():
                print(f"worktree: session worktree gone ({session.worktree_path}), cleared", file=sys.stderr)
                clear_session(self.session_file)
            else:
                self.current_session = session

        # 扫描 active（快速恢复，不调 git）
        for child in self.worktree_dir.iterdir():
            if child.is_dir():
                sha = _resolve_head_sha_from_fs(str(child))
                name = _filename_to_name(child.name)
                if name:
                    self.active[name] = Worktree(
                        name=name,
                        path=str(child),
                        branch=f"worktree-{child.name}",
                        head_commit=sha or "",
                    )

    def list(self) -> list[Worktree]:
        return sorted(self.active.values(), key=lambda w: w.name)

    def get(self, name: str) -> Worktree | None:
        return self.active.get(name)


def _verify_repo_root(repo_root: str) -> None:
    """验证 repo_root 是 git 仓库根目录。"""
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        actual = str(Path(result.stdout.strip()).resolve())
        expected = str(Path(repo_root).resolve())
        if actual != expected:
            raise ValueError(f"not a git repo root: {repo_root} (git says {actual})")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise ValueError(f"git not available or timeout: {e}")


def _filename_to_name(filename: str) -> str:
    """将 flat slug 文件名还原为原始 slug（+ 替换为 /）。"""
    return filename.replace("+", "/")
