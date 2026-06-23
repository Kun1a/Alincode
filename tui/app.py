"""TUI 主控：创建 prompt_toolkit Application，管理事件循环和组件交互。"""

import asyncio
from typing import List

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout

from provider import BaseProvider, Message
from tui.chat_area import ChatArea
from tui.input_area import InputArea
from tui.status_bar import StatusBar
from tui.styles import style


async def run(provider: BaseProvider, model: str) -> None:
    """启动全屏 TUI 对话界面。

    Args:
        provider: LLM provider 实例
        model: 模型名
    """
    # 组件实例
    status_bar = StatusBar()
    chat_area = ChatArea()
    messages: List[Message] = []

    # 欢迎信息
    status_bar.set_info(provider.provider_name, model)
    chat_area.append_info(f"══ MewCode v0.2 ══  {provider.provider_name} │ {model}  ══")

    # ---- 并发控制 ----
    _chatting = False  # 防止并发发送消息

    # ---- 输入回调 ----
    def on_input(text: str) -> None:
        """用户输入回调（由 InputArea 的 accept_handler 触发）。"""
        nonlocal _chatting

        # 处理内置命令
        cmd = text.strip()
        if cmd == "/exit":
            app.exit()
            return
        if cmd == "/clear":
            messages.clear()
            chat_area.append_info("对话历史已清空")
            return

        # 防止并发——上一轮回复尚未完成时拒绝新输入
        if _chatting:
            chat_area.append_info("请等待当前回复完成...")
            return

        # 追加用户消息
        chat_area.append_user(text)
        messages.append(Message(role="user", content=text))
        status_bar.update_turn_count(len([m for m in messages if m.role == "user"]))

        # 异步调用 LLM
        _chatting = True
        asyncio.create_task(_do_chat(text))

    async def _do_chat(_user_text: str) -> None:
        """异步调用 provider.chat() 并流式更新对话区。"""
        nonlocal _chatting
        chat_area.start_stream()
        full_response = ""
        try:
            async for token in provider.chat(messages, model):
                chat_area.stream_token(token)
                full_response += token
        except Exception as e:
            chat_area.append_info(f"错误: {e}")
        finally:
            chat_area.finish_stream()
            if full_response.strip():
                messages.append(Message(role="assistant", content=full_response))
            _chatting = False

    # ---- 输入区 ----
    input_area = InputArea(on_submit=on_input)

    # ---- 布局 ----
    layout = Layout(
        HSplit([
            status_bar,   # 顶栏 1 行
            chat_area,    # 对话区填充
            input_area,   # 输入区 4 行
        ])
    )

    # ---- 全局快捷键 ----
    kb = KeyBindings()

    @kb.add("c-c")
    def _(event):
        """Ctrl+C 退出。"""
        event.app.exit()

    @kb.add("pageup")
    def _(event):
        """PageUp 向上滚动对话区。"""
        chat_area.scroll_up(5)

    @kb.add("pagedown")
    def _(event):
        """PageDown 向下滚动对话区。"""
        chat_area.scroll_down(5)

    @kb.add("c-home")
    def _(event):
        """Ctrl+Home 滚回顶部。"""
        chat_area.scroll_up(9999)

    @kb.add("c-end")
    def _(event):
        """Ctrl+End 滚回底部。"""
        chat_area.scroll_to_bottom()

    # ---- Application ----
    app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=True,
        mouse_support=True,
    )

    await app.run_async()
