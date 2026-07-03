"""Worktree slug 校验（F1）。"""

import re

MAX_SLUG_LEN = 64
_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def validate_slug(name: str) -> None:
    """校验 worktree name（slug）。

    规则：非空、长度 ≤ 64、按 / 切段每段匹配 [a-zA-Z0-9._-]+、不能是 . 或 ..、
    无连续 //、无首末 /。失败抛 ValueError。
    """
    if not name:
        raise ValueError("slug 不能为空")
    if len(name) > MAX_SLUG_LEN:
        raise ValueError(f"slug 长度不能超过 {MAX_SLUG_LEN}，当前 {len(name)}")
    if name.startswith("/"):
        raise ValueError("slug 不能以 / 开头")
    if name.endswith("/"):
        raise ValueError("slug 不能以 / 结尾")
    if "//" in name:
        raise ValueError("slug 不能包含连续的 //")

    for segment in name.split("/"):
        if segment in (".", ".."):
            raise ValueError(f"slug 段名不能是 '{segment}'")
        if not _SEGMENT_RE.match(segment):
            raise ValueError(f"slug 段名包含非法字符: '{segment}'")


def flat_slug(name: str) -> str:
    """将嵌套 slug 的 / 替换为 + 以避免 Git D/F 冲突。"""
    return name.replace("/", "+")
