"""环境信息采集与渲染（F2/AC3）。"""

from __future__ import annotations

import asyncio
import datetime
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Environment:
    """当前运行环境快照——每次 Agent.run 时采集一次。"""
    cwd: str = ""
    os_name: str = ""
    date: str = ""
    git_status: str = ""
    version: str = ""
    model: str = ""

    def render(self) -> str:
        parts = ["## 环境信息"]
        if self.cwd:
            parts.append(f"- 工作目录: {self.cwd}")
        if self.os_name:
            parts.append(f"- 操作系统: {self.os_name}")
        if self.date:
            parts.append(f"- 当前日期: {self.date}")
        if self.version:
            parts.append(f"- 应用版本: {self.version}")
        if self.model:
            parts.append(f"- 当前模型: {self.model}")
        if self.git_status:
            parts.append(f"- Git 状态:\n{self.git_status}")
        return "\n".join(parts)


async def gather_environment(
    cwd: str | None = None,
    version: str = "0.3.0",
    model: str = "",
) -> Environment:
    """异步采集环境信息，失败项留空不中断（N4/AC13）。"""
    env = Environment(
        cwd=cwd or str(Path.cwd()),
        os_name=platform.system() + " " + platform.release(),
        date=datetime.date.today().isoformat(),
        version=version,
        model=model,
    )
    try:
        env.git_status = await _git_status(env.cwd)
    except Exception:
        env.git_status = ""
    return env


async def _git_status(cwd: str) -> str:
    """获取 git status --porcelain 输出，超时 2s 降级为空（N4）。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        text = stdout_b.decode("utf-8", errors="replace").strip()
        if text:
            # 取前 10 行，避免过长
            lines = text.split("\n")[:10]
            if len(lines) >= 10:
                lines.append("...")
            return "\n".join(f"    {ln}" for ln in lines)
        return "（无变更）"
    except asyncio.TimeoutError:
        if proc:
            proc.kill()
        return ""
    except Exception:
        return ""
