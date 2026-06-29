"""Hook Executor：command / prompt / http / subagent 四类动作执行器。"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from Alincode.hook.rule import Rule, Payload


@dataclass
class ExecutionResult:
    blocked: bool = False
    reason: str = ""
    prompt: str = ""           # 仅 prompt 动作非空
    err: Exception | None = None


class Executor:
    """四类 Hook 动作执行器。"""

    def __init__(self) -> None:
        self._http_client: httpx.AsyncClient | None = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def run(
        self, rule: "Rule", payload: "Payload", *, blocking: bool,
    ) -> ExecutionResult:
        action = rule.action
        at = action.type.value

        if at == "command" and action.command:
            return await self._run_command(action.command.command, payload, blocking, rule)
        if at == "prompt" and action.prompt:
            return ExecutionResult(prompt=action.prompt.text)
        if at == "http" and action.http:
            return await self._run_http(action.http, payload, blocking, rule.timeout_s)
        if at == "subagent" and action.subagent:
            return self._run_subagent(action.subagent)

        return ExecutionResult(err=RuntimeError(f"unknown action type: {action.type}"))

    # ── Command ─────────────────────────────────────────

    async def _run_command(
        self, command: str, payload: "Payload", blocking: bool, rule: "Rule",
    ) -> ExecutionResult:
        """执行 shell 命令。payload 以单行 JSON 通过 stdin 传入。

        拦截语义（仅 blocking=True 时生效）：
          - rule.reject=True  → 命令输出作为拒绝原因，blocked=True
          - rule.reject=False → returncode==2 才拦截（兼容旧语义）
        """
        payload_json = _marshal_sorted(payload)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(payload_json),
                    timeout=rule.timeout_s,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
                return ExecutionResult(err=TimeoutError(f"command timeout after {rule.timeout_s}s"))

            code = proc.returncode

            if blocking and rule.reject:
                # reject 模式：输出作为拒绝原因
                reason = _decode_output(stdout, stderr)
                if code != 0:
                    err_info = stderr.decode("utf-8", errors="replace").strip()
                    if err_info:
                        reason = f"{reason} [命令异常: {err_info}]"
                    else:
                        reason = f"{reason} [命令异常: exit code {code}]"
                return ExecutionResult(blocked=True, reason=reason)

            if blocking and code == 2:
                # 兼容旧语义：exit 2 表达拦截
                reason = _decode_output(stderr, stdout)
                return ExecutionResult(blocked=True, reason=reason)

            if code == 0:
                return ExecutionResult()

            # 非零 → 失败不拦截
            err_msg = stderr.decode("utf-8", errors="replace").strip() or f"exit code {code}"
            return ExecutionResult(err=RuntimeError(err_msg))

        except OSError as e:
            return ExecutionResult(err=e)

    # ── HTTP ────────────────────────────────────────────

    async def _run_http(
        self, ha, payload: "Payload", blocking: bool, timeout: float,
    ) -> ExecutionResult:
        method = ha.method or "POST"

        if ha.body is None:
            body = json.dumps(payload, sort_keys=True)
        else:
            try:
                body = ha.body.format_map(payload)
            except Exception as e:
                return ExecutionResult(err=ValueError(f"template render failed: {e}"))

        client = self._get_http_client()

        try:
            resp = await client.request(
                method, ha.url,
                content=body,
                headers=ha.headers,
                timeout=timeout,
            )

            if 200 <= resp.status_code < 300 and blocking:
                try:
                    data = resp.json()
                    if isinstance(data, dict) and data.get("decision") == "block":
                        reason = str(data.get("reason", ""))
                        return ExecutionResult(blocked=True, reason=reason)
                except (json.JSONDecodeError, ValueError):
                    pass

            return ExecutionResult()

        except httpx.TimeoutException as e:
            return ExecutionResult(err=e)
        except httpx.HTTPError as e:
            return ExecutionResult(err=e)
        except OSError as e:
            return ExecutionResult(err=e)

    # ── Subagent（占位）──────────────────────────────────

    def _run_subagent(self, sa) -> ExecutionResult:
        print(
            f"[hook subagent] not yet implemented, skipped: {sa.agent_name}",
            file=sys.stderr,
        )
        return ExecutionResult()


# ── 辅助 ────────────────────────────────────────────────

def _marshal_sorted(payload: "Payload") -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _decode_output(stdout: bytes, stderr: bytes) -> str:
    """优先用 stdout，否则 stderr。"""
    out = stdout.decode("utf-8", errors="replace").strip()
    if out:
        return out
    return stderr.decode("utf-8", errors="replace").strip()
