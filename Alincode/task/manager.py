"""后台任务管理器：Manager + BackgroundTask + PartialState（T19-T21）。"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Alincode.agent import Agent
    from Alincode.conversation import ConversationManager


class Status(IntEnum):
    RUNNING = 0
    COMPLETED = 1
    FAILED = 2
    CANCELLED = 3


@dataclass
class TaskUsage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass
class PartialState:
    """前台→后台移交时已收集的中间状态。"""
    last_assistant_text: str = ""
    tool_count: int = 0
    last_activity: str = ""
    usage: TaskUsage = field(default_factory=TaskUsage)


@dataclass
class BackgroundTask:
    """一个后台子 Agent 的完整状态快照。"""
    id: str
    name: str
    sub_agent: "Agent"
    conv: "ConversationManager"
    task: str
    status: Status = Status.RUNNING
    result: str = ""
    err: BaseException | None = None
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    handle: asyncio.Task | None = None
    usage: TaskUsage = field(default_factory=TaskUsage)
    tool_count: int = 0
    last_activity: str = ""


class TaskNotFound(Exception):
    pass


class TaskBusy(Exception):
    pass


class Manager:
    """管理后台任务。协程安全（单事件循环）。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, BackgroundTask] = {}
        self._by_name: dict[str, str] = {}
        self._done: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
        self._counter: int = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"task_{time.time_ns() ^ self._counter:08x}"

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def list(self) -> list[BackgroundTask]:
        return sorted(self._tasks.values(), key=lambda bt: bt.start_time)

    def subscribe_done(self) -> asyncio.Queue[str]:
        return self._done

    async def launch(
        self, ag: "Agent", conv: "ConversationManager",
        name: str, task_text: str,
    ) -> str:
        """启动后台子 Agent。返回 task_id。"""
        task_id = self._next_id()
        bt = BackgroundTask(
            id=task_id, name=name, sub_agent=ag, conv=conv, task=task_text,
            status=Status.RUNNING,
        )

        async with self._lock:
            self._tasks[task_id] = bt
            if name:
                self._by_name[name] = task_id

        events: asyncio.Queue = asyncio.Queue(maxsize=64)
        aggregator = asyncio.create_task(self._aggregate_events(events, bt))

        async def runner() -> None:
            try:
                text = await ag.run_to_completion(conv, task_text, events)
                bt.result = text
                bt.status = Status.COMPLETED
            except asyncio.CancelledError:
                bt.status = Status.CANCELLED
            except BaseException as e:
                bt.status = Status.FAILED
                bt.err = e
            finally:
                bt.end_time = time.monotonic()
                aggregator.cancel()
                try:
                    self._done.put_nowait(task_id)
                except asyncio.QueueFull:
                    print(
                        f"task manager: done queue full, dropping notification for {task_id}",
                        file=sys.stderr,
                    )

        bt.handle = asyncio.create_task(runner())
        return task_id

    async def adopt_running(
        self, ag: "Agent", conv: "ConversationManager",
        name: str, events: asyncio.Queue,
        handle: asyncio.Task, partial: PartialState,
    ) -> str:
        """接管已经在前台启动的子 Agent，转后台继续跑。"""
        task_id = self._next_id()
        bt = BackgroundTask(
            id=task_id, name=name, sub_agent=ag, conv=conv, task="",
            status=Status.RUNNING,
            tool_count=partial.tool_count,
            last_activity=partial.last_activity,
            usage=partial.usage,
            handle=handle,
        )

        async with self._lock:
            self._tasks[task_id] = bt
            if name:
                self._by_name[name] = task_id

        aggregator = asyncio.create_task(self._aggregate_events(events, bt))

        async def monitor() -> None:
            try:
                await handle
                bt.result = partial.last_assistant_text
                bt.status = Status.COMPLETED if bt.status == Status.RUNNING else bt.status
            except asyncio.CancelledError:
                bt.status = Status.CANCELLED
            except BaseException as e:
                bt.status = Status.FAILED
                bt.err = e
            finally:
                bt.end_time = time.monotonic()
                aggregator.cancel()
                try:
                    self._done.put_nowait(task_id)
                except asyncio.QueueFull:
                    pass

        asyncio.create_task(monitor())
        return task_id

    async def stop(self, task_id: str) -> bool:
        bt = self._tasks.get(task_id)
        if bt is None:
            return False
        if bt.handle:
            bt.handle.cancel()
        return True

    async def send_message(self, name: str, message: str) -> str:
        """给已完成的 Agent 续派任务。"""
        async with self._lock:
            task_id = self._by_name.get(name)
            if task_id is None:
                raise TaskNotFound(f"no task with name: {name}")

            bt = self._tasks.get(task_id)
            if bt is None:
                raise TaskNotFound(f"task {task_id} not found")
            if bt.conv is None:
                raise TaskNotFound(f"task {task_id}: conversation already released")
            if bt.status not in (Status.COMPLETED, Status.FAILED):
                raise TaskBusy(f"task {task_id} is {bt.status.name}, not ready for new message")

            bt.conv.add_user(message)
            bt.status = Status.RUNNING
            bt.tool_count = 0
            bt.last_activity = ""

        # 重新跑
        events: asyncio.Queue = asyncio.Queue(maxsize=64)
        aggregator = asyncio.create_task(self._aggregate_events(events, bt))

        async def runner() -> None:
            try:
                text = await bt.sub_agent.run_to_completion(bt.conv, "", events)
                bt.result = text
                bt.status = Status.COMPLETED
            except asyncio.CancelledError:
                bt.status = Status.CANCELLED
            except BaseException as e:
                bt.status = Status.FAILED
                bt.err = e
            finally:
                bt.end_time = time.monotonic()
                aggregator.cancel()
                try:
                    self._done.put_nowait(task_id)
                except asyncio.QueueFull:
                    pass

        bt.handle = asyncio.create_task(runner())
        return task_id

    async def _aggregate_events(self, queue: asyncio.Queue, bt: BackgroundTask) -> None:
        """消费事件队列，更新 task 状态。"""
        while True:
            ev = await queue.get()
            if ev is None:
                break
            try:
                if hasattr(ev, 'tool') and ev.tool and ev.tool.phase.value == "start":
                    bt.tool_count += 1
                    bt.last_activity = ev.tool.name
                if hasattr(ev, 'usage') and ev.usage:
                    bt.usage.input += ev.usage.input_tokens
                    bt.usage.output += ev.usage.output_tokens
            except Exception:
                pass
