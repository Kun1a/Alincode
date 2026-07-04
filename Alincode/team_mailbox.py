"""队员 Loop incoming-messages 注入(T20) + Plan 审批(T32)。

agent.py 每轮迭代调 LLM 前调 ingest_team_mailbox,检查 TeammateContext 的未读消息,
构造 <incoming-messages> reminder 注入到 runtime.pending_reminders。
若收到 plan_approval_response(approve=True),切换权限模式为 default;
approve=False 时在 reminder 中附加 feedback 文案。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Alincode.agent import Agent


async def ingest_team_mailbox(agent: "Agent") -> str | None:
    """检查队员邮箱未读消息,构造 <incoming-messages> reminder(T20)。

    若不在队员上下文(TeammateContext 为 None),返回 None。
    否则读未读消息 → 构造 reminder → mark_read → 返回 reminder 字符串。

    T32:若收到 plan_approval_response(approve=True),切换权限模式为 default;
         approve=False 时在 reminder 中附加 feedback 文案。
    """
    from Alincode.team_hook import teammate_context

    tc = teammate_context()
    if tc is None:
        return None

    indices, messages = await tc.read_unread()
    if not messages:
        return None

    # 标记已读
    await tc.mark_read(indices)

    # 构造 <incoming-messages> reminder(F42 格式)
    parts: list[str] = [f"收到 {len(messages)} 条新消息:"]
    feedback_parts: list[str] = []

    for i, msg in enumerate(messages, 1):
        # T32: Plan 审批处理
        if msg.type == "plan_approval_response":
            payload = msg.payload or {}
            approved = payload.get("approve", False)
            if approved:
                # 切换权限模式为 default
                if tc.set_permission_mode is not None:
                    tc.set_permission_mode("default")
                agent.permission_mode = "default"
                parts.append(
                    f"[{i}] 来自 {msg.from_}"
                    f"(type=plan_approval_response,ts={msg.timestamp}): "
                    f"Plan 已批准,已切换到 default 模式。{msg.summary}"
                )
            else:
                feedback = payload.get("feedback", "")
                line = (
                    f"[{i}] 来自 {msg.from_}"
                    f"(type=plan_approval_response,ts={msg.timestamp}): "
                    f"Plan 未通过审批。{msg.summary}"
                )
                if feedback:
                    line += f"\n    反馈: {feedback}"
                feedback_parts.append(line)
            continue

        # 普通消息:text / shutdown_request 等
        content_preview = (msg.content or "")[:200]
        parts.append(
            f"[{i}] 来自 {msg.from_}(type={msg.type},ts={msg.timestamp}): "
            f"{msg.summary}\n    {content_preview}"
        )

    # 合并 feedback 消息到末尾
    all_parts = parts + feedback_parts
    reminder = "<incoming-messages>\n" + "\n".join(all_parts) + "\n</incoming-messages>"

    return reminder
