"""跨进程文件锁(T5 + T9 共用)。

用 os.open(O_CREAT|O_EXCL|O_WRONLY) 抢锁:文件不存在则创建成功,
已存在则抛 FileExistsError。Python 没有 Go 的 syscall.Flock 跨平台等价,
所以走 EEXIST 抢占(在 Windows / macOS / Linux 都可用)。

参数(spec F33/F8):
- 最多重试 10 次
- 5-100ms 随机抖动
- 持锁超 10 秒视为 stale,直接清掉重试
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

LOCK_MAX_RETRIES = 10
LOCK_STALE_AFTER = 10.0
LOCK_BACKOFF_MIN = 0.005
LOCK_BACKOFF_MAX = 0.1


@asynccontextmanager
async def acquire(lock_path: str) -> AsyncIterator[None]:
    """抢文件锁,async context manager。

    抢锁失败按 5-100ms 随机抖动重试,最多 10 次;
    持锁超 10 秒视为 stale 直接清掉;退出时删除 lock 文件。
    """
    acquired = False
    for attempt in range(LOCK_MAX_RETRIES):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            # 检查是否 stale
            p = Path(lock_path)
            try:
                mtime = p.stat().st_mtime
                if time.time() - mtime > LOCK_STALE_AFTER:
                    # stale lock,删掉重试
                    os.unlink(lock_path)
                    continue
            except FileNotFoundError:
                # 被别人删了,直接重试
                continue
            # 未 stale,抖动等待
            await asyncio.sleep(random.uniform(LOCK_BACKOFF_MIN, LOCK_BACKOFF_MAX))
    if not acquired:
        raise TimeoutError(f"抢锁超时(重试 {LOCK_MAX_RETRIES} 次): {lock_path}")

    try:
        yield
    finally:
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass
