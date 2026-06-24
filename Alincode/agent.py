"""Agent 单轮闭环编排：请求#1（带工具）→ 执行 → 请求#2（续答）→ 停。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator

from Alincode.client import BaseProvider
from Alincode.conversation import (
    ConversationManager,
    ToolCall,
    ToolResult,
)
from Alincode.tools import Registry, DEFAULT_TIMEOUT


class Phase(Enum):
    """工具调用生命周期阶段。"""
    START = "start"  # 工具开始执行
    END = "end"      # 工具执行完毕


@dataclass
class ToolEvent:
    """一次工具调用的开始 / 结束（供 TUI 渲染工具行与结果摘要）。"""
    name: str
    args: str = ""         # 参数预览（用于 ● name(args)）
    phase: Phase = Phase.START
    result: str = ""       # phase=END：结果摘要
    is_error: bool = False  # phase=END：是否错误


@dataclass
class Event:
    """单轮闭环对外事件流元素，TUI 据非 None 字段分派渲染。"""
    text: str = ""                # 文本增量（preamble 或最终答复）
    tool: ToolEvent | None = None  # 工具调用开始 / 结束
    done: bool = False            # 本轮结束
    err: Exception | None = None  # 出错（不中断会话）


# 续答为空的占位提示（AC9）
EMPTY_FINAL_PROMPT = "（最终答复为空——已达到单轮上限。）"


class Agent:
    """持有 provider 与注册中心，执行单轮闭环。

    单轮流程：
    1. 请求#1：带工具定义，收集 preamble 文本 + tool_calls
    2. 若无 tool_calls：直接返回 preamble 文本作为最终答复
    3. 若有 tool_calls：逐工具执行 → 结果回灌进对话历史
    4. 请求#2：带工具定义但不执行新 call，收集最终文本答复
    5. 结束——不循环（AC9）
    """

    def __init__(self, provider: BaseProvider, registry: Registry, model: str = "") -> None:
        self._provider = provider
        self._registry = registry
        self._model = model

    async def run(self, conv: ConversationManager) -> AsyncIterator[Event]:
        """执行单轮闭环，async generator 吐出事件流。"""
        defs = self._registry.definitions()

        # ── 请求 #1 ──────────────────────────────────
        preamble = ""
        tool_calls: list[ToolCall] = []
        err_first = None

        async for se in self._provider.stream(conv.messages, self._model, defs):
            if se.err:
                err_first = se.err
                break
            if se.text:
                preamble += se.text
                yield Event(text=se.text)
            if se.tool_calls:
                tool_calls.extend(se.tool_calls)

        if err_first:
            yield Event(err=err_first)
            yield Event(done=True)
            return

        # 无工具调用 → 纯文本回合
        if not tool_calls:
            if preamble.strip():
                conv.add_assistant(preamble)
            yield Event(done=True)
            return

        # ── 工具调用回合 ──────────────────────────────
        conv.add_assistant_with_tool_calls(preamble, tool_calls)

        results: list[ToolResult] = []

        for call in tool_calls:
            # 参数预览：截断到 80 字符
            args_preview = call.input if len(call.input) <= 80 else call.input[:77] + "..."

            yield Event(tool=ToolEvent(
                name=call.name,
                args=args_preview,
                phase=Phase.START,
            ))

            r = await self._registry.execute(call.name, call.input, timeout=DEFAULT_TIMEOUT)

            # 结果摘要：取前 500 字符截断
            result_preview = r.content if len(r.content) <= 500 else r.content[:497] + "..."

            yield Event(tool=ToolEvent(
                name=call.name,
                args=args_preview,
                phase=Phase.END,
                result=result_preview,
                is_error=r.is_error,
            ))

            results.append(ToolResult(
                tool_call_id=call.id,
                content=r.content,
                is_error=r.is_error,
            ))

        # 回灌工具结果
        conv.add_tool_results(results)

        # ── 请求 #2（续答）──────────────────────────────
        final = ""
        err_second = None
        more_tools_ignored = False

        async for se in self._provider.stream(conv.messages, self._model, defs):
            if se.err:
                err_second = se.err
                break
            if se.text:
                final += se.text
                yield Event(text=se.text)
            if se.tool_calls:
                # 单轮上限：忽略再次请求的工具调用
                more_tools_ignored = True

        if err_second:
            yield Event(err=err_second)
            yield Event(done=True)
            return

        # 空最终答复 → 占位提示
        if not final.strip():
            final = EMPTY_FINAL_PROMPT if more_tools_ignored else ""
            if final:
                yield Event(text=final)

        if final.strip():
            conv.add_assistant(final)
        yield Event(done=True)
