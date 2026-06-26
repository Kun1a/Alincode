"""Agent Loop 编排：多轮 ReAct + 权限检查（ASK 不阻塞）+ 逐字流式。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator

from Alincode.client import BaseProvider, Request, System as SystemBlocks
from Alincode.conversation import (
    ConversationManager,
    ToolCall,
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
from Alincode.tools import Registry, Result, DEFAULT_TIMEOUT

MAX_ITERATIONS = 25
MAX_UNKNOWN_RUN = 3


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
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._model = model
        self._version = version
        self._engine = engine or PermissionEngine()

    async def run(
        self,
        conv: ConversationManager,
        mode: Mode = Mode.DEFAULT,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        if cancel is None:
            cancel = asyncio.Event()

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

            if cancel.is_set():
                yield Event(notice=NOTICE_CANCELLED, done=True)
                conv.ensure_assistant_tail(NOTICE_CANCELLED)
                return
            if err:
                yield Event(err=err, notice=NOTICE_PROVIDER_ERROR, done=True)
                conv.ensure_assistant_tail(NOTICE_PROVIDER_ERROR)
                return
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
            conv.add_tool_results(tool_calls, tool_results)

        yield Event(notice=NOTICE_MAX_ITER, done=True)
        conv.ensure_assistant_tail(NOTICE_MAX_ITER)

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
