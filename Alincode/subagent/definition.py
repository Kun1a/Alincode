"""SubAgent Definition 数据类型（T1）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Source(IntEnum):
    """定义来源优先级：数字越大优先级越高。"""
    BUILTIN = 0
    USER = 1
    PROJECT = 2
    PLUGIN = 3  # 占位，本期不实现

    def __str__(self) -> str:
        return {0: "builtin", 1: "user", 2: "project", 3: "plugin"}.get(int(self), "unknown")


@dataclass
class Definition:
    """一个 Agent 角色的完整定义，从 Markdown + YAML frontmatter 解析。"""

    name: str                              # frontmatter.name — 角色名
    description: str                       # frontmatter.description — 用途说明
    tools: list[str] = field(default_factory=list)             # 工具白名单；空 = 不收窄
    disallowed_tools: list[str] = field(default_factory=list)  # 工具黑名单
    model: str = "inherit"                 # haiku / sonnet / opus / inherit
    max_turns: int = 0                     # 0 = 沿用全局 MAX_ITERATIONS
    permission_mode: str = "default"       # default / acceptEdits / plan / bypassPermissions / dontAsk
    dont_ask: bool = False                 # 是否自动批准 ASK 类工具
    background: bool = False               # 强制后台
    system_prompt: str = ""                # Markdown body（去 frontmatter 后的全文）
    file_path: str = ""                    # 定义文件路径（调试用）
    source: Source = Source.BUILTIN

    def is_fork(self) -> bool:
        return self.name == "__fork__"
