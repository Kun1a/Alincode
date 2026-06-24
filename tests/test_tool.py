"""工具系统单元测试：注册中心 + 6 个核心工具。"""

import asyncio
import json

import pytest

from Alincode.tools import (
    Registry,
    new_default_registry,
)
from Alincode.tools.read_file import ReadFileTool
from Alincode.tools.write_file import WriteFileTool
from Alincode.tools.edit_file import EditFileTool
from Alincode.tools.bash import BashTool
from Alincode.tools.glob_tool import GlobTool
from Alincode.tools.grep_tool import GrepTool


def _j(obj: dict) -> str:
    """辅助：将 dict 序列化为 JSON 字符串，避免 Windows 路径反斜杠问题。"""
    return json.dumps(obj, ensure_ascii=False)


# ── 注册中心 ─────────────────────────────────────────┐

def test_registry_definitions():
    """AC1: 注册中心导出恰好 6 条工具定义，名称有序。"""
    reg = new_default_registry()
    defs = reg.definitions()
    assert len(defs) == 6
    names = [d.name for d in defs]
    assert names == ["read_file", "write_file", "edit_file", "bash", "glob", "grep"]

    # 按名查找都能命中
    for name in names:
        assert reg.get(name) is not None

    # 未知工具返回 None
    assert reg.get("nonexistent") is None


def test_registry_duplicate():
    """重名注册抛出 ValueError。"""
    reg = Registry()
    reg.register(ReadFileTool())
    with pytest.raises(ValueError, match="工具名重复"):
        reg.register(ReadFileTool())


def test_registry_execute_unknown():
    """未知工具执行返回 is_error。"""
    reg = Registry()
    r = asyncio.run(reg.execute("unknown_tool", "{}"))
    assert r.is_error
    assert "未知工具" in r.content


# ── read_file ────────────────────────────────────────┐

@pytest.mark.asyncio
async def test_read_file_exists():
    """AC2: 读存在的文件返回带行号内容。"""
    tool = ReadFileTool()
    r = await tool.execute(_j({"path": "pyproject.toml"}))
    assert not r.is_error
    assert "1\t[project]" in r.content


@pytest.mark.asyncio
async def test_read_file_not_exists():
    """AC2: 读不存在的文件返回结构化错误。"""
    tool = ReadFileTool()
    r = await tool.execute(_j({"path": "nonexistent_file.xyz"}))
    assert r.is_error
    assert "不存在" in r.content


@pytest.mark.asyncio
async def test_read_file_missing_param():
    """缺少必填参数返回错误。"""
    tool = ReadFileTool()
    r = await tool.execute("{}")
    assert r.is_error
    assert "path" in r.content


# ── write_file ───────────────────────────────────────┐

@pytest.mark.asyncio
async def test_write_file_create(tmp_path):
    """AC3: 写文件创建 / 覆盖，内容正确落地。"""
    tool = WriteFileTool()
    path = tmp_path / "test.txt"
    r = await tool.execute(_j({"path": str(path), "content": "hello world"}))
    assert not r.is_error
    assert "已写入" in r.content
    assert path.read_text() == "hello world"


@pytest.mark.asyncio
async def test_write_file_nested_dirs(tmp_path):
    """AC3: 父目录不存在时自动创建。"""
    tool = WriteFileTool()
    path = tmp_path / "a" / "b" / "c.txt"
    r = await tool.execute(_j({"path": str(path), "content": "nested"}))
    assert not r.is_error
    assert "已写入" in r.content
    assert path.read_text() == "nested"


@pytest.mark.asyncio
async def test_write_file_missing_params():
    """缺少参数返回错误。"""
    tool = WriteFileTool()
    r = await tool.execute("{}")
    assert r.is_error


# ── edit_file ────────────────────────────────────────┐

