"""会话列表扫描（T5）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from Alincode.compact.state import parse_session_time


@dataclass
class SessionInfo:
    """会话列表摘要信息。"""
    id: str
    title: str
    modified_at: datetime
    model: str
    size: int
    dir: str


def list_sessions(sessions_dir: str) -> list[SessionInfo]:
    """扫描 sessions_dir 返回按修改时间倒序的会话列表。"""
    sessions_path = Path(sessions_dir)
    if not sessions_path.is_dir():
        return []

    result: list[SessionInfo] = []
    for child in sorted(sessions_path.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        try:
            parse_session_time(child.name)
        except ValueError:
            continue  # 旧格式跳过

        jsonl = child / "conversation.jsonl"
        if not jsonl.is_file():
            continue

        stat = jsonl.stat()
        title, model = _read_first_user(jsonl)

        result.append(SessionInfo(
            id=child.name,
            title=title,
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            model=model,
            size=stat.st_size,
            dir=str(child),
        ))

    result.sort(key=lambda s: s.modified_at, reverse=True)
    return result


def _read_first_user(jsonl_path: Path) -> tuple[str, str]:
    """读 JSONL 第一条 user 消息，返回 (title, model)。"""
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("role") == "user":
                    title = str(data.get("content", "")).strip()
                    if len(title) > 50:
                        title = title[:47] + "..."
                    model = str(data.get("model", ""))
                    return (title, model)
    except Exception:
        pass
    return ("(无标题)", "")
