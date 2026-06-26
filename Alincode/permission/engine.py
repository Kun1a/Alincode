"""权限引擎：五层防御流水线——黑名单→沙箱→规则→模式→Ask（F6/AC8）。"""

from __future__ import annotations

import json

from Alincode.permission import (
    Verdict, ToolCategory, RuleRecord, Mode,
)
from Alincode.permission.blacklist import check_blacklist
from Alincode.permission.sandbox import check_sandbox
from Alincode.permission.rules import (
    match_rule, tool_to_category,
)
from Alincode.permission.config_loader import load_rules, save_allow_rule


# 模式兜底矩阵：{mode: {category: Verdict}}
# Deny 只来自黑名单/沙箱/deny 规则。模式最多 Ask。
MODE_FALLBACK = {
    Mode.DEFAULT: {
        ToolCategory.READ: Verdict.ALLOW,
        ToolCategory.GLOB: Verdict.ALLOW,
        ToolCategory.GREP: Verdict.ALLOW,
        ToolCategory.WRITE: Verdict.ASK,
        ToolCategory.EDIT: Verdict.ASK,
        ToolCategory.EXEC: Verdict.ASK,
    },
    Mode.ACCEPT_EDITS: {
        ToolCategory.READ: Verdict.ALLOW,
        ToolCategory.GLOB: Verdict.ALLOW,
        ToolCategory.GREP: Verdict.ALLOW,
        ToolCategory.WRITE: Verdict.ALLOW,
        ToolCategory.EDIT: Verdict.ALLOW,
        ToolCategory.EXEC: Verdict.ASK,
    },
    Mode.PLAN: {
        # PLAN 下写/执行类工具根本不会被注入，但兜底仍为 ASK
        ToolCategory.READ: Verdict.ALLOW,
        ToolCategory.GLOB: Verdict.ALLOW,
        ToolCategory.GREP: Verdict.ALLOW,
        ToolCategory.WRITE: Verdict.ASK,
        ToolCategory.EDIT: Verdict.ASK,
        ToolCategory.EXEC: Verdict.ASK,
    },
    Mode.BYPASS: {
        ToolCategory.READ: Verdict.ALLOW,
        ToolCategory.GLOB: Verdict.ALLOW,
        ToolCategory.GREP: Verdict.ALLOW,
        ToolCategory.WRITE: Verdict.ALLOW,
        ToolCategory.EDIT: Verdict.ALLOW,
        ToolCategory.EXEC: Verdict.ALLOW,
    },
}


class PermissionEngine:
    """五层防御流水线：黑名单→沙箱→规则→模式→返回裁决。

    黑名单不可绕过（bypass 模式也拦）。
    """

    def __init__(self, project_root: str = "", rules: list[RuleRecord] | None = None) -> None:
        self.project_root = project_root
        self._rules = rules or []

    def reload_rules(self, project_root: str = "") -> None:
        """重新加载三层配置规则。"""
        root = project_root or self.project_root
        self._rules = load_rules(root)
        self.project_root = root

    def add_session_rule(self, rule: RuleRecord) -> None:
        """添加会话级临时规则（最高优先级——插在最前面）。"""
        self._rules.insert(0, rule)

    def check(
        self,
        tool_name: str,
        tool_args: str,
        mode: Mode,
    ) -> tuple[Verdict, str]:
        """五层流水线权限检查。

        Returns:
            (Verdict, reason_str) — Deny/Ask 带原因，Allow 不带
        """
        category = tool_to_category(tool_name)

        # ── 第 1 层：黑名单（仅作用于命令执行）──────────
        if category == ToolCategory.EXEC:
            cmd = _extract_command(tool_args)
            if cmd and check_blacklist(cmd):
                return Verdict.DENY, "黑名单拦截：该命令被安全策略禁止"

        # ── 第 2 层：沙箱（仅作用于文件类工具）─────────
        if category in (ToolCategory.READ, ToolCategory.WRITE, ToolCategory.EDIT):
            file_path = _extract_path(tool_args)
            if file_path and self.project_root:
                if not check_sandbox(file_path, self.project_root):
                    return Verdict.DENY, f"沙箱拦截：路径 '{file_path}' 在项目根目录之外"

        # ── 第 3 层：规则匹配 ──────────────────────────
        rule = match_rule(tool_name, tool_args, self._rules)
        if rule:
            if rule.verdict == "deny":
                return Verdict.DENY, f"规则 deny：{rule.tool}({rule.pattern})"
            else:
                return Verdict.ALLOW, ""

        # ── 第 4 层：模式兜底 ──────────────────────────
        if category is not None:
            fallback = MODE_FALLBACK[mode].get(category)
        elif mode == Mode.BYPASS:
            # BYPASS 模式：未知工具也放行（黑名单+沙箱已在前层覆盖风险）
            fallback = Verdict.ALLOW
        else:
            # 未知工具——安全默认（N7/AC15）：按有副作用 ASK
            fallback = Verdict.ASK

        if fallback == Verdict.DENY:
            return Verdict.DENY, "模式兜底拦截：当前权限模式下该类操作不被允许"
        elif fallback == Verdict.ASK:
            return Verdict.ASK, f"模式兜底确认：在 {mode.value} 模式下 {tool_name} 需要人工批准"
        else:
            return Verdict.ALLOW, ""

    def save_permanent_allow(self, tool_friendly: str, args_str: str) -> bool:
        """永久放行：写入本地配置层。"""
        return save_allow_rule(tool_friendly, args_str, self.project_root)


def _extract_command(args_str: str) -> str:
    """提取 bash 工具参数中的 command。"""
    try:
        data = json.loads(args_str) if args_str.strip() else {}
    except json.JSONDecodeError:
        return ""
    return data.get("command", "")


def _extract_path(args_str: str) -> str:
    """提取文件类工具参数中的 path。"""
    try:
        data = json.loads(args_str) if args_str.strip() else {}
    except json.JSONDecodeError:
        return ""
    return data.get("path", "")


def new_engine(project_root: str) -> tuple[PermissionEngine, str | None]:
    """工厂函数：构造权限引擎并加载规则。

    总是返回 (engine, err_str)。加载失败降级为空规则引擎，不抛异常（N5）。
    """
    err = None
    try:
        rules = load_rules(project_root)
    except Exception as e:
        rules = []
        err = f"权限规则加载降级: {e}"
    return PermissionEngine(project_root=project_root, rules=rules), err
