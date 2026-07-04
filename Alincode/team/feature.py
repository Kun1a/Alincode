"""Team feature flag 读取(T15)。

对应 spec F11(G11 Fork 路径受 FORK_TEAMMATE 控制,默认关闭)。
通过 config 的 features 字段读取,用 getattr 兜底(避免 T25 未完成时报错)。
"""

from __future__ import annotations

from typing import Any


def fork_teammate_enabled(cfg: Any) -> bool:
    """读 cfg.features.fork_teammate(F11)。

    cfg 无 features 字段时返回 False(默认关闭)。
    """
    features = getattr(cfg, "features", None)
    if features is None:
        return False
    return bool(getattr(features, "fork_teammate", False))
