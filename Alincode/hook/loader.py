"""Hook 配置加载：从 config.yaml 的 hooks 节点解析规则。

配置格式：
  hooks:
    - id: block-json
      event: pre_tool_use
      if: 'tool == "write_file" && args.file_path =~ /\\.json$/'
      action:
        type: command
        command: 'echo "禁止直接写入 JSON 文件"'
      reject: true

也兼容从独立 hooks.yaml 文件加载（旧格式，用于测试/迁移）。
"""

from __future__ import annotations

import re as _re
import sys
from pathlib import Path

import yaml

from Alincode.hook.event import parse_event, is_blocking
from Alincode.hook.rule import (
    Rule, Condition, AtomCondition, Action, ActionType, CombineMode,
    CommandAction, PromptAction, HttpAction, SubagentAction,
)
from Alincode.hook.engine import Engine
from Alincode.hook.matcher import parse_condition


def load_from_dict(hooks_list: list[dict], source: str = "config.yaml") -> Engine:
    """从 config.yaml 的 hooks 列表构造 Engine。"""
    rules: list[Rule] = []
    seen_ids: set[str] = set()

    for idx, raw in enumerate(hooks_list):
        if not isinstance(raw, dict):
            print(f"[hook] hooks[{idx}] is not a dict, skipped", file=sys.stderr)
            continue

        rule = _compile_rule(raw, source, idx)
        if rule is None:
            continue

        if rule.id in seen_ids:
            print(f'[hook] duplicate id "{rule.id}" skipped', file=sys.stderr)
            continue

        seen_ids.add(rule.id)
        rules.append(rule)

    return Engine(rules=rules, sources=[source])


def load_from_file(file_path: str | Path) -> Engine:
    """从独立 hooks.yaml 文件加载（兼容旧格式）。"""
    file_path = Path(file_path)
    if not file_path.is_file():
        return Engine(rules=[], sources=[])

    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[hook] failed to parse {file_path}: {e}", file=sys.stderr)
        return Engine(rules=[], sources=[])

    if not isinstance(data, dict) or "hooks" not in data:
        return Engine(rules=[], sources=[])

    return load_from_dict(data["hooks"], str(file_path.resolve()))


# ── 内部编译 ────────────────────────────────────────────

def _compile_rule(raw: dict, source: str, idx: int) -> Rule | None:
    """校验并编译单条 hook 规则。"""
    # id 必填
    rule_id = raw.get("id", "")
    if not rule_id or not isinstance(rule_id, str):
        print(f"[hook] hooks[{idx}] in {source}: 'id' required, skipped", file=sys.stderr)
        return None

    # event 必填
    event_str = raw.get("event", "")
    event = parse_event(str(event_str))
    if event is None:
        print(f'[hook {rule_id}]: unknown event "{event_str}", skipped', file=sys.stderr)
        return None

    # action 必填
    action = _compile_action(rule_id, raw.get("action", {}), source)
    if action is None:
        return None

    # 条件（可选，新格式是字符串表达式）
    condition = None
    if_raw = raw.get("if")
    if if_raw is not None:
        if isinstance(if_raw, str):
            condition = parse_condition(if_raw)
        elif isinstance(if_raw, dict):
            # 向后兼容旧结构化格式
            condition = _compile_condition_legacy(rule_id, if_raw, source)
        if condition is None and isinstance(if_raw, str) and if_raw.strip():
            # parse_condition 已打印错误
            return None

    # reject（新格式：拦截开关）
    reject = bool(raw.get("reject", False))

    # only_once
    only_once = bool(raw.get("only_once", False))

    # async
    async_mode = bool(raw.get("async", False))
    if async_mode and is_blocking(event):
        print(f'[hook {rule_id}]: async not allowed for blocking events, skipped', file=sys.stderr)
        return None

    # timeout
    timeout_s = _parse_duration(raw.get("timeout", "30s"))
    if timeout_s is None:
        timeout_s = 30.0

    return Rule(
        id=rule_id,
        event=event,
        action=action,
        condition=condition,
        reject=reject,
        only_once=only_once,
        async_mode=async_mode,
        timeout_s=timeout_s,
        source=source,
    )


