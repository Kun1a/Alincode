"""MCP 工具适配单测：adapt_tool / execute / 名称校验 / 非文本 block。"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from Alincode.mcp.tool import McpTool, adapt_tool, _is_text_content


# ── mock helpers ──────────────────────────────────────

@dataclasses.dataclass
class _FakeTool:
    """模拟 MCP SDK 返回的远端工具对象。"""
    name: str = "search"
    description: str = "搜索文档"
    inputSchema: dict | None = None
    annotations: object | None = None


class _FakeSession:
    """模拟 MCP ClientSession，记录调用。"""
    def __init__(self) -> None:
        self.results: list[object] = []

    async def call_tool(self, name: str, arguments: dict | None) -> object:
        self.results.append((name, arguments))
        return _FakeResult(content=[_FakeTextBlock("ok")], isError=False)


@dataclasses.dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclasses.dataclass
class _FakeImageBlock:
    type: str = "image"
    data: str = "base64..."


@dataclasses.dataclass
class _FakeResult:
    content: list
    isError: bool = False


class _SlowSession:
    """模拟慢速 session。"""
    async def call_tool(self, name: str, arguments: dict | None) -> object:
        await asyncio.sleep(10)
        return _FakeResult(content=[_FakeTextBlock("too late")], isError=False)


class _ErrorSession:
    """模拟报错 session。"""
    async def call_tool(self, name: str, arguments: dict | None) -> object:
        raise RuntimeError("connection lost")


# ── adapt_tool ────────────────────────────────────────

def test_adapt_tool_normal():
    """正常远端工具 → McpTool，字段完整。"""
    session = _FakeSession()
    ft = _FakeTool(
        name="search",
        description="搜索文档",
        inputSchema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    tool = adapt_tool("my_server", ft, session)
    assert tool is not None
    assert tool.name() == "mcp__my_server__search"
    assert tool.server_name == "my_server"
    assert "搜索文档" in tool.description()
    assert tool.parameters()["type"] == "object"
    assert tool.read_only is False


def test_adapt_tool_missing_description():
    """无 description 时生成默认描述。"""
    session = _FakeSession()
    ft = _FakeTool(name="do", description="")
    tool = adapt_tool("srv", ft, session)
    assert tool is not None
    assert "来自 MCP server srv" in tool.description()


def test_adapt_tool_read_only_hint():
    """readOnlyHint=True → read_only=True。"""
    session = _FakeSession()
    ann = MagicMock()
    ann.readOnlyHint = True
    ft = _FakeTool(name="list", description="list items", annotations=ann)
    tool = adapt_tool("srv", ft, session)
    assert tool is not None
    assert tool.read_only is True


def test_adapt_tool_no_input_schema():
    """无 inputSchema → 默认空 object schema。"""
    session = _FakeSession()
    ft = _FakeTool(name="ping", description="ping", inputSchema=None)
    tool = adapt_tool("srv", ft, session)
    assert tool is not None
    assert tool.parameters() == {"type": "object"}


def test_adapt_tool_illegal_name():
    """非法工具名（含特殊字符）→ 返回 None。"""
    session = _FakeSession()
    ft = _FakeTool(name="bad name!", description="坏人")
    tool = adapt_tool("srv", ft, session)
    assert tool is None


# ── execute ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_ok():
    """正常调用返回 content。"""
    session = _FakeSession()
    tool = McpTool(
        full_name="mcp__test__search",
        remote_name="search",
        description="搜索",
        parameters={"type": "object"},
        read_only=True,
        caller=session,
        server_name="test",
    )
    r = await tool.execute(json.dumps({"query": "hello"}))
    assert not r.is_error
    assert r.content == "ok"
    assert session.results == [("search", {"query": "hello"})]


@pytest.mark.asyncio
async def test_execute_empty_args():
    """无参数或空字符串 → args=None。"""
    session = _FakeSession()
    tool = McpTool(
        full_name="mcp__test__search",
        remote_name="search",
        description="搜索",
        parameters={"type": "object"},
        read_only=True,
        caller=session,
        server_name="test",
    )
    r = await tool.execute("")
    assert not r.is_error
    assert session.results[0][1] is None


@pytest.mark.asyncio
async def test_execute_invalid_json():
    """非法 JSON → is_error。"""
    tool = McpTool(
        full_name="mcp__test__f",
        remote_name="f",
        description="desc",
        parameters={"type": "object"},
        read_only=True,
        caller=_FakeSession(),
        server_name="test",
    )
    r = await tool.execute("not json")
    assert r.is_error
    assert "JSON 解析失败" in r.content


@pytest.mark.asyncio
async def test_execute_non_dict_json():
    """非对象 JSON（数组/字符串）→ is_error。"""
    tool = McpTool(
        full_name="mcp__test__f",
        remote_name="f",
        description="desc",
        parameters={"type": "object"},
        read_only=True,
        caller=_FakeSession(),
        server_name="test",
    )
    r = await tool.execute("[1, 2, 3]")
    assert r.is_error
    assert "必须" in r.content


@pytest.mark.asyncio
async def test_execute_timeout(monkeypatch):
    """超时 → is_error。"""
    monkeypatch.setattr("Alincode.mcp.tool.execute_timeout", 0.5)
    tool = McpTool(
        full_name="mcp__test__slow",
        remote_name="slow",
        description="慢",
        parameters={"type": "object"},
        read_only=True,
        caller=_SlowSession(),
        server_name="test",
    )
    r = await tool.execute("{}")
    assert r.is_error
    assert "超时" in r.content


@pytest.mark.asyncio
async def test_execute_session_error():
    """session 报错 → is_error。"""
    tool = McpTool(
        full_name="mcp__test__err",
        remote_name="err",
        description="报错",
        parameters={"type": "object"},
        read_only=True,
        caller=_ErrorSession(),
        server_name="test",
    )
    r = await tool.execute("{}")
    assert r.is_error
    assert "失败" in r.content


@pytest.mark.asyncio
async def test_execute_is_error_from_server():
    """远端返回 isError=True → Result.is_error=True。"""
    session = _FakeSession()
    session.results = []  # 清掉默认
    session.call_tool = AsyncMock(return_value=_FakeResult(
        content=[_FakeTextBlock("server error")], isError=True
    ))
    tool = McpTool(
        full_name="mcp__test__f",
        remote_name="f",
        description="desc",
        parameters={"type": "object"},
        read_only=True,
        caller=session,
        server_name="test",
    )
    r = await tool.execute("{}")
    assert r.is_error
    assert "server error" in r.content


# ── _is_text_content ──────────────────────────────────

def test_is_text_content_true():
    assert _is_text_content(_FakeTextBlock("hello"))


def test_is_text_content_false():
    assert not _is_text_content(_FakeImageBlock())


def test_is_text_content_no_type():
    block = MagicMock()
    block.text = "x"
    del block.type
    assert not _is_text_content(block)


# ── 非文本 block 警告 ─────────────────────────────────

@pytest.mark.asyncio
async def test_execute_non_text_block_dropped():
    """非文本 block 被丢弃，文本 block 合并。"""
    session = _FakeSession()
    session.call_tool = AsyncMock(return_value=_FakeResult(
        content=[
            _FakeTextBlock("part1"),
            _FakeImageBlock(),
            _FakeTextBlock("part2"),
        ],
        isError=False,
    ))
    import Alincode.mcp.tool as mod
    mod._non_text_warned.clear()
    tool = McpTool(
        full_name="mcp__test__multi",
        remote_name="multi",
        description="多种 block",
        parameters={"type": "object"},
        read_only=True,
        caller=session,
        server_name="test",
    )
    r = await tool.execute("{}")
    assert not r.is_error
    assert r.content == "part1\npart2"
