"""Coordinator Mode 单测(T24)。覆盖双锁判定、工具白名单、提示词后缀、env_truthy。"""

from __future__ import annotations

from dataclasses import dataclass

from Alincode.coordinator import (
    COORDINATOR_ALLOWED_TOOLS,
    allowed_tools,
    env_truthy,
    is_enabled,
    system_prompt_suffix,
)


@dataclass
class FakeFeatures:
    """模拟 FeaturesConfig。"""

    coordinator_mode: bool = False
    fork_teammate: bool = False


@dataclass
class FakeConfig:
    """模拟 AppConfig,可控制 features 字段。"""

    features: FakeFeatures | None = None


class TestEnvTruthy:
    """env_truthy 各种输入。"""

    def test_one(self):
        assert env_truthy("1") is True

    def test_true(self):
        assert env_truthy("true") is True

    def test_yes(self):
        assert env_truthy("yes") is True

    def test_uppercase(self):
        assert env_truthy("TRUE") is True
        assert env_truthy("YES") is True

    def test_zero(self):
        assert env_truthy("0") is False

    def test_false(self):
        assert env_truthy("false") is False

    def test_empty(self):
        assert env_truthy("") is False

    def test_random(self):
        assert env_truthy("random") is False

    def test_whitespace(self):
        assert env_truthy("  yes  ") is True


class TestIsEnabled:
    """双锁判定:feature flag × env var,只有 11 返回 True。"""

    def test_both_off(self, monkeypatch):
        monkeypatch.delenv("MEWCODE_COORDINATOR_MODE", raising=False)
        cfg = FakeConfig(features=FakeFeatures(coordinator_mode=False))
        assert is_enabled(cfg) is False

    def test_feature_off_env_on(self, monkeypatch):
        monkeypatch.setenv("MEWCODE_COORDINATOR_MODE", "1")
        cfg = FakeConfig(features=FakeFeatures(coordinator_mode=False))
        assert is_enabled(cfg) is False

    def test_feature_on_env_off(self, monkeypatch):
        monkeypatch.delenv("MEWCODE_COORDINATOR_MODE", raising=False)
        cfg = FakeConfig(features=FakeFeatures(coordinator_mode=True))
        assert is_enabled(cfg) is False

    def test_both_on(self, monkeypatch):
        monkeypatch.setenv("MEWCODE_COORDINATOR_MODE", "1")
        cfg = FakeConfig(features=FakeFeatures(coordinator_mode=True))
        assert is_enabled(cfg) is True

    def test_no_features_attr(self, monkeypatch):
        """cfg 无 features 字段时返回 False。"""
        monkeypatch.setenv("MEWCODE_COORDINATOR_MODE", "1")
        cfg = object()  # 无 features 属性
        assert is_enabled(cfg) is False

    def test_features_none(self, monkeypatch):
        monkeypatch.setenv("MEWCODE_COORDINATOR_MODE", "1")
        cfg = FakeConfig(features=None)
        assert is_enabled(cfg) is False


class TestAllowedTools:
    """工具白名单:含 bash 不含 write_file/edit_file。"""

    def test_contains_bash(self):
        tools = allowed_tools()
        assert "bash" in tools

    def test_no_write_file(self):
        tools = allowed_tools()
        assert "write_file" not in tools

    def test_no_edit_file(self):
        tools = allowed_tools()
        assert "edit_file" not in tools

    def test_returns_copy(self):
        """allowed_tools() 返回拷贝,修改不影响常量。"""
        tools = allowed_tools()
        tools.append("evil")
        assert "evil" not in COORDINATOR_ALLOWED_TOOLS

    def test_matches_constant(self):
        assert allowed_tools() == COORDINATOR_ALLOWED_TOOLS


class TestSystemPromptSuffix:
    """提示词后缀含关键字。"""

    def test_contains_keyword(self):
        """含 "Coordinator" 或 "派完" 关键字。"""
        suffix = system_prompt_suffix()
        assert "Coordinator" in suffix or "派完" in suffix

    def test_contains_phase_keywords(self):
        """四阶段关键字齐全。"""
        suffix = system_prompt_suffix()
        assert "Research" in suffix
        assert "Synthesis" in suffix
        assert "Implementation" in suffix
        assert "Verification" in suffix

    def test_contains_discipline(self):
        """纪律段:派完队员就停手。"""
        suffix = system_prompt_suffix()
        assert "派完" in suffix
