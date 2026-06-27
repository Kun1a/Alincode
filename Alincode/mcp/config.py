"""MCP 配置加载：两层 YAML 合并、${VAR} 展开、字段校验（F1/F2/F3）。"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ── 类型 ──────────────────────────────────────────────

@dataclass
class ServerConfig:
    """单个 MCP server 的完整定义（已展开 ${VAR}、已校验）。"""
    type: str  # "stdio" | "http"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    """mcp_servers 在内存中的归一化形式（已合并）。"""
    servers: dict[str, ServerConfig] = field(default_factory=dict)


# ── 原始配置结构 ──────────────────────────────────────

@dataclass
class _RawServer:
    type: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


# ── 变量展开 ──────────────────────────────────────────

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_vars(s: str) -> tuple[str, list[str]]:
    """展开字符串中的 ${VAR}，返回 (结果, 未定义变量列表)。"""
    undefined: list[str] = []

    def _repl(m: re.Match) -> str:
        name = m.group(1)
        val = os.environ.get(name)
        if val is None:
            if name not in undefined:
                undefined.append(name)
            return ""
        return val

    return _VAR_RE.sub(_repl, s), undefined


def _apply_expansion(name: str, srv: _RawServer) -> None:
    """对 server 的 env/headers 值做 ${VAR} 展开（原地修改）。"""
    warned: set[str] = set()
    for d in (srv.env, srv.headers):
        for k, v in list(d.items()):
            expanded, undef = _expand_vars(v)
            d[k] = expanded
            for u in undef:
                if u not in warned:
                    warned.add(u)
                    print(
                        f"[mcp] warn: undefined env var ${{{u}}} "
                        f"referenced by server {name}",
                        file=sys.stderr,
                    )


# ── 文件加载 ──────────────────────────────────────────

def _load_file(path: Path) -> dict[str, _RawServer]:
    """加载一个 YAML 配置文件的 mcp_servers 段。文件不存在或格式非法返回空。"""
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[mcp] warn: skip config file {path}: {e}", file=sys.stderr)
        return {}
    servers_raw = data.get("mcp_servers")
    if not isinstance(servers_raw, dict):
        return {}
    result: dict[str, _RawServer] = {}
    for name, srv_data in servers_raw.items():
        if not isinstance(srv_data, dict):
            continue
        result[name] = _RawServer(
            type=str(srv_data.get("type", "")).strip(),
            command=str(srv_data.get("command", "")).strip(),
            args=_as_str_list(srv_data.get("args")),
            env=_as_str_map(srv_data.get("env")),
            url=str(srv_data.get("url", "")).strip(),
            headers=_as_str_map(srv_data.get("headers")),
        )
    return result


def _as_str_list(val) -> list[str]:
    if not isinstance(val, list):
        return []
    return [str(v) for v in val]


def _as_str_map(val) -> dict[str, str]:
    if not isinstance(val, dict):
        return {}
    return {str(k): str(v) for k, v in val.items()}


# ── 合并与校验 ────────────────────────────────────────

def _merge_servers(
    user: dict[str, _RawServer], project: dict[str, _RawServer],
) -> dict[str, _RawServer]:
    """两层合并：复制 user，project 同名完整覆盖。"""
    merged = dict(user)
    merged.update(project)
    return merged


def _validate_server(name: str, srv: _RawServer) -> ServerConfig | None:
    """校验并转换为 ServerConfig。非法返回 None + stderr 告警。"""
    t = srv.type
    if t not in ("stdio", "http"):
        reason = f"unknown or missing type '{t}'"
        print(f"[mcp] warn: skip server {name}: {reason}", file=sys.stderr)
        return None
    if t == "stdio" and not srv.command:
        print(f"[mcp] warn: skip server {name}: missing command for stdio", file=sys.stderr)
        return None
    if t == "http" and not srv.url:
        print(f"[mcp] warn: skip server {name}: missing url for http", file=sys.stderr)
        return None
    return ServerConfig(
        type=t,
        command=srv.command,
        args=srv.args,
        env=srv.env,
        url=srv.url,
        headers=srv.headers,
    )


# ── 公共入口 ──────────────────────────────────────────

def load_config(root: str) -> Config:
    """加载并合并两层 MCP 配置。永不抛异常（降级为空 Config）。"""
    user_path = Path.home() / ".alincode" / "config.yaml"
    project_path = Path(root) / ".Alincode" / "mcp.yaml"

    user_servers = _load_file(user_path)
    project_servers = _load_file(project_path)

    # 对两层分别展开变量
    for name, srv in user_servers.items():
        _apply_expansion(name, srv)
    for name, srv in project_servers.items():
        _apply_expansion(name, srv)

    merged = _merge_servers(user_servers, project_servers)

    result = Config()
    for name, srv in merged.items():
        sc = _validate_server(name, srv)
        if sc:
            result.servers[name] = sc
    return result
