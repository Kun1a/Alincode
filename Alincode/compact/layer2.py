"""第 2 层 LLM 摘要：摘要 + 恢复 + 近期原文 + PTL 重试 + 熔断（T12-T17）。"""

from __future__ import annotations

import logging
import math

from Alincode.compact.const import (
    RECENT_KEEP_TOKENS,
    RECENT_KEEP_MESSAGES,
    PTL_RETRY_LIMIT,
    PTL_DROP_PERCENTAGE,
    ESTIMATE_CHARS_PER_TOKEN,
)
from typing import TYPE_CHECKING

from Alincode.compact.recovery import build_recovery_attachment
from Alincode.compact.summary_prompt import build_summary_prompt, extract_summary
from Alincode.compact.token import estimate_tokens, message_chars
from Alincode.conversation import Message

if TYPE_CHECKING:
    from Alincode.compact.compact import ManageInput

logger = logging.getLogger(__name__)


# ── 近期原文 ────────────────────────────────────────

def pick_recent_tail(msgs: list[Message]) -> list[Message]:
    """从 msgs 尾部累加，满足两个下界后才停止。

    - 累计估算 token ≥ RECENT_KEEP_TOKENS 且
    - 累计消息数 ≥ RECENT_KEEP_MESSAGES
    之后做 tool_use/tool_result 配对修正：若截断点夹在配对中间，
    向前推到 tool_use 的 assistant 之前。
    """
    if not msgs:
        return []

    tail_token = 0
    tail_count = 0
    start_idx = len(msgs)

    for i in range(len(msgs) - 1, -1, -1):
        tail_token += math.ceil(message_chars([msgs[i]]) / ESTIMATE_CHARS_PER_TOKEN)
        tail_count += 1
        start_idx = i
        if tail_token >= RECENT_KEEP_TOKENS and tail_count >= RECENT_KEEP_MESSAGES:
            break

    # 配对修正：若截断点首条是 tool，前推到上一个 assistant（带 tool_calls）
    while start_idx > 0 and msgs[start_idx].role == "tool":
        start_idx -= 1
        # 继续前推直到找到带 tool_calls 的 assistant
        while start_idx > 0 and not (
            msgs[start_idx].role == "assistant" and msgs[start_idx].tool_calls
        ):
            start_idx -= 1

    return list(msgs[start_idx:])


# ── 角色衔接修正 ──────────────────────────────────────

def _join_after_summary(
    summary_and_recovery: Message,
    recent: list[Message],
) -> list[Message]:
    """拼接摘要+恢复消息和近期原文，避免 user/user 连续。

    摘要+恢复消息固定 role="user"。
    若 recent[0].role == "user"，插入 assistant 衔接占位。
    若 recent[0].role == "tool"，前推到第一条非 tool（防御性）。
    """
    if not recent:
        return [summary_and_recovery]

    # 防御性：丢弃开头的 tool
    while recent and recent[0].role == "tool":
        recent = recent[1:]

    if not recent:
        return [summary_and_recovery]

    result = [summary_and_recovery]

    if recent[0].role == "user":
        # 插入衔接占位，避免 user/user 连续
        result.append(
            Message(
                role="assistant",
                content="（已加载上下文摘要与恢复信息。请继续。）",
            )
        )

    result.extend(recent)
    return result


# ── 分组 ──────────────────────────────────────────

def group_by_user_turn(msgs: list[Message]) -> list[list[Message]]:
    """按"用户提交 → 一组 assistant/tool 往返"分组。

    每遇到 role=="user" 就开新组。
    第一条不是 user 时，塞进第 0 组。
    """
    groups: list[list[Message]] = []
    for msg in msgs:
        if msg.role == "user" or not groups:
            groups.append([])
        groups[-1].append(msg)
    return groups


# ── 单次摘要请求 ────────────────────────────────────

