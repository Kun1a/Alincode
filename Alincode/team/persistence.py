"""Team 持久化工具:sanitize / atomic_write_json / read_json / reload_from_disk_locked。

对应 spec F5 step1、F8/F9 原子写、F19c 跨进程 reload 兜底、F63。
所有写操作原子(先写 .tmp 再 os.replace),受 Team._lock 保护。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Alincode.team.types import Team


# sanitize:只保留 [a-zA-Z0-9._-],其他替换为 -,首尾去 -
_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9._-]")


def sanitize(name: str) -> str:
    """把用户给的名字转成路径安全的 sanitized_name(F5 step1)。

    只保留 [a-zA-Z0-9._-],其他字符替换为 -,首尾去 -。
    空字符串或全非法字符返回 ""(调用方应拒绝)。
    """
    cleaned = _SANITIZE_RE.sub("-", name).strip("-")
    return cleaned


def atomic_write_json(path: str | Path, value: Any) -> None:
    """原子写 JSON:先写 <path>.tmp 再 os.replace(F8/F63)。

    os.replace 跨平台原子,避免读到半成品。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    content = json.dumps(value, indent=2, ensure_ascii=False)
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, p)


def read_json(path: str | Path) -> Any:
    """读 JSON 文件。不存在抛 FileNotFoundError。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding="utf-8"))


async def reload_from_disk_locked(team: "Team") -> None:
    """跨进程 reload 兜底(F19c)。

    调用方必须已持 team._lock。从 team.config_path 重读 config.json,
    把 members 字段覆盖到 in-memory。失败(文件不存在/解析失败)静默回退到内存现状。

    必要性:Pane 后端的 Lead 与子进程是两个独立进程,各持一份内存中的 Team。
    若不 reload,会出现"子进程读 config 时 Lead 的 add_member 还没写入,
    子进程修改自己内存 Team 没看见自己,set_member_active 静默 no-op"的丢更新。
    """
    try:
        data = read_json(team.config_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # 静默回退:用内存现状
        return
    if not isinstance(data, dict):
        return
    raw_members = data.get("members", [])
    if not isinstance(raw_members, list):
        return
    # 延迟 import 避免循环
    from Alincode.team.types import TeammateInfo

    team.members = [
        TeammateInfo.from_dict(m) for m in raw_members if isinstance(m, dict)
    ]
