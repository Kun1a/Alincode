"""Hook 数据结构：Rule / Condition / Action / Payload。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Alincode.hook.event import Event


class CombineMode(str, Enum):
    ALL_OF = "all_of"
    ANY_OF = "any_of"


class ActionType(str, Enum):
    COMMAND = "command"
    PROMPT = "prompt"
    HTTP = "http"
    SUBAGENT = "subagent"


# ── 条件原子 ────────────────────────────────────────────

@dataclass
class AtomCondition:
    """原子条件：字段 + 运算符 + 值。"""
    field: str          # 如 "tool"、"args.file_path"
    op: str             # "==" | "=~" | "!=" | "!~"
    value: str          # 比较值（正则时不含 / 分隔符）


@dataclass
class Condition:
    """条件组合：all_of / any_of 二选一。"""
    mode: CombineMode
    atoms: list[AtomCondition]

    @classmethod
    def all_of(cls, atoms: list[AtomCondition]) -> "Condition":
        return cls(mode=CombineMode.ALL_OF, atoms=atoms)

    @classmethod
    def any_of(cls, atoms: list[AtomCondition]) -> "Condition":
        return cls(mode=CombineMode.ANY_OF, atoms=atoms)


# ── 动作 ────────────────────────────────────────────────

@dataclass
class CommandAction:
    command: str


@dataclass
class PromptAction:
    text: str


@dataclass
class HttpAction:
    url: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None


@dataclass
class SubagentAction:
    agent_name: str
    prompt: str


@dataclass
class Action:
    type: ActionType
    command: CommandAction | None = None
    prompt: PromptAction | None = None
    http: HttpAction | None = None
    subagent: SubagentAction | None = None


# ── 规则 ────────────────────────────────────────────────

@dataclass
class Rule:
    """一条 Hook 规则。"""
    id: str                         # 唯一标识（原 name）
    event: "Event"
    action: Action
    condition: Condition | None = None
    reject: bool = False            # 拦截语义：用 stdout 作为拒绝原因
    only_once: bool = False
    async_mode: bool = False        # 后台异步执行
    timeout_s: float = 30.0
    source: str = ""


# ── 类型别名 ────────────────────────────────────────────

Payload = dict[str, Any]
