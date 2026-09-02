# tests/web/test_server.py
"""REST + WebSocket 集成测试（FastAPI TestClient，不起真实端口）。"""

import json
import mimetypes

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from Alincode.bootstrap import AppContext
from Alincode.config import AppConfig, ProviderConfig
from Alincode.conversation import StreamEvent
from Alincode.tools import Registry
from Alincode.profile.store import ProfileStore
from Alincode.profile.service import ProfileService
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


def test_frontend_module_is_served_as_javascript_when_system_mime_is_missing(tmp_path, monkeypatch):
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text('<script type="module" src="/app.js"></script>', encoding="utf-8")
    (frontend / "app.js").write_text("console.log('ready')", encoding="utf-8")
    monkeypatch.setattr("Alincode.web.server.webui_dist", lambda: frontend)
    monkeypatch.setitem(mimetypes.types_map, ".js", "text/plain")

    client = TestClient(create_app(_ctx(tmp_path, FakeProvider([[]]))))

    assert client.get("/app.js").headers["content-type"].startswith("application/javascript")


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


def test_desktop_ws_requires_an_unlocked_profile_and_uses_private_history(tmp_path):
    store = ProfileStore(tmp_path / "profiles")
    client = TestClient(create_app(
        _ctx(tmp_path, FakeProvider([[]])), auth=LocalAuth("launch"), profile_store=store,
    ))
    assert client.post("/api/auth/exchange", json={"token": "launch"}).status_code == 204

    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("/ws"):
            pass
    assert error.value.code == 1008

    profile = client.post("/api/profiles", json={"name": "Alin", "password": "secret"}).json()
    profile_service = ProfileService(store)
    profile_service.save_provider(
        profile["id"], protocol="openai", model="profile-model",
        base_url="https://api.example.test", api_key="sk-profile-key",
    )
    workspace = tmp_path / "profile-workspace"
    workspace.mkdir()
    profile_service.set_workspace(profile["id"], workspace)
    with client.websocket_connect("/ws") as conn:
        info = conn.receive_json()
        assert info["type"] == "session.info"
        assert info["model"] == "profile-model"
        assert info["workspace"] == str(workspace.resolve())

    assert not any(store.sessions_dir(profile["id"]).iterdir())


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

    saved_provider = client.put("/api/profile/provider", json={
        "protocol": "anthropic", "model": "claude-test", "base_url": "https://api.example.com",
        "api_key": "sk-secret1234",
    })
    assert saved_provider.status_code == 200
    assert saved_provider.json() == {
        "protocol": "anthropic", "model": "claude-test", "base_url": "https://api.example.com",
        "api_key": "sk-••••1234",
    }
    assert "secret" not in client.get("/api/profile/provider").text
    provider_without_new_key = client.put("/api/profile/provider", json={
        "protocol": "anthropic", "model": "claude-renamed", "base_url": "https://api.example.com",
        "api_key": "",
    })
    assert provider_without_new_key.status_code == 200
    assert provider_without_new_key.json()["api_key"] == "sk-••••1234"
    assert ProfileService(store).provider_key(profile["id"]) == "sk-secret1234"

    assert client.put("/api/profile/budget", json={"budget": 1000}).json()["budget"] == 1000

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    missing_workspace = tmp_path / "missing-workspace"
    file_workspace = tmp_path / "not-a-directory.txt"
    file_workspace.write_text("not a directory", encoding="utf-8")
    assert client.put("/api/profile/workspace", json={"path": str(missing_workspace)}).status_code == 400
    assert client.put("/api/profile/workspace", json={"path": str(file_workspace)}).status_code == 400
    assert client.put("/api/profile/workspace", json={"path": str(workspace)}).json() == {
        "path": str(workspace.resolve()),
    }
    assert client.get("/api/profile/workspace").json() == {"path": str(workspace.resolve())}


def test_profile_workspaces_can_keep_multiple_projects_and_switch_default(tmp_path):
    store = ProfileStore(tmp_path / "profiles")
    client = TestClient(create_app(
        _ctx(tmp_path, FakeProvider([[]])), auth=LocalAuth("launch"), profile_store=store,
    ))
    assert client.post("/api/auth/exchange", json={"token": "launch"}).status_code == 204
    client.post("/api/profiles", json={"name": "Alin", "password": "secret"})
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()

    saved = client.put("/api/profile/workspaces", json={
        "paths": [str(project_a), str(project_b)], "active_path": str(project_b),
    })

    assert saved.status_code == 200
    assert saved.json() == {
        "paths": [str(project_a.resolve()), str(project_b.resolve())],
        "active_path": str(project_b.resolve()),
    }
    assert client.get("/api/profile/workspaces").json() == saved.json()


def test_profiles_keep_provider_budget_and_history_isolated(tmp_path):
    store = ProfileStore(tmp_path / "profiles")
    profile_service = ProfileService(store)
    client = TestClient(create_app(
        _ctx(tmp_path, FakeProvider([[]])), auth=LocalAuth("launch"), profile_store=store,
    ))
    assert client.post("/api/auth/exchange", json={"token": "launch"}).status_code == 204

    profile_a = client.post("/api/profiles", json={"name": "A", "password": "a-pass"}).json()
    assert client.put("/api/profile/provider", json={
        "protocol": "openai", "model": "model-a", "base_url": "https://a.example", "api_key": "sk-key-a",
    }).status_code == 200
    assert client.put("/api/profile/budget", json={"budget": 11}).status_code == 200
    profile_service.record_usage(profile_a["id"], input_tokens=1, output_tokens=2)
    a_session_id = "20260901-000000-aa"
    a_history = store.sessions_dir(profile_a["id"]) / a_session_id
    a_history.mkdir()
    (a_history / "conversation.jsonl").write_text('{"role":"user","content":"A","ts":1}\n', encoding="utf-8")

    assert client.post("/api/profile/lock").status_code == 204
    profile_b = client.post("/api/profiles", json={"name": "B", "password": "b-pass"}).json()
    assert client.put("/api/profile/provider", json={
        "protocol": "openai", "model": "model-b", "base_url": "https://b.example", "api_key": "sk-key-b",
    }).status_code == 200
    assert client.put("/api/profile/budget", json={"budget": 22}).status_code == 200
    profile_service.record_usage(profile_b["id"], input_tokens=3, output_tokens=4)
    b_session_id = "20260901-000000-bb"
    b_history = store.sessions_dir(profile_b["id"]) / b_session_id
    b_history.mkdir()
    (b_history / "conversation.jsonl").write_text('{"role":"user","content":"B","ts":1}\n', encoding="utf-8")

    assert client.get("/api/profile/provider").json()["model"] == "model-b"
    assert client.get("/api/profile/budget").json()["budget"] == 22
    assert client.get("/api/profile/budget").json()["used_tokens"] == 7
    assert [item["id"] for item in client.get("/api/sessions").json()] == [b_session_id]

    assert client.post("/api/profile/lock").status_code == 204
    assert client.post(f"/api/profiles/{profile_a['id']}/unlock", json={"password": "a-pass"}).status_code == 200
    assert client.get("/api/profile/provider").json()["model"] == "model-a"
    assert client.get("/api/profile/budget").json()["budget"] == 11
    assert client.get("/api/profile/budget").json()["used_tokens"] == 3
    assert [item["id"] for item in client.get("/api/sessions").json()] == [a_session_id]
