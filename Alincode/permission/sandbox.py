"""沙箱：路径围栏——先解析符号链接再前缀比对防逃逸（F2/N2/AC2）。"""

from pathlib import Path


def check_sandbox(target_path: str, project_root: str) -> bool:
    """检查文件操作路径是否在项目根内。

    先解析目标路径的符号链接（或祖先目录），再与项目根做前缀比对。
    新建文件按最近已存在祖先目录解析。

    Args:
        target_path: 文件操作的绝对或相对路径
        project_root: 项目根目录（已 resolve 的绝对路径）

    Returns:
        True 表示在沙箱内（放行），False 表示越界（拦截）
    """
    pr = Path(project_root).resolve()
    try:
        tp = Path(target_path)
        if not tp.is_absolute():
            tp = Path.cwd() / tp
        tp = _resolve_existing(tp)
        return _is_under(tp, pr)
    except Exception:
        return False


def _resolve_existing(p: Path) -> Path:
    """解析路径——目标存在就 resolve，不存在就回退到最近已存在祖先。"""
    if p.exists():
        return p.resolve()
    # 向上找最近存在的祖先
    for ancestor in p.parents:
        if ancestor.exists():
            return ancestor.resolve() / p.relative_to(ancestor)
    # 极端情况：路径没有已存在祖先，返回原始值（safe default → deny）
    return p


def _is_under(p: Path, root: Path) -> bool:
    """前缀判断：p 是否在 root 下。使用 Path.is_relative_to (Python ≥3.9)。"""
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False
