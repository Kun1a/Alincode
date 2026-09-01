"""桌面本机启动令牌与 Profile 会话测试。"""

import pytest

from Alincode.web.auth import LocalAuth


def test_launch_token_exchanges_once_for_local_session():
    auth = LocalAuth("launch-token")

    session_id = auth.exchange_launch_token("launch-token")

    assert auth.exchange_launch_token("launch-token") is None
    assert auth.profile_for(session_id) is None
    assert auth.unlock(session_id, "profile-a") is True
    assert auth.profile_for(session_id) == "profile-a"


def test_invalid_or_unknown_session_is_rejected():
    auth = LocalAuth("launch-token")

    assert auth.exchange_launch_token("wrong") is None
    assert auth.unlock("unknown", "profile-a") is False
    assert auth.profile_for("unknown") is None
