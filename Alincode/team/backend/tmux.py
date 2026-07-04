"""Tmux 后端(T12)。

对应 spec F15-F16。在 tmux pane 里 spawn mewcode 子进程。
$TMUX 内走 split-window,外部走 new-session -d(不静默回退)。
initial_prompt 不走命令行,由 spawn 前预写入 mailbox(F13)。
"""

from __future__ import annotations

import asyncio
import os
import sys

from Alincode.team.backend import SpawnRequest
from Alincode.team.types import BackendType


def build_member_cmd(req: SpawnRequest) -> list[str]:
    """构造 `python -m Alincode --team-member ...` 命令(F15)。

    --agent-id 必传:子进程不需要读 Lead 还没写完的 config.json 找自己。
    initial_prompt 不走命令行,由 spawn 前预写入 mailbox。
    """
    cmd = [
        sys.executable,
        "-m",
        "Alincode",
        "--team-member",
        "--team",
        req.team_name,
        "--member",
        req.member_name,
        "--agent-id",
        req.agent_id,
        "--session-dir",
        req.session_dir,
        "--worktree",
        req.worktree_path,
    ]
    if req.agent_type:
        cmd += ["--agent-type", req.agent_type]
    if req.model:
        cmd += ["--model", req.model]
    if req.plan_mode_required:
        cmd.append("--plan-mode")
    return cmd


class TmuxBackend:
    """tmux pane 后端。"""

    def type(self) -> BackendType:
        return BackendType.TMUX

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        """在 tmux 里 spawn pane(F15-F16)。

        $TMUX 内:split-window -h;外部:new-session -d。
        返回 (pane_id, agent_id)。
        """
        cmd = build_member_cmd(req)
        in_tmux = bool(os.environ.get("TMUX"))
        if in_tmux:
            args = [
                "tmux",
                "split-window",
                "-h",
                "-P",
                "-F",
                "#{pane_id}",
                "--",
            ] + cmd
        else:
            # F16:外部走 new-session -d(detached)
            args = [
                "tmux",
                "new-session",
                "-d",
                "-P",
                "-F",
                "#{pane_id}",
                "--",
            ] + cmd
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"tmux spawn 失败(rc={proc.returncode}): {stderr.decode().strip()}"
            )
        pane_id = stdout.decode().strip()
        return (pane_id, req.agent_id)

    async def wake(self, pane_id: str, agent_id: str) -> None:
        """通过 send-keys 唤醒目标 pane(F15)。

        空回车触发子进程 stdin reader 读到一行,立刻去 mailbox 轮询。
        """
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "send-keys",
            "-t",
            pane_id,
            "",
            "Enter",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    async def kill(self, pane_id: str, agent_id: str) -> None:
        """kill-pane,忽略 pane not found(F15)。"""
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "kill-pane",
            "-t",
            pane_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
