"""本地 WebUI 附件的读取与提示词渲染。"""

from __future__ import annotations

from pathlib import Path

MAX_ATTACHMENTS = 10
MAX_FILE_BYTES = 200 * 1024


def load_attachments(paths: list[str]) -> list[tuple[str, str]]:
    """读取用户选择的 UTF-8 文本文件，不接受目录、二进制或过大内容。"""
    if len(paths) > MAX_ATTACHMENTS:
        raise ValueError(f"一次最多添加 {MAX_ATTACHMENTS} 个文件")
    result: list[tuple[str, str]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"附件不是文件: {path}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"单个附件不能超过 200 KB: {path.name}")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"附件必须是 UTF-8 文本文件: {path.name}") from error
        result.append((str(path), content))
    return result


def render_attachment_context(attachments: list[tuple[str, str]]) -> str:
    """把附件放进本轮 reminder，避免污染会话历史。"""
    if not attachments:
        return ""
    blocks = ["<user-attached-files>"]
    for path, content in attachments:
        blocks.extend((f'<file path="{path}">', content, "</file>"))
    blocks.append("</user-attached-files>")
    return "\n".join(blocks)
