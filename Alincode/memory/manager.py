"""记忆管理器：编排两级笔记的加载和异步更新（T12）。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from Alincode.memory.store import Store
from Alincode.memory.types import UpdateAction
from Alincode.memory.prompts import MEMORY_UPDATE_PROMPT
import Alincode.memory.store as _store_module

if TYPE_CHECKING:
    from Alincode.client import BaseProvider
    from Alincode.conversation import Message

logger = logging.getLogger(__name__)


class Manager:
    """编排项目级和用户级笔记。"""

    def __init__(
        self,
        project_dir: str,
        user_dir: str,
        provider: "BaseProvider | None" = None,
        model: str = "",
    ) -> None:
        self._project = Store(project_dir)
        self._user = Store(user_dir)
        self._provider = provider
        self._model = model

    def set_provider(self, provider: "BaseProvider", model: str) -> None:
        self._provider = provider
        self._model = model

    def load_index(self) -> str:
        """合并两级索引，截断到 25KB。"""
        parts: list[str] = []
        project_idx = self._project.load_index()
        user_idx = self._user.load_index()
        if project_idx.strip():
            parts.append(project_idx.strip())
        if user_idx.strip():
            parts.append(user_idx.strip())
        combined = "\n".join(parts)
        limit = _store_module.INDEX_MAX_BYTES
        if len(combined.encode("utf-8")) > limit:
            truncated = combined.encode("utf-8")[:limit]
            combined = truncated.decode("utf-8", errors="replace") + "\n(index truncated)"
        return combined

    async def update_async(self, recent_msgs: list["Message"]) -> None:
        """异步触发 LLM 记忆更新。失败静默。"""
        if self._provider is None:
            return
        try:
            await self._do_update(recent_msgs)
        except Exception as e:
            logger.warning("memory update failed: %s", e)

    async def _do_update(self, recent_msgs: list["Message"]) -> None:
        index = self.load_index()
        conv_text = self._serialize(recent_msgs)
        prompt = MEMORY_UPDATE_PROMPT.format(index=index or "(空)", conversation=conv_text)

        from Alincode.client import Request, System
        from Alincode.conversation import Message

        req = Request(
            system=System(stable="", environment=""),
            messages=[Message(role="user", content=prompt)],
            model=self._model,
            tools=[],
        )

        text_buf: list[str] = []
        async for ev in self._provider.stream(req):
            if ev.err:
                raise ev.err
            if ev.text:
                text_buf.append(ev.text)

        full = "".join(text_buf)
        # 提取 JSON 数组
        actions_data = _extract_json_array(full)
        if not actions_data:
            return

        actions = []
        for item in actions_data:
            actions.append(UpdateAction(
                action=item.get("action", ""),
                level=item.get("level", ""),
                type=item.get("type", ""),
                title=item.get("title", ""),
                slug=item.get("slug", ""),
                content=item.get("content", ""),
                filename=item.get("filename", ""),
            ))

        for act in actions:
            store = self._project if act.level == "project" else self._user
            await asyncio.to_thread(store.apply, [act])

    def _serialize(self, msgs: list["Message"]) -> str:
        """快速序列化消息列表为文本。"""
        parts: list[str] = []
        for m in msgs:
            role = m.role
            if role == "user":
                parts.append(f"用户: {m.content}")
            elif role == "assistant":
                if m.content:
                    parts.append(f"助手: {m.content}")
                for tc in (m.tool_calls or []):
                    parts.append(f"[调用工具 {tc.name}]")
            elif role == "tool":
                for tr in (m.tool_results or []):
                    parts.append(f"[工具结果: {tr.content[:200]}]")
        return "\n".join(parts)


def _extract_json_array(text: str) -> list[dict] | None:
    """从 LLM 输出中提取第一个 JSON 数组。"""
    import re
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group())
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return None
