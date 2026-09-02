# Alincode/web/protocol.py
"""协议投影层：多态 Event → WebSocket JSON（纯函数，无 IO）。

Event 携带不可序列化成员（ApprovalRequest.respond 是活 Future、err 是 Exception），
本层负责安全投影：approval 用 request_id 替代 Future 并登记到注册表，
err 转 str。投影顺序与 TUI 的分支处理顺序一致（app.py 的 _consume_events）。
"""

from __future__ import annotations

import itertools

from Alincode.agent import Event, Phase
from Alincode.conversation import Message
from Alincode.permission import ApprovalRequest

_request_counter = itertools.count(1)

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_write", "cache_read")


def project_event(ev: Event, approvals: dict[str, ApprovalRequest]) -> list[dict]:
    """Event → 下行消息列表（多数情况 1 条；err+notice+done 组合会多于 1 条）。"""
    out: list[dict] = []

    if ev.compact is not None:
        c = ev.compact
        out.append({
            "type": "compact",
            "phase": c.phase.value,
            "before": c.before,
            "after": c.after,
            "error": str(c.err) if c.err else "",
        })
    if ev.err is not None:
        out.append({"type": "turn.error", "message": str(ev.err)})
    if ev.notice:
        out.append({"type": "notice", "text": ev.notice})
    if ev.usage is not None:
        out.append({"type": "usage",
                    **{f: getattr(ev.usage, f) for f in USAGE_FIELDS}})
    if ev.iter:
        out.append({"type": "iter", "value": ev.iter})
    if ev.text:
        out.append({"type": "text.delta", "delta": ev.text})
    if ev.tool is not None:
        t = ev.tool
        if t.phase is Phase.START:
            out.append({"type": "tool.start", "name": t.name, "args": t.args})
        else:
            message = {"type": "tool.end", "name": t.name,
                       "result": t.result, "is_error": t.is_error}
            if t.duration_ms is not None:
                message["duration_ms"] = t.duration_ms
            out.append(message)
    if ev.approval is not None:
        rid = f"a{next(_request_counter)}"
        approvals[rid] = ev.approval
        out.append({
            "type": "approval.request",
            "request_id": rid,
            "tool_name": ev.approval.tool_name,
            "tool_args": ev.approval.tool_args,
            "reason": ev.approval.reason,
        })
    if ev.done:
        out.append({"type": "turn.done"})
    return out


def project_messages(msgs: list[Message]) -> list[dict]:
    """历史 Message 列表 → Block 列表（与前端 Block 类型同形）。"""
    blocks: list[dict] = []
    pending: dict[str, dict] = {}
    for m in msgs:
        if m.role == "user":
            blocks.append({"kind": "user", "content": m.content})
        elif m.role == "assistant":
            if m.content:
                blocks.append({"kind": "assistant", "content": m.content})
            for tc in m.tool_calls or []:
                b = {"kind": "tool", "name": tc.name, "args": tc.input,
                     "state": "running"}
                pending[tc.id] = b
                blocks.append(b)
        elif m.tool_results:
            for tr in m.tool_results:
                b = pending.get(tr.tool_call_id)
                if b is not None:
                    b["state"] = "done"
                    b["result"] = tr.content[:500]
                    b["isError"] = tr.is_error
                    if tr.duration_ms is not None:
                        b["durationMs"] = tr.duration_ms
    return blocks
