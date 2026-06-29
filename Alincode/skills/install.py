"""InstallSkill：下载 zip 并解压到项目目录 .Alincode/skills/（T16）。"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


async def install_from_url(source: str, catalog, work_dir: str) -> str:
    """从 URL 下载 zip，解压到 <work_dir>/.Alincode/skills/。

    校验：路径不可含 ..、不可为绝对路径、不可为符号链接。
    """
    try:
        import httpx
    except ImportError:
        raise ImportError(
            "InstallSkill 需要 httpx 库。请运行: uv add httpx"
        )

    target_base = Path(work_dir) / ".Alincode" / "skills"
    target_base.mkdir(parents=True, exist_ok=True)

    # 下载到临时文件（限时 60s，限大小 50MB）
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(source)
        response.raise_for_status()
        content = response.read()
    if len(content) > 50 * 1024 * 1024:
        raise ValueError("下载文件超过 50MB 限制")

    # 写入临时文件
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        skill_name = _extract_zip(tmp_path, target_base)
    finally:
        os.unlink(tmp_path)

    # 热加载
    catalog.reload(work_dir)
    return skill_name


def _extract_zip(zip_path: str, target_base: Path) -> str:
    """解压 zip 并校验路径安全。返回顶层目录名。"""
    top_dir = None

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename

            # 安全检查
            parts = Path(name).parts
            if not parts:
                continue
            if top_dir is None:
                top_dir = parts[0]
            # 不可 ..
            if ".." in parts:
                raise ValueError(f"unsafe path in zip: {name}")
            # 不可绝对路径
            if Path(name).is_absolute():
                raise ValueError(f"absolute path in zip: {name}")
            # 不可符号链接
            if info.is_symlink():
                raise ValueError(f"symlink in zip: {name}")
            # 必须在顶层目录下
            if parts[0] != top_dir:
                raise ValueError(f"path outside top dir in zip: {name}")

    if top_dir is None:
        raise ValueError("empty zip")

    # 解压
    dest = target_base / top_dir
    if dest.exists():
        shutil.rmtree(dest)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(target_base)

    return top_dir
