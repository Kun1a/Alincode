"""ActiveSkills：已激活 Skill 的跨轮列表（T7）。"""

from __future__ import annotations

import threading

from Alincode.skills.types import ActiveEntry


class ActiveSkills:
    """管理已激活 Skill 的列表，支持重复激活覆盖。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[ActiveEntry] = []
        self._index: dict[str, int] = {}

    def activate(self, name: str, body: str) -> None:
        with self._lock:
            if name in self._index:
                idx = self._index[name]
                self._entries[idx] = ActiveEntry(name=name, body=body)
            else:
                self._index[name] = len(self._entries)
                self._entries.append(ActiveEntry(name=name, body=body))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._index.clear()

    def snapshot(self) -> list[ActiveEntry]:
        with self._lock:
            return list(self._entries)

    def names(self) -> list[str]:
        return [e.name for e in self.snapshot()]
