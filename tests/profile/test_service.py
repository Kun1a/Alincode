"""Profile 密钥保护、配置摘要与预算行为测试。"""

import json
from pathlib import Path

import pytest

from Alincode.profile.service import ProfileService
from Alincode.profile import secrets
from Alincode.profile.store import ProfileStore


def test_provider_key_is_protected_and_summary_is_masked(tmp_path):
    store = ProfileStore(tmp_path)
    profile = store.create("Alin", "correct-password")
    service = ProfileService(store)

    service.save_provider(
        profile.id,
        protocol="openai",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key="sk-test-secret-9nF2",
    )

    assert service.provider_summary(profile.id) == {
        "protocol": "openai",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-••••9nF2",
    }
    assert service.provider_key(profile.id) == "sk-test-secret-9nF2"
    assert "sk-test-secret-9nF2" not in "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in tmp_path.rglob("*.json")
    )
    config = service.provider_config(profile.id)
    assert config.name == profile.id
    assert config.protocol == "openai"
    assert config.model == "deepseek-chat"
    assert config.base_url == "https://api.deepseek.com"
    assert config.api_key == "sk-test-secret-9nF2"


def test_usage_reaches_budget_and_blocks_new_turns(tmp_path):
    store = ProfileStore(tmp_path)
    profile = store.create("Alin", "correct-password")
    service = ProfileService(store)

    service.set_budget(profile.id, 100)
    service.record_usage(profile.id, input_tokens=40, output_tokens=60)

    assert service.budget_status(profile.id) == {
        "budget": 100,
        "input_tokens": 40,
        "output_tokens": 60,
        "used_tokens": 100,
        "blocked": True,
    }


def test_workspace_must_be_an_existing_directory(tmp_path):
    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Alin", "correct-password")
    service = ProfileService(store)
    workspace = tmp_path / "project"
    workspace.mkdir()

    service.set_workspace(profile.id, workspace)

    assert service.workspace(profile.id) == str(workspace.resolve())
    with pytest.raises(ValueError, match="项目目录不存在"):
        service.set_workspace(profile.id, tmp_path / "missing")


def test_profile_can_keep_multiple_workspaces_and_choose_an_active_one(tmp_path):
    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Alin", "correct-password")
    service = ProfileService(store)
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()

    saved = service.save_workspaces(profile.id, [project_a, project_b], active_path=project_b)

    assert saved == {
        "paths": [str(project_a.resolve()), str(project_b.resolve())],
        "active_path": str(project_b.resolve()),
    }
    assert service.workspace(profile.id) == str(project_b.resolve())


def test_profile_mcp_servers_are_saved_without_provider_configuration(tmp_path):
    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Alin", "correct-password")
    service = ProfileService(store)
    servers = {"filesystem": {"type": "stdio", "command": "npx", "args": ["-y", "server"]}}

    service.save_mcp_servers(profile.id, servers)

    assert service.mcp_servers(profile.id) == servers


def test_dpapi_refuses_non_windows_instead_of_storing_plaintext(monkeypatch):
    monkeypatch.setattr(secrets.os, "name", "posix")

    with pytest.raises(RuntimeError, match="仅支持 Windows"):
        secrets.protect("test-api-key")


def test_profile_service_survives_windows_atomic_replace_failure(tmp_path, monkeypatch):
    original_replace = Path.replace

    def fail_for_temporary_file(path: Path, target: Path):
        if path.suffix == ".tmp":
            raise OSError(17, "cross-device move", None, 17)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_for_temporary_file)
    store = ProfileStore(tmp_path / "profiles")
    profile = store.create("Alin", "correct-password")
    service = ProfileService(store)
    workspace = tmp_path / "project"
    workspace.mkdir()

    service.save_provider(
        profile.id, protocol="openai", model="deepseek-chat",
        base_url="https://api.deepseek.com", api_key="sk-test-secret",
    )
    service.set_budget(profile.id, 100)
    service.set_workspace(profile.id, workspace)

    assert service.provider_config(profile.id).model == "deepseek-chat"
    assert service.budget_status(profile.id)["budget"] == 100
    assert service.workspace(profile.id) == str(workspace.resolve())
