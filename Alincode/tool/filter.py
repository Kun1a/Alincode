"""工具过滤多层防线（T8 / F26-F30）。"""

from __future__ import annotations

from dataclasses import dataclass, field

# 任何子 Agent 永远不能用的工具名列表
ALL_AGENT_DISALLOWED_TOOLS: list[str] = ["Agent"]

# 自定义 Agent 额外禁用（本期为空，接口预留）
CUSTOM_AGENT_DISALLOWED_TOOLS: list[str] = []

# 后台 Agent 工具白名单
ASYNC_AGENT_ALLOWED_TOOLS: list[str] = [
    "read_file", "write_file", "edit_file",
    "glob", "grep",
    "bash",
    "load_skill", "install_skill",
]


@dataclass
class FilterParams:
    """工具过滤参数。"""
    all_tools: list[str]              # registry 的全部工具名
    source: int = 0                    # subagent.Source 的整数值
    background: bool = False
    allowed: list[str] = field(default_factory=list)    # Agent 定义 tools 白名单
    disallowed: list[str] = field(default_factory=list) # Agent 定义 disallowedTools 黑名单


def apply_agent_tool_filter(p: FilterParams) -> list[str]:
    """按 F30 顺序应用五层过滤，返回最终工具名列表。"""
    result = list(p.all_tools)

    # 1. 全局禁止
    result = [n for n in result if n not in ALL_AGENT_DISALLOWED_TOOLS]

    # 2. 自定义 Agent 额外禁止（本期为空）
    if p.source >= 2:  # user/project/plugin
        result = [n for n in result if n not in CUSTOM_AGENT_DISALLOWED_TOOLS]

    # 3. 后台白名单交集
    if p.background:
        allowed_set = set(ASYNC_AGENT_ALLOWED_TOOLS)
        # MCP 工具 / skill 工具动态放行
        result = [n for n in result if n in allowed_set or _is_mcp_or_skill(n)]

    # 4. 黑名单排除
    if p.disallowed:
        dis_set = set(p.disallowed)
        result = [n for n in result if n not in dis_set]

    # 5. 白名单收窄
    if p.allowed:
        allowed_set = set(p.allowed)
        result = [n for n in result if n in allowed_set]

    return result


def _is_mcp_or_skill(name: str) -> bool:
    """MCP 工具（mcp__ 前缀）和 skill 工具动态识别。"""
    return name.startswith("mcp__") or name.startswith("skill__")
