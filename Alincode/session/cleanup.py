"""会话过期清理（T7）。"""

from __future__ import annotations

import datetime as _dt
import logging
import shutil
from pathlib import Path

from Alincode.compact.state import parse_session_time

logger = logging.getLogger(__name__)


def clean_expired(sessions_dir: str, max_age: _dt.timedelta) -> None:
    """删除超过 max_age 的会话目录。

    只处理能解析出时间戳的新格式目录，旧格式跳过。
    """
    sessions_path = Path(sessions_dir)
    if not sessions_path.is_dir():
        return

    now = _dt.datetime.now()
    for child in sessions_path.iterdir():
        if not child.is_dir():
            continue
        try:
            ts = parse_session_time(child.name)
        except ValueError:
            continue  # 旧格式跳过
        if now - ts > max_age:
            try:
                shutil.rmtree(child)
                logger.info("cleanup: removed expired session %s", child.name)
            except Exception as e:
                logger.warning("cleanup: failed to remove %s: %s", child.name, e)
