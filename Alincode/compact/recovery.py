"""恢复三段：最近读过的文件快照 + 当前可用工具列表 + 边界提示（T10-T11）。"""

from __future__ import annotations

from Alincode.compact.const import (
    ESTIMATE_CHARS_PER_TOKEN,
    RECOVERY_FILE_LIMIT,
    RECOVERY_TOKENS_PER_FILE,
)
from Alincode.compact.state import FileReadRecord
from Alincode.conversation import ToolDefinition
import json

BOUNDARY_NOTICE: str = """## 边界提示
需要文件原文、错误原文、用户原话时，请使用文件读取工具重新读取对应路径，不要依据摘要内容做猜测。如果摘要中提到某个文件但你未读过其内容，必须先读文件再做代码修改。"""


def render_file_block(rec: FileReadRecord) -> str:
    """渲染单个文件快照：路径 / 时间戳 / 内容片段（必要时截断）。"""
    char_limit = int(RECOVERY_TOKENS_PER_FILE * ESTIMATE_CHARS_PER_TOKEN)
    content = rec.content
    truncated = False
    if len(content) > char_limit:
        content = content[:char_limit]
        truncated = True

    lines = [
        f"### {rec.path}",
        f"[read at] {rec.timestamp.isoformat()}",
        content,
    ]
    if truncated:
        lines.append("(content truncated)")
    return "\n".join(lines)


def render_tools_block(defs: list[ToolDefinition]) -> str:
    """渲染工具列表：每行一个工具名 + 用途 + 参数 schema 摘要。"""
    lines = ["## 当前可用工具"]
    if not defs:
        lines.append("(无)")
    for d in defs:
        schema_str = json.dumps(d.input_schema, separators=(",", ":"), ensure_ascii=False)
        lines.append(f"- **{d.name}**: {d.description}")
        lines.append(f"  schema: {schema_str}")
    return "\n".join(lines)


def build_recovery_attachment(
    snapshot: list[FileReadRecord],
    tool_defs: list[ToolDefinition],
) -> str:
    """构造摘要后的"恢复三段"内容。

    调用方必须先在 run_summary 入口拍一次快照后传入。
    本函数纯函数，不修改任何外部状态。

    三段：
      1. 最近读过的文件快照（取前 RECOVERY_FILE_LIMIT 个）
      2. 当前可用工具列表（直接来自入参 tool_defs）
      3. 边界提示消息（固定文案）
    """
    parts: list[str] = []

    # 第一段：最近读过的文件
    parts.append("## 最近读过的文件")
    recent = snapshot[:RECOVERY_FILE_LIMIT]
    if recent:
        for rec in recent:
            parts.append(render_file_block(rec))
    else:
        parts.append("(无)")

    # 第二段：当前可用工具
    parts.append(render_tools_block(tool_defs))

    # 第三段：边界提示
    parts.append(BOUNDARY_NOTICE)

    return "\n\n".join(parts)
