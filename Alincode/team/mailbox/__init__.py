"""邮箱 Box(T6):write / read / read_unread / mark_read。

对应 spec F33。所有公开方法都走文件锁(acquire)。
邮箱文件:<dir>/<agent_id>.json,结构 {"messages": [...]}。
锁文件:<dir>/<agent_id>.lock。
read-modify-write,走 os.replace 原子替换。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from Alincode.team.filelock import acquire
from Alincode.team.mailbox.message import Message, MessageType
from Alincode.team.persistence import atomic_write_json, read_json

__all__ = ["Box", "Message", "MessageType"]


class Box:
    """邮箱:每个收件人一个 <agent_id>.json 文件 + <agent_id>.lock 锁文件。"""

    def __init__(self, dir_: str) -> None:
        self._dir = dir_
        Path(self._dir).mkdir(parents=True, exist_ok=True)

    def _path(self, agent_id: str) -> str:
        return os.path.join(self._dir, f"{agent_id}.json")

    def _lock_path(self, agent_id: str) -> str:
        return os.path.join(self._dir, f"{agent_id}.lock")

    async def write(self, agent_id: str, msg: Message) -> None:
        """写一条消息到收件人邮箱(F33)。

        抢锁 → read-modify-write → 原子替换。
        timestamp=0 时自动补 int(time.time())。
        """
        async with acquire(self._lock_path(agent_id)):
            path = self._path(agent_id)
            try:
                data = read_json(path)
            except FileNotFoundError:
                data = {"messages": []}
            if not isinstance(data, dict):
                data = {"messages": []}
            if msg.timestamp == 0:
                msg.timestamp = int(time.time())
            data.setdefault("messages", []).append(msg.to_dict())
            atomic_write_json(path, data)

    async def read(self, agent_id: str) -> list[Message]:
        """读取收件人全部消息。"""
        async with acquire(self._lock_path(agent_id)):
            path = self._path(agent_id)
            try:
                data = read_json(path)
            except FileNotFoundError:
                return []
            msgs = data.get("messages", []) if isinstance(data, dict) else []
            return [Message.from_dict(m) for m in msgs if isinstance(m, dict)]

    async def read_unread(
        self, agent_id: str
    ) -> tuple[list[int], list[dict[str, Any]]]:
        """读取未读消息,返回 (indices, raw_dicts)。

        indices 是未读消息在 messages 数组中的索引,用于 mark_read。
        返回原始 dict(不转 Message),方便调用方按需提取字段。
        """
        async with acquire(self._lock_path(agent_id)):
            path = self._path(agent_id)
            try:
                data = read_json(path)
            except FileNotFoundError:
                return [], []
            msgs = data.get("messages", []) if isinstance(data, dict) else []
            indices = []
            unread = []
            for i, m in enumerate(msgs):
                if isinstance(m, dict) and not m.get("read", False):
                    indices.append(i)
                    unread.append(m)
            return indices, unread

    async def mark_read(self, agent_id: str, indices: list[int]) -> None:
        """按 indices 把对应消息标记为 read=True。"""
        async with acquire(self._lock_path(agent_id)):
            path = self._path(agent_id)
            try:
                data = read_json(path)
            except FileNotFoundError:
                return
            msgs = data.get("messages", []) if isinstance(data, dict) else []
            for i in indices:
                if 0 <= i < len(msgs) and isinstance(msgs[i], dict):
                    msgs[i]["read"] = True
            atomic_write_json(path, data)
