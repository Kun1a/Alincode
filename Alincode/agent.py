"""Agent Loop 编排：多轮 ReAct 循环，自主调用工具直到任务完成。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator

from Alincode.client import BaseProvider
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
from Alincode.prompts import PLAN_MODE_REMINDER
from Alincode.tools import Registry, Result, DEFAULT_TIMEOUT

# ── 常量 ────────────────────────────────────────────

MAX_ITERATIONS = 25
MAX_UNKNOWN_RUN = 3


# ── 模式 ────────────────────────────────────────────

class Mode(Enum):
    NORMAL = "normal"
    PLAN = "plan"


# ── 工具调用阶段 ───────────────────────────────────────

class Phase(Enum):
    START = "start"
    END = "end"


@dataclass
class ToolEvent:
    """一次工具调用的开始 / 结束。"""
    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass
class Event:
    """Agent 对外事件流元素。"""
    text: str = ""
    tool: ToolEvent | None = None
    usage: Usage | None = None
    iter: int = 0
    notice: str = ""
    done: bool = False
    err: Exception | None = None


# ── 辅助 ────────────────────────────────────────────

def _args_preview(c: ToolCall) -> str:
    return c.input if len(c.input) <= 80 else c.input[:77] + "..."

def _result_preview(r: Result) -> str:
    return r.content if len(r.content) <= 500 else r.content[:497] + "..."


# ── Agent ────────────────────────────────────────────

class Agent:
    """ReAct 循环编排：多轮调 LLM → 执行工具 → 回灌结果 → 继续。"""

    def __init__(self, provider: BaseProvider, registry: Registry, model: str = "") -> None:
        self._provider = provider
        self._registry = registry
        self._model = model

    async def run(
        self,
        conv: ConversationManager,
        mode: Mode = Mode.NORMAL,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        """执行多轮 ReAct 循环。"""
        if cancel is None:
            cancel = asyncio.Event()

        if mode == Mode.PLAN:
            defs = self._registry.read_only_definitions()
            suffix = PLAN_MODE_REMINDER
        else:
            defs = self._registry.definitions()
            suffix = ""

        unknown_run = 0
        total_input = 0
        total_output = 0

        for iteration in range(1, MAX_ITERATIONS + 1):
            if cancel.is_set():
                yield Event(notice=NOTICE_CANCELLED, done=True)
                conv.ensure_assistant_tail(NOTICE_CANCELLED)
                return

            yield Event(iter=iteration)

            # ── 流式请求 LLM ──────────────────────
            preamble, tool_calls, tu_in, tu_out, events, err = \
                await self._stream_once(conv, defs, suffix, cancel)

            total_input += tu_in
            total_output += tu_out
            if tu_in or tu_out:
                yield Event(usage=Usage(
                    input_tokens=total_input, output_tokens=total_output,
                ))
            for ev in events:
                yield ev

            if cancel.is_set():
                yield Event(notice=NOTICE_CANCELLED, done=True)
                conv.ensure_assistant_tail(NOTICE_CANCELLED)
                return

            if err:
                yield Event(err=err, notice=NOTICE_PROVIDER_ERROR, done=True)
                conv.ensure_assistant_tail(NOTICE_PROVIDER_ERROR)
                return

            # ── 自然完成 ───────────────────────────
            if not tool_calls:
                if preamble.strip():
                    conv.add_assistant(preamble)
                yield Event(done=True)
                return

            # ── 未知工具检测 ───────────────────────
            known = [c for c in tool_calls if self._registry.get(c.name)]
            if not known:
                unknown_run += 1
                if unknown_run >= MAX_UNKNOWN_RUN:
                    yield Event(notice=NOTICE_UNKNOWN_TOOLS, done=True)
                    conv.ensure_assistant_tail(NOTICE_UNKNOWN_TOOLS)
                    return
            else:
                unknown_run = 0

            # ── assistant(tool_calls) ──────────────
            conv.add_assistant_with_tool_calls(preamble, tool_calls)

            # ── 保序分批执行工具 ─────────────────══
            results, cancelled = await self._execute_batch(
                tool_calls, cancel,
            )
            if cancelled:
                yield Event(notice=NOTICE_CANCELLED, done=True)
                conv.ensure_assistant_tail(NOTICE_CANCELLED)
                return

            # ── 按序发送所有工具事件 ───────────────
            for r_obj in results:
                for te in r_obj.events:
                    yield Event(tool=te)

            # ── 回灌工具结果 ──────────────────────
            tool_results = [
                ToolResult(
                    tool_call_id=call.id,
                    content=r_obj.result.content,
                    is_error=r_obj.result.is_error,
                )
                for call, r_obj in zip(tool_calls, results)
            ]
            conv.add_tool_results(tool_calls, tool_results)

            # suffix 仅首轮注入
            if suffix and iteration > 1:
                suffix = ""

        # 迭代上限
        yield Event(notice=NOTICE_MAX_ITER, done=True)
        conv.ensure_assistant_tail(NOTICE_MAX_ITER)

    async def _stream_once(
        self, conv, defs, suffix, cancel,
    ) -> tuple[str, list[ToolCall], int, int, list[Event], Exception | None]:
        """单次 LLM 流式请求。返回 (preamble, tool_calls, in_tokens, out_tokens, events, err)。"""
        preamble = ""
        tool_calls: list[ToolCall] = []
        events: list[Event] = []
        err = None
        tu_in = 0
        tu_out = 0

        try:
            async for se in self._provider.stream(
                conv.messages, self._model, defs, system_suffix=suffix,
            ):
                if cancel.is_set():
                    break
                if se.err:
                    err = se.err
                    break
                if se.text:
                    preamble += se.text
                    events.append(Event(text=se.text))
                if se.usage:
                    tu_in += se.usage.input_tokens
                    tu_out += se.usage.output_tokens
                if se.tool_calls:
                    tool_calls.extend(se.tool_calls)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            err = e

        return preamble, tool_calls, tu_in, tu_out, events, err

    async def _execute_batch(
        self, calls: list[ToolCall], cancel: asyncio.Event,
    ) -> tuple[list[_BatchResult], bool]:
        """保序分批并发执行。返回 (results, cancelled)。

        连续只读并发，有副作用串行。START/END 事件按调用序。
        """
        results: list[_BatchResult | None] = [None] * len(calls)
        i = 0

        while i < len(calls):
            if cancel.is_set():
                return [r for r in results if r], True

            call = calls[i]
            if self._registry.is_read_only(call.name):
                # 收集连续只读段
                batch_end = i
                while batch_end < len(calls) and self._registry.is_read_only(calls[batch_end].name):
                    batch_end += 1
                batch_indices = list(range(i, batch_end))

                # (1) 先按序发 START
                for idx in batch_indices:
                    c = calls[idx]
                    results[idx] = _BatchResult(
                        result=Result(content="", is_error=False),
                        events=[ToolEvent(
                            name=c.name, args=_args_preview(c), phase=Phase.START,
                        )],
                    )

                # (2) 并发执行
                async def _do(idx: int) -> tuple[int, Result]:
                    return idx, await self._registry.execute(
                        calls[idx].name, calls[idx].input, DEFAULT_TIMEOUT,
                    )

                tasks = [asyncio.create_task(_do(idx)) for idx in batch_indices]
                for coro in asyncio.as_completed(tasks):
                    if cancel.is_set():
                        for t in tasks:
                            t.cancel()
                        return [r for r in results if r], True
                    idx, r = await coro
                    results[idx].result = r

                # (3) 按序发 END
                for idx in batch_indices:
                    r = results[idx].result
                    results[idx].events.append(ToolEvent(
                        name=calls[idx].name, args=_args_preview(calls[idx]),
                        phase=Phase.END, result=_result_preview(r), is_error=r.is_error,
                    ))

                i = batch_end
            else:
                # 有副作用——串行
                if cancel.is_set():
                    return [r for r in results if r], True

                events = [ToolEvent(
                    name=call.name, args=_args_preview(call), phase=Phase.START,
                )]
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
    """工具执行结果 + 关联事件列表。"""
    result: Result
    events: list[ToolEvent] = field(default_factory=list)
