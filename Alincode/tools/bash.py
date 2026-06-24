"""bash 工具：执行 shell 命令，返回 stdout/stderr/退出码。"""

from __future__ import annotations

import asyncio
import json

from Alincode.tools import Result, _truncate

# 输出上限：10000 行 / 30000 字符
MAX_LINES = 10000
MAX_CHARS = 30000


class BashTool:
    """执行命令工具：在工作目录下执行 shell 命令，受超时约束。

    命令通过 asyncio.create_subprocess_shell 执行，
    超时由 Registry 层 asyncio.wait_for 控制。
    非零退出码不作为 is_error（让模型自己判断）。
    """

    def name(self) -> str:
        return "bash"

    def description(self) -> str:
        return (
            "执行 shell 命令并返回标准输出、标准错误和退出码。"
            "适用于运行测试、安装依赖、查看文件列表、构建项目等操作。"
            "命令在项目工作目录下执行。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令",
                }
            },
            "required": ["command"],
        }

    async def execute(self, args: str) -> Result:
        """执行 shell 命令。"""
        try:
            data = json.loads(args) if args and args.strip() else {}
            command = data.get("command", "")
        except json.JSONDecodeError as e:
            return Result(content=f"参数 JSON 解析失败: {e}", is_error=True)

        if not command:
            return Result(content="缺少必填参数: command", is_error=True)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await proc.communicate()
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")

            parts = [f"exit_code: {proc.returncode}"]
            if stdout:
                parts.append(f"stdout:\n{stdout}")
            else:
                parts.append("stdout: (空)")
            if stderr:
                parts.append(f"stderr:\n{stderr}")
            else:
                parts.append("stderr: (空)")

            result = _truncate("\n".join(parts), MAX_LINES, MAX_CHARS)
            return Result(content=result)
        except OSError as e:
            return Result(content=f"执行命令失败: {e}", is_error=True)
