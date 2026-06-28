"""系统提示装配：模块化构建、缓存分离、环境注入（F1/AC1）。"""

from __future__ import annotations

from dataclasses import dataclass

from Alincode.prompt.modules import FIXED_MODULES, OPTIONAL_MODULES
from Alincode.prompt.environment import Environment, gather_environment
from Alincode.prompt.reminder import (
    system_reminder,
    plan_reminder,
    PLAN_FULL,
    PLAN_LITE,
    EXECUTE_DIRECTIVE,
)


@dataclass
class Module:
    """系统提示的一个可装配模块。"""
    priority: int
    key: str
    content: str


def _to_modules(raw: list[dict]) -> list[Module]:
    """将原始 dict 列表转为 Module 对象，空 content 自动过滤。"""
    return [Module(**item) for item in raw if item.get("content", "").strip()]


def assemble_system(
    fixed: list[Module] | None = None,
    optional: list[Module] | None = None,
    instructions: str = "",
    memory: str = "",
) -> str:
    """将固定和可选模块按优先级排序，以空行分隔拼装（AC1）。

    Args:
        fixed: 固定模块列表，None 时使用默认 FIXED_MODULES
        optional: 可选模块列表，None 时使用默认 OPTIONAL_MODULES
        instructions: 非空时填入 custom_instructions 槽位
        memory: 非空时填入 long_term_memory 槽位

    Returns:
        完整的系统提示文本（稳定块）
    """
    if fixed is None:
        fixed = _to_modules(FIXED_MODULES)
    if optional is None:
        optional = _to_modules(OPTIONAL_MODULES)

    # 用传入值填充可选模块
    for m in optional:
        if m.key == "custom_instructions" and instructions:
            m.content = instructions
        elif m.key == "long_term_memory" and memory:
            m.content = memory

    all_modules = sorted(fixed + optional, key=lambda m: m.priority)
    return "\n\n".join(m.content for m in all_modules if m.content.strip())


def build_system_prompt(
    env: Environment | None = None,
    instructions: str = "",
    memory: str = "",
) -> tuple[str, str]:
    """构建完整系统提示，返回 (stable_block, environment_block)。

    - stable_block：模块化系统提示，可缓存（N1/AC5）
    - environment_block：动态环境信息，不缓存
    - instructions：非空时填入 custom_instructions 槽位
    - memory：非空时填入 long_term_memory 槽位
    """
    stable = assemble_system(instructions=instructions, memory=memory)
    env_block = env.render() if env else ""
    return stable, env_block


__all__ = [
    "Module",
    "assemble_system",
    "build_system_prompt",
    "Environment",
    "gather_environment",
    "system_reminder",
    "plan_reminder",
    "PLAN_FULL",
    "PLAN_LITE",
    "EXECUTE_DIRECTIVE",
]
