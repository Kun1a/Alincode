"""SubAgent Markdown 解析器：frontmatter + body → Definition（T2）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from Alincode.subagent.definition import Definition, Source

UTF8_BOM = b"\xef\xbb\xbf"
AGENT_NAME_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{0,31}$")

VALID_MODELS = {"inherit", "haiku", "sonnet", "opus"}
VALID_PERMISSION_MODES = {"default", "acceptEdits", "plan", "bypassPermissions", "dontAsk"}


def parse_frontmatter_and_body(text: str) -> tuple[dict, str]:
    """从 Markdown 文本中分离 YAML frontmatter 和 body。

    返回 (frontmatter_dict, body_text)。
    frontmatter 以 --- 开始和结束。
    """
    text = text.strip()
    if not text.startswith("---"):
        raise ValueError("missing frontmatter (must start with ---)")

    # 找到第二个 ---
    end_marker = text.index("---", 3) if "---" in text[3:] else -1
    if end_marker < 0:
        raise ValueError("unclosed frontmatter")

    fm_text = text[3:end_marker].strip()
    body = text[end_marker + 3:].lstrip("\n")
    fm_dict = yaml.safe_load(fm_text) or {}
    if not isinstance(fm_dict, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return fm_dict, body


def parse_definition(data: bytes, file_path: str, source: Source) -> Definition:
    """从 Markdown 文件字节内容解析 Agent 定义。

    Raises ValueError on critical failure (missing name/description).
    非法字段 stderr 警告并 fallback 到默认值。
    """
    if data.startswith(UTF8_BOM):
        data = data[len(UTF8_BOM):]
    text = data.decode("utf-8")

    fm, body = parse_frontmatter_and_body(text)

    name = str(fm.get("name", "")).strip()
    if not name or not AGENT_NAME_REGEX.match(name):
        raise ValueError(f"invalid or missing name: {name!r}")

    description = str(fm.get("description", "")).strip()
    if not description:
        raise ValueError("description is required")

    # tools 白名单
    tools = _str_list(fm.get("tools"))

    # disallowedTools 黑名单
    disallowed_tools = _str_list(fm.get("disallowedTools"))

    # model
    model_str = str(fm.get("model", "")).strip().lower()
    if not model_str:
        model_str = "inherit"
    if model_str not in VALID_MODELS:
        print(f"subagent {name}: unknown model {model_str!r}, defaulting to inherit", file=sys.stderr)
        model_str = "inherit"

    # maxTurns
    max_turns = 0
    raw_turns = fm.get("maxTurns")
    if raw_turns is not None:
        try:
            max_turns = int(raw_turns)
        except (ValueError, TypeError):
            print(f"subagent {name}: invalid maxTurns {raw_turns!r}, defaulting to 0", file=sys.stderr)

    # permissionMode
    perm_str = str(fm.get("permissionMode", "")).strip()
    if not perm_str:
        perm_str = "default"
    dont_ask = False
    if perm_str == "dontAsk":
        dont_ask = True
        perm_str = "default"
    if perm_str not in VALID_PERMISSION_MODES:
        print(f"subagent {name}: unknown permissionMode {perm_str!r}, defaulting to default", file=sys.stderr)
        perm_str = "default"

    # background
    background = bool(fm.get("background", False))

    # isolation
    isolation_str = str(fm.get("isolation", "")).strip()
    if isolation_str not in ("", "worktree"):
        print(
            f"subagent {name}: unknown isolation {isolation_str!r}, defaulting to empty",
            file=sys.stderr,
        )
        isolation_str = ""

    return Definition(
        name=name,
        description=description,
        tools=tools,
        disallowed_tools=disallowed_tools,
        model=model_str,
        max_turns=max_turns,
        permission_mode=perm_str,
        dont_ask=dont_ask,
        background=background,
        isolation=isolation_str,
        system_prompt=body.strip(),
        file_path=file_path,
        source=source,
    )


def parse_file(path: str, source: Source) -> Definition:
    """从文件路径读取并解析 Agent 定义。"""
    return parse_definition(Path(path).read_bytes(), path, source)


def _str_list(val: object) -> list[str]:
    """安全取字符串列表。"""
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if x]
    return []
