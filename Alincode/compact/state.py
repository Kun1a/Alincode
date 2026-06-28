"""上下文管理状态对象：替换决策账本、熔断器、文件追踪、会话上下文（T2-T4）。"""

from __future__ import annotations

import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import logging

logger = logging.getLogger(__name__)


# ── 会话生命周期 ──────────────────────────────────────

def _new_session_id() -> str:
    """生成 YYYYMMDD-HHMMSS-xxxx 格式的会话 id（防同秒碰撞）。"""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        hex_str = secrets.token_hex(2)
    except Exception:
        import random
        import time
        logger.warning("secrets.token_hex failed, falling back to random")
        hex_str = random.Random(time.time()).randbytes(2).hex()
    return f"{ts}-{hex_str}"


def parse_session_time(session_id: str) -> datetime:
    """从会话 ID 前 15 位解析时间戳，供清理和排序使用。"""
    ts_str = session_id[:15]
    return datetime.strptime(ts_str, "%Y%m%d-%H%M%S")


@dataclass
class SessionContext:
    """会话生命周期信息。"""
    session_id: str
    session_dir: str
    spill_dir: str


def new_session_context(workspace: str) -> SessionContext:
    """创建会话上下文。落盘目录在首次 spill 时懒创建。"""
    session_id = _new_session_id()
    ws_path = Path(workspace)
    session_dir = str(ws_path / ".Alincode" / "sessions" / session_id)
    spill_dir = os.path.join(session_dir, "tool-results")
    return SessionContext(
        session_id=session_id, session_dir=session_dir, spill_dir=spill_dir,
    )


def open_session_context(workspace: str, session_id: str) -> SessionContext:
    """打开已有会话目录（恢复场景）。不创建目录。"""
    ws_path = Path(workspace)
    session_dir = str(ws_path / ".Alincode" / "sessions" / session_id)
    spill_dir = os.path.join(session_dir, "tool-results")
    return SessionContext(
        session_id=session_id, session_dir=session_dir, spill_dir=spill_dir,
    )


# ── 替换决策账本 ──────────────────────────────────────

class ContentReplacementState:
    """会话级的"工具结果替换决策账本"，保证 prompt cache 前缀逐字节稳定。

    _seen_ids 记录已经决策过的 tool_use_id（无论决策是替换还是保留原文）。
    _replacements 只保存"决定替换"那一支的预览字符串。
    同一个 tool_use_id 一旦进入 _seen_ids 就再也不会被重新评估。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seen_ids: set[str] = set()
        self._replacements: dict[str, str] = {}

    def decide_once(
        self,
        tool_use_id: str,
        original: str,
        decide: Callable[[], tuple[str, str]],
    ) -> str:
        """持锁完成"查账本 → 决策 → 写账本"原子操作。

        decide 回调在持锁状态下被调用，返回 (decision, preview)：
          - ("kept", _)     → 写 _seen_ids，不写 _replacements；返回原 content
          - ("replaced", p) → 写 _seen_ids + _replacements；返回 preview
          - ("skip", _)     → 不写任何账本；返回原 content（下一轮重试）

        若 id 已 Seen：直接返回账本中存量结果（不再调 decide）。
        """
        with self._lock:
            if tool_use_id in self._seen_ids:
                return self._replacements.get(tool_use_id, original)
            decision, preview = decide()
            if decision == "kept":
                self._seen_ids.add(tool_use_id)
                return original
            elif decision == "replaced":
                self._seen_ids.add(tool_use_id)
                self._replacements[tool_use_id] = preview
                return preview
            elif decision == "skip":
                return original
            else:
                # 未知 decision，保守返回原文
                return original


# ── 自动摘要熔断器 ──────────────────────────────────

class AutoCompactTrackingState:
    """跟踪自动摘要连续失败次数，用于熔断。

    手动 / 紧急压缩路径不读这个字段。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._consecutive_failures = 0

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1

    def tripped(self) -> bool:
        from Alincode.compact.const import MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES
        with self._lock:
            return self._consecutive_failures >= MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES


# ── 文件追踪状态 ──────────────────────────────────────

@dataclass
class FileReadRecord:
    """单次文件读取记录。"""
    path: str       # 绝对路径
    content: str    # 不带行号前缀的纯净字节解码内容
    timestamp: datetime  # 最后一次成功读取的时间


class RecoveryState:
    """Agent 主循环写、compact 摘要时读的文件追踪状态。

    键为文件绝对路径，避免相对路径在不同 cwd 下错乱。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._files: dict[str, FileReadRecord] = {}

    def record_file(self, path: str, content: str) -> None:
        """记录一次成功的文件读取。路径非绝对时自动 resolve。"""
        if not Path(path).is_absolute():
            path = str(Path(path).resolve())
        with self._lock:
            self._files[path] = FileReadRecord(
                path=path,
                content=content,
                timestamp=datetime.now(),
            )

    def snapshot(self) -> list[FileReadRecord]:
        """返回按 timestamp 倒序排序的拷贝列表。"""
        with self._lock:
            records = list(self._files.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records
