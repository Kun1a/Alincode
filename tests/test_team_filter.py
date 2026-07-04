"""工具过滤 + build_teammate_tools 单测。

原 TEAMMATE_EXTRA_TOOLS / teammate 分支已移除（Team 工具由 build_teammate_tools
per-team 实例化，不注册到全局 registry，不需要 filter 层面控制）。
本测试覆盖简化后的 filter 逻辑 + build_teammate_tools 构造独立工具集。
"""

from __future__ import annotations

from Alincode.tool.filter import (
    ALL_AGENT_DISALLOWED_TOOLS,
    FilterParams,
    apply_agent_tool_filter,
)
from Alincode.tools import new_default_registry
from Alincode.tools.teammate_tools import build_teammate_tools


ALL_TOOLS = [
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "bash",
    "Agent",
    "TeamCreate",
    "TeamDelete",
    "load_skill",
]


class TestAgentToolFilter:
    """简化后的 filter 逻辑测试。"""

    def test_agent_tool_disallowed(self):
        """普通子 Agent 看不到 Agent 工具。"""
        result = apply_agent_tool_filter(FilterParams(all_tools=ALL_TOOLS))
        assert "Agent" not in result

    def test_basic_tools_preserved(self):
        """基本工具保留。"""
        result = apply_agent_tool_filter(FilterParams(all_tools=ALL_TOOLS))
        assert "read_file" in result
        assert "bash" in result
        assert "write_file" in result

    def test_background_whitelist(self):
        """后台 Agent 只能用白名单工具。"""
        result = apply_agent_tool_filter(
            FilterParams(all_tools=ALL_TOOLS, background=True)
        )
        assert "read_file" in result
        assert "bash" in result
        # Agent 不在白名单
        assert "Agent" not in result
        # TeamCreate 不在白名单
        assert "TeamCreate" not in result

    def test_disallowed_tools(self):
        """黑名单排除。"""
        result = apply_agent_tool_filter(
            FilterParams(all_tools=ALL_TOOLS, disallowed=["bash"])
        )
        assert "bash" not in result
        assert "read_file" in result

    def test_allowed_tools(self):
        """白名单收窄。"""
        result = apply_agent_tool_filter(
            FilterParams(all_tools=ALL_TOOLS, allowed=["read_file", "bash"])
        )
        assert "read_file" in result
        assert "bash" in result
        assert "write_file" not in result

    def test_all_agent_disallowed_constant(self):
        """ALL_AGENT_DISALLOWED_TOOLS 含 Agent。"""
        assert "Agent" in ALL_AGENT_DISALLOWED_TOOLS


class TestBuildTeammateTools:
    """build_teammate_tools 构造独立工具集测试。"""

    def test_excludes_lead_only_tools(self):
        """队员工具集不含 Agent / TeamCreate / TeamDelete。"""
        parent = new_default_registry()
        # 模拟注册 Agent / TeamCreate / TeamDelete

        class FakeAgentTool:
            def name(self):
                return "Agent"

            def description(self):
                return ""

            def parameters(self):
                return {}

            @property
            def read_only(self):
                return False

            async def execute(self, args):
                pass

        class FakeTeamCreateTool:
            def name(self):
                return "TeamCreate"

            def description(self):
                return ""

            def parameters(self):
                return {}

            @property
            def read_only(self):
                return False

            async def execute(self, args):
                pass

        class FakeTeamDeleteTool:
            def name(self):
                return "TeamDelete"

            def description(self):
                return ""

            def parameters(self):
                return {}

            @property
            def read_only(self):
                return False

            async def execute(self, args):
                pass

        parent.register(FakeAgentTool())
        parent.register(FakeTeamCreateTool())
        parent.register(FakeTeamDeleteTool())

        # 构造 mock team_manager
        class FakeTeamManager:
            pass

        teammate_reg = build_teammate_tools(
            parent_registry=parent,
            team_manager=FakeTeamManager(),
            team_name="demo",
        )
        names = [d.name for d in teammate_reg.definitions()]
        assert "Agent" not in names
        assert "TeamCreate" not in names
        assert "TeamDelete" not in names

    def test_includes_team_tools(self):
        """队员工具集含 5 个 Team 工具（无 Team 前缀）。"""
        parent = new_default_registry()

        class FakeTeamManager:
            pass

        teammate_reg = build_teammate_tools(
            parent_registry=parent,
            team_manager=FakeTeamManager(),
            team_name="demo",
        )
        names = [d.name for d in teammate_reg.definitions()]
        assert "TaskCreate" in names
        assert "TaskGet" in names
        assert "TaskList" in names
        assert "TaskUpdate" in names
        assert "SendMessage" in names

    def test_includes_base_tools(self):
        """队员工具集含基础工具。"""
        parent = new_default_registry()

        class FakeTeamManager:
            pass

        teammate_reg = build_teammate_tools(
            parent_registry=parent,
            team_manager=FakeTeamManager(),
            team_name="demo",
        )
        names = [d.name for d in teammate_reg.definitions()]
        assert "read_file" in names
        assert "write_file" in names
        assert "edit_file" in names
        assert "bash" in names
        assert "glob" in names
        assert "grep" in names

    def test_not_registered_to_parent(self):
        """Team 工具不注册到父 registry。"""
        parent = new_default_registry()
        original_count = len(parent.definitions())

        class FakeTeamManager:
            pass

        build_teammate_tools(
            parent_registry=parent,
            team_manager=FakeTeamManager(),
            team_name="demo",
        )
        # 父 registry 工具数不变
        assert len(parent.definitions()) == original_count

    def test_separate_registry(self):
        """每次构造返回独立的 Registry。"""
        parent = new_default_registry()

        class FakeTeamManager:
            pass

        reg1 = build_teammate_tools(
            parent_registry=parent,
            team_manager=FakeTeamManager(),
            team_name="team1",
        )
        reg2 = build_teammate_tools(
            parent_registry=parent,
            team_manager=FakeTeamManager(),
            team_name="team2",
        )
        assert reg1 is not reg2
