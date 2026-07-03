"""工具上下文：explicit cwd 注入（F16/F18）。"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_cwd_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("cwd", default=None)


@contextmanager
def with_cwd(dir_path: str) -> Iterator[None]:
    """在上下文内设置工具级的 cwd。"""
    token = _cwd_ctx.set(str(dir_path))
    try:
        yield
    finally:
        _cwd_ctx.reset(token)


def cwd_from_ctx() -> str | None:
    """获取当前上下文的 cwd。"""
    return _cwd_ctx.get()


def resolve_path(p: str) -> str:
    """解析路径：绝对路径直接返回，相对路径优先用 ctx cwd 拼接。"""
    path = Path(p)
    if path.is_absolute():
        return str(path)
    ctx_cwd = cwd_from_ctx()
    if ctx_cwd:
        return str(Path(ctx_cwd) / p)
    return str(Path.cwd() / p)
