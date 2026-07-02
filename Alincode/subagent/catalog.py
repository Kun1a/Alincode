"""SubAgent Catalog：三层加载 + 同名覆盖（T6）。"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from Alincode.subagent.definition import Definition, Source
from Alincode.subagent.parser import parse_file
from Alincode.subagent.embed import builtin_definitions


class Catalog:
    """Agent 定义目录：按优先级 builtin < user < project 加载，同名高优先级覆盖。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._defs: dict[str, Definition] = {}
        self._by_source: dict[Source, list[Definition]] = {s: [] for s in Source}

    def resolve(self, name: str) -> Definition | None:
        with self._lock:
            return self._defs.get(name)

    def list(self) -> list[Definition]:
        with self._lock:
            return sorted(self._defs.values(), key=lambda d: d.name)

    def list_by_source(self, src: Source) -> list[Definition]:
        with self._lock:
            return list(self._by_source.get(src, []))

    def fork_definition(self) -> Definition:
        """返回 Fork 路径用的临时 Definition。"""
        return Definition(
            name="__fork__",
            description="Fork-based subagent",
            model="inherit",
            max_turns=25,
            permission_mode="default",
        )

    def _add_all(self, defs: list[Definition], source: Source) -> None:
        """注册一批定义，同名时后者覆盖前者。"""
        with self._lock:
            for d in defs:
                self._defs[d.name] = d
                self._by_source[source].append(d)


def load_catalog(root: str) -> Catalog:
    """按 builtin → user → project 顺序加载，构造 Catalog。

    首次启动时自动将内置 Agent 定义同步到项目 .Alincode/agents/ 目录，
    方便用户查看和修改。
    """
    c = Catalog()

    # 1. 内置（从包内读取，同时同步到项目目录）
    builtins = builtin_definitions()
    c._add_all(builtins, Source.BUILTIN)

    # 同步内置定义到项目目录（不覆盖已有文件）
    project_agents_dir = Path(root) / ".Alincode" / "agents"
    _seed_builtins(builtins, project_agents_dir)

    # 2. 用户级
    user_dir = Path.home() / ".Alincode" / "agents"
    c._add_all(_load_from_dir(user_dir, Source.USER), Source.USER)

    # 3. 项目级
    c._add_all(_load_from_dir(project_agents_dir, Source.PROJECT), Source.PROJECT)

    return c


def _seed_builtins(defs: list[Definition], project_dir: Path) -> None:
    """将内置 Agent 定义复制到项目目录（如不存在）。"""
    try:
        from importlib.resources import files as res_files
        pkg = res_files("Alincode.subagent.builtin")
        if not pkg.is_dir():
            return
        project_dir.mkdir(parents=True, exist_ok=True)
        for entry in pkg.iterdir():
            if not entry.name.endswith(".md"):
                continue
            target = project_dir / entry.name
            if not target.exists():
                target.write_bytes(entry.read_bytes())
    except Exception as e:
        print(f"[subagent] failed to seed builtins to {project_dir}: {e}", file=sys.stderr)


def _load_from_dir(directory: Path, source: Source) -> list[Definition]:
    """从目录加载所有 .md 文件。解析失败 stderr 警告并跳过。"""
    if not directory.is_dir():
        return []

    defs: list[Definition] = []
    for md_file in sorted(directory.glob("*.md")):
        try:
            d = parse_file(str(md_file), source)
            defs.append(d)
        except Exception as e:
            print(
                f"subagent {md_file.name}: parse error: {e}, skipped",
                file=sys.stderr,
            )
    return defs
