"""Hook 条件匹配：表达式解析 + 字段路径取值 + 条件求值。

表达式语法：
  原子: field op value
    op: == (精确) | =~ (正则 /.../) | != (不等) | !~ (正则不匹配)
  组合: atom && atom (all_of) | atom || atom (any_of)
  不支持 && 和 || 混用在同一层。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Alincode.hook.rule import Condition, AtomCondition, Payload


# ── 表达式解析 ──────────────────────────────────────────

def parse_condition(expr: str | None) -> "Condition | None":
    """解析条件表达式字符串，返回 Condition 或 None（无条件触发）。

    expr 为 None / 空串 → None。
    解析失败 → 打印 stderr 并返回 None。
    """
    if not expr or not expr.strip():
        return None

    stripped = expr.strip()
    and_idx = _find_toplevel_op(stripped, "&&")
    or_idx = _find_toplevel_op(stripped, "||")

    if and_idx >= 0 and or_idx >= 0:
        import sys
        print(f"[hook] condition expression mixes && and || at top level: {expr!r}", file=sys.stderr)
        return None

    if and_idx >= 0:
        mode = "all_of"
        parts = _split_toplevel(stripped, "&&")
    elif or_idx >= 0:
        mode = "any_of"
        parts = _split_toplevel(stripped, "||")
    else:
        atom = _parse_atom(stripped)
        if atom is None:
            return None
        from Alincode.hook.rule import Condition
        return Condition.all_of([atom])

    atoms = []
    for part in parts:
        atom = _parse_atom(part.strip())
        if atom is None:
            return None
        atoms.append(atom)

    if not atoms:
        return None

    from Alincode.hook.rule import Condition, CombineMode
    mode_enum = CombineMode.ALL_OF if mode == "all_of" else CombineMode.ANY_OF
    return Condition(mode=mode_enum, atoms=atoms)


# ── 公共状态机 ──────────────────────────────────────────

def _walk_toplevel(s: str, op: str, on_op):
    """遍历字符串，在顶层 op 出现时回调 on_op(start, end)。

    自动跟踪引号（""、''）、正则字面量（/.../）、括号深度，
    仅在深度 0 且不在引号/正则内时识别 op。
    """
    in_dq = False
    in_sq = False
    in_re = False
    depth = 0
    start = 0
    i = 0
    oplen = len(op)

    while i < len(s):
        ch = s[i]
        if in_dq:
            if ch == '\\' and i + 1 < len(s):
                i += 2
                continue
            if ch == '"':
                in_dq = False
            i += 1
            continue
        if in_sq:
            if ch == '\\' and i + 1 < len(s):
                i += 2
                continue
            if ch == "'":
                in_sq = False
            i += 1
            continue
        if in_re:
            if ch == '\\' and i + 1 < len(s):
                i += 2
                continue
            if ch == '/':
                in_re = False
            i += 1
            continue
        if ch == '"':
            in_dq = True
            i += 1
            continue
        if ch == "'":
            in_sq = True
            i += 1
            continue
        if ch == '/':
            in_re = True
            i += 1
            continue
        if ch == '(':
            depth += 1
            i += 1
            continue
        if ch == ')':
            depth -= 1
            i += 1
            continue
        if depth == 0 and s[i:i + oplen] == op:
            on_op(start, i)
            start = i + oplen
            i = start
            continue
        i += 1

    # 末尾残余
    on_op(start, len(s), is_tail=True)


def _find_toplevel_op(s: str, op: str) -> int:
    """查找顶层 op 首次出现的位置，返回索引或 -1。"""
    result = -1

    def _found(start, end, is_tail=False):
        nonlocal result
        if result < 0 and not is_tail:
            result = end  # end 即 op 在 s 中的起始位置

    _walk_toplevel(s, op, _found)
    return result


def _split_toplevel(s: str, op: str) -> list[str]:
    """按顶层 op 切分。"""
    parts: list[str] = []

    def _collect(start, end, is_tail=False):
        parts.append(s[start:end])

    _walk_toplevel(s, op, _collect)
    return [p for p in parts if p.strip()]


# ── 原子解析 ────────────────────────────────────────────

def _parse_atom(s: str) -> "AtomCondition | None":
    """解析单个原子条件：field op value。"""
    import sys

    for op in ("=~", "!~", "==", "!="):
        idx = _find_toplevel_op(s, op)
        if idx >= 0:
            field = s[:idx].strip()
            rest = s[idx + len(op):].strip()

            if op in ("=~", "!~"):
                if rest.startswith("/") and rest.endswith("/"):
                    value = rest[1:-1]
                else:
                    print(f"[hook] invalid regex literal in: {s!r}", file=sys.stderr)
                    return None
            else:
                value = _unquote(rest)

            if not field:
                print(f"[hook] empty field in atom: {s!r}", file=sys.stderr)
                return None

            from Alincode.hook.rule import AtomCondition
            return AtomCondition(field=field, op=op, value=value)

    print(f"[hook] unknown operator in atom: {s!r}", file=sys.stderr)
    return None


def _unquote(s: str) -> str:
    """去掉引号（双引号或单引号）。"""
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


# ── 字段路径取值 ────────────────────────────────────────

def get_by_path(p: "Payload", path: str) -> str:
    """按 `.` 分隔路径从 payload 取值，返回字符串。"""
    parts = path.split(".")
    cur = p
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return ""
        cur = cur[part]
        if cur is None:
            return ""

    if isinstance(cur, bool):
        return str(cur)
    if isinstance(cur, (int, float)):
        return str(cur)
    if isinstance(cur, str):
        return cur
    return json.dumps(cur, sort_keys=True)


# ── 条件求值 ────────────────────────────────────────────

def eval_condition(c: "Condition | None", p: "Payload") -> bool:
    """求值条件表达式。c 为 None 时无条件触发。"""
    if c is None:
        return True

    results = []
    for atom in c.atoms:
        field_val = get_by_path(p, atom.field)
        op = atom.op
        if op == "==":
            results.append(field_val == atom.value)
        elif op == "!=":
            results.append(field_val != atom.value)
        elif op == "=~":
            try:
                results.append(bool(re.search(atom.value, field_val)))
            except re.error:
                results.append(False)
        elif op == "!~":
            try:
                results.append(not bool(re.search(atom.value, field_val)))
            except re.error:
                results.append(False)
        else:
            results.append(False)

    from Alincode.hook.rule import CombineMode
    if c.mode == CombineMode.ALL_OF:
        return all(results)
    return any(results)
