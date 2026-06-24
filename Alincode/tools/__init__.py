"""Tools 子系统：统一工具抽象、注册中心、核心工具集。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from Alincode.conversation import ToolDefinition

# 单个工具执行的默认超时秒数（不可配）
DEFAULT_TIMEOUT: float = 30.0


# ── 工具执行结果 ─────────────────────────────────────────

@dataclass
class Result:
    """工具执行结果——永远以值类型返回，从不抛 Python 异常给上层。

    is_error=True 表示结构化错误，content 即为错误描述。
    """
    content: str
    is_error: bool = False


# ── 工具抽象 ────────────────────────────────────────────

@runtime_checkable
class Tool(Protocol):
    """统一工具抽象（F1）。

    每个工具暴露名称、给模型看的描述、参数 JSON Schema、执行入口。
    参数取 raw JSON 字符串，方便从 LLM 工具调用的 input 字段直接传入。
    """

    def name(self) -> str:
        """模型看到的工具名，如 "read_file"。"""
        ...

    def description(self) -> str:
        """给模型的用途说明，影响模型选工具的质量。"""
        ...

    def parameters(self) -> dict[str, Any]:
        """手写 JSON Schema（type/properties/required/description）。"""
        ...

    async def execute(self, args: str) -> Result:
        """执行工具，args 为 raw JSON 字符串。超时由 Registry 层控制。"""
        ...


# ── 辅助：文本截断 ────────────────────────────────────────

def _truncate(s: str, max_lines: int, max_chars: int) -> str:
    """按行数和字符数上限截断文本，超出尾部追加 [truncated] 标注。

    Args:
        s: 原始文本
        max_lines: 最多保留的行数
        max_chars: 最多保留的字符数
    """
    lines = s.split("\n")
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append("[truncated]")
        s = "\n".join(lines)

    if len(s) > max_chars:
        s = s[:max_chars] + "\n[truncated]"

    return s


# ── 注册中心 ────────────────────────────────────────────

class Registry:
    """集中登记工具、按名查我、导出 API 定义、按名执行。

    保持注册顺序，导出的工具定义列表稳定可预测。
    """

    def __init__(self) -> None:
        self._order: list[str] = []
        self._tools: dict[str, Tool] = {}

    def register(self, t: Tool) -> None:
        """注册工具。重名时抛出 ValueError。"""
        n = t.name()
        if n in self._tools:
            raise ValueError(f"工具名重复: {n}")
        self._order.append(n)
        self._tools[n] = t

    def get(self, name: str) -> Tool | None:
        """按名查找工具，未找到返回 None。"""
        return self._tools.get(name)

    def definitions(self) -> list[ToolDefinition]:
        """按注册顺序导出协议无关工具定义列表（F3/AC1）。"""
        return [
            ToolDefinition(
                name=t.name(),
                description=t.description(),
                input_schema=t.parameters(),
            )
            for t in map(self._tools.get, self._order)
            if t is not None
        ]

    async def execute(self, name: str, args: str, timeout: float = DEFAULT_TIMEOUT) -> Result:
        """按名查找工具并执行，受超时保护。

        未知工具 / 超时 / 异常全部转换为 Result(is_error=True)，
        不抛异常给上层（F5/F9/N4）。
        """
        tool = self.get(name)
        if tool is None:
            return Result(content=f"未知工具: {name}", is_error=True)

        try:
            return await asyncio.wait_for(tool.execute(args), timeout=timeout)
        except asyncio.TimeoutError:
            return Result(content=f"工具 {name} 执行超时（{timeout}s）", is_error=True)
        except Exception as e:
            return Result(content=f"工具 {name} 异常: {e}", is_error=True)


# ── 默认工具集工厂 ─────────────────────────────────────────

def new_default_registry() -> Registry:
    """构造并注册 6 个核心工具，返回 Registry。

    工具按序注册：read_file、write_file、edit_file、bash、glob、grep。
    """
    from Alincode.tools.read_file import ReadFileTool
    from Alincode.tools.write_file import WriteFileTool
    from Alincode.tools.edit_file import EditFileTool
    from Alincode.tools.bash import BashTool
    from Alincode.tools.glob_tool import GlobTool
    from Alincode.tools.grep_tool import GrepTool

    registry = Registry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(BashTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    return registry


__all__ = [
    "Tool",
    "Result",
    "Registry",
    "DEFAULT_TIMEOUT",
    "_truncate",
    "new_default_registry",
]
