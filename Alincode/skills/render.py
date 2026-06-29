"""Skill body 渲染：$ARGUMENTS 替换 + 建议工具提示（T8）。"""

from Alincode.skills.types import Skill


def render_body(s: Skill, args: str = "") -> str:
    """渲染 Skill body 为最终注入文本。"""
    body = s.prompt_body

    # "建议工具"提示
    if s.meta.allowed_tools:
        tools_str = ", ".join(s.meta.allowed_tools)
        hint = (
            f"This skill is designed to use only these tools: {tools_str}. "
            f"Prefer them over other tools when possible.\n\n---\n\n"
        )
        body = hint + body

    # $ARGUMENTS 替换
    if "$ARGUMENTS" in body:
        body = body.replace("$ARGUMENTS", args)
    elif args.strip():
        body += "\n\n## User Request\n\n" + args

    return body
