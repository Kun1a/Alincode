"""SendMessage 工具：给队员发消息。

name 为 "SendMessage"（去掉 Team 前缀）。
to 支持队员名/agent_id/* 广播。
type: text/shutdown_request/shutdown_response/plan_approval_response。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from Alincode.tools import Result, Tool
from Alincode.tools._team_helpers import get_team, json_result
from Alincode.team.mailbox import Box, Message, MessageType

if TYPE_CHECKING:
    from Alincode.team.manager import Manager


class SendMessageTool(Tool):
    """给队员发消息。

    team_name 为空时从 TeammateContext 解析（全局注册场景）。
    build_teammate_tools 构造时绑 team_name（per-team 实例化）。
    """

    def __init__(self, team_manager: "Manager", team_name: str = ""):
        self._mgr = team_manager
        self._team_name = team_name

    def name(self) -> str:
        return "SendMessage"

    @property
    def read_only(self) -> bool:
        return True

    def description(self) -> str:
        return (
            "给队员发消息。to 支持队员名/agent_id/* 广播。"
            "type: text/shutdown_request/shutdown_response/plan_approval_response。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "队员名 / agent_id / * 广播"},
                "summary": {
                    "type": "string",
                    "description": "5-10 词摘要(text 类型必填)",
                },
                "message": {"type": "string", "description": "消息正文"},
                "type": {
                    "type": "string",
                    "description": "text/shutdown_request/shutdown_response/plan_approval_response",
                },
                "payload": {"type": "object", "description": "结构化消息载荷"},
            },
            "required": ["to"],
        }

    async def execute(self, args: str) -> Result:
        data = json.loads(args) if args.strip() else {}
        team = get_team(self._mgr, self._team_name)
        if team is None:
            return Result(content="不在 Team 上下文中", is_error=True)

        to = data.get("to", "")
        msg_type_str = data.get("type", "text")
        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            msg_type = MessageType.TEXT

        # 校验消息类型权限(F34)
        from Alincode.team_hook import teammate_context

        tc = teammate_context()
        from_name = tc.member_name if tc else "lead"

        if msg_type == MessageType.PLAN_APPROVAL_RESPONSE and from_name != "lead":
            return Result(
                content="plan_approval_response 仅 Lead 可发送", is_error=True
            )
        if msg_type == MessageType.SHUTDOWN_RESPONSE and to != "lead":
            return Result(content="shutdown_response 只能发给 Lead", is_error=True)

        box = Box(team.mailbox_dir)
        msg = Message(
            from_=from_name,
            to=to,
            type=msg_type,
            summary=data.get("summary", ""),
            content=data.get("message", ""),
            payload=data.get("payload"),
        )

        # 解析目标
        if to == "*":
            # 广播:除发件人外所有成员
            targets = [
                (m.agent_id, m)
                for m in team.members
                if m.name != from_name and m.agent_id != "lead"
            ]
        else:
            # 单个目标:name 或 agent_id
            if self._mgr.reg is not None:
                aid = self._mgr.reg.resolve(to)
            else:
                aid = to
            if aid is None:
                # 尝试按 agent_id 直查成员
                m = team.member_by_agent_id(to)
                if m is None:
                    return Result(content=f"找不到目标 '{to}'", is_error=True)
                aid = m.agent_id
            m = team.member_by_agent_id(aid)
            targets = [(aid, m)] if m else [(aid, None)]

        delivered = []
        for aid, m in targets:
            await box.write(aid, msg)
            delivered.append(aid)
            # Pane 后端唤醒(T31 续写检测后续补)
            if m and m.backend_type != "in-process" and m.pane_id:
                try:
                    from Alincode.team.backend import new_backend

                    backend = new_backend(m.backend_type)
                    await backend.wake(m.pane_id, aid)
                except Exception:
                    pass  # 唤醒失败不阻断消息投递

        return json_result({"delivered_to": delivered})
