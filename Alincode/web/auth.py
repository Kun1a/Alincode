"""桌面本机启动令牌和已解锁 Profile 会话。"""

from __future__ import annotations

import secrets


class LocalAuth:
    """只在内存中保存桌面窗口的本机认证状态。"""

    def __init__(self, launch_token: str) -> None:
        self._launch_token = launch_token
        self._sessions: dict[str, str | None] = {}

    def exchange_launch_token(self, token: str) -> str | None:
        """一次性启动令牌换取浏览器会话标识。"""
        if self._launch_token is None or not secrets.compare_digest(token, self._launch_token):
            return None
        self._launch_token = None
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = None
        return session_id

    def unlock(self, session_id: str, profile_id: str) -> bool:
        """把有效本机会话绑定到已解锁的 Profile。"""
        if session_id not in self._sessions:
            return False
        self._sessions[session_id] = profile_id
        return True

    def profile_for(self, session_id: str) -> str | None:
        """返回会话已解锁的 Profile；无效或锁定状态均为 None。"""
        return self._sessions.get(session_id)

    def lock(self, session_id: str) -> bool:
        """锁定 Profile，但保留本机浏览器会话。"""
        if session_id not in self._sessions:
            return False
        self._sessions[session_id] = None
        return True
