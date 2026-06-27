"""MCP 客户端：自动发现并注册外部 MCP Server 提供的工具。"""

from Alincode.mcp.config import Config, ServerConfig, load_config
from Alincode.mcp.manager import Manager, new_manager

__all__ = [
    "Config",
    "ServerConfig",
    "Manager",
    "load_config",
    "new_manager",
]
