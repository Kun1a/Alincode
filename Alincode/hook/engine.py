"""Hook Engine：事件分派 + only_once 集合 + DispatchResult。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Alincode.hook.rule import Rule, Payload
    from Alincode.hook.event import Event

from Alincode.hook.event import is_blocking
from Alincode.hook.matcher import eval_condition
from Alincode.hook.executor import Executor


@dataclass
class DispatchResult:
    blocked: bool = False
    reason: str = ""
    blocking_hook_id: str = ""
    injected_prompts: list[str] = field(default_factory=list)


class Engine:
    """Hook 规则引擎。"""

    def __init__(self, rules: list["Rule"], sources: list[str]) -> None:
        self._rules = list(rules)
        self._sources = list(sources)
        self._once_fired: set[str] = set()
        self._lock = asyncio.Lock()
        self._executor = Executor()

    @property
    def sources(self) -> list[str]:
        return list(self._sources)

    @property
    def rules(self) -> list["Rule"]:
        return list(self._rules)

    async def dispatch(self, event: "Event", payload: "Payload") -> DispatchResult:
        """按事件分派 Hook 规则。"""
        result = DispatchResult()

        for rule in self._rules:
            if rule.event is not event:
                continue

            # only_once 检查
            if rule.only_once:
                async with self._lock:
                    if rule.id in self._once_fired:
                        continue

            # 条件求值
            if not eval_condition(rule.condition, payload):
                continue

            # async hook：起 task 不等待
            if rule.async_mode:
                asyncio.create_task(self._executor.run(rule, payload, blocking=False))
                if rule.only_once:
                    async with self._lock:
                        self._once_fired.add(rule.id)
                continue

            # 同步执行
            outcome = await self._executor.run(
                rule, payload, blocking=is_blocking(event),
            )

            if outcome.err is not None:
                print(
                    f"[hook {rule.id}] {event.value} failed: {outcome.err}",
                    file=sys.stderr,
                )
                continue

            if outcome.prompt:
                result.injected_prompts.append(outcome.prompt)

            if rule.only_once:
                async with self._lock:
                    self._once_fired.add(rule.id)

            if outcome.blocked and is_blocking(event):
                result.blocked = True
                result.reason = outcome.reason
                result.blocking_hook_id = rule.id
                break

        return result

    async def reset_for_new_session(self) -> None:
        async with self._lock:
            self._once_fired.clear()
