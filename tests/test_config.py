"""Config 单测：context_window 字段 + effective_context_window（T25）。"""

from Alincode.config import ProviderConfig, effective_context_window


def test_effective_context_window_unconfigured():
    """anthropic + 不配置 → 200000。"""
    p = ProviderConfig(protocol="anthropic", model="m", base_url="u", api_key="k")
    assert effective_context_window(p) == 200000


def test_effective_context_window_zero():
    """openai + 配置 0 → 128000。"""
    p = ProviderConfig(protocol="openai", model="m", base_url="u", api_key="k", context_window=0)
    assert effective_context_window(p) == 128000


def test_effective_context_window_positive():
    """anthropic + 配置 80000 → 80000。"""
    p = ProviderConfig(protocol="anthropic", model="m", base_url="u", api_key="k", context_window=80000)
    assert effective_context_window(p) == 80000


def test_effective_context_window_unknown_protocol():
    """未知 protocol + 不配置 → 200000（保守默认）。"""
    p = ProviderConfig(protocol="custom", model="m", base_url="u", api_key="k")
    assert effective_context_window(p) == 200000


def test_config_loader_reads_context_window(tmp_path):
    """YAML 中的 context_window 被正确读取。"""
    import yaml
    from Alincode.config import ConfigLoader
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "providers": [{
            "name": "test",
            "protocol": "anthropic",
            "model": "claude-opus-4-8",
            "base_url": "https://api.example.com",
            "api_key": "sk-test",
            "context_window": 100000,
        }],
    }))
    app_cfg = ConfigLoader.load(str(config_file))
    assert len(app_cfg.providers) == 1
    assert app_cfg.providers[0].context_window == 100000


def test_config_loader_old_format(tmp_path):
    """旧扁平格式仍然兼容。"""
    import yaml
    from Alincode.config import ConfigLoader
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "protocol": "openai",
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
    }))
    app_cfg = ConfigLoader.load(str(config_file))
    assert len(app_cfg.providers) == 1
    assert app_cfg.providers[0].protocol == "openai"


def test_config_loader_mcp_servers(tmp_path):
    """mcp_servers 段被正确解析。"""
    import yaml
    from Alincode.config import ConfigLoader
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump({
        "providers": [{
            "protocol": "anthropic",
            "model": "m",
            "base_url": "u",
            "api_key": "k",
        }],
        "mcp_servers": {
            "test_srv": {"type": "stdio", "command": "echo", "args": ["hi"]},
        },
    }))
    app_cfg = ConfigLoader.load(str(config_file))
    assert "test_srv" in app_cfg.mcp_servers
    assert app_cfg.mcp_servers["test_srv"]["command"] == "echo"