def _compile_action(rule_id: str, raw: dict, source: str) -> Action | None:
    """校验 action 对象。"""
    type_str = raw.get("type", "")
    try:
        action_type = ActionType(type_str)
    except ValueError:
        print(f'[hook {rule_id}]: unknown action type "{type_str}", skipped', file=sys.stderr)
        return None

    if action_type == ActionType.COMMAND:
        cmd = raw.get("command", "")
        if not cmd:
            print(f'[hook {rule_id}]: command action requires "command", skipped', file=sys.stderr)
            return None
        return Action(type=action_type, command=CommandAction(command=str(cmd)))

    if action_type == ActionType.PROMPT:
        text = raw.get("text", "")
        if not text:
            print(f'[hook {rule_id}]: prompt action requires "text", skipped', file=sys.stderr)
            return None
        return Action(type=action_type, prompt=PromptAction(text=str(text)))

    if action_type == ActionType.HTTP:
        url = raw.get("url", "")
        if not url:
            print(f'[hook {rule_id}]: http action requires "url", skipped', file=sys.stderr)
            return None
        method = str(raw.get("method", "POST")).upper()
        headers = {str(k): str(v) for k, v in raw.get("headers", {}).items()} if isinstance(raw.get("headers"), dict) else {}
        body = str(raw["body"]) if raw.get("body") is not None else None
        return Action(type=action_type, http=HttpAction(url=str(url), method=method, headers=headers, body=body))

    if action_type == ActionType.SUBAGENT:
        agent_name = str(raw.get("agent_name", ""))
        prompt = str(raw.get("prompt", ""))
        if not agent_name or not prompt:
            print(f'[hook {rule_id}]: subagent action requires "agent_name" and "prompt", skipped', file=sys.stderr)
            return None
        return Action(type=action_type, subagent=SubagentAction(agent_name=agent_name, prompt=prompt))

    return None


def _compile_condition_legacy(rule_id: str, raw: dict, source: str) -> Condition | None:
    """向后兼容旧结构化条件格式（all_of / any_of + match dict）。"""
    has_all = "all_of" in raw
    has_any = "any_of" in raw
    if has_all and has_any:
        print(f'[hook {rule_id}]: "if" cannot contain both all_of and any_of, skipped', file=sys.stderr)
        return None
    if not has_all and not has_any:
        print(f'[hook {rule_id}]: "if" must contain all_of or any_of, skipped', file=sys.stderr)
        return None

    mode = CombineMode.ALL_OF if has_all else CombineMode.ANY_OF
    raw_atoms = raw["all_of"] if has_all else raw["any_of"]
    if not isinstance(raw_atoms, list) or not raw_atoms:
        return None

    atoms = []
    for i, atom_raw in enumerate(raw_atoms):
        if not isinstance(atom_raw, dict):
            return None
        field = str(atom_raw.get("field", ""))
        match_raw = atom_raw.get("match", {})
        if not isinstance(match_raw, dict):
            return None

        match_type = match_raw.get("type", "exact")
        match_value = match_raw.get("value", "")

        if match_type == "exact":
            atoms.append(AtomCondition(field=field, op="==", value=str(match_value)))
        elif match_type == "regex":
            atoms.append(AtomCondition(field=field, op="=~", value=str(match_value)))
        elif match_type == "glob":
            # glob 转成 fnmatch 语义 — 用通配符直接存
            atoms.append(AtomCondition(field=field, op="=~", value=_glob_to_regex(str(match_value))))
        elif match_type == "not":
            inner = match_raw.get("inner", {})
            inner_type = inner.get("type", "exact")
            inner_value = str(inner.get("value", ""))
            if inner_type == "exact":
                atoms.append(AtomCondition(field=field, op="!=", value=inner_value))
            elif inner_type == "regex":
                atoms.append(AtomCondition(field=field, op="!~", value=inner_value))
            elif inner_type == "glob":
                atoms.append(AtomCondition(field=field, op="!~", value=_glob_to_regex(inner_value)))

    if not atoms:
        return None
    return Condition(mode=mode, atoms=atoms)


def _glob_to_regex(pattern: str) -> str:
    """简单 glob → regex（仅支持 * 和 **）。"""
    s = _re.escape(pattern)
    s = s.replace(r"\*\*", "___DOUBLESTAR___")
    s = s.replace(r"\*", r"[^/]*")
    s = s.replace("___DOUBLESTAR___", r".*")
    return s


def _parse_duration(s: object) -> float | None:
    """解析时长字符串。"""
    if isinstance(s, (int, float)):
        return float(s)
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    m = _re.match(r"^(\d+(?:\.\d+)?)$", s)
    if m:
        return float(m.group(1))
    m = _re.match(r"^(\d+(?:\.\d+)?)\s*([smh])$", s)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit == "s":
            return val
        if unit == "m":
            return val * 60
        if unit == "h":
            return val * 3600
    return None
