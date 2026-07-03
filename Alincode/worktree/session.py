"""Worktree session 持久化（F30/F31）。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorktreeSession:
    """当前活跃的 Worktree 会话。"""
    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str = ""
    original_head_commit: str = ""
    session_id: str = ""

    def to_dict(self) -> dict:
        return {
            "original_cwd": self.original_cwd,
            "worktree_path": self.worktree_path,
            "worktree_name": self.worktree_name,
            "original_branch": self.original_branch,
            "original_head_commit": self.original_head_commit,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorktreeSession":
        return cls(
            original_cwd=d.get("original_cwd", ""),
            worktree_path=d.get("worktree_path", ""),
            worktree_name=d.get("worktree_name", ""),
            original_branch=d.get("original_branch", ""),
            original_head_commit=d.get("original_head_commit", ""),
            session_id=d.get("session_id", ""),
        )


def load_session(file_path: Path) -> WorktreeSession | None:
    """读取 session 文件。不存在返回 None。"""
    if not file_path.is_file():
        return None
    try:
        text = file_path.read_text(encoding="utf-8").strip()
        if not text or text == "null":
            return None
        data = json.loads(text)
        return WorktreeSession.from_dict(data)
    except (json.JSONDecodeError, TypeError):
        return None


def save_session(file_path: Path, session: WorktreeSession | None) -> None:
    """原子写 session 文件。session=None 时写 null。"""
    tmp = Path(str(file_path) + ".tmp")

    if session is None:
        tmp.write_text("null", encoding="utf-8")
    else:
        data = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
        tmp.write_text(data, encoding="utf-8")

    os.replace(tmp, file_path)


def clear_session(file_path: Path) -> None:
    save_session(file_path, None)
