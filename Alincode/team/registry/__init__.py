"""Agent 名称注册表(T7)。

对应 spec F35-F38。name ↔ agent_id 双向映射。
用 threading.Lock(同步,非 asyncio)——register/unregister 在 spawn 路径同步调用。
task.Manager 委托这套 registry,替换原 _by_name 的局部状态(F37)。
"""

from __future__ import annotations

import threading


class AgentNameRegistry:
    """Agent name ↔ agent_id 双向映射(F35)。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[str, str] = {}  # name → agent_id
        self._by_id: dict[str, str] = {}  # agent_id → name

    def register(self, name: str, agent_id: str) -> None:
        """注册 name → agent_id(F38:后注册覆盖前注册)。"""
        with self._lock:
            # 若 name 已存在,清理旧 agent_id 反向映射
            old_id = self._by_name.get(name)
            if old_id is not None and old_id != agent_id:
                self._by_id.pop(old_id, None)
            # 若 agent_id 已有其他 name,清理旧 name 正向映射
            old_name = self._by_id.get(agent_id)
            if old_name is not None and old_name != name:
                self._by_name.pop(old_name, None)
            self._by_name[name] = agent_id
            self._by_id[agent_id] = name

    def unregister(self, name: str) -> None:
        """按 name 注销。"""
        with self._lock:
            agent_id = self._by_name.pop(name, None)
            if agent_id is not None and self._by_id.get(agent_id) == name:
                del self._by_id[agent_id]

    def unregister_by_agent_id(self, agent_id: str) -> None:
        """按 agent_id 注销。"""
        with self._lock:
            name = self._by_id.pop(agent_id, None)
            if name is not None and self._by_name.get(name) == agent_id:
                del self._by_name[name]

    def resolve(self, name_or_id: str) -> str | None:
        """解析 name 或 agent_id → agent_id(F36)。

        先按 name 查,失败按 agent_id 直查(返回自身)。
        """
        with self._lock:
            # 先按 name 查
            aid = self._by_name.get(name_or_id)
            if aid is not None:
                return aid
            # 再按 agent_id 直查
            if name_or_id in self._by_id:
                return name_or_id
            return None

    def name_of(self, agent_id: str) -> str | None:
        """按 agent_id 反查 name。"""
        with self._lock:
            return self._by_id.get(agent_id)

    def list_(self) -> dict[str, str]:
        """返回 name → agent_id 的拷贝。"""
        with self._lock:
            return dict(self._by_name)
