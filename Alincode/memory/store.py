"""单级记忆存储：笔记文件 CRUD + 索引读写（T9）。"""

from __future__ import annotations

import os
import threading
import yaml
from datetime import datetime
from pathlib import Path

from Alincode.memory.types import UpdateAction

INDEX_MAX_LINES = 200
INDEX_MAX_BYTES = 25000


class Store:
    """管理单级（项目或用户）的笔记文件和索引。"""

    def __init__(self, dir_path: str) -> None:
        self._dir = dir_path
        self._lock = threading.Lock()

    def ensure_dir(self) -> None:
        Path(self._dir).mkdir(parents=True, exist_ok=True)

    def load_index(self) -> str:
        """读取 MEMORY.md 内容，不存在返回空字符串。"""
        idx_path = os.path.join(self._dir, "MEMORY.md")
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def apply(self, actions: list[UpdateAction]) -> None:
        """执行 create/update/delete 操作。"""
        with self._lock:
            self.ensure_dir()
            for act in actions:
                if act.action == "create":
                    self._create(act)
                elif act.action == "update":
                    self._update(act)
                elif act.action == "delete":
                    self._delete(act)

    def _create(self, act: UpdateAction) -> None:
        """创建新笔记文件并追加索引行。"""
        filename = f"{act.type}_{act.slug}.md"
        filepath = os.path.join(self._dir, filename)
        now = datetime.now().isoformat()
        frontmatter = {
            "type": act.type,
            "title": act.title,
            "created": now,
            "updated": now,
        }
        content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n\n" + act.content
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        self._append_index(act.type, act.title, act.content)

    def _update(self, act: UpdateAction) -> None:
        """重写笔记文件内容和 frontmatter，并更新索引行。"""
        filepath = os.path.join(self._dir, act.filename)
        # 读现有 frontmatter
        existing = {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    existing = yaml.safe_load(parts[1]) or {}
        except Exception:
            pass

        now = datetime.now().isoformat()
        frontmatter = {
            "type": existing.get("type", act.type),
            "title": act.title or existing.get("title", ""),
            "created": existing.get("created", now),
            "updated": now,
        }
        content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n\n" + act.content
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    def _delete(self, act: UpdateAction) -> None:
        """删除笔记文件。"""
        filepath = os.path.join(self._dir, act.filename)
        try:
            os.remove(filepath)
        except FileNotFoundError:
            pass

    def _append_index(self, note_type: str, title: str, content: str) -> None:
        """在 MEMORY.md 末尾追加摘要行。超限时由 LLM 在下次更新时处理。"""
        idx_path = os.path.join(self._dir, "MEMORY.md")
        # 截取一句话描述
        desc = content.split("\n")[0].strip()
        if len(desc) > 80:
            desc = desc[:77] + "..."
        line = f"- [{note_type}] {title} — {desc}\n"

        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                existing = f.read()
        except FileNotFoundError:
            existing = ""

        with open(idx_path, "w", encoding="utf-8") as f:
            f.write(existing + line)
