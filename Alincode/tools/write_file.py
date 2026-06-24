"""write_file 工具：写入（覆盖）文件，父目录不存在时自动创建。"""

from __future__ import annotations

import json
from pathlib import Path

from Alincode.tools import Result


class WriteFileTool:
    """写文件工具：给定路径与内容，写入（覆盖）文件。

    父目录不存在时自动递归创建。
    """

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return (
            "写入（覆盖）指定路径的文件。"
            "父目录不存在时自动创建。"
            "适用于创建新文件或覆盖已有文件。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要写入的文件路径（相对或绝对）",
                },
                "content": {
                    "type": "string",
                    "description": "要写入文件的完整文本内容",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: str) -> Result:
        """执行写入。"""
        try:
            data = json.loads(args) if args and args.strip() else {}
            path_str = data.get("path", "")
            content = data.get("content", "")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)

        if not path_str:
            return Result(content="缺少必填参数: path", is_error=True)
        if "content" not in (data if isinstance(data, dict) else {}):
            return Result(content="缺少必填参数: content", is_error=True)

        file_path = Path(path_str)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            byte_count = len(content.encode("utf-8"))
            return Result(content=f"已写入 {path_str}（{byte_count} 字节）")
        except OSError as e:
            return Result(content=f"写入文件失败: {e}", is_error=True)