async def summarize_once(in_: ManageInput, msgs: list[Message]) -> str:
    """发一次摘要请求，不传 tools，返回提取后的 <summary> 正文。

    摘要请求结束后不更新 SessionRuntime.usage_anchor。
    错误（包括 PTL）透传给调用方。
    """
    from Alincode.client import Request, System

    req = Request(
        system=System(stable="", environment=""),
        messages=build_summary_prompt(msgs),
        model=getattr(in_, "model", ""),
        tools=[],
    )

    text_buf: list[str] = []
    async for ev in in_.provider.stream(req):
        if ev.err is not None:
            raise ev.err
        if ev.text:
            text_buf.append(ev.text)
        # 忽略 usage 和 tool_calls

    return extract_summary("".join(text_buf))


# ── 摘要请求 PTL 自重试 ──────────────────────────────

async def ptl_retry(
    in_: ManageInput,
    msgs: list[Message],
    first_err: Exception,
) -> str:
    """实现 F27 的丢消息组策略。

    - 前 PTL_RETRY_LIMIT 次：每次丢最旧 1 组
    - 超过后：每次按剩余组数 × PTL_DROP_PERCENTAGE 丢
    - 直到能塞下或全部丢光
    """
    from Alincode.client import PromptTooLongError

    groups = group_by_user_turn(msgs)
    errors = [first_err]
    retry_count = 0

    while groups:
        if retry_count < PTL_RETRY_LIMIT:
            drop = 1
        else:
            drop = math.ceil(len(groups) * PTL_DROP_PERCENTAGE)
            drop = max(drop, 1)

        groups = groups[drop:]
        if not groups:
            break

        flat = [m for g in groups for m in g]
        try:
            return await summarize_once(in_, flat)
        except PromptTooLongError as e:
            errors.append(e)
            retry_count += 1
            continue
        except Exception:
            raise  # 非 PTL 异常直接上抛

    # 全部丢光
    last_err = errors[-1] if errors else first_err
    raise last_err


# ── 摘要 + 恢复 + 拼接 ──────────────────────────────

async def run_summary(in_: ManageInput) -> list[Message]:
    """核心：摘要请求 → 解析 → 恢复三段 → 近期原文 → 拼接。"""
    from Alincode.client import PromptTooLongError

    old_msgs = in_.conv.messages
    # 入口拍快照
    recovery_snapshot = in_.recovery.snapshot()

    try:
        summary_text = await summarize_once(in_, old_msgs)
    except PromptTooLongError as e:
        summary_text = await ptl_retry(in_, old_msgs, e)

    recovery_text = build_recovery_attachment(recovery_snapshot, in_.tool_defs)

    combined_content = "## 历史会话摘要\n" + summary_text + "\n\n" + recovery_text
    summary_and_recovery = Message(role="user", content=combined_content)

    recent_tail = pick_recent_tail(old_msgs)
    return _join_after_summary(summary_and_recovery, recent_tail)


# ── 自动 / 手动 / 紧急 ───────────────────────────────

def _estimate_msgs(msgs: list[Message]) -> int:
    """统一用纯字符估算 token（不用 anchor），保证 before/after 口径一致。"""
    return estimate_tokens(0, msgs, 0)


async def auto_compact(in_: ManageInput) -> tuple[list[Message], int, int]:
    """自动摘要：不计入熔断（由 manage_context 根据结果判断）。"""
    old_msgs = in_.conv.messages
    before_tok = _estimate_msgs(old_msgs)
    new_msgs = await run_summary(in_)
    after_tok = _estimate_msgs(new_msgs)
    return (new_msgs, before_tok, after_tok)


async def force_compact(in_: ManageInput) -> tuple[list[Message], int, int]:
    """手动 / 紧急摘要：不计入熔断。"""
    old_msgs = in_.conv.messages
    before_tok = _estimate_msgs(old_msgs)
    new_msgs = await run_summary(in_)
    after_tok = _estimate_msgs(new_msgs)
    return (new_msgs, before_tok, after_tok)
