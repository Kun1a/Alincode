"""Worktree 创建 + 快速恢复 + 创建后设置（F6-F10/T5）。"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from Alincode.worktree.slug import validate_slug, flat_slug
from Alincode.worktree.git import _run_git, _resolve_head_sha_from_fs
from Alincode.worktree.manager import Worktree


async def create(
    mgr, name: str, base_ref: str, manual: bool,
) -> Worktree:
    """创建 Worktree（含快速恢复 + 创建后设置）。"""
    validate_slug(name)

    async with mgr.lock:
        if name in mgr.active:
            raise ValueError(f"worktree '{name}' 已存在")

        flat = flat_slug(name)
        wt_path = mgr.worktree_dir / flat
        branch = f"worktree-{flat}"

        # 快速恢复：目录已存在时仅读文件系统
        if wt_path.exists():
            sha = _resolve_head_sha_from_fs(str(wt_path))
            wt = Worktree(
                name=name, path=str(wt_path), branch=branch,
                head_commit=sha or "", manual=manual,
            )
            mgr.active[name] = wt
            return wt

        # 执行 git worktree add
        try:
            await _run_git(mgr.repo_root, "worktree", "add", "-B", branch, str(wt_path), base_ref)
        except Exception:
            shutil.rmtree(wt_path, ignore_errors=True)
            raise

        # 创建后设置（best-effort）
        await _perform_post_creation_setup(mgr.repo_root, wt_path, mgr.symlink_dirs)

        # 取 head SHA
        head_sha = ""
        try:
            head_sha = await _run_git(str(wt_path), "rev-parse", "HEAD")
        except Exception:
            head_sha = "unknown"

        wt = Worktree(
            name=name, path=str(wt_path), branch=branch,
            based_on=base_ref, head_commit=head_sha,
            created=datetime.now(), manual=manual,
        )
        mgr.active[name] = wt
        return wt


async def _perform_post_creation_setup(
    repo_root: str, wt_path: Path, symlink_dirs: list[str],
) -> None:
    """创建后四项设置，失败仅 stderr 警告，不中断。"""
    await _setup_copy_configs(repo_root, wt_path)
    await _setup_git_hooks(repo_root, wt_path)
    await _setup_symlink_dirs(repo_root, wt_path, symlink_dirs)
    await _setup_copy_ignored(repo_root, wt_path)


async def _setup_copy_configs(repo_root: str, wt_path: Path) -> None:
    """A: 复制本地配置文件。"""
    for cfg_name in ["config.yaml", "settings.local.yaml"]:
        src = Path(repo_root) / ".Alincode" / cfg_name
        if not src.is_file():
            continue
        dst_dir = wt_path / ".Alincode"
        dst = dst_dir / cfg_name
        if not dst.exists():
            try:
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            except OSError as e:
                print(f"worktree: setup copy config {cfg_name}: {e}", file=sys.stderr)


async def _setup_git_hooks(repo_root: str, wt_path: Path) -> None:
    """B: 配置 git hooks path。"""
    husky_dir = Path(repo_root) / ".husky"
    hooks_path = None
    if husky_dir.is_dir():
        hooks_path = str(husky_dir.resolve())
    else:
        import subprocess
        try:
            result = subprocess.run(
                ["git", "-C", repo_root, "config", "--get", "core.hooksPath"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                hooks_path = result.stdout.strip()
        except Exception:
            pass

    if hooks_path:
        try:
            await _run_git(str(wt_path), "config", "core.hooksPath", hooks_path)
        except Exception as e:
            print(f"worktree: setup git hooks: {e}", file=sys.stderr)


async def _setup_symlink_dirs(
    repo_root: str, wt_path: Path, symlink_dirs: list[str],
) -> None:
    """C: 软链大目录。"""
    for d in symlink_dirs:
        src = Path(repo_root) / d
        dst = wt_path / d
        if src.exists() and not dst.exists():
            try:
                os.symlink(str(src), str(dst))
            except OSError as e:
                print(f"worktree: setup symlink {d}: {e}", file=sys.stderr)


async def _setup_copy_ignored(repo_root: str, wt_path: Path) -> None:
    """D: 按 .worktreeinclude 复制被忽略的文件。"""
    include_file = Path(repo_root) / ".worktreeinclude"
    if not include_file.is_file():
        return

    try:
        patterns = [
            line.strip() for line in include_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    except OSError:
        return

    if not patterns:
        return

    try:
        out = await _run_git(
            repo_root, "ls-files", "--others", "--ignored",
            "--exclude-standard",
        )
    except RuntimeError:
        return

    import fnmatch
    for line in out.splitlines():
        rel_path = line.strip()
        if not rel_path:
            continue
        for pat in patterns:
            if fnmatch.fnmatch(rel_path, pat):
                src = Path(repo_root) / rel_path
                dst = wt_path / rel_path
                if not dst.exists() and src.is_file():
                    try:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                    except OSError as e:
                        print(f"worktree: setup copy ignored {rel_path}: {e}", file=sys.stderr)
                break
