"""Matcher Protocol 与四种匹配实现：Exact / Glob / Regex / Not（F1/F2/F3）。

权限规则与 Hook 条件共用同一套匹配语义。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Protocol


class Matcher(Protocol):
    """规则匹配的统一接口。四种实现：ExactMatcher / GlobMatcher / RegexMatcher / NotMatcher。"""

    def match(self, s: str) -> bool: ...
    def __str__(self) -> str: ...   # 调试 / /hooks 输出用


# ── 四种实现 ────────────────────────────────────────────

@dataclass(frozen=True)
class ExactMatcher:
    """精确匹配：整串相等。"""

    value: str

    def match(self, s: str) -> bool:
        return s == self.value

    def __str__(self) -> str:
        return f"={self.value}"


@dataclass(frozen=True)
class GlobMatcher:
    """Glob 通配匹配：用 fnmatch 做大小写敏感匹配。

    is_command: True 时匹配整串（command 模式），False 时匹配路径段内（path 模式）。
    两种模式都使用 fnmatch，区别在于调用方的语义约定。
    """

    pattern: str
    is_command: bool = False

    def match(self, s: str) -> bool:
        return fnmatch(s, self.pattern)

    def __str__(self) -> str:
        return self.pattern


@dataclass(frozen=True)
class RegexMatcher:
    """正则匹配：用 re.search 做部分匹配。"""

    src: str
    compiled: re.Pattern[str]

    def match(self, s: str) -> bool:
        return self.compiled.search(s) is not None

    def __str__(self) -> str:
        return f"~{self.src}"


@dataclass(frozen=True)
class NotMatcher:
    """反向匹配：对内层 matcher 取反。"""

    inner: Matcher

    def match(self, s: str) -> bool:
        return not self.inner.match(s)

    def __str__(self) -> str:
        return f"!{self.inner}"


# ── 工厂 ────────────────────────────────────────────────

def compile_matcher(pattern: str, *, is_command: bool = False) -> Matcher:
    """解析单条匹配描述串，返回 Matcher 实例。失败抛 ValueError。

    描述串规则：
      "=value"  → ExactMatcher("value")
      "~regex"  → RegexMatcher("regex", re.compile("regex"))
      "!inner"  → NotMatcher(compile_matcher(inner, is_command=is_command))
      "value"   → GlobMatcher("value", is_command=is_command)

    空字符串抛出 ValueError。
    """
    if not pattern:
        raise ValueError("empty matcher pattern")

    head, rest = pattern[0], pattern[1:]

    if head == "=":
        return ExactMatcher(rest)

    if head == "~":
        try:
            return RegexMatcher(rest, re.compile(rest))
        except re.error as e:
            raise ValueError(f"invalid regex: {e}") from e

    if head == "!":
        inner = compile_matcher(rest, is_command=is_command)
        return NotMatcher(inner)

    return GlobMatcher(pattern, is_command)
