"""为队员构造独立工具集（per-team 实例化，不注册到全局 registry）。

build_teammate_tools: 从父 registry 取基础工具(read_file/bash等)，
新建 Team 工具实例(TaskCreate/TaskGet/TaskList/TaskUpdate/SendMessage)绑定 team_name。
返回一个新的 Registry，供队员 Agent 使用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from Alincode.tools import Registry

if TYPE_CHECKING:
    from Alincode.team.manager import Manager


# 队员不应拥有的工具（Lead 专属 / 全局管理工具）
_LEAD_ONLY_TOOLS = {"Agent", "TeamCreate", "TeamDelete"}


def build_teammate_tools(
    parent_registry: Registry,
    team_manager: "Manager",
    team_name: str,
    agent_id: str = "",
    agent_name: str = "",
    backend_type: str = "in-process",
    definition: object | None = None,
) -> Registry:
    """为队员构造独立工具集。

    从 parent_registry 取基础工具(read_file/bash/grep/glob/edit_file/write_file/
    load_skill/mcp__*等)，排除 Lead 专属工具(Agent/TeamCreate/TeamDelete)。
    新建 5 个 Team 工具实例(TaskCreate/TaskGet/TaskList/TaskUpdate/SendMessage)
    绑定 team_name，注册到新 Registry。
    不注册到全局 registry，返回一个新的 Registry。
    """
    from Alincode.tools.task_create import TaskCreateTool
    from Alincode.tools.task_get import TaskGetTool
    from Alincode.tools.task_list import TaskListTool
    from Alincode.tools.task_update import TaskUpdateTool
    from Alincode.tools.send_message import SendMessageTool

    registry = Registry()

    # 1. 从父 registry 复制基础工具（排除 Lead 专属）
    for tool_name, tool in parent_registry.tools():
        if tool_name in _LEAD_ONLY_TOOLS:
            continue
        registry.register(tool)

    # 2. 新建 Team 工具实例（绑 team_name）
    registry.register(TaskCreateTool(team_manager, team_name))
    registry.register(TaskGetTool(team_manager, team_name))
    registry.register(TaskListTool(team_manager, team_name))
    registry.register(TaskUpdateTool(team_manager, team_name))
    registry.register(SendMessageTool(team_manager, team_name))

    return registry
