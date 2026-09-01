# tests/web/test_server.py
"""REST + WebSocket 集成测试（FastAPI TestClient，不起真实端口）。"""

import json

from fastapi.testclient import TestClient

from Alincode.bootstrap import AppContext
from Alincode.config import AppConfig, ProviderConfig
from Alincode.conversation import StreamEvent
from Alincode.tools import Registry
from Alincode.profile.store import ProfileStore
from Alincode.web.auth import LocalAuth
from Alincode.web.server import create_app

from tests.test_agent import FakeProvider


def _ctx(tmp_path, provider) -> AppContext:
    from Alincode.permission.engine import PermissionEngine
    return AppContext(
        app_cfg=AppConfig(),
        provider_cfg=ProviderConfig(name="fake", protocol="anthropic",
                                    model="m", base_url="", api_key=""),
        provider=provider, registry=Registry(), engine=PermissionEngine(),
        instruction_text="", memory_text="", memory_manager=None,
        workspace=str(tmp_path), catalog=None, hook_engine=None,
        subagent_catalog=None, task_mgr=None, wt_mgr=None, team_mgr=None,
        agent_tool=None, team_commands=[], mcp_mgr=None,
    )


def test_health_and_sessions(tmp_path):
    # 造一个历史会话目录
    sdir = tmp_path / ".Alincode" / "sessions" / "20260815-000000-ab"
    sdir.mkdir(parents=True)
    (sdir / "conversation.jsonl").write_text(
        json.dumps({"role": "user", "content": "旧话题", "ts": 1}) + "\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(_ctx(tmp_path, FakeProvider([[]]))))
    assert client.get("/api/health").json() == {"ok": True}
    sessions = client.get("/api/sessions").json()
    assert sessions and sessions[0]["id"] == "20260815-000000-ab"
    blocks = client.get("/api/sessions/20260815-000000-ab/messages").json()
    assert blocks[0] == {"kind": "user", "content": "旧话题"}


def test_ws_full_turn(tmp_path):
    provider = FakeProvider([[StreamEvent(text="嗨"), StreamEvent(done=True)]])
    client = TestClient(create_app(_ctx(tmp_path, provider)))
    with client.websocket_connect("/ws") as conn:
        info = conn.receive_json()
        assert info["type"] == "session.info"
        conn.send_json({"type": "chat.send", "text": "在吗"})
        got = []
        for _ in range(20):
            m = conn.receive_json()
            got.append(m["type"])
            if m["type"] == "turn.done":
                break
        assert "text.delta" in got


def test_desktop_profile_api_requires_a_one_time_launch_token(tmp_path):
    store = ProfileStore(tmp_path / "profiles")
    auth = LocalAuth("launch-token")
    client = TestClient(create_app(
        _ctx(tmp_path, FakeProvider([[]])), auth=auth, profile_store=store,
    ))

    assert client.get("/api/profiles").status_code == 401
    assert client.post("/api/auth/exchange", json={"token": "wrong"}).status_code == 401

    assert client.post("/api/auth/exchange", json={"token": "launch-token"}).status_code == 204
    created = client.post("/api/profiles", json={"name": "Alin", "password": "secret"})
    assert created.status_code == 201
    profile = created.json()
    assert profile["name"] == "Alin"
    assert client.get("/api/profile").json() == profile

    history_dir = store.sessions_dir(profile["id"]) / "20260901-000000-ab"
    history_dir.mkdir()
    (history_dir / "conversation.jsonl").write_text(
        json.dumps({"role": "user", "content": "私有历史", "ts": 1}) + "\n",
        encoding="utf-8",
    )
    assert client.get("/api/sessions").json()[0]["id"] == "20260901-000000-ab"

    assert client.post("/api/profile/lock").status_code == 204
    assert client.get("/api/profile").status_code == 403
    assert client.get("/api/sessions").status_code == 403
    assert client.post(
        f"/api/profiles/{profile['id']}/unlock", json={"password": "secret"},
    ).json() == profile

    assert client.get("/api/profiles").json() == [profile]
    assert client.post("/api/auth/exchange", json={"token": "launch-token"}).status_code == 401
