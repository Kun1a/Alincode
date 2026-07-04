"""AgentNameRegistry 单测(T7)。覆盖 F35-F38。"""

from __future__ import annotations

from Alincode.team.registry import AgentNameRegistry


class TestAgentNameRegistry:
    def test_register_resolve(self):
        reg = AgentNameRegistry()
        reg.register("alice", "agent-123")
        assert reg.resolve("alice") == "agent-123"
        assert reg.name_of("agent-123") == "alice"

    def test_resolve_by_agent_id(self):
        reg = AgentNameRegistry()
        reg.register("alice", "agent-123")
        # 输入 agent_id 直查,返回自身
        assert reg.resolve("agent-123") == "agent-123"

    def test_resolve_unknown(self):
        reg = AgentNameRegistry()
        assert reg.resolve("unknown") is None

    def test_overwrite_same_name(self):
        """F38:后注册覆盖前注册。"""
        reg = AgentNameRegistry()
        reg.register("alice", "agent-123")
        reg.register("alice", "agent-456")
        assert reg.resolve("alice") == "agent-456"
        assert reg.name_of("agent-123") is None  # 旧 agent_id 被清理
        assert reg.name_of("agent-456") == "alice"

    def test_overwrite_same_agent_id(self):
        """不同 name 指向同一 agent_id,旧 name 被清理。"""
        reg = AgentNameRegistry()
        reg.register("alice", "agent-123")
        reg.register("bob", "agent-123")
        assert reg.resolve("alice") is None  # 旧 name 被清理
        assert reg.resolve("bob") == "agent-123"
        assert reg.name_of("agent-123") == "bob"

    def test_unregister(self):
        reg = AgentNameRegistry()
        reg.register("alice", "agent-123")
        reg.unregister("alice")
        assert reg.resolve("alice") is None
        assert reg.name_of("agent-123") is None

    def test_unregister_by_agent_id(self):
        reg = AgentNameRegistry()
        reg.register("alice", "agent-123")
        reg.unregister_by_agent_id("agent-123")
        assert reg.resolve("alice") is None
        assert reg.name_of("agent-123") is None

    def test_list(self):
        reg = AgentNameRegistry()
        reg.register("alice", "agent-1")
        reg.register("bob", "agent-2")
        d = reg.list_()
        assert d == {"alice": "agent-1", "bob": "agent-2"}
