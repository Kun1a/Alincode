"""MCP 工具适配：把远端工具包装成内置 Tool 协议（F7/F8）。"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import Any, Protocol

from Alincode.tools import Result

_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_non_text_warned: set[str] = set()
execute_timeout: float = 30.0  # 包级变量，单测可临时修改


class CalleeSession(Protocol):
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None,
    ) -> Any: ...


class McpTool:
    """实现 Tool 协议的 MCP 远端工具——所有属性走方法，兼容 Protocol。"""

    def __init__(
        self,
        full_name: str,
        remote_name: str,
        description: str,
        parameters: dict[str, Any],
        read_only: bool,
        caller: CalleeSession,
        server_name: str = "",
    ) -> None:
        self._full_name = full_name
        self._remote_name = remote_name
        self._description = description
        self._parameters = parameters
        self._read_only = read_only
        self._caller = caller
        self.server_name = server_name

    def name(self) -> str:
        return self._full_name

    def description(self) -> str:
        return self._description

    def parameters(self) -> dict[str, Any]:
        return self._parameters

    @property
    def read_only(self) -> bool:
        return self._read_only

    async def execute(self, args: str) -> Result:
        import json
        try:
            arg_map: dict[str, Any] | None = json.loads(args) if args.strip() else None
        except json.JSONDecodeError:
            return Result(content="MCP 工具参数 JSON 解析失败", is_error=True)
        if arg_map is not None and not isinstance(arg_map, dict):
            return Result(
                content="MCP 工具参数必须是 JSON 对象（不能是数组或基本类型）",
                is_error=True,
            )

        try:
            result = await asyncio.wait_for(
                self._caller.call_tool(self._remote_name, arg_map),
                timeout=execute_timeout,
            )
        except asyncio.TimeoutError:
            return Result(content=f"MCP 工具调用超时 ({execute_timeout:.0f}s)", is_error=True)
        except Exception as e:
            return Result(content=f"MCP 工具调用失败: {e}", is_error=True)

        texts = []
        non_text_count = 0
        for block in getattr(result, "content", []) or []:
            if _is_text_content(block):
                texts.append(block.text)
            else:
                non_text_count += 1

        if non_text_count and self._full_name not in _non_text_warned:
            _non_text_warned.add(self._full_name)
            print(
                f"[mcp] warn: tool {self._full_name} returned "
                f"{non_text_count} non-text content block(s) (dropped)",
                file=sys.stderr,
            )

        content = "\n".join(texts)
        is_error = bool(getattr(result, "isError", False))
        return Result(content=content, is_error=is_error)


def _is_text_content(block: Any) -> bool:
    return hasattr(block, "text") and hasattr(block, "type") and block.type == "text"


def adapt_tool(
    server_name: str,
    remote_tool: Any,
    session: CalleeSession,
) -> McpTool | None:
    tool_name = getattr(remote_tool, "name", "")
    full_name = f"mcp__{server_name}__{tool_name}"

    if not _VALID_NAME.fullmatch(full_name):
        print(
            f"[mcp] warn: skip tool {full_name}: "
            f"name contains illegal characters",
            file=sys.stderr,
        )
        return None

    desc = getattr(remote_tool, "description", "") or ""
    if not desc:
        desc = f"来自 MCP server {server_name} 的工具 {tool_name}"

    raw_schema = getattr(remote_tool, "inputSchema", None) or {}
    schema = dict(raw_schema) if isinstance(raw_schema, dict) else {}
    if not schema:
        schema = {"type": "object"}

    annotations = getattr(remote_tool, "annotations", None)
    read_only = bool(getattr(annotations, "readOnlyHint", False)) if annotations else False

    return McpTool(
        full_name=full_name,
        remote_name=tool_name,
        description=desc,
        parameters=schema,
        read_only=read_only,
        caller=session,
        server_name=server_name,
    )
