"""feature flag 单测(T15)。覆盖 fork_teammate_enabled。"""

from __future__ import annotations

from dataclasses import dataclass

from Alincode.team.feature import fork_teammate_enabled


@dataclass
class FakeFeatures:
    fork_teammate: bool = False


@dataclass
class FakeConfig:
    features: FakeFeatures = None  # type: ignore[assignment]


class TestForkTeammateEnabled:
    def test_true(self):
        cfg = FakeConfig(features=FakeFeatures(fork_teammate=True))
        assert fork_teammate_enabled(cfg) is True

    def test_false(self):
        cfg = FakeConfig(features=FakeFeatures(fork_teammate=False))
        assert fork_teammate_enabled(cfg) is False

    def test_no_features_attr(self):
        cfg = object()  # 无 features 属性
        assert fork_teammate_enabled(cfg) is False

    def test_features_none(self):
        cfg = FakeConfig(features=None)
        assert fork_teammate_enabled(cfg) is False
