"""权限系统类型定义：五层防御的公共数据结构。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum


# ── 裁决结果 ──────────────────────────────────────────

class Verdict(Enum):
    ALLOW = "allow"   # 放行
    DENY = "deny"     # 拦截（回灌结构化错误）
    ASK = "ask"       # 人在回路（发 ApprovalRequest，等用户决策）


# ── 人在回路结果 ──────────────────────────────────────

class Outcome(Enum):
    ALLOW_ONCE = "allow_once"      # 允许本次
    ALLOW_FOREVER = "allow_forever"  # 永久允许（写本地配置）
    DENY_ONCE = "deny_once"        # 拒绝本次


# ── 人在回路请求 ──────────────────────────────────────

@dataclass
class ApprovalRequest:
    """向 TUI 发出的待批准请求。"""
    tool_name: str
    tool_args: str         # 参数预览
    reason: str            # 触发原因（如 "writing outside project root"）
    verdict: Verdict       # 原始裁决（ASK）
    respond: asyncio.Future | None = None  # TUI 调 set_result(Outcome)


# ── 工具调用类别 ──────────────────────────────────────

class ToolCategory(Enum):
    READ = "read"          # read_file
    WRITE = "write"        # write_file
    EDIT = "edit"          # edit_file
    EXEC = "exec"          # bash
    GLOB = "glob"          # glob
    GREP = "grep"          # grep


# ── 规则记录 ──────────────────────────────────────────

@dataclass
class RuleRecord:
    """一条权限规则。"""
    tool: str              # 友好名或内部名
    pattern: str           # 参数/路径匹配模式
    verdict: str           # "allow" | "deny"
    source: str = ""       # 来自哪个文件


# ── 模式枚举 ──────────────────────────────────────────

class Mode(Enum):
    DEFAULT = "default"            # 只读 Allow，写/执行 Ask
    ACCEPT_EDITS = "acceptEdits"   # 文件写 Allow，命令执行 Ask
    PLAN = "plan"                  # 仅只读工具可见
    BYPASS = "bypassPermissions"   # 全 Allow（黑名单+沙箱除外）
