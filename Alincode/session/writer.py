"""Session Writer：JSONL 追加写入 conversation.jsonl（T4）。"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass

from Alincode.conversation import Message


@dataclass
class Entry:
    """JSONL 单行数据表示。"""
    role: str = ""
    content: str = ""
    tool_calls: list[dict] | None = None
    tool_results: list[dict] | None = None
    ts: int = 0
    model: str | None = None
    type: str | None = None  # "compact" 或省略

    @classmethod
    def from_message(cls, msg: Message, model: str = "", is_first: bool = False) -> "Entry":
        entry = cls(
            role=msg.role,
            content=msg.content,
            ts=int(time.time()),
        )
        if is_first and model:
            entry.model = model
        if msg.tool_calls:
            entry.tool_calls = [
                {"id": tc.id, "name": tc.name, "input": tc.input}
                for tc in msg.tool_calls
            ]
        if msg.tool_results:
            entry.tool_results = [
                {"tool_call_id": tr.tool_call_id, "content": tr.content,
                 "is_error": tr.is_error}
                for tr in msg.tool_results
            ]
        return entry

    @classmethod
    def compact_marker(cls) -> "Entry":
        return cls(type="compact", ts=int(time.time()))


class Writer:
    """向 conversation.jsonl 追加写入。"""

    def __init__(self, session_dir: str) -> None:
        os.makedirs(session_dir, exist_ok=True)
        self._path = os.path.join(session_dir, "conversation.jsonl")
        self._lock = threading.Lock()
        self._file = open(self._path, "ab")

    @classmethod
    def open_existing(cls, session_dir: str) -> "Writer":
        """以追加模式打开已有会话。"""
        inst = cls.__new__(cls)
        inst._path = os.path.join(session_dir, "conversation.jsonl")
        inst._lock = threading.Lock()
        inst._file = open(inst._path, "ab")
        return inst

    def append(self, msg: Message, model: str = "", is_first: bool = False) -> None:
        """追加一条消息到 JSONL。"""
        entry = Entry.from_message(msg, model=model, is_first=is_first)
        _dict = _entry_to_dict(entry, is_first=is_first)
        line = json.dumps(_dict, ensure_ascii=False) + "\n"
        with self._lock:
            self._file.write(line.encode("utf-8"))
            self._file.flush()
            os.fsync(self._file.fileno())

    def write_compact_marker(self) -> None:
        """写入压缩标记行。"""
        entry = Entry.compact_marker()
        _dict = {"type": "compact", "ts": entry.ts}
        line = json.dumps(_dict, ensure_ascii=False) + "\n"
        with self._lock:
            self._file.write(line.encode("utf-8"))
            self._file.flush()
            os.fsync(self._file.fileno())

    def append_all(self, msgs: list[Message]) -> None:
        """批量追加消息列表，只做一次 fsync。"""
        lines: list[str] = []
        for msg in msgs:
            entry = Entry.from_message(msg, is_first=False)
            _dict = _entry_to_dict(entry, is_first=False)
            lines.append(json.dumps(_dict, ensure_ascii=False))
        data = "\n".join(lines) + "\n"
        with self._lock:
            self._file.write(data.encode("utf-8"))
            self._file.flush()
            os.fsync(self._file.fileno())

    def close(self) -> None:
        with self._lock:
            try:
                self._file.close()
            except Exception:
                pass

    def __enter__(self) -> "Writer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _entry_to_dict(entry: Entry, is_first: bool = False) -> dict:
    """转为 JSON 兼容字典，去除空值字段。"""
    d: dict = {"role": entry.role, "ts": entry.ts}
    if entry.content:
        d["content"] = entry.content
    if is_first and entry.model:
        d["model"] = entry.model
    if entry.tool_calls:
        d["tool_calls"] = entry.tool_calls
    if entry.tool_results:
        d["tool_results"] = entry.tool_results
    return d
