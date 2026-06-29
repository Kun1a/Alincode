"""规则匹配：精确与 glob 匹配 + 友好名映射（F3/AC3/AC4）。

升级：支持 Matcher（Exact/Glob/Regex/Not）做权限匹配，同时保持向后兼容。
"""

from __future__ import annotations

import fnmatch

from Alincode.permission import RuleRecord, ToolCategory

# 友好名 → 内部工具名 + 类别
_FRIENDLY_MAP: dict[str, tuple[str, ToolCategory]] = {
    "Read": ("read_file", ToolCategory.READ),
    "Write": ("write_file", ToolCategory.WRITE),
    "Edit": ("edit_file", ToolCategory.EDIT),
    "Bash": ("bash", ToolCategory.EXEC),
    "Glob": ("glob", ToolCategory.GLOB),
    "Grep": ("grep", ToolCategory.GREP),
}

# 内部工具名 → 类别
_TOOL_CATEGORY: dict[str, ToolCategory] = {
    name: cat for _, (name, cat) in _FRIENDLY_MAP.items()
}

# 内部名 ↔ 友好名（规则存储用友好名）
_INTERNAL_TO_FRIENDLY = {name: friendly for friendly, (name, _) in _FRIENDLY_MAP.items()}


def friendly_to_internal(friendly: str) -> tuple[str, ToolCategory] | None:
    """将友好名转换到内部工具名和类别。未匹配返回 None。"""
    return _FRIENDLY_MAP.get(friendly)


def tool_to_category(tool_name: str) -> ToolCategory | None:
    """内部工具名 → 类别。未注册工具返回 None（安全默认：按有副作用）。"""
    return _TOOL_CATEGORY.get(tool_name)


def tool_to_friendly(tool_name: str) -> str:
    """内部工具名 → 友好名（用于规则写入）。"""
    return _INTERNAL_TO_FRIENDLY.get(tool_name, tool_name)


def match_rule(tool_name: str, args_str: str, rules: list[RuleRecord]) -> RuleRecord | None:
    """在规则列表中匹配——返回首条命中的规则（deny 优先）。

    匹配规则：
    1. 提取参数的"主匹配值"（文件类=path，bash=command）
    2. 逐条规则优先用 matcher（Matcher 实例），否则 fallback 到 pattern fnmatch
    3. deny 规则优先于 allow（同层）
    """
    extract = _extract_match_value(tool_name, args_str)
    if extract is None:
        return None

    deny_hit: RuleRecord | None = None
    allow_hit: RuleRecord | None = None

    for rule in rules:
        r_tool_name, _ = friendly_to_internal(rule.tool) or (rule.tool, None)
        if r_tool_name != tool_name:
            continue
        if not _match_rule_value(extract, rule):
            continue
        if rule.verdict == "deny":
            if deny_hit is None:
                deny_hit = rule
        elif rule.verdict == "allow":
            if allow_hit is None:
                allow_hit = rule

    # deny 优先
    return deny_hit or allow_hit


def _match_rule_value(value: str, rule: RuleRecord) -> bool:
    """单条规则的匹配值判定：优先用 matcher，回退到 pattern fnmatch。"""
    if rule.matcher is not None:
        # matcher is a Matcher Protocol instance
        return rule.matcher.match(value)  # type: ignore[union-attr]
    # 向后兼容：无 matcher 时用 pattern 做 fnmatch
    if rule.pattern:
        return fnmatch.fnmatch(value, rule.pattern)
    # pattern 为空 → 全匹配（该工具所有参数都命中）
    return True


def _extract_match_value(tool_name: str, args_str: str) -> str | None:
    """从工具参数 JSON 中提取用于规则匹配的主值。"""
    import json
    try:
        data = json.loads(args_str) if args_str.strip() else {}
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    cat = tool_to_category(tool_name)
    if cat is None:
        # 未知工具 → 不参与规则匹配（由 engine 按安全默认处理）
        return None
    if cat == ToolCategory.EXEC:
        return data.get("command", "")
    elif cat in (ToolCategory.READ, ToolCategory.WRITE, ToolCategory.EDIT):
        return data.get("path", "")
    elif cat in (ToolCategory.GLOB, ToolCategory.GREP):
        return data.get("path") or data.get("pattern", "")
    return ""


def _fnmatch(value: str, pattern: str) -> bool:
    """fnmatch 匹配——大小写敏感，pattern 可含 * ** ? 等通配符。"""
    return fnmatch.fnmatch(value, pattern)
