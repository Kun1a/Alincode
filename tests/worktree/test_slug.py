"""Worktree slug 校验测试（T1）。"""

import pytest

from Alincode.worktree.slug import validate_slug, flat_slug


# ── 合法 ──────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "alice",
    "team/alice",
    "v1.0",
    "a_b",
    "agent-a1b2c3d",
])
def test_valid_slugs(name):
    validate_slug(name)  # 不抛异常


# ── 非法 ──────────────────────────────────────────────

@pytest.mark.parametrize("name,msg", [
    ("", "不能为空"),
    ("../etc", ".."),
    ("..", ".."),
    ("./x", "不能是 '.' 或 '..'"),
    ("a//b", "连续"),
    ("/x", "开头"),
    ("a/", "结尾"),
    ("a b", "非法字符"),
    ("a;b", "非法字符"),
    ("a" * 65, "长度"),
])
def test_invalid_slugs(name, msg):
    with pytest.raises(ValueError):
        validate_slug(name)


# ── flat_slug ─────────────────────────────────────────

def test_flat_slug():
    assert flat_slug("alice") == "alice"
    assert flat_slug("team/alice") == "team+alice"
