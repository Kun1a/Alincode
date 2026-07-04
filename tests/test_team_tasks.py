"""tasks Store 单测(T8)。覆盖 F26-F30、AC10-AC11。"""

from __future__ import annotations

import pytest

from Alincode.team.tasks import (
    Filter,
    Patch,
    Status,
    Store,
    Task,
    TaskNotFoundError,
)


class TestStoreCreate:
    async def test_create_returns_id(self, tmp_path):
        store = Store(str(tmp_path / "tasks.json"))
        tid = await store.create(Task(title="do something"))
        assert tid.startswith("task_")
        # task_ + 6 hex 字符
        assert len(tid) == len("task_") + 6

    async def test_create_multiple(self, tmp_path):
        store = Store(str(tmp_path / "tasks.json"))
        ids = set()
        for i in range(5):
            tid = await store.create(Task(title=f"task-{i}"))
            ids.add(tid)
        assert len(ids) == 5  # id 唯一


class TestStoreGet:
    async def test_get(self, tmp_path):
        store = Store(str(tmp_path / "tasks.json"))
        tid = await store.create(Task(title="test", description="desc"))
        t = await store.get(tid)
        assert t.title == "test"
        assert t.description == "desc"
        assert t.status == Status.PENDING

    async def test_get_not_found(self, tmp_path):
        store = Store(str(tmp_path / "tasks.json"))
        with pytest.raises(TaskNotFoundError):
            await store.get("task_nonexistent")


class TestStoreList:
    async def test_list_by_status(self, tmp_path):
        store = Store(str(tmp_path / "tasks.json"))
        await store.create(Task(title="t1"))
        t2 = await store.create(Task(title="t2"))
        await store.update(t2, Patch(status=Status.IN_PROGRESS))
        pending = await store.list_(Filter(status=Status.PENDING))
        inprogress = await store.list_(Filter(status=Status.IN_PROGRESS))
        assert len(pending) == 1
        assert pending[0].title == "t1"
        assert len(inprogress) == 1
        assert inprogress[0].title == "t2"

    async def test_list_all_no_filter(self, tmp_path):
        store = Store(str(tmp_path / "tasks.json"))
        await store.create(Task(title="t1"))
        await store.create(Task(title="t2"))
        result = await store.list_()
        assert len(result) == 2


class TestStoreUpdate:
    async def test_update_status(self, tmp_path):
        store = Store(str(tmp_path / "tasks.json"))
        tid = await store.create(Task(title="test"))
        await store.update(tid, Patch(status=Status.COMPLETED))
        t = await store.get(tid)
        assert t.status == Status.COMPLETED

    async def test_update_title(self, tmp_path):
        store = Store(str(tmp_path / "tasks.json"))
        tid = await store.create(Task(title="old"))
        await store.update(tid, Patch(title="new"))
        t = await store.get(tid)
        assert t.title == "new"

    async def test_update_not_found(self, tmp_path):
        store = Store(str(tmp_path / "tasks.json"))
        with pytest.raises(TaskNotFoundError):
            await store.update("task_nonexistent", Patch(title="x"))


class TestDependency:
    async def test_add_blocked_by_bidirectional(self, tmp_path):
        """AC10:add_blocked_by 双向更新。"""
        store = Store(str(tmp_path / "tasks.json"))
        t1 = await store.create(Task(title="blocker"))
        t2 = await store.create(Task(title="blocked"))
        await store.update(t2, Patch(add_blocked_by=[t1]))
        # t2 的 blocked_by 含 t1
        t2_obj = await store.get(t2)
        assert t1 in t2_obj.blocked_by
        # t1 的 blocks 含 t2(双向)
        t1_obj = await store.get(t1)
        assert t2 in t1_obj.blocks

    async def test_remove_blocked_by_bidirectional(self, tmp_path):
        store = Store(str(tmp_path / "tasks.json"))
        t1 = await store.create(Task(title="blocker"))
        t2 = await store.create(Task(title="blocked"))
        await store.update(t2, Patch(add_blocked_by=[t1]))
        await store.update(t2, Patch(remove_blocked_by=[t1]))
        t2_obj = await store.get(t2)
        assert t1 not in t2_obj.blocked_by
        t1_obj = await store.get(t1)
        assert t2 not in t1_obj.blocks

    async def test_is_ready(self, tmp_path):
        """AC11:is_ready 反映 blocked_by 是否全 completed。"""
        store = Store(str(tmp_path / "tasks.json"))
        t1 = await store.create(Task(title="blocker"))
        t2 = await store.create(Task(title="blocked"))
        await store.update(t2, Patch(add_blocked_by=[t1]))
        # t1 未完成 → t2 not ready
        result = await store.list_(Filter(status=Status.PENDING))
        t2_obj = [t for t in result if t.id == t2][0]
        assert t2_obj.is_ready is False
        # t1 完成 → t2 ready
        await store.update(t1, Patch(status=Status.COMPLETED))
        result = await store.list_(Filter(status=Status.PENDING))
        t2_obj = [t for t in result if t.id == t2][0]
        assert t2_obj.is_ready is True

    async def test_add_blocks_bidirectional(self, tmp_path):
        """add_blocks 应同时给对方加 blocked_by。"""
        store = Store(str(tmp_path / "tasks.json"))
        t1 = await store.create(Task(title="blocker"))
        t2 = await store.create(Task(title="blocked"))
        await store.update(t1, Patch(add_blocks=[t2]))
        # t1 的 blocks 含 t2
        t1_obj = await store.get(t1)
        assert t2 in t1_obj.blocks
        # t2 的 blocked_by 含 t1(双向)
        t2_obj = await store.get(t2)
        assert t1 in t2_obj.blocked_by
