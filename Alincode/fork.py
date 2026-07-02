"""Fork 路径辅助：build_forked_messages / is_fork_context（T12/F22-F24）。"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Alincode.conversation import Message

FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

FORK_BOILERPLATE = """<fork_boilerplate>
你是一个 Fork 出来的工作进程。你不是主 Agent。
规则（不可协商）：
1. 不能再 Fork（调用 Agent 工具会被拦截）。
2. 不要对话、不要提问、不要请求确认。
3. 直接使用工具：读文件、搜索代码、做修改。
4. 严格限制在你被分配的任务范围内。
5. 最终报告以 "Scope:" 开头，500 字以内。
</fork_boilerplate>

"""


def build_forked_messages(parent_msgs: list["Message"], task: str) -> list["Message"]:
    """克隆父对话 → 处理悬空 tool_use → 追加 Boilerplate + task。

    1. 深拷贝全部消息
    2. 扫描末尾 assistant 消息的 tool_calls，为未配对的 tool_call 生成 placeholder ToolResult
    3. 追加 user 消息 = FORK_BOILERPLATE + task
    """
    from Alincode.conversation import Message

    cloned = deepcopy(parent_msgs)

    # 收集所有 tool_call_id 及其配对情况
    tool_call_ids: set[str] = set()
    paired_ids: set[str] = set()

    for msg in cloned:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_call_ids.add(tc.id)
        elif msg.role == "tool" and msg.tool_results:
            for tr in msg.tool_results:
                paired_ids.add(tr.tool_call_id)

    # 未配对的 tool_call
    unpaired = tool_call_ids - paired_ids
    if unpaired:
        from Alincode.conversation import ToolResult as TR
        placeholder_results = [
            TR(tool_call_id=uid, content="[forked, skipped]", is_error=True)
            for uid in unpaired
        ]
        cloned.append(Message(role="tool", tool_results=placeholder_results))

    # 追加 Boilerplate user 消息
    cloned.append(Message(role="user", content=FORK_BOILERPLATE + task))

    return cloned


def is_fork_context(msgs: list["Message"]) -> bool:
    """检测对话历史是否来自 Fork（扫描 FORK_BOILERPLATE_TAG）。"""
    for msg in msgs:
        content = msg.content or ""
        if FORK_BOILERPLATE_TAG in content:
            return True
    return False
