"""glob 工具：按 glob 模式匹配文件路径。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from Alincode.tools import Result

MAX_RESULTS = 100


class GlobTool:
    """按模式找文件工具：给定 glob 模式，返回匹配的文件路径列表。

    使用 pathlib 原生 glob（支持 ** 递归匹配）。
    结果按字母排序，最多 100 条。
    """

    @property
    def read_only(self) -> bool:
        return True

    def name(self) -> str:
        return "glob"

    def description(self) -> str:
        return (
            "按 glob 模式查找文件，返回匹配的文件路径列表。"
            "支持 ** 递归匹配（如 `**/*.py` 搜索全部 Python 文件）。"
            "结果按字母排序，最多 100 条。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "glob 模式，如 `**/*.py` 或 `src/**/*.ts`",
                },
                "path": {
                    "type": "string",
                    "description": "搜索起始目录，默认为当前工作目录 '.'",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, args: str) -> Result:
        """执行 glob 搜索。"""
        try:
            data = json.loads(args) if args and args.strip() else {}
            pattern = data.get("pattern", "")
            root_str = data.get("path") or "."
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)

        if not pattern:
            return Result(content="缺少必填参数: pattern", is_error=True)

        root = Path(root_str)
        try:
            # 使用 pathlib 原生 glob（支持 **）
            matches = []
            count = 0
            for p in root.glob(pattern):
                if p.is_file() and not self._is_ignored(p):
                    matches.append(str(p))
                    count += 1
                    if count >= MAX_RESULTS:
                        break
                # 每 100 次让出 event loop
                if count % 100 == 0:
                    await asyncio.sleep(0)

            matches.sort()

            if not matches:
                return Result(content=f"无匹配: {pattern}（在 {root_str} 下）")

            lines = [f"匹配 {pattern}（在 {root_str} 下）共 {len(matches)} 条:"] + matches
            if count >= MAX_RESULTS:
                lines.append("[truncated]")
            return Result(content="\n".join(lines))
        except OSError as e:
            return Result(content=f"glob 搜索失败: {e}", is_error=True)

    @staticmethod
    def _is_ignored(p: Path) -> bool:
        """排除常见忽略目录。"""
        parts = set(p.parts)
        return bool(
            parts & {".git", ".venv", "node_modules", "__pycache__",
                      ".idea", ".vscode", "venv", ".tox", ".mypy_cache"}
        )
