"""Matcher 四种类型单元测试（F1/F2/F3，AC1-AC3）。"""

import pytest

from Alincode.permission.matcher import (
    compile_matcher,
    ExactMatcher,
    GlobMatcher,
    RegexMatcher,
    NotMatcher,
)


# ── Exact ───────────────────────────────────────────────

@pytest.mark.parametrize("pattern, target, expected", [
    ("=git status", "git status", True),
    ("=git status", "git status -s", False),
    ("=foo", "foo", True),
    ("=foo", "bar", False),
    ("=", "", True),
], ids=["exact-hit", "exact-miss-extra", "exact-simple", "exact-simple-miss", "exact-empty"])
def test_exact_match(pattern, target, expected):
    m = compile_matcher(pattern)
    assert isinstance(m, ExactMatcher)
    assert m.match(target) == expected


# ── Glob ────────────────────────────────────────────────

@pytest.mark.parametrize("pattern, target, expected", [
    ("git *", "git status", True),
    ("git *", "npm install", False),
    ("*.py", "foo.py", True),
    ("*.py", "foo.txt", False),
    ("test_*", "test_foo", True),
    ("test_*", "x_test_foo", False),
], ids=["glob-cmd-hit", "glob-cmd-miss", "glob-py-hit", "glob-py-miss", "glob-prefix-hit", "glob-prefix-miss"])
def test_glob_match(pattern, target, expected):
    m = compile_matcher(pattern)
    assert isinstance(m, GlobMatcher)
    assert m.match(target) == expected


# ── Regex ───────────────────────────────────────────────

@pytest.mark.parametrize("pattern, target, expected", [
    ("~^npm (install|test)$", "npm install", True),
    ("~^npm (install|test)$", "npm run dev", False),
    ("~delete", "please delete that file", True),
    ("~delete", "keep it", False),
], ids=["regex-hit", "regex-miss", "regex-contains-hit", "regex-contains-miss"])
def test_regex_match(pattern, target, expected):
    m = compile_matcher(pattern)
    assert isinstance(m, RegexMatcher)
    assert m.match(target) == expected


# ── Not ─────────────────────────────────────────────────

@pytest.mark.parametrize("pattern, target, expected", [
    ("!=foo", "foo", False),
    ("!=foo", "bar", True),
    ("!~^rm", "rm -rf .", False),
    ("!~^rm", "ls -lh", True),
    ("!git *", "git status", False),
    ("!git *", "npm install", True),
], ids=["not-exact-hit", "not-exact-miss", "not-regex-hit", "not-regex-miss",
        "not-glob-hit", "not-glob-miss"])
def test_not_match(pattern, target, expected):
    m = compile_matcher(pattern)
    assert isinstance(m, NotMatcher)
    assert m.match(target) == expected


# ── 编译失败 ───────────────────────────────────────────

def test_compile_invalid_regex():
    with pytest.raises(ValueError, match="invalid regex"):
        compile_matcher("~[invalid")


def test_compile_empty():
    with pytest.raises(ValueError, match="empty matcher pattern"):
        compile_matcher("")


# ── __str__ ────────────────────────────────────────────

def test_str_exact():
    assert str(compile_matcher("=foo")) == "=foo"


def test_str_regex():
    assert str(compile_matcher("~foo.*")) == "~foo.*"


def test_str_glob():
    assert str(compile_matcher("git *")) == "git *"


def test_str_not():
    assert str(compile_matcher("!~^rm")) == "!~^rm"


# ── 向后兼容：无前缀 = Glob ────────────────────────────

def test_no_prefix_is_glob():
    m = compile_matcher("Bash(git *)")
    assert isinstance(m, GlobMatcher)
    assert m.match("Bash(git status)") is True
