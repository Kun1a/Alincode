"""内置 Agent 定义加载（T5）。"""

from __future__ import annotations

from importlib.resources import files

from Alincode.subagent.parser import parse_definition
from Alincode.subagent.definition import Definition, Source


def builtin_definitions() -> list[Definition]:
    """读取随包发布的内置 Agent 定义文件。解析失败直接 raise（代码 bug）。"""
    pkg = files("Alincode.subagent.builtin")
    if not pkg.is_dir():
        return []

    defs: list[Definition] = []
    for entry in sorted(pkg.iterdir()):
        if not entry.name.endswith(".md"):
            continue
        data = entry.read_bytes()
        d = parse_definition(data, f"builtin:{entry.name}", Source.BUILTIN)
        defs.append(d)
    return sorted(defs, key=lambda d: d.name)
