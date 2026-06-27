"""Agent Loop 编排：多轮 ReAct + 权限检查（ASK 不阻塞）+ 逐字流式 + 上下文管理。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator

from Alincode.client import BaseProvider, PromptTooLongError, Request, System as SystemBlocks
from Alincode.compact import (
    manage_context,
    TriggerKind,
    ManageInput,
    estimate_tokens,
    usage_anchor as calc_usage_anchor,
    SUMMARY_RESERVE,
    AUTO_SAFETY_MARGIN,
    MANUAL_SAFETY_MARGIN,
)
from Alincode.conversation import (
    ConversationManager,
    ToolCall,
    ToolDefinition,
    ToolResult,
    Usage,
    NOTICE_MAX_ITER,
    NOTICE_UNKNOWN_TOOLS,
    NOTICE_CANCELLED,
    NOTICE_PROVIDER_ERROR,
)
from Alincode.permission import Verdict, Outcome, ApprovalRequest, Mode
from Alincode.permission.engine import PermissionEngine
from Alincode.prompt import build_system_prompt, gather_environment, plan_reminder
from Alincode.runtime import SessionRuntime
from Alincode.tools import Registry, Result, DEFAULT_TIMEOUT

MAX_ITERATIONS = 25
MAX_UNKNOWN_RUN = 3


class CompactPhase(Enum):
    BEFORE_AUTO = "before_auto"
    AFTER_AUTO = "after_auto"
    BEFORE_EMERGENCY = "before_emergency"
    AFTER_EMERGENCY = "after_emergency"


@dataclass
class CompactEvent:
    phase: CompactPhase
    before: int = 0
    after: int = 0
    err: Exception | None = None


class Phase(Enum):
    START = "start"
    END = "end"


@dataclass
class ToolEvent:
    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass
class Event:
    text: str = ""
    tool: ToolEvent | None = None
    usage: Usage | None = None
    iter: int = 0
    notice: str = ""
    done: bool = False
    err: Exception | None = None
    approval: ApprovalRequest | None = None
    compact: CompactEvent | None = None


def _args_preview(c: ToolCall) -> str:
    return c.input if len(c.input) <= 80 else c.input[:77] + "..."


def _result_preview(r: Result) -> str:
    return r.content if len(r.content) <= 500 else r.content[:497] + "..."


class Agent:
    """ReAct 循环 + 权限检查——ASK 在 run() 中处理，不阻塞。"""

    def __init__(
        self,
        provider: BaseProvider,
        registry: Registry,
        model: str = "",
        version: str = "0.3.0",
        engine: PermissionEngine | None = None,
        *,
        runtime: SessionRuntime | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._model = model
        self._version = version
        self._engine = engine or PermissionEngine()
        self.runtime = runtime or SessionRuntime()
        self._run_lock = asyncio.Lock()

    async def run(
        self,
        conv: ConversationManager,
        mode: Mode = Mode.DEFAULT,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        if cancel is None:
            cancel = asyncio.Event()

        async with self._run_lock:
            async for ev in self._run_impl(conv, mode, cancel):
                yield ev

    async def _run_impl(
        self,
        conv: ConversationManager,
        mode: Mode,
        cancel: asyncio.Event,
    ) -> AsyncIterator[Event]:
        env = await gather_environment(
            cwd=None, version=self._version, model=self._model
        )
        stable, env_block = build_system_prompt(env)

        if mode == Mode.PLAN:
            defs = self._registry.read_only_definitions()
        else:
            defs = self._registry.definitions()

        unknown_run = 0
        total_input = 0
        total_output = 0

        for iteration in range(1, MAX_ITERATIONS + 1):
            if cancel.is_set():
                yield Event(notice=NOTICE_CANCELLED, done=True)
                conv.ensure_assistant_tail(NOTICE_CANCELLED)
                return

            yield Event(iter=iteration)

            # ── 上下文管理 ──────────────────────────
            async with self.runtime._lock:
                anchor = self.runtime.usage_anchor
                anchor_len = self.runtime.anchor_msg_len
                cw = self.runtime.context_window
            c_msgs = conv.messages
            est = estimate_tokens(anchor, c_msgs, anchor_len)

            threshold = cw - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN if cw > SUMMARY_RESERVE + AUTO_SAFETY_MARGIN else 0
            will_summarize = threshold > 0 and est >= threshold

            if will_summarize:
                yield Event(compact=CompactEvent(phase=CompactPhase.BEFORE_AUTO))

            in_ = ManageInput(
                conv=conv,
                provider=self._provider,
                context_window=cw,
                tool_defs=defs,
                replacement=self.runtime.replacement,
                recovery=self.runtime.recovery,
                auto_tracking=self.runtime.auto_tracking,
                session=self.runtime.session,
                usage_anchor=anchor,
                anchor_msg_len=anchor_len,
                estimated_token=est,
                trigger=TriggerKind.AUTO,
                model=self._model,
            )
            try:
                out = await manage_context(in_)
                mc_err = None
            except Exception as e:
                mc_err = e
                out = None

            if will_summarize:
                yield Event(compact=CompactEvent(
                    phase=CompactPhase.AFTER_AUTO,
                    before=est,
                    after=out.after_tokens if out else 0,
                    err=mc_err,
                ))
            if mc_err:
                yield Event(err=mc_err, notice=str(mc_err), done=True)
                conv.ensure_assistant_tail(str(mc_err))
                return

            reminder = plan_reminder(iteration) if mode == Mode.PLAN else ""
            req = Request(
                system=SystemBlocks(stable=stable, environment=env_block),
                messages=conv.messages,
                model=self._model,
                tools=defs,
                reminder=reminder,
            )

            preamble = ""
            tool_calls: list[ToolCall] = []
            err = None
            tu_in = 0
            tu_out = 0

            try:
                async for se in self._provider.stream(req):
                    if cancel.is_set():
                        break
                    if se.err:
                        err = se.err
                        break
                    if se.text:
                        preamble += se.text
                        yield Event(text=se.text)
                    if se.usage:
                        tu_in += se.usage.input_tokens
                        tu_out += se.usage.output_tokens
                    if se.tool_calls:
                        tool_calls.extend(se.tool_calls)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err = e

            total_input += tu_in
            total_output += tu_out
            if tu_in or tu_out:
                yield Event(
                    usage=Usage(input_tokens=total_input, output_tokens=total_output)
                )

            # ── 紧急压缩 ──────────────────────────
            emergency_retried = False
            if isinstance(err, PromptTooLongError) and not emergency_retried:
                emergency_retried = True
                yield Event(compact=CompactEvent(phase=CompactPhase.BEFORE_EMERGENCY))

                ein = ManageInput(
                    conv=conv,
                    provider=self._provider,
                    context_window=cw,
                    tool_defs=defs,
                    replacement=self.runtime.replacement,
                    recovery=self.runtime.recovery,
                    auto_tracking=self.runtime.auto_tracking,
                    session=self.runtime.session,
                    usage_anchor=anchor,
                    anchor_msg_len=anchor_len,
                    estimated_token=est,
                    trigger=TriggerKind.EMERGENCY,
                    model=self._model,
                )
                e_out = None
                e_err = None
                try:
                    e_out = await manage_context(ein)
                except Exception as exc:
                    e_err = exc

                yield Event(compact=CompactEvent(
                    phase=CompactPhase.AFTER_EMERGENCY,
                    before=est,
                    after=e_out.after_tokens if e_out else 0,
                    err=e_err,
                ))

                if e_err:
                    yield Event(err=e_err, notice=str(e_err), done=True)
                    conv.ensure_assistant_tail(str(e_err))
                    return

                # 重置锚点，重估
                async with self.runtime._lock:
                    self.runtime.usage_anchor = 0
                    self.runtime.anchor_msg_len = 0
                est2 = estimate_tokens(0, conv.messages, 0)
                if est2 >= cw - MANUAL_SAFETY_MARGIN:
                    yield Event(err=err, notice="紧急压缩后仍超窗口", done=True)
                    conv.ensure_assistant_tail("紧急压缩后仍超窗口")
                    return

                # 重试
                retry_req = Request(
                    system=SystemBlocks(stable=stable, environment=env_block),
                    messages=conv.messages,
                    model=self._model,
                    tools=defs,
                    reminder=reminder,
                )
                preamble = ""
                tool_calls.clear()
                err = None
                tu_in, tu_out = 0, 0
                try:
                    async for se in self._provider.stream(retry_req):
                        if cancel.is_set():
                            break
                        if se.err:
                            err = se.err
                            break
                        if se.text:
                            preamble += se.text
                            yield Event(text=se.text)
                        if se.usage:
                            tu_in += se.usage.input_tokens
                            tu_out += se.usage.output_tokens
                        if se.tool_calls:
                            tool_calls.extend(se.tool_calls)
                except asyncio.CancelledError:
                    raise
                except Exception as e2:
                    err = e2
                total_input += tu_in
                total_output += tu_out

            if cancel.is_set():
                yield Event(notice=NOTICE_CANCELLED, done=True)
                conv.ensure_assistant_tail(NOTICE_CANCELLED)
                return
            if err:
                yield Event(err=err, notice=NOTICE_PROVIDER_ERROR, done=True)
                conv.ensure_assistant_tail(NOTICE_PROVIDER_ERROR)
                return

            # 更新锚点（主对话路径）
            if tu_in or tu_out:
                u = Usage(input_tokens=tu_in, output_tokens=tu_out)
                async with self.runtime._lock:
                    self.runtime.usage_anchor = calc_usage_anchor(u)
                    self.runtime.anchor_msg_len = conv.length()

            if not tool_calls:
                if preamble.strip():
                    conv.add_assistant(preamble)
                yield Event(done=True)
                return

            known = [c for c in tool_calls if self._registry.get(c.name)]
            if not known:
                unknown_run += 1
                if unknown_run >= MAX_UNKNOWN_RUN:
                    yield Event(notice=NOTICE_UNKNOWN_TOOLS, done=True)
                    conv.ensure_assistant_tail(NOTICE_UNKNOWN_TOOLS)
                    return
            else:
                unknown_run = 0

            conv.add_assistant_with_tool_calls(preamble, tool_calls)

            # ── 权限检查 + 执行 ──────────────────────────
            batch_results = self._build_batch_results(tool_calls, mode)

            # 处理 ASK：yield 审批事件并等待
            for br in batch_results:
                if br.pending:
                    yield Event(approval=br.pending)
                    try:
                        outcome = await br.pending.respond
                    except asyncio.CancelledError:
                        outcome = Outcome.DENY_ONCE

                    if outcome == Outcome.ALLOW_FOREVER:
                        from Alincode.permission.rules import tool_to_friendly

                        self._engine.save_permanent_allow(
                            tool_to_friendly(br.call.name),
                            br.call.input,
                        )
                    if outcome in (Outcome.ALLOW_ONCE, Outcome.ALLOW_FOREVER):
                        br.pending = None
                    else:
                        br.result = Result(content="用户拒绝了该操作", is_error=True)
                        br.events.append(
                            ToolEvent(
                                name=br.call.name,
                                args=_args_preview(br.call),
                                phase=Phase.END,
                                result="用户拒绝了该操作",
                                is_error=True,
                            )
                        )
                        br.pending = None
                        br.call = None

                if cancel.is_set():
                    break

            if cancel.is_set():
                yield Event(notice=NOTICE_CANCELLED, done=True)
                conv.ensure_assistant_tail(NOTICE_CANCELLED)
                return

            # 执行已批准的工具（保序分批并发）
            cancelled = await self._execute_approved(batch_results, cancel)
            if cancelled:
                yield Event(notice=NOTICE_CANCELLED, done=True)
                conv.ensure_assistant_tail(NOTICE_CANCELLED)
                return

            # yield 工具事件 + 回灌结果
            for br in batch_results:
                for te in br.events:
                    yield Event(tool=te)

            tool_results = [
                ToolResult(
                    tool_call_id=call.id,
                    content=br.result.content,
                    is_error=br.result.is_error,
                )
                for call, br in zip(tool_calls, batch_results)
            ]

            # ── ReadFile 追踪 ───────────────────────
            for call, br in zip(tool_calls, batch_results):
                if call.name == "read_file" and not br.result.is_error:
                    try:
                        import json
                        args = json.loads(call.input) if call.input else {}
                        path = args.get("path", "")
                        if path:
                            import pathlib
                            abs_path = str(pathlib.Path(path).resolve())
                            data = await asyncio.to_thread(
                                pathlib.Path(abs_path).read_bytes
                            )
                            self.runtime.recovery.record_file(
                                abs_path, data.decode("utf-8", errors="replace")
                            )
                    except (OSError, json.JSONDecodeError):
                        pass

            conv.add_tool_results(tool_calls, tool_results)

        yield Event(notice=NOTICE_MAX_ITER, done=True)
        conv.ensure_assistant_tail(NOTICE_MAX_ITER)

    async def run_force_compact(
        self,
        conv: ConversationManager,
        tool_defs: list[ToolDefinition],
    ) -> tuple[int, int]:
        """手动 /compact：跳过阈值、熔断，无条件触发摘要。

        TUI 在 asyncio.create_task 里调用。
        入口先 async with self._run_lock 保证不与 run 并发。
        """
        async with self._run_lock:
            est = estimate_tokens(0, conv.messages, 0)
            in_ = ManageInput(
                conv=conv,
                provider=self._provider,
                context_window=self.runtime.context_window,
                tool_defs=tool_defs,
                replacement=self.runtime.replacement,
                recovery=self.runtime.recovery,
                auto_tracking=self.runtime.auto_tracking,
                session=self.runtime.session,
                usage_anchor=0,
                anchor_msg_len=0,
                estimated_token=est,
                trigger=TriggerKind.MANUAL,
                model=self._model,
            )
            out = await manage_context(in_)
            return (out.before_tokens, out.after_tokens)

    def _build_batch_results(
        self, calls: list[ToolCall], mode: Mode,
    ) -> list[_BatchResult]:
        """第一遍：权限检查，不执行。"""
        results: list[_BatchResult] = []
        for call in calls:
            if self._registry.get(call.name) is None:
                results.append(_BatchResult(
                    result=Result(content=f"未知工具: {call.name}", is_error=True),
                    events=[
                        ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.START),
                        ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.END,
                                  result=f"未知工具: {call.name}", is_error=True),
                    ],
                ))
                continue
            verdict, reason = self._engine.check(call.name, call.input, mode)
            if verdict == Verdict.DENY:
                results.append(_BatchResult(
                    result=Result(content=f"权限被拒绝: {reason}", is_error=True),
                    events=[
                        ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.START),
                        ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.END,
                                  result=f"权限被拒绝: {reason}", is_error=True),
                    ],
                ))
                continue
            if verdict == Verdict.ASK:
                fut: asyncio.Future = asyncio.Future()
                approval = ApprovalRequest(
                    tool_name=call.name, tool_args=_args_preview(call),
                    reason=reason, verdict=verdict, respond=fut,
                )
                results.append(_BatchResult(
                    result=Result(content="", is_error=False),
                    events=[ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.START)],
                    pending=approval, call=call,
                ))
                continue
            results.append(_BatchResult(
                result=Result(content="", is_error=False), call=call,
                events=[ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.START)],
            ))
        return results

    async def _execute_approved(
        self, batch_results: list[_BatchResult], cancel: asyncio.Event,
    ) -> bool:
        """执行已批准的工具——保序分批并发。"""
        pending_exec: list[tuple[int, _BatchResult]] = [
            (i, br) for i, br in enumerate(batch_results)
            if br.call and not br.pending
        ]
        pe_i = 0
        while pe_i < len(pending_exec):
            if cancel.is_set():
                return True
            idx, br = pending_exec[pe_i]
            call = br.call
            is_ro = self._registry.is_read_only(call.name)
            if is_ro:
                batch_end = pe_i
                while (
                    batch_end < len(pending_exec)
                    and self._registry.is_read_only(pending_exec[batch_end][1].call.name)
                ):
                    batch_end += 1
                batch = pending_exec[pe_i:batch_end]
                if len(batch) == 1:
                    _, br2 = batch[0]
                    r = await self._registry.execute(br2.call.name, br2.call.input, DEFAULT_TIMEOUT)
                    br2.result = r
                    br2.events.append(ToolEvent(
                        name=br2.call.name, args=_args_preview(br2.call), phase=Phase.END,
                        result=_result_preview(r), is_error=r.is_error,
                    ))
                else:
                    async def _ro_exec(bri: _BatchResult) -> tuple[_BatchResult, Result]:
                        return bri, await self._registry.execute(
                            bri.call.name, bri.call.input, DEFAULT_TIMEOUT,
                        )
                    tasks = [asyncio.create_task(_ro_exec(bri)) for _, bri in batch]
                    for coro in asyncio.as_completed(tasks):
                        if cancel.is_set():
                            for t in tasks:
                                t.cancel()
                            return True
                        bri, r = await coro
                        bri.result = r
                    for _, bri in batch:
                        r = bri.result
                        bri.events.append(ToolEvent(
                            name=bri.call.name, args=_args_preview(bri.call), phase=Phase.END,
                            result=_result_preview(r), is_error=r.is_error,
                        ))
                pe_i = batch_end
            else:
                r = await self._registry.execute(call.name, call.input, DEFAULT_TIMEOUT)
                br.result = r
                br.events.append(ToolEvent(
                    name=call.name, args=_args_preview(call), phase=Phase.END,
                    result=_result_preview(r), is_error=r.is_error,
                ))
                pe_i += 1
        return False


@dataclass
class _BatchResult:
    result: Result
    events: list[ToolEvent] = field(default_factory=list)
    pending: ApprovalRequest | None = None
    call: ToolCall | None = None

    def _build_batch_results(
        self,
        calls: list[ToolCall],
        mode: Mode,
    ) -> list[_BatchResult]:
        """第一遍：权限检查，不执行。返回带裁决的 _BatchResult 列表。"""
        results: list[_BatchResult] = []

        for call in calls:
            # 未注册 → Deny
            if self._registry.get(call.name) is None:
                results.append(
                    _BatchResult(
                        result=Result(content=f"未知工具: {call.name}", is_error=True),
                        events=[
                            ToolEvent(
                                name=call.name,
                                args=_args_preview(call),
                                phase=Phase.START,
                            ),
                            ToolEvent(
                                name=call.name,
                                args=_args_preview(call),
                                phase=Phase.END,
                                result=f"未知工具: {call.name}",
                                is_error=True,
                            ),
                        ],
                    )
                )
                continue

            verdict, reason = self._engine.check(call.name, call.input, mode)

            if verdict == Verdict.DENY:
                results.append(_BatchResult(
                    result=Result(content=f"权限被拒绝: {reason}", is_error=True),
                    events=[
                        ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.START),
                        ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.END,
                                  result=f"权限被拒绝: {reason}", is_error=True),
                    ],
                ))
                continue

            if verdict == Verdict.ASK:
                fut: asyncio.Future = asyncio.Future()
                approval = ApprovalRequest(
                    tool_name=call.name, tool_args=_args_preview(call),
                    reason=reason, verdict=verdict, respond=fut,
                )
                results.append(_BatchResult(
                    result=Result(content="", is_error=False),
                    events=[ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.START)],
                    pending=approval, call=call,
                ))
                continue

            # ALLOW
            results.append(_BatchResult(
                result=Result(content="", is_error=False), call=call,
                events=[ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.START)],
            ))

        return results

    async def _execute_approved(
        self,
        batch_results: list[_BatchResult],
        cancel: asyncio.Event,
    ) -> bool:
        """执行已批准的工具——保序分批并发。返回 True 表示被取消。"""
        pending_exec: list[tuple[int, _BatchResult]] = [
            (i, br) for i, br in enumerate(batch_results) if br.call and not br.pending
        ]

        pe_i = 0
        while pe_i < len(pending_exec):
            if cancel.is_set():
                return True

            idx, br = pending_exec[pe_i]
            call = br.call
            is_ro = self._registry.is_read_only(call.name)

            if is_ro:
                batch_end = pe_i
                while batch_end < len(pending_exec) and self._registry.is_read_only(
                    pending_exec[batch_end][1].call.name
                ):
                    batch_end += 1
                batch = pending_exec[pe_i:batch_end]

                if len(batch) == 1:
                    _, br2 = batch[0]
                    r = await self._registry.execute(
                        br2.call.name, br2.call.input, DEFAULT_TIMEOUT
                    )
                    br2.result = r
                    br2.events.append(
                        ToolEvent(
                            name=br2.call.name,
                            args=_args_preview(br2.call),
                            phase=Phase.END,
                            result=_result_preview(r),
                            is_error=r.is_error,
                        )
                    )
                else:

                    async def _ro_exec(
                        bri: _BatchResult,
                    ) -> tuple[_BatchResult, Result]:
                        return bri, await self._registry.execute(
                            bri.call.name, bri.call.input, DEFAULT_TIMEOUT
                        )

                    tasks = [asyncio.create_task(_ro_exec(bri)) for _, bri in batch]
                    for coro in asyncio.as_completed(tasks):
                        if cancel.is_set():
                            for t in tasks:
                                t.cancel()
                            return True
                        bri, r = await coro
                        bri.result = r
                    for _, bri in batch:
                        r = bri.result
                        bri.events.append(
                            ToolEvent(
                                name=bri.call.name,
                                args=_args_preview(bri.call),
                                phase=Phase.END,
                                result=_result_preview(r),
                                is_error=r.is_error,
                            )
                        )
                pe_i = batch_end
            else:
                r = await self._registry.execute(call.name, call.input, DEFAULT_TIMEOUT)
                br.result = r
                br.events.append(
                    ToolEvent(
                        name=call.name,
                        args=_args_preview(call),
                        phase=Phase.END,
                        result=_result_preview(r),
                        is_error=r.is_error,
                    )
                )
                pe_i += 1

        return False
