"""edit_file 工具：唯一匹配替换，匹配不到或多匹配给可区分错误。"""

from __future__ import annotations

import json
from pathlib import Path

from Alincode.tools import Result


class EditFileTool:
    """改文件工具：对原文片段做唯一匹配替换。

    匹配 0 次 → 结构化错误"未找到匹配的内容"
    匹配 >1 次 → 结构化错误"匹配到 N 处，old_string 不唯一，请提供更长上下文"
    匹配恰好 1 次 → 唯一替换后写回，返回成功。
    """

    read_only: bool = False

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return (
            "对文件中的指定文本片段做**唯一匹配替换**。"
            "**编辑文件前必须先用 read_file 读取最新内容**。"
            "old_string 在文件中必须恰好出现一次，否则不执行修改并返回错误。"
            "优先用 edit_file 做精确局部修改，不要用 bash sed/awk 等命令来改文件。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要修改的文件路径（相对或绝对）",
                },
                "old_string": {
                    "type": "string",
                    "description": "要被替换的原文片段（必须在文件中恰好出现一次）",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的新文本片段",
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, args: str) -> Result:
        """执行替换。"""
        try:
            data = json.loads(args) if args and args.strip() else {}
            path_str = data.get("path", "")
            old_string = data.get("old_string", "")
            new_string = data.get("new_string", "")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)

        if not path_str:
            return Result(content="缺少必填参数: path", is_error=True)
        if "old_string" not in (data if isinstance(data, dict) else {}):
            return Result(content="缺少必填参数: old_string", is_error=True)

        file_path = Path(path_str)
        if not file_path.is_file():
            return Result(content=f"文件不存在: {path_str}", is_error=True)

        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            hint = "文件似乎是二进制文件，无法编辑" if isinstance(e, UnicodeDecodeError) else ""
            return Result(content=f"读取文件失败: {e}。{hint}".rstrip("。 ") + "。", is_error=True)

        count = content.count(old_string)
        if count == 0:
            return Result(
                content="未找到匹配的内容。请检查 old_string 是否与文件中文本完全一致（包括缩进和空格）。",
                is_error=True,
            )
        if count > 1:
            return Result(
                content=f"匹配到 {count} 处，old_string 不唯一，请提供更长上下文使其唯一。",
                is_error=True,
            )

        # count == 1，唯一替换
        new_content = content.replace(old_string, new_string, 1)
        try:
            file_path.write_text(new_content, encoding="utf-8")
            return Result(content=f"已成功替换 {path_str} 中的 1 处匹配")
        except OSError as e:
            return Result(content=f"写入文件失败: {e}", is_error=True)
