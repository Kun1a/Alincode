"""本机 Profile 的轻量数据模型。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    """Profile 的非敏感摘要。"""

    id: str
    name: str
