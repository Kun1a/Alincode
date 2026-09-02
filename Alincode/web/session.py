# Alincode/web/session.py
"""WebSession：单个浏览器会话 = 一个 SessionBundle + 事件流消费协程。

与 TUI 的关系：消费的是同一个 Agent.run() 异步事件流，
本类等价于 app.py 中 _start_agent/_consume_events/_approve 的 Web 形态。
下行消息统一进 outbox 队列，由服务端单一 pump 协程发送，
避免消费任务与请求处理并发写 socket。
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from Alincode.bootstrap import AppContext
from Alincode.core_session import SessionBundle, create_session
from Alincode.hook.event import Event as HookEvent
from Alincode.permission import ApprovalRequest, Mode, Outcome
from Alincode.profile.service import ProfileService
from Alincode.prompts import SYSTEM_PROMPT
from Alincode.web.protocol import project_event, project_messages
from Alincode.web.attachments import load_attachments, render_attachment_context

OUTCOME_MAP = {
    "allow_once": Outcome.ALLOW_ONCE,
    "allow_forever": Outcome.ALLOW_FOREVER,
    "deny_once": Outcome.DENY_ONCE,
}


class WebSession:
    def __init__(
        self,
        ctx: AppContext,
        session_root: str | None = None,
        profile_service: ProfileService | None = None,
        profile_id: str | None = None,
        context_factory: Callable[[str], Awaitable[AppContext]] | None = None,
    ) -> None:
        if (profile_service is None) != (profile_id is None):
            raise ValueError("Profile 用量统计需要同时提供服务和标识")
        self._ctx = ctx
        self._session_root = session_root
        self._profile_service = profile_service
        self._profile_id = profile_id
        self._context_factory = context_factory
        self.bundle: SessionBundle = create_session(ctx, session_root=session_root)
        self.outbox: asyncio.Queue[dict] = asyncio.Queue()
        self._approvals: dict[str, ApprovalRequest] = {}
        self._turn_task: asyncio.Task | None = None
        self._cancel = asyncio.Event()
        self._mode = Mode.DEFAULT
        self.busy = False
        self._closed = False

    # ── 生命周期 ──────────────────────────────────────

    async def open(self) -> None:
        self.bundle.conv.add_system(SYSTEM_PROMPT)   # 对应 app.py on_mount 注入
        await self._emit({
            "type": "session.info",
            "session_id": self.bundle.session_id,
            "workspace": self._ctx.workspace,
            "model": self._ctx.provider_cfg.model,
            "mode": self._mode.value,
        })
        await self._dispatch(HookEvent.SESSION_START)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._turn_task and not self._turn_task.done():
            self._cancel.set()
            self._turn_task.cancel()
        await self._dispatch(HookEvent.SESSION_END)
        self.bundle.writer.close()

    # ── 上行消息分发 ──────────────────────────────────

    async def handle(self, data: dict) -> None:
        t = data.get("type")
        if t == "chat.send":
            paths = data.get("attachments", [])
            await self.send_user(
                str(data.get("text", "")), paths if isinstance(paths, list) else [],
            )
        elif t == "approval.respond":
            await self.respond_approval(str(data.get("request_id", "")),
                                        str(data.get("outcome", "")))
        elif t == "turn.cancel":
            self.cancel_turn()
        elif t == "session.resume":
            await self.resume(str(data.get("session_id", "")))
        elif t == "session.new":
            workspace = data.get("workspace")
            await self.new_session(workspace if isinstance(workspace, str) else None)
        elif t == "mode.set":
            await self.set_mode(str(data.get("mode", "")))
        else:
            await self._emit({"type": "notice", "text": f"未知消息类型: {t}"})

    # ── 用户消息 → 新轮次（对应 app.py:695-718）──────

    async def send_user(self, text: str, attachment_paths: list[str] | None = None) -> None:
        text = text.strip()
        if not text:
            return
        if self.busy:
            await self._emit({"type": "notice", "text": "请等待当前回复完成..."})
            return
        if self._profile_service is not None and self._profile_id is not None:
            status = self._profile_service.budget_status(self._profile_id)
            if status["blocked"]:
                await self._emit({"type": "budget.status", **status})
                await self._emit({
                    "type": "notice", "text": "本地 token 预算已用尽，请在设置中提高预算。",
                })
                return

        if self._ctx.hook_engine is not None:
            result = await self._ctx.hook_engine.dispatch(
                HookEvent.USER_PROMPT_SUBMIT,
                {"event": HookEvent.USER_PROMPT_SUBMIT.value,
                 "session_id": self.bundle.session_id,
                 "cwd": self._ctx.workspace, "mode": self._mode.value,
                 "prompt": text},
            )
            if result.blocked:
                await self._emit({"type": "notice",
                                  "text": f"[hook {result.blocking_hook_id}] {result.reason}"})
                return
            self.bundle.runtime.append_reminders(result.injected_prompts)

        if attachment_paths:
            if not all(isinstance(path, str) for path in attachment_paths):
                await self._emit({"type": "notice", "text": "附件路径格式错误。"})
                return
            try:
                attachments = load_attachments(attachment_paths)
            except (OSError, ValueError) as error:
                await self._emit({"type": "notice", "text": str(error)})
                return
            self.bundle.runtime.append_reminders([render_attachment_context(attachments)])

        self._save_workspace_metadata()
        self.bundle.conv.add_user(text)
        await self._emit({"type": "history.append",
                          "block": {"kind": "user", "content": text}})
        self.busy = True
        self._cancel = asyncio.Event()
        self._turn_task = asyncio.create_task(self._run_turn())

    async def _run_turn(self) -> None:
        """消费 agent.run() 事件流——与 TUI 共享的同一事件源。"""
        try:
            async for ev in self.bundle.agent.run(
                self.bundle.conv, mode=self._mode, cancel=self._cancel
            ):
                for msg in project_event(ev, self._approvals):
                    await self._emit(msg)
                if ev.usage is not None and self._profile_service is not None and self._profile_id:
                    self._profile_service.record_usage(
                        self._profile_id,
                        input_tokens=ev.usage.input_tokens,
                        output_tokens=ev.usage.output_tokens,
                    )
                    await self._emit({
                        "type": "budget.status",
                        **self._profile_service.budget_status(self._profile_id),
                    })
                if ev.err is not None or ev.done:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:  # 兜底：循环本身崩溃也要告知前端
            await self._emit({"type": "turn.error", "message": str(e)})
        finally:
            self.busy = False

    # ── 审批回传（对应 app.py:536-540）────────────────

    async def respond_approval(self, request_id: str, outcome: str) -> None:
        req = self._approvals.pop(request_id, None)
        if req is None or req.respond is None or req.respond.done():
            return
        result = OUTCOME_MAP.get(outcome, Outcome.DENY_ONCE)
        # 先广播 resolved 再唤醒 agent 循环，保证前端先收到回执、后收到 tool.end
        await self._emit({
            "type": "approval.resolved", "request_id": request_id,
            "outcome": result.value,
        })
        req.respond.set_result(result)

    def cancel_turn(self) -> None:
        self._cancel.set()

    async def set_mode(self, value: str) -> None:
        if self.busy:
            await self._emit({"type": "notice", "text": "请等待当前任务完成后再切换执行模式。"})
            return
        try:
            self._mode = Mode(value)
        except ValueError:
            await self._emit({"type": "notice", "text": "不支持的执行模式。"})
            return
        await self._emit({
            "type": "session.info",
            "session_id": self.bundle.session_id,
            "workspace": self._ctx.workspace,
            "model": self._ctx.provider_cfg.model,
            "mode": self._mode.value,
        })

    async def new_session(self, workspace: str | None = None) -> None:
        if self.busy:
            await self._emit({"type": "notice", "text": "请等待当前任务完成后再新建对话。"})
            return
        if workspace:
            if not await self._switch_workspace(workspace):
                return
        old = self.bundle
        self.bundle = create_session(self._ctx, session_root=self._session_root)
        old.writer.close()
        self.bundle.conv.add_system(SYSTEM_PROMPT)
        await self._emit({
            "type": "session.info",
            "session_id": self.bundle.session_id,
            "workspace": self._ctx.workspace,
            "model": self._ctx.provider_cfg.model,
            "mode": self._mode.value,
        })
        await self._emit({"type": "history", "session_id": self.bundle.session_id, "blocks": []})

    # ── 会话恢复（对应 app.py:753-839 的精简版）──────

    async def resume(self, session_id: str) -> None:
        if self.busy:
            await self._emit({"type": "notice", "text": "请等待当前任务完成..."})
            return
        session_dir = os.path.join(
            self._session_root or os.path.join(self._ctx.workspace, ".Alincode", "sessions"),
            session_id,
        )
        if not os.path.isdir(session_dir):
            await self._emit({"type": "notice", "text": f"会话 {session_id} 不存在。"})
            return
        workspace = self._load_workspace_metadata(session_dir)
        if workspace and not await self._switch_workspace(workspace):
            return
        old = self.bundle
        self.bundle = create_session(
            self._ctx, resume_id=session_id, session_root=self._session_root,
        )
        old.writer.close()
        await self._emit({
            "type": "session.info",
            "session_id": self.bundle.session_id,
            "workspace": self._ctx.workspace,
            "model": self._ctx.provider_cfg.model,
            "mode": self._mode.value,
        })
        await self._emit({
            "type": "history",
            "session_id": session_id,
            "blocks": project_messages(self.bundle.conv.messages),
        })

    # ── 内部 ──────────────────────────────────────────

    async def _emit(self, msg: dict) -> None:
        await self.outbox.put(msg)

    async def _switch_workspace(self, workspace: str) -> bool:
        """为选择的项目构建独立上下文，防止工具仍在旧目录执行。"""
        requested = str(Path(workspace).expanduser().resolve())
        if requested == self._ctx.workspace:
            return True
        if self._context_factory is None:
            await self._emit({"type": "notice", "text": "当前入口不支持切换项目目录。"})
            return False
        try:
            self._ctx = await self._context_factory(requested)
        except (FileNotFoundError, ValueError) as error:
            await self._emit({"type": "notice", "text": str(error)})
            return False
        return True

    def _save_workspace_metadata(self) -> None:
        """仅在首条真实消息时落盘，空白新对话不会进入历史列表。"""
        metadata = Path(self.bundle.runtime.session.session_dir) / "session.json"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(json.dumps({"workspace": self._ctx.workspace}), encoding="utf-8")

    @staticmethod
    def _load_workspace_metadata(session_dir: str) -> str | None:
        try:
            data = json.loads((Path(session_dir) / "session.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        workspace = data.get("workspace") if isinstance(data, dict) else None
        return workspace if isinstance(workspace, str) and workspace else None

    async def _dispatch(self, event: HookEvent) -> None:
        if self._ctx.hook_engine is None:
            return
        result = await self._ctx.hook_engine.dispatch(event, {
            "event": event.value,
            "session_id": self.bundle.session_id,
            "cwd": self._ctx.workspace,
            "mode": self._mode.value,
        })
        if event is HookEvent.SESSION_START:
            self.bundle.runtime.append_reminders(result.injected_prompts)
