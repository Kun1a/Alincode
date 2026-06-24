"""grep 工具：按正则模式搜索文件内容，返回 file:line:content 格式。"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from Alincode.tools import Result

MAX_HITS = 100
MAX_LINE_LENGTH = 500  # 单行截断长度


class GrepTool:
    """搜代码内容工具：给定正则模式，在文件内容中检索命中位置。

    返回格式：file:lineno:content（最多 100 条命中）。
    正则非法、路径不存在等以结构化错误返回。
    """

    @property
    def read_only(self) -> bool:
        return True

    def name(self) -> str:
        return "grep"

    def description(self) -> str:
        return (
            "按正则模式搜索文件内容，返回命中文件的路径、行号和匹配行内容。"
            "适用于在代码库中查找函数定义、变量使用、错误信息等。"
            "可使用 path 参数限定搜索目录，glob 参数过滤文件名。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Python 正则表达式，用于匹配文件内容中的行。"
                        "例如 `def foo` 搜索函数定义，`TODO` 搜索待办注释。"
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "搜索起始目录，默认为当前工作目录 '.'",
                },
                "glob": {
                    "type": "string",
                    "description": "文件名过滤 glob，如 `*.py` 或 `*.{js,ts}`，可选",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, args: str) -> Result:
        """执行 grep 搜索。"""
        try:
            data = json.loads(args) if args and args.strip() else {}
            pattern_str = data.get("pattern", "")
            root_str = data.get("path") or "."
            file_glob = data.get("glob") or ""
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)

        if not pattern_str:
            return Result(content="缺少必填参数: pattern", is_error=True)

        # 编译正则
        try:
            rx = re.compile(pattern_str)
        except re.error as e:
            return Result(content=f"正则非法: {e}", is_error=True)

        root = Path(root_str)
        if not root.exists():
            return Result(content=f"路径不存在: {root_str}", is_error=True)

        hits: list[str] = []
        files_scanned = 0
        try:
            # 构建文件迭代器
            if root.is_dir():
                if file_glob:
                    files = root.rglob(file_glob)
                else:
                    files = root.rglob("*")
            else:
                files = [root]

            for file_path in files:
                if not file_path.is_file():
                    continue
                if self._is_ignored(file_path):
                    continue

                files_scanned += 1
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        for lineno, line in enumerate(f, 1):
                            if len(line) > MAX_LINE_LENGTH:
                                # 超长行：对截断部分搜索，标注可能不完整
                                truncated = line[:MAX_LINE_LENGTH]
                                if rx.search(truncated):
                                    hits.append(f"{file_path}:{lineno}:{truncated.rstrip()} [截断，搜索结果可能不完整]")
                                else:
                                    hits.append(f"{file_path}:{lineno}:[行过长，搜索截断未能完整覆盖]")
                                continue
                            if rx.search(line):
                                hits.append(f"{file_path}:{lineno}:{line.rstrip()}")
                                if len(hits) >= MAX_HITS:
                                    break
                except (OSError, UnicodeDecodeError):
                    # 跳过无法读取的文件
                    continue

                if len(hits) >= MAX_HITS:
                    break

                # 每文件让出 event loop
                if files_scanned % 50 == 0:
                    await asyncio.sleep(0)

        except OSError as e:
            return Result(content=f"grep 搜索失败: {e}", is_error=True)

        if not hits:
            return Result(content=f"无命中: /{pattern_str}/（在 {root_str} 下，扫描 {files_scanned} 个文件）")

        result_lines = [
            f"搜索 /{pattern_str}/（在 {root_str} 下）共 {len(hits)} 条命中:"
        ] + hits
        if len(hits) >= MAX_HITS:
            result_lines.append("[truncated]")

        return Result(content="\n".join(result_lines))

    @staticmethod
    def _is_ignored(p: Path) -> bool:
        """排除常见忽略目录。"""
        parts = set(p.parts)
        return bool(
            parts & {".git", ".venv", "node_modules", "__pycache__",
                      ".idea", ".vscode", "venv", ".tox", ".mypy_cache"}
        )
