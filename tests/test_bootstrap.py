# tests/test_bootstrap.py
"""bootstrap 共享装配工厂冒烟测试。"""

import os
import pytest

from Alincode.bootstrap import build_context, resolve_config_path
from Alincode.config import ProviderConfig


@pytest.mark.asyncio
async def test_build_context_smoke(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "providers:\n"
        "  - name: fake\n"
        "    protocol: anthropic\n"
        "    model: test-model\n"
        "    base_url: http://localhost:9\n"
        "    api_key: sk-test\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / ".Alincode", exist_ok=True)

    ctx = await build_context(str(cfg))

    assert ctx.workspace == str(tmp_path.resolve())
    assert ctx.provider_cfg.model == "test-model"
    assert ctx.registry is not None
    assert ctx.engine is not None
    assert ctx.agent_tool is not None
    # read_file 是默认注册表成员
    names = [d.name for d in ctx.registry.definitions()]
    assert "read_file" in names
    # load_skill 已注册（共享 registry，供 core_session 重绑 active_skills）
    assert "load_skill" in names


def test_resolve_config_path_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        resolve_config_path(None)


@pytest.mark.asyncio
async def test_build_context_accepts_desktop_workspace_and_provider_override(tmp_path):
    config_dir = tmp_path / "config"
    workspace = tmp_path / "workspace"
    config_dir.mkdir()
    workspace.mkdir()
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        "providers:\n"
        "  - name: file\n"
        "    protocol: anthropic\n"
        "    model: file-model\n"
        "    base_url: http://localhost:9\n"
        "    api_key: file-key\n",
        encoding="utf-8",
    )
    override = ProviderConfig(
        name="desktop", protocol="openai", model="desktop-model",
        base_url="https://api.example.test", api_key="desktop-key",
    )

    ctx = await build_context(
        str(config_path), workspace=str(workspace), provider_override=override,
    )

    assert ctx.workspace == str(workspace.resolve())
    assert ctx.provider_cfg is override
