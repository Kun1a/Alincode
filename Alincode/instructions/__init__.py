"""项目指令加载：三层 MEWCODE.md + @include 展开（T3）。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_INCLUDE_RE = re.compile(r"^@include\s+(.+)$")


@dataclass
class Loader:
    """三层 MEWCODE.md 加载器。"""
    project_root: str
    user_home: str = ""
    max_depth: int = 5

    def __post_init__(self):
        if not self.user_home:
            self.user_home = os.path.expanduser("~")

    def load(self) -> str:
        """按优先级加载三层指令文件，返回拼接后的完整指令文本。"""
        paths = [
            (os.path.join(self.project_root, "MEWCODE.md"),
             os.path.realpath(self.project_root)),
            (os.path.join(self.project_root, ".Alincode", "MEWCODE.md"),
             os.path.realpath(self.project_root)),
            (os.path.join(self.user_home, ".Alincode", "MEWCODE.md"),
             os.path.realpath(self.user_home + "/.Alincode")),
        ]
        parts: list[str] = []
        for file_path, boundary in paths:
            content = self._load_file(
                file_path, boundary, depth=1,
                visited=set(), is_top=True,
            )
            if content.strip():
                parts.append(content.strip())
        return "\n\n".join(parts)

    def _load_file(
        self,
        path: str,
        boundary: str,
        depth: int,
        visited: set[str],
        is_top: bool = False,
    ) -> str:
        """加载单个文件，递归处理 @include。"""
        # 深度检查
        if depth > self.max_depth:
            if is_top:
                return ""  # 顶层文件不存在
            return f"<!-- @include 超过最大嵌套深度，已跳过: {path} -->\n"

        # 解析绝对路径（先于存在性检查，才能做逃逸判断）
        abs_path = os.path.realpath(path)

        # 路径逃逸检测（先于文件存在性）
        if not _is_under(abs_path, boundary):
            return f"<!-- @include 路径超出允许范围，已跳过: {path} -->\n"

        # 文件存在性
        if not os.path.isfile(abs_path):
            return ""

        # 环路检测
        if abs_path in visited:
            return f"<!-- @include 检测到环路，已跳过: {path} -->\n"
        visited.add(abs_path)

        # 读取并检查二进制
        try:
            with open(abs_path, "rb") as f:
                head = f.read(512)
            if b"\x00" in head:
                return f"<!-- @include 文件为二进制格式，已跳过: {path} -->\n"
            with open(abs_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return ""

        result: list[str] = []
        for line in lines:
            m = _INCLUDE_RE.match(line.rstrip("\n\r"))
            if m:
                ref = m.group(1).strip()
                # 相对路径基于当前文件所在目录解析
                ref_path = os.path.join(os.path.dirname(abs_path), ref)
                expanded = self._load_file(
                    ref_path, boundary, depth + 1, visited,
                    is_top=False,
                )
                result.append(expanded)
            else:
                result.append(line)

        return "".join(result)


def _is_under(path: str, boundary: str) -> bool:
    """检查 path 是否在 boundary 目录下。"""
    try:
        return Path(path).resolve().is_relative_to(Path(boundary).resolve())
    except (ValueError, OSError):
        return False
