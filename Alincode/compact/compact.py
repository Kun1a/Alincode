"""上下文管理编排入口：manage_context + TriggerKind 枚举（T18）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from Alincode.compact.const import (
    SUMMARY_RESERVE,
    AUTO_SAFETY_MARGIN,
)
from Alincode.compact.layer1 import offload_and_snip
from Alincode.compact.layer2 import auto_compact, force_compact
from Alincode.compact.token import estimate_tokens

if TYPE_CHECKING:
    from Alincode.client import BaseProvider
    from Alincode.compact.state import (
        ContentReplacementState,
        RecoveryState,
        AutoCompactTrackingState,
        SessionContext,
    )
    from Alincode.conversation import ConversationManager, ToolDefinition

logger = logging.getLogger(__name__)


class TriggerKind(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    EMERGENCY = "emergency"


@dataclass
class ManageInput:
    """manage_context 的入参容器。"""
    conv: "ConversationManager"
    provider: "BaseProvider"
    context_window: int
    tool_defs: list["ToolDefinition"]
    replacement: "ContentReplacementState"
    recovery: "RecoveryState"
    auto_tracking: "AutoCompactTrackingState"
    session: "SessionContext"
    usage_anchor: int = 0
    anchor_msg_len: int = 0
    estimated_token: int = 0
    trigger: TriggerKind = TriggerKind.AUTO
    model: str = ""


@dataclass
class ManageOutput:
    before_tokens: int
    after_tokens: int


async def manage_context(in_: ManageInput) -> ManageOutput:
    """Agent 每轮请求前必调的唯一入口。

    编排两层调用顺序、决定走自动 / 手动 / 紧急路径、
    把替换/摘要后的消息写回 Conversation、更新熔断器计数。
    """
    logger.info(
        "manage_context: trigger=%s estimated=%d window=%d threshold=%d",
        in_.trigger.value, in_.estimated_token, in_.context_window,
        in_.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN,
    )
    # sanity check：context_window 必须 > SUMMARY_RESERVE + AUTO_SAFETY_MARGIN
    min_window = SUMMARY_RESERVE + AUTO_SAFETY_MARGIN
    if in_.context_window <= min_window:
        logger.warning(
            f"context_window ({in_.context_window}) <= {min_window}, "
            f"skipping auto layer2"
        )
        # 仍然跑第 1 层
        layer1_out = offload_and_snip(in_.conv.messages, in_.replacement, in_.session)
        in_.conv.replace_messages(layer1_out)
        return ManageOutput(
            before_tokens=in_.estimated_token,
            after_tokens=in_.estimated_token,
        )

    if in_.trigger == TriggerKind.MANUAL:
        # 跳过 layer1、阈值、熔断；直接 force_compact
        new_msgs, before, after = await force_compact(in_)
        if after >= before:
            logger.info(
                "manual compact: after (%d) >= before (%d), discarding",
                after, before,
            )
            return ManageOutput(before_tokens=before, after_tokens=before)
        in_.conv.replace_messages(new_msgs)
        return ManageOutput(before_tokens=before, after_tokens=after)

    if in_.trigger == TriggerKind.EMERGENCY:
        # 先强制跑一次 layer1，再 force_compact
        layer1_out = offload_and_snip(in_.conv.messages, in_.replacement, in_.session)
        in_.conv.replace_messages(layer1_out)
        new_msgs, before, after = await force_compact(in_)
        if after >= before:
            logger.info(
                "emergency compact: after (%d) >= before (%d), discarding",
                after, before,
            )
            return ManageOutput(before_tokens=before, after_tokens=before)
        in_.conv.replace_messages(new_msgs)
        return ManageOutput(before_tokens=before, after_tokens=after)

    # ── AUTO 路径 ──────────────────────────────────
    # a. 第 1 层
    layer1_out = offload_and_snip(in_.conv.messages, in_.replacement, in_.session)
    in_.conv.replace_messages(layer1_out)

    # b. 用 layer1 之后的消息统一纯字符估算
    est_tokens = estimate_tokens(0, layer1_out, 0)

    # c. 阈值判断
    threshold = in_.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN

    if est_tokens < threshold or in_.auto_tracking.tripped():
        return ManageOutput(
            before_tokens=in_.estimated_token,
            after_tokens=est_tokens,
        )

    # d. 触发第 2 层摘要
    try:
        new_msgs, before, after = await auto_compact(in_)
    except Exception:
        in_.auto_tracking.record_failure()
        raise
    # 兜底：摘要后反而变大，放弃本次压缩
    if after >= before:
        logger.info(
            "auto_compact: after (%d) >= before (%d), discarding compression",
            after, before,
        )
        in_.auto_tracking.record_failure()
        return ManageOutput(before_tokens=before, after_tokens=before)
    in_.auto_tracking.record_success()
    in_.conv.replace_messages(new_msgs)
    return ManageOutput(before_tokens=before, after_tokens=after)
