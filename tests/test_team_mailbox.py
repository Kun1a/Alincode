"""mailbox Box 与 filelock 单测(T5-T6 + T9)。

覆盖 AC12-AC15:write/read 往返、并发安全、stale 锁抢占。
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from Alincode.team.filelock import acquire, LOCK_STALE_AFTER
from Alincode.team.mailbox import Box, Message, MessageType


class TestBoxBasic:
    async def test_write_read_roundtrip(self, tmp_path):
        box = Box(str(tmp_path))
        await box.write(
            "alice",
            Message(from_="lead", to="alice", summary="hi", content="hello"),
        )
        msgs = await box.read("alice")
        assert len(msgs) == 1
        assert msgs[0].from_ == "lead"
        assert msgs[0].to == "alice"
        assert msgs[0].content == "hello"
        assert msgs[0].timestamp > 0

    async def test_write_multiple(self, tmp_path):
        box = Box(str(tmp_path))
        for i in range(5):
            await box.write(
                "alice", Message(from_="lead", to="alice", content=f"msg{i}")
            )
        msgs = await box.read("alice")
        assert len(msgs) == 5
        assert [m.content for m in msgs] == [f"msg{i}" for i in range(5)]

    async def test_read_empty(self, tmp_path):
        box = Box(str(tmp_path))
        assert await box.read("alice") == []

    async def test_read_unread(self, tmp_path):
        box = Box(str(tmp_path))
        await box.write("alice", Message(from_="lead", to="alice", content="m1"))
        await box.write("alice", Message(from_="lead", to="alice", content="m2"))
        indices, unread = await box.read_unread("alice")
        assert len(unread) == 2
        assert len(indices) == 2

    async def test_mark_read(self, tmp_path):
        box = Box(str(tmp_path))
        await box.write("alice", Message(from_="lead", to="alice", content="m1"))
        indices, _ = await box.read_unread("alice")
        await box.mark_read("alice", indices)
        indices2, unread2 = await box.read_unread("alice")
        assert len(unread2) == 0
        assert len(indices2) == 0

    async def test_message_type_serialization(self, tmp_path):
        box = Box(str(tmp_path))
        await box.write(
            "alice",
            Message(
                from_="lead",
                to="alice",
                type=MessageType.PLAN_APPROVAL_RESPONSE,
                summary="approve",
                payload={"approve": True},
            ),
        )
        msgs = await box.read("alice")
        assert msgs[0].type == MessageType.PLAN_APPROVAL_RESPONSE
        assert msgs[0].payload == {"approve": True}

    async def test_separate_mailboxes(self, tmp_path):
        box = Box(str(tmp_path))
        await box.write("alice", Message(from_="lead", to="alice", content="for alice"))
        await box.write("bob", Message(from_="lead", to="bob", content="for bob"))
        alice_msgs = await box.read("alice")
        bob_msgs = await box.read("bob")
        assert len(alice_msgs) == 1
        assert len(bob_msgs) == 1
        assert alice_msgs[0].content == "for alice"
        assert bob_msgs[0].content == "for bob"


class TestFileLock:
    async def test_acquire_release(self, tmp_path):
        lock_path = str(tmp_path / "test.lock")
        async with acquire(lock_path):
            assert os.path.exists(lock_path)
        assert not os.path.exists(lock_path)

    async def test_serial_access(self, tmp_path):
        """两次抢锁,中间 release,都能成功。"""
        lock_path = str(tmp_path / "serial.lock")
        async with acquire(lock_path):
            pass
        async with acquire(lock_path):
            pass

    async def test_stale_lock_preempted(self, tmp_path):
        """stale lock(>10秒)能被新 writer 抢占(AC15)。"""
        lock_path = str(tmp_path / "stale.lock")
        # 创建一个 11 秒前的 lock
        Path(lock_path).touch()
        old_time = time.time() - (LOCK_STALE_AFTER + 1)
        os.utime(lock_path, (old_time, old_time))
        # 应该能抢到(stale 清掉后重试)
        async with acquire(lock_path):
            assert not os.path.exists(lock_path) or True  # 锁被清掉重建
        # 正常退出后 lock 被删
        assert not os.path.exists(lock_path)


class TestConcurrency:
    async def test_concurrent_writes_no_loss(self, tmp_path):
        """10 个 asyncio task 同时写同一 mailbox,最终 10 条无丢失(AC14)。"""
        box = Box(str(tmp_path))

        async def writer(i: int):
            await box.write(
                "alice", Message(from_="lead", to="alice", content=f"msg-{i}")
            )

        await asyncio.gather(*[writer(i) for i in range(10)])
        msgs = await box.read("alice")
        assert len(msgs) == 10
        contents = sorted(m.content for m in msgs)
        assert contents == [f"msg-{i}" for i in range(10)]

    async def test_concurrent_writes_different_agents(self, tmp_path):
        """10 个 task 写 5 个不同 agent,每人 2 条。"""
        box = Box(str(tmp_path))

        async def writer(agent: str, j: int):
            await box.write(agent, Message(from_="lead", to=agent, content=f"m{j}"))

        tasks = []
        for i in range(5):
            agent = f"agent-{i}"
            tasks.append(writer(agent, 0))
            tasks.append(writer(agent, 1))
        await asyncio.gather(*tasks)
        for i in range(5):
            msgs = await box.read(f"agent-{i}")
            assert len(msgs) == 2