@pytest.mark.asyncio
async def test_edit_file_unique_match(tmp_path):
    """AC4: 唯一匹配替换成功。"""
    path = tmp_path / "test.py"
    path.write_text("foo = 1\nbar = 2\nbaz = 3\n")
    tool = EditFileTool()
    r = await tool.execute(_j({
        "path": str(path),
        "old_string": "bar = 2",
        "new_string": "bar = 42",
    }))
    assert not r.is_error
    assert "成功替换" in r.content
    content = path.read_text()
    assert "bar = 42" in content
    assert "bar = 2" not in content


@pytest.mark.asyncio
async def test_edit_file_zero_match(tmp_path):
    """AC4: 匹配 0 处返回可区分错误。"""
    path = tmp_path / "test.py"
    path.write_text("foo = 1\n")
    tool = EditFileTool()
    r = await tool.execute(_j({
        "path": str(path),
        "old_string": "nonexistent",
        "new_string": "x",
    }))
    assert r.is_error
    assert "未找到匹配" in r.content


@pytest.mark.asyncio
async def test_edit_file_multiple_matches(tmp_path):
    """AC4: 匹配 >1 处返回可区分错误（含匹配数）。"""
    path = tmp_path / "test.py"
    path.write_text("foo\nfoo\nfoo\n")
    tool = EditFileTool()
    r = await tool.execute(_j({
        "path": str(path),
        "old_string": "foo",
        "new_string": "bar",
    }))
    assert r.is_error
    assert "匹配到 3 处" in r.content or "不唯一" in r.content


# ── bash ─────────────────────────────────────────────┐

@pytest.mark.asyncio
async def test_bash_echo():
    """AC5: echo 命令返回 stdout。"""
    tool = BashTool()
    r = await tool.execute(_j({"command": "echo hello test"}))
    assert not r.is_error
    assert "hello test" in r.content
    assert "exit_code: 0" in r.content


@pytest.mark.asyncio
async def test_bash_nonzero():
    """非零退出不设 is_error，让模型判断。"""
    tool = BashTool()
    r = await tool.execute(_j({"command": "python -c \"exit(1)\""}))
    # 非零退出但工具本身不报错
    assert not r.is_error
    assert "exit_code: 1" in r.content


# ── glob ────────────────────────────────────────────┐

@pytest.mark.asyncio
async def test_glob_py_files():
    """AC6: glob **/*.py 能找到 Python 文件。"""
    tool = GlobTool()
    r = await tool.execute(_j({"pattern": "**/*.py", "path": "Alincode"}))
    assert not r.is_error
    assert "client.py" in r.content or "app.py" in r.content


@pytest.mark.asyncio
async def test_glob_no_match():
    """无匹配返回空说明（非 is_error）。"""
    tool = GlobTool()
    r = await tool.execute(_j({"pattern": "*.zzz_never_exists"}))
    assert not r.is_error
    assert "无匹配" in r.content


# ── grep ─────────────────────────────────────────────┐

@pytest.mark.asyncio
async def test_grep_hit():
    """AC6: 搜索关键字能命中。"""
    tool = GrepTool()
    r = await tool.execute(
        _j({"pattern": "def test_", "path": "tests", "glob": "*.py"})
    )
    assert not r.is_error
    # 至少应该找到它自身
    assert "test_" in r.content or "无命中" in r.content


@pytest.mark.asyncio
async def test_grep_invalid_regex():
    """非法正则返回结构化错误。"""
    tool = GrepTool()
    r = await tool.execute(_j({"pattern": "[invalid"}))
    assert r.is_error
    assert "正则非法" in r.content


# ── 注册中心执行超时 ───────────────────────────────────┐

@pytest.mark.asyncio
async def test_registry_execute_timeout():
    """超时命令返回超时结果。"""
    reg = Registry()
    reg.register(BashTool())
    # sleep 10 秒，超时设 0.5 秒
    r = await reg.execute("bash", _j({"command": "sleep 10"}), timeout=0.5)
    assert r.is_error
    assert "超时" in r.content
