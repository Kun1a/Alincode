"""摘要 Prompt 模板：9 部分结构 + 两阶段输出 + 对话序列化 + 解析（T9）。"""

from __future__ import annotations

import logging
import re

from Alincode.conversation import Message

logger = logging.getLogger(__name__)

SUMMARY_INSTRUCTION: str = """你正在为编程助手的对话历史做摘要。你必须分两阶段输出，且不调用任何工具。

第一阶段：在 `<analysis>` 标签内写出你的分析草稿。
第二阶段：在 `<summary>` 标签内写出正式摘要。

<analysis>
（在这里写分析草稿——这部分会被丢弃，请简要整理对话结构和关键点）
</analysis>

<summary>
## 1 主要请求和意图
（用户最初和持续的目标是什么？）

## 2 关键技术概念
（使用了哪些技术、框架、库？）

## 3 文件和代码段
（修改了哪些文件？哪些代码段是关键？）

## 4 错误和修复
（遇到了哪些错误？如何修复的？）

## 5 问题解决过程
（解决问题的整体过程是怎样的？）

## 6 所有用户消息原文
（逐条列出用户的所有原始消息，不要改写、不要概括）

## 7 待办任务
（哪些任务已完成？哪些还在进行中？）

## 8 当前工作（最详细）
（当前正在做什么？停在哪一步？上下文是什么？）

## 9 可能的下一步
（接下来应该做什么？）
</summary>

不要调用任何工具，输出纯文本。"""


def serialize_conversation(msgs: list[Message]) -> str:
    """把对话扁平化成可读文本。

    - user/assistant: `role: <content>`
    - assistant 带 tool_calls: `[call <name> id=<id> args=<json>]`
    - tool 消息: `[result id=<id> is_error=<bool>] <content>`
    """
    lines: list[str] = []
    for msg in msgs:
        if msg.role == "user":
            lines.append(f"user: {msg.content}")
        elif msg.role == "assistant":
            if msg.content:
                lines.append(f"assistant: {msg.content}")
            for tc in (msg.tool_calls or []):
                lines.append(f"[call {tc.name} id={tc.id} args={tc.input}]")
        elif msg.role == "tool":
            for tr in (msg.tool_results or []):
                lines.append(
                    f"[result id={tr.tool_call_id} is_error={tr.is_error}] {tr.content}"
                )
        elif msg.role == "system":
            lines.append(f"system: {msg.content}")
    return "\n".join(lines)


def build_summary_prompt(msgs: list[Message]) -> list[Message]:
    """把对话嵌入固定摘要模板，返回单条 user 消息的列表。"""
    serialized = serialize_conversation(msgs)
    content = f"{SUMMARY_INSTRUCTION}\n\n[conversation]\n{serialized}"
    return [Message(role="user", content=content)]


def extract_summary(raw: str) -> str:
    """从模型返回的整段文本中抠出 <summary>...</summary> 之间的正文。

    提取失败时返回原文 + logging warning，避免硬失败。
    """
    matches = re.findall(r"<summary>(.*?)</summary>", raw, re.DOTALL)
    if matches:
        # 取最后一段 <summary>
        return matches[-1].strip()
    # 尝试从末尾开始（未闭合标签的情况）
    idx = raw.rfind("<summary>")
    if idx != -1:
        after = raw[idx + len("<summary>"):].strip()
        if after:
            logger.warning("summary closing tag </summary> not found, using tail")
            return after
    logger.warning("summary tags not found, returning raw text")
    return raw.strip()
