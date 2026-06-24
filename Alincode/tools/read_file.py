"""read_file 工具：读取文件内容，带行号返回。"""

from __future__ import annotations

import json
from pathlib import Path

from Alincode.tools import Result, _truncate

# 上限：2000 行 / 256KB
MAX_LINES = 2000
MAX_CHARS = 256 * 1024


class ReadFileTool:
    """读取文件工具：给定路径，返回带行号的文本内容。

    行号格式：`    1\tcontent`（右对齐 6 位）。
    文件不存在 / 不可读 / 是目录时返回结构化错误。
    """

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return (
            "读取指定文件的文本内容，返回带行号的文本。"
            "适用于查看源代码、文档、配置文件。"
            "文件不存在或不可读时返回错误信息。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要读取的文件路径（相对或绝对）",
                }
            },
            "required": ["path"],
        }

    async def execute(self, args: str) -> Result:
        """执行读取。"""
        try:
            data = json.loads(args) if args and args.strip() else {}
            path_str = data.get("path", "")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)

        if not path_str:
            return Result(content="缺少必填参数: path", is_error=True)

        file_path = Path(path_str)
        if not file_path.exists():
            return Result(content=f"文件不存在: {path_str}", is_error=True)
        if file_path.is_dir():
            return Result(content=f"路径是目录而非文件: {path_str}", is_error=True)

        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return Result(content=f"无权限读取文件: {path_str}", is_error=True)
        except OSError as e:
            return Result(content=f"读取文件失败: {e}", is_error=True)

        lines = text.split("\n")
        numbered = [f"{i+1:6d}\t{line}" for i, line in enumerate(lines)]

        result = _truncate("\n".join(numbered), MAX_LINES, MAX_CHARS)
        return Result(content=result)
