"""Prompt 包桥接：避免 skills ↔ prompt 循环依赖（T9）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptItem:
    """第一阶段：名字 + 描述（注入 system prompt skills-catalog 模块）。"""
    name: str
    description: str


@dataclass(frozen=True)
class PromptEntry:
    """第二阶段：激活的 Skill 正文（注入 env context active-skills 块）。"""
    name: str
    body: str


def catalog_to_prompt_items(catalog) -> list[PromptItem]:
    """从 Catalog 提取第一阶段列表。"""
    return [PromptItem(name=s.meta.name, description=s.meta.description) for s in catalog.list()]


def active_to_prompt_entries(active) -> list[PromptEntry]:
    """从 ActiveSkills 提取第二阶段列表。"""
    return [PromptEntry(name=e.name, body=e.body) for e in active.snapshot()]
