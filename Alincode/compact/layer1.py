"""第 1 层预防性压缩：单工具结果落盘 + 聚合判断 + 预览体（T6-T8）。"""

from __future__ import annotations

import copy
from pathlib import Path

from Alincode.compact.const import (
    SINGLE_RESULT_LIMIT,
    MESSAGE_AGGREGATE_LIMIT,
    PREVIEW_HEAD_BYTES,
    PREVIEW_HEAD_LINES,
)
from Alincode.compact.state import ContentReplacementState, SessionContext
from Alincode.conversation import Message


def spill_single(session: SessionContext, tool_use_id: str, content: str) -> None:
    """把单条 tool_result 内容写入 spill_dir/<tool_use_id>。

    幂等：文件已存在则不重写、不报错。失败抛 OSError 由上层捕获。
    """
    import logging
    _log = logging.getLogger(__name__)
    path = Path(session.spill_dir) / tool_use_id
    if path.exists():
        _log.info("spill: id=%s already exists, skipping", tool_use_id)
        return
    _log.info("spill: writing %d bytes to %s", len(content.encode("utf-8")), path)
    path.write_bytes(content.encode("utf-8"))


def _head_preview(content: str) -> str:
    """提取预览体头部：先按行截 PREVIEW_HEAD_LINES 行，再按字节截 PREVIEW_HEAD_BYTES。"""
    lines = content.splitlines(keepends=True)
    if len(lines) > PREVIEW_HEAD_LINES:
        lines = lines[:PREVIEW_HEAD_LINES]
    head = "".join(lines)
    head_bytes = head.encode("utf-8")
    if len(head_bytes) > PREVIEW_HEAD_BYTES:
        # 二次字节截断，需保证 UTF-8 边界对齐
        truncated = head_bytes[:PREVIEW_HEAD_BYTES]
        head = truncated.decode("utf-8", errors="replace")
    return head


def build_preview(original_bytes: int, head: str, spill_path: str) -> str:
    """构造替换体字符串，包含原始字节数、头部预览、落盘路径、重读提示。

    只在首次决策为替换时调用一次；之后所有轮次复用 _replacements 中存好的字符串。
    """
    parts = [
        f"[content offloaded] original size: {original_bytes} bytes",
        f"[saved to] {spill_path}",
        "[head preview]",
        head,
        "完整内容已保存到上述路径，如需查看请用文件读取工具读取该路径，不要凭头部预览猜测全文",
    ]
    return "\n".join(parts)


def offload_and_snip(
    msgs: list[Message],
    state: ContentReplacementState,
    session: SessionContext,
) -> list[Message]:
    """遍历 msgs，针对每条 role=="tool" 消息的 tool_results 做单条/聚合落盘。

    规则：
      1. 已 Seen 的 id 通过 decide_once 直接复用存量结果。
      2. 未决策的项按字节倒序处理：
         a. 单条 > SINGLE_RESULT_LIMIT → 落盘 → replaced
         b. 剩余聚合 > MESSAGE_AGGREGATE_LIMIT → 继续按倒序落盘
         c. 未落盘的 kept
      3. 落盘失败 → skip（保持原文，不写账本，下次重试）
      4. 落盘→改写→写账本在同一临界区内通过 decide_once 完成

    返回新的 list[Message]，不修改入参。
    """
    out = copy.deepcopy(msgs)

    tool_msg_count = 0
    total_results = 0
    for msg in out:
        if msg.role == "tool":
            tool_msg_count += 1
            total_results += len(msg.tool_results or [])

    import logging
    _log = logging.getLogger(__name__)
    _log.info("layer1: scanning %d msgs, %d tool msgs, %d tool_results",
              len(out), tool_msg_count, total_results)

    for msg in out:
        if msg.role != "tool":
            continue
        results = msg.tool_results
        if not results:
            continue

        # 分离已决策（在 _seen_ids 中）和未决策
        candidates: list[tuple[int, int]] = []  # [(index, byte_size)]

        for i, tr in enumerate(results):
            tid = tr.tool_call_id
            if tid in state._seen_ids:
                # 已决策：若是 replaced 则应用 preview，否则保持原文
                existing = state._replacements.get(tid)
                if existing is not None:
                    results[i] = type(results[i])(
                        tool_call_id=tid,
                        content=existing,
                        is_error=results[i].is_error,
                    )
                # kept → 保持原文
            else:
                bsize = len(tr.content.encode("utf-8"))
                candidates.append((i, bsize))

        if not candidates:
            continue

        # 未决策的项按字节倒序
        candidates.sort(key=lambda x: x[1], reverse=True)

        # 当前 RoleTool 消息内所有未决策项的字节聚合
        remaining_bytes = sum(bsize for _, bsize in candidates)

        for idx, bsize in candidates:
            tid = results[idx].tool_call_id
            content = results[idx].content

            must_spill = bsize > SINGLE_RESULT_LIMIT
            over_budget = remaining_bytes > MESSAGE_AGGREGATE_LIMIT

            _log.info("layer1 candidate: id=%s bsize=%d must_spill=%s over_budget=%s",
                      tid, bsize, must_spill, over_budget)

            if must_spill or over_budget:
                def _make_decide(tid_, content_, bsize_):
                    def _decide():
                        try:
                            spill_single(session, tid_, content_)
                        except OSError:
                            return ("skip", "")
                        spill_path = str(Path(session.spill_dir) / tid_)
                        preview = build_preview(
                            bsize_, _head_preview(content_), spill_path
                        )
                        return ("replaced", preview)
                    return _decide

                # 确保参数被正确捕获
                new_content = state.decide_once(
                    tid, content, _make_decide(tid, content, bsize)
                )
                results[idx] = type(results[idx])(
                    tool_call_id=tid,
                    content=new_content,
                    is_error=results[idx].is_error,
                )
                if new_content != content:
                    remaining_bytes -= bsize
                else:
                    # skip → 未替换，但已从 candidates 扣除预算影响
                    pass
            else:
                # kept
                state.decide_once(tid, content, lambda: ("kept", ""))

    return out
