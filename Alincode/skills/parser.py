"""SKILL.md 与 tool.json 解析（T2）。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

from Alincode.skills.types import Skill, SkillMeta, SkillSource, ToolSpec

_VALID_NAME = re.compile(r"^[a-z][a-z0-9-]*$")


def parse_skill_dir(dir_path: Path, source: SkillSource) -> Skill:
    """解析单个 Skill 目录 → Skill。"""
    skill_md = dir_path / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"no SKILL.md in {dir_path}")

    data = skill_md.read_text(encoding="utf-8")
    meta_dict, body = _parse_frontmatter_and_body(data)
    meta = _build_meta(meta_dict)
    tool_specs = _parse_tool_json(dir_path)

    return Skill(
        meta=meta,
        prompt_body=body,
        source_dir=dir_path.resolve(),
        source=source,
        tool_specs=tool_specs,
    )


def _parse_frontmatter_and_body(data: str) -> tuple[dict, str]:
    """分离 YAML frontmatter 与 Markdown 正文。"""
    data = data.lstrip()
    if not data.startswith("---\n"):
        raise ValueError("SKILL.md must start with --- frontmatter")
    end = data.find("\n---\n", 4)
    if end == -1:
        raise ValueError("SKILL.md frontmatter not closed with ---")
    fm_text = data[4:end].strip()
    body = data[end + 4:].strip()
    meta = yaml.safe_load(fm_text) or {}
    if not isinstance(meta, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML mapping")
    return meta, body


def _build_meta(d: dict) -> SkillMeta:
    """从 frontmatter dict 构建 SkillMeta，校验合法性。"""
    name = str(d.get("name", "")).strip()
    if not _VALID_NAME.match(name) or len(name) > 32:
        raise ValueError(f"invalid skill name: {name!r}")

    desc = str(d.get("description", "")).strip()
    if not desc:
        raise ValueError(f"skill {name}: description is required")

    mode = str(d.get("mode", "inline")).strip().lower()
    if mode not in ("", "inline", "fork"):
        print(f"[skills] warn: {name}: unknown mode '{mode}', falling back to inline", file=sys.stderr)
        mode = "inline"
    if not mode:
        mode = "inline"

    fork_ctx = str(d.get("fork_context", "none")).strip().lower()
    if fork_ctx not in ("", "none", "recent", "full"):
        fork_ctx = "none"

    allowed = d.get("allowed_tools")
    if isinstance(allowed, list):
        allowed = [str(t) for t in allowed]
    else:
        allowed = []

    model = d.get("model")
    if model is not None:
        model = str(model).strip() or None

    return SkillMeta(
        name=name,
        description=desc,
        allowed_tools=allowed,
        mode=mode,
        fork_context=fork_ctx,
        model=model,
    )


def _parse_tool_json(dir_path: Path) -> list[ToolSpec]:
    """解析 tool.json（可选）。"""
    tool_json = dir_path / "tool.json"
    if not tool_json.is_file():
        return []
    try:
        data = json.loads(tool_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[skills] warn: {dir_path}/tool.json parse error: {e}", file=sys.stderr)
        return []
    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, list):
        return []
    specs = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name", ""))
        if not _VALID_NAME.match(name):
            continue
        cmd = t.get("command")
        if not isinstance(cmd, list) or not cmd:
            continue
        specs.append(ToolSpec(
            name=name,
            description=str(t.get("description", "")),
            input_schema=t.get("input_schema") or {"type": "object"},
            command=[str(c) for c in cmd],
            base_dir=dir_path.resolve(),
        ))
    return specs
