"""Catalog：三层路径扫描与覆盖管理（T4）。"""

from __future__ import annotations

import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from Alincode.skills.parser import parse_skill_dir
from Alincode.skills.types import Skill, SkillSource


@dataclass
class ValidationIssue:
    skill_name: str
    tool_name: str


class Catalog:
    """三层 Skill 目录：内置 < 用户 < 项目，同名按优先级覆盖。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_name: dict[str, Skill] = {}
        self._order: list[str] = []
        self._last_mtime: float = 0.0

    # ── 查询 ────────────────────────────────

    def get(self, name: str) -> Skill | None:
        with self._lock:
            return self._by_name.get(name)

    def list(self) -> list[Skill]:
        with self._lock:
            return [self._by_name[n] for n in self._order]

    def names(self) -> list[str]:
        with self._lock:
            return list(self._order)

    # ── 注册 ────────────────────────────────

    def register(self, s: Skill) -> None:
        with self._lock:
            if s.meta.name in self._by_name:
                self._by_name[s.meta.name] = s
            else:
                self._by_name[s.meta.name] = s
                self._order.append(s.meta.name)
                self._order.sort()

    # ── 加载 ────────────────────────────────

    @classmethod
    def load(cls, work_dir: str | Path) -> "Catalog":
        work_dir = Path(work_dir)
        catalog = cls()
        # 内置
        _load_builtin_into(catalog)
        # 用户级
        user_dir = Path.home() / ".Alincode" / "skills"
        _load_dir_into(catalog, user_dir, SkillSource.USER)
        # 项目级
        project_dir = work_dir / ".Alincode" / "skills"
        _load_dir_into(catalog, project_dir, SkillSource.PROJECT)
        return catalog

    def reload(self, work_dir: str | Path) -> None:
        new_cat = Catalog.load(work_dir)
        with self._lock:
            self._by_name = new_cat._by_name
            self._order = new_cat._order

    def reload_if_changed(self, work_dir: str | Path) -> None:
        """仅在目录 mtime 变化时重扫（避免每轮请求都扫描磁盘）。"""
        work_dir = Path(work_dir)
        max_mtime = 0.0
        for base in [
            work_dir / ".Alincode" / "skills",
            Path.home() / ".Alincode" / "skills",
            Path(tempfile.gettempdir()) / "alincode-builtin-skills",
        ]:
            if base.is_dir():
                try:
                    mtime = base.stat().st_mtime
                    if mtime > max_mtime:
                        max_mtime = mtime
                except OSError:
                    pass
        if max_mtime > self._last_mtime:
            self.reload(work_dir)
            self._last_mtime = max_mtime

    # ── 校验 ────────────────────────────────

    def validate_tools(self, reg) -> list[ValidationIssue]:
        issues = []
        for s in self.list():
            for t_name in s.meta.allowed_tools:
                if t_name in ("load_skill", "install_skill"):
                    continue
                if reg.get(t_name) is None:
                    issues.append(ValidationIssue(s.meta.name, t_name))
        return issues


def _load_builtin_into(catalog: Catalog) -> None:
    """加载内置 Skill。"""
    import importlib.resources
    try:
        base = importlib.resources.files("Alincode.skills.builtin")
    except Exception:
        return
    if not base.is_dir():
        return
    success, attempted = 0, 0
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        attempted += 1
        name = entry.name
        try:
            s = _load_skill_from_traversable(entry, SkillSource.BUILTIN)
            if s:
                catalog.register(s)
                success += 1
        except Exception as e:
            print(f"[skills] warn: builtin/{name} parse error: {e}", file=sys.stderr)
    if attempted > 0 and success == 0:
        print("[skills] error: no builtin skills loaded, check package integrity", file=sys.stderr)


def _load_skill_from_traversable(traversable, source: SkillSource) -> Skill | None:
    """从 importlib Traversable 加载 Skill。"""
    skill_md = traversable / "SKILL.md"
    if not skill_md.is_file():
        return None

    data = skill_md.read_text(encoding="utf-8")
    # 复用 parser 的核心逻辑
    from Alincode.skills.parser import _parse_frontmatter_and_body, _build_meta
    meta_dict, body = _parse_frontmatter_and_body(data)
    meta = _build_meta(meta_dict)

    # 找缓存的真实路径
    import tempfile
    cache_dir = Path(tempfile.gettempdir()) / "alincode-builtin-skills" / meta.name
    # 确保缓存存在
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "SKILL.md").write_text(data, encoding="utf-8")

    return Skill(
        meta=meta, prompt_body=body,
        source_dir=cache_dir.resolve(),
        source=source, tool_specs=[],
    )


def _load_dir_into(catalog: Catalog, base_dir: Path, source: SkillSource) -> None:
    """遍历子目录，每个调 parse_skill_dir。"""
    if not base_dir.is_dir():
        return
    for child in sorted(base_dir.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "SKILL.md").is_file():
            print(f"[skills] warn: {child} has no SKILL.md, skipping", file=sys.stderr)
            continue
        try:
            skill = parse_skill_dir(child, source)
            catalog.register(skill)
        except Exception as e:
            print(f"[skills] warn: {child.name} parse error: {e}", file=sys.stderr)
