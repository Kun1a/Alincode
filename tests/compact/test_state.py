"""状态对象单测：决策冻结、熔断计数、文件追踪并发、会话上下文（T22 子集）。"""

import threading
import time

from Alincode.compact.state import (
    new_session_context,
    ContentReplacementState,
    AutoCompactTrackingState,
    RecoveryState,
)


# ── SessionContext ──────────────────────────────────

def test_new_session_context_creates_dir(tmp_path):
    """会话目录按需创建，session_id 格式正确。"""
    ctx = new_session_context(str(tmp_path))
    assert "-" in ctx.session_id
    assert ctx.spill_dir.endswith("tool-results")
    import os
    assert os.path.isdir(ctx.spill_dir)


def test_new_session_context_unique():
    """两次调用产生不同 session_id。"""
    ctx1 = new_session_context(".")
    ctx2 = new_session_context(".")
    assert ctx1.session_id != ctx2.session_id


def test_new_session_context_rand_fail_fallback(monkeypatch):
    """secrets.token_hex 失败时降级到 random，不抛异常。"""
    def _fail(*args, **kwargs):
        raise RuntimeError("mock failure")
    monkeypatch.setattr("secrets.token_hex", _fail)
    ctx = new_session_context(".")
    assert "-" in ctx.session_id


# ── ContentReplacementState ─────────────────────────

def test_decide_once_freeze_kept():
    """kept 后账本冻结，后续调用直接返回原文。"""
    s = ContentReplacementState()
    call_count = [0]

    def decide():
        call_count[0] += 1
        return ("kept", "")

    r1 = s.decide_once("id1", "original", decide)
    assert r1 == "original"
    assert call_count[0] == 1

    # 第二次：decide 不再被调用
    r2 = s.decide_once("id1", "original", decide)
    assert r2 == "original"
    assert call_count[0] == 1  # 未增加


def test_decide_once_freeze_replaced():
    """replaced 后返回冻结的 preview，不复调用 decide。"""
    s = ContentReplacementState()
    call_count = [0]

    def decide():
        call_count[0] += 1
        return ("replaced", "preview_v1")

    r1 = s.decide_once("id1", "original", decide)
    assert r1 == "preview_v1"
    assert call_count[0] == 1

    r2 = s.decide_once("id1", "original", decide)
    assert r2 == "preview_v1"
    assert call_count[0] == 1  # 未增加


def test_decide_once_skip_does_not_mark():
    """skip 后账本不写，下次仍可重试。"""
    s = ContentReplacementState()
    call_count = [0]

    def _decide():
        call_count[0] += 1
        return ("skip", "")

    r1 = s.decide_once("id1", "original", _decide)
    assert r1 == "original"
    assert call_count[0] == 1

    # 第二次仍然调用 decide（未被标记为 Seen）
    r2 = s.decide_once("id1", "original", _decide)
    assert r2 == "original"
    assert call_count[0] == 2


# ── AutoCompactTrackingState ────────────────────────

def test_auto_tracking_tripped():
    """连续失败 3 次后跳闸。"""
    at = AutoCompactTrackingState()
    assert not at.tripped()
    at.record_failure()
    at.record_failure()
    assert not at.tripped()
    at.record_failure()
    assert at.tripped()


def test_auto_tracking_success_resets():
    """成功清零。"""
    at = AutoCompactTrackingState()
    at.record_failure()
    at.record_failure()
    at.record_success()
    assert not at.tripped()
    at.record_failure()
    assert not at.tripped()


def test_auto_tracking_concurrent():
    """并发 record_success / record_failure / tripped 无竞态。"""
    at = AutoCompactTrackingState()
    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        for _ in range(100):
            at.record_failure()
            at.record_success()
            at.tripped()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 最终 state 一致
    assert not at.tripped()


# ── RecoveryState ──────────────────────────────────

def test_recovery_state_snapshot_order(tmp_path):
    """snapshot 按 timestamp 倒序。"""
    rs = RecoveryState()
    a = str(tmp_path / "a.txt")
    b = str(tmp_path / "b.txt")
    c = str(tmp_path / "c.txt")
    rs.record_file(a, "content A")
    time.sleep(0.01)
    rs.record_file(b, "content B")
    time.sleep(0.01)
    rs.record_file(c, "content C")

    snap = rs.snapshot()
    assert len(snap) == 3
    assert snap[0].path == c
    assert snap[1].path == b
    assert snap[2].path == a


def test_recovery_state_record_file_resolves_relative():
    """相对路径自动 resolve 为绝对路径。"""
    rs = RecoveryState()
    rs.record_file("test.txt", "hello")
    snap = rs.snapshot()
    assert len(snap) == 1
    assert snap[0].path != "test.txt"  # 已 resolve


def test_recovery_state_concurrent():
    """50 个并发 thread record_file + snapshot 无异常。"""
    rs = RecoveryState()
    barrier = threading.Barrier(50)

    def worker(i):
        barrier.wait()
        for _ in range(10):
            rs.record_file(f"/f{i}_{_}.txt", f"content_{i}_{_}")
            rs.snapshot()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 无异常就是通过
