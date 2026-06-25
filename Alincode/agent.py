"""Agent Loop 编排：多轮 ReAct 循环 + 逐字流式（不缓冲整个回复）。"""

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
from Alincode.prompt import (
    build_system_prompt,
    gather_environment,
    plan_reminder,
)
from Alincode.tools import Registry, Result, DEFAULT_TIMEOUT

MAX_ITERATIONS = 25
MAX_UNKNOWN_RUN = 3


class Mode(Enum):
    NORMAL = "normal"
    PLAN = "plan"


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


def _args_preview(c: ToolCall) -> str:
    return c.input if len(c.input) <= 80 else c.input[:77] + "..."

def _result_preview(r: Result) -> str:
    return r.content if len(r.content) <= 500 else r.content[:497] + "..."


class Agent:
    """ReAct 循环编排——每 token 立即 yield，不在内部缓冲整个回复。"""

    def __init__(self, provider: BaseProvider, registry: Registry, model: str = "", version: str = "0.3.0") -> None:
        self._provider = provider
        self._registry = registry
        self._model = model
        self._version = version

    async def run(
        self, conv: ConversationManager,
        mode: Mode = Mode.NORMAL,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        if cancel is None:
            cancel = asyncio.Event()

        env = await gather_environment(cwd=None, version=self._version, model=self._model)
        stable, env_block = build_system_prompt(env)
        defs = self._registry.read_only_definitions() if mode == Mode.PLAN else self._registry.definitions()

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
                messages=conv.messages, model=self._model, tools=defs,
                reminder=reminder,
            )

            # ★ 直接消费 provider 流，逐 token yield——不收集到列表
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
                        yield Event(text=se.text)          # ← 逐字 yield
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
                yield Event(usage=Usage(input_tokens=total_input, output_tokens=total_output))

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

            results, cancelled = await self._execute_batch(tool_calls, cancel)
            if cancelled:
                yield Event(notice=NOTICE_CANCELLED, done=True)
                conv.ensure_assistant_tail(NOTICE_CANCELLED)
                return

            for r_obj in results:
                for te in r_obj.events:
                    yield Event(tool=te)

            tool_results = [
                ToolResult(tool_call_id=call.id, content=r_obj.result.content, is_error=r_obj.result.is_error)
                for call, r_obj in zip(tool_calls, results)
            ]
            conv.add_tool_results(tool_calls, tool_results)

        yield Event(notice=NOTICE_MAX_ITER, done=True)
        conv.ensure_assistant_tail(NOTICE_MAX_ITER)

    async def _execute_batch(
        self, calls: list[ToolCall], cancel: asyncio.Event,
    ) -> tuple[list[_BatchResult], bool]:
        results: list[_BatchResult | None] = [None] * len(calls)
        i = 0

        while i < len(calls):
            if cancel.is_set():
                return [r for r in results if r], True

            call = calls[i]
            if self._registry.is_read_only(call.name):
                batch_end = i
                while batch_end < len(calls) and self._registry.is_read_only(calls[batch_end].name):
                    batch_end += 1
                batch_indices = list(range(i, batch_end))

                for idx in batch_indices:
                    c = calls[idx]
                    results[idx] = _BatchResult(
                        result=Result(content="", is_error=False),
                        events=[ToolEvent(name=c.name, args=_args_preview(c), phase=Phase.START)],
                    )

                async def _do(idx: int) -> tuple[int, Result]:
                    return idx, await self._registry.execute(calls[idx].name, calls[idx].input, DEFAULT_TIMEOUT)

                tasks = [asyncio.create_task(_do(idx)) for idx in batch_indices]
                for coro in asyncio.as_completed(tasks):
                    if cancel.is_set():
                        for t in tasks:
                            t.cancel()
                        return [r for r in results if r], True
                    idx, r = await coro
                    results[idx].result = r

                for idx in batch_indices:
                    r = results[idx].result
                    results[idx].events.append(ToolEvent(
                        name=calls[idx].name, args=_args_preview(calls[idx]),
                        phase=Phase.END, result=_result_preview(r), is_error=r.is_error,
                    ))
                i = batch_end
            else:
                if cancel.is_set():
                    return [r for r in results if r], True

                events = [ToolEvent(name=call.name, args=_args_preview(call), phase=Phase.START)]
                r = await self._registry.execute(call.name, call.input, DEFAULT_TIMEOUT)
                events.append(ToolEvent(
                    name=call.name, args=_args_preview(call), phase=Phase.END,
                    result=_result_preview(r), is_error=r.is_error,
                ))
                results[i] = _BatchResult(result=r, events=events)
                i += 1

        return [r for r in results if r], False


@dataclass
class _BatchResult:
    result: Result
    events: list[ToolEvent] = field(default_factory=list)
