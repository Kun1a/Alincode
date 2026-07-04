"""iTerm2 后端(T13)。

对应 spec F17。通过 it2 CLI 在 iTerm2 里 split pane spawn 子进程。
it2 CLI 命令以官方为准,先按 spec 描述实现,实测可能要调。
"""

from __future__ import annotations

import asyncio
import shlex

from Alincode.team.backend import SpawnRequest
from Alincode.team.backend.tmux import build_member_cmd
from Alincode.team.types import BackendType


class Iterm2Backend:
    """iTerm2 pane 后端。"""

    def type(self) -> BackendType:
        return BackendType.ITERM2

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        """it2 split --new-pane --command(F17)。"""
        cmd = build_member_cmd(req)
        cmd_str = " ".join(shlex.quote(c) for c in cmd)
        args = ["it2", "split", "--new-pane", "--command", cmd_str]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"it2 spawn 失败(rc={proc.returncode}): {stderr.decode().strip()}"
            )
        pane_id = stdout.decode().strip()
        return (pane_id, req.agent_id)

    async def wake(self, pane_id: str, agent_id: str) -> None:
        """it2 send-text 空文本即唤醒(F17)。"""
        proc = await asyncio.create_subprocess_exec(
            "it2",
            "send-text",
            "--pane",
            pane_id,
            "",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    async def kill(self, pane_id: str, agent_id: str) -> None:
        """it2 close-pane(F17)。"""
        proc = await asyncio.create_subprocess_exec(
            "it2",
            "close-pane",
            "--pane",
            pane_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
