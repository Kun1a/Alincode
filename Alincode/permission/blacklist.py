"""黑名单：正则硬拦截高危命令，不可配置绕过（F1/N1/AC1）。"""

import re

# 黑名单模式列表——编译好的正则，不可外部配置
_PATTERNS: list[re.Pattern] = [
    # rm -rf / -r / 类
    re.compile(r"\brm\s+(-[a-z]*[rf][a-z]*)\s+.*/", re.IGNORECASE),
    # fork bomb
    re.compile(r":\(\)\s*\{?\s*:\s*\|?\s*:\s*&?\s*\}?\s*;?\s*:", re.IGNORECASE),
    re.compile(r"\bperl\s+-e\s+.*fork\b", re.IGNORECASE),
    re.compile(r"\bpython\s+-c\s+.*fork\b", re.IGNORECASE),
    # 写块设备
    re.compile(r"\bdd\s+if=\S*\s+of=/dev/[a-z]+\b", re.IGNORECASE),
    re.compile(r">\s*/dev/sd[a-z]\b", re.IGNORECASE),
    # 危险格式化/删除
    re.compile(r"\bmkfs\.\S*\s+/dev/[a-z]+\b", re.IGNORECASE),
    re.compile(r"\bchmod\s+(-R\s+)?777\s+/", re.IGNORECASE),
    # 改系统关键文件
    re.compile(r"\bcurl\s+.*\|\s*(ba)?sh\b", re.IGNORECASE),
    re.compile(r"\bwget\s+.*\s*-O\s+.*\|\s*(ba)?sh\b", re.IGNORECASE),
]

# 黑名单显式声明：不可配置绕过
BLACKLIST_UNAVOIDABLE = True


def check_blacklist(command: str) -> bool:
    """检查命令是否命中黑名单。返回 True 表示命中（应拦截）。

    Args:
        command: 要检查的 shell 命令字符串

    Returns:
        True 如果命中黑名单，False 否则
    """
    for pat in _PATTERNS:
        if pat.search(command):
            return True
    return False
