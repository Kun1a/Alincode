"""MCP 配置单测——两层合并 / 变量展开 / 字段校验 / 降级（AC1-AC3）。"""

import os

import yaml

from Alincode.mcp.config import (
    Config,
    load_config,
    _expand_vars,
    _validate_server,
    _RawServer,
)


def test_expand_vars_defined():
    os.environ["TEST_MCP_VAR"] = "hello"
    result, undef = _expand_vars("prefix_${TEST_MCP_VAR}_suffix")
    assert result == "prefix_hello_suffix"
    assert undef == []


def test_expand_vars_undefined():
    result, undef = _expand_vars("${UNDEFINED_VAR_XYZ}")
    assert result == ""
    assert "UNDEFINED_VAR_XYZ" in undef


def test_expand_vars_no_var():
    result, undef = _expand_vars("plain text")
    assert result == "plain text"
    assert undef == []


def test_validate_stdio_ok():
    srv = _RawServer(type="stdio", command="node", args=["server.js"])
    result = _validate_server("test", srv)
    assert result is not None
    assert result.type == "stdio"
    assert result.command == "node"


def test_validate_stdio_missing_command():
    srv = _RawServer(type="stdio", command="")
    result = _validate_server("test", srv)
    assert result is None


def test_validate_http_ok():
    srv = _RawServer(type="http", url="https://example.com/mcp")
    result = _validate_server("test", srv)
    assert result is not None


def test_validate_http_missing_url():
    srv = _RawServer(type="http", url="")
    result = _validate_server("test", srv)
    assert result is None


def test_validate_unknown_type():
    srv = _RawServer(type="sse", command="echo")
    result = _validate_server("test", srv)
    assert result is None


def test_load_config_empty(tmp_path):
    """AC1: 无配置文件 → 空 Config。"""
    cfg = load_config(str(tmp_path))
    assert isinstance(cfg, Config)
    assert cfg.servers == {}


def test_load_config_project_only(tmp_path):
    """AC1: 仅项目级配置生效。"""
    (tmp_path / ".Alincode").mkdir(parents=True, exist_ok=True)
    project_file = tmp_path / ".Alincode" / "mcp.yaml"
    project_file.write_text(yaml.dump({
        "mcp_servers": {
            "demo": {"type": "stdio", "command": "echo", "args": ["hello"]}
        }
    }))

    # 需要 monkeypatch 用户级路径为不存在
    import Alincode.mcp.config as cfg_mod
    orig = cfg_mod.Path.home
    cfg_mod.Path.home = lambda: tmp_path / "nonexistent_home"
    try:
        cfg = load_config(str(tmp_path))
        assert "demo" in cfg.servers
        assert cfg.servers["demo"].command == "echo"
    finally:
        cfg_mod.Path.home = orig


def test_load_config_file_exists_no_mcp_servers_key(tmp_path):
    """YAML 文件存在但缺少 mcp_servers 键 → 空 Config（不崩溃）。"""
    (tmp_path / ".Alincode").mkdir(parents=True, exist_ok=True)
    project_file = tmp_path / ".Alincode" / "mcp.yaml"
    project_file.write_text(yaml.dump({"other_key": "value"}))

    import Alincode.mcp.config as cfg_mod
    orig = cfg_mod.Path.home
    cfg_mod.Path.home = lambda: tmp_path / "nonexistent_home"
    try:
        cfg = load_config(str(tmp_path))
        assert isinstance(cfg, Config)
        assert cfg.servers == {}
    finally:
        cfg_mod.Path.home = orig
