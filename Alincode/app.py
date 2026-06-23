"""TUI 主控：Textual App，管理对话界面和组件交互。"""

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import Footer, Header, RichLog, TextArea

from Alincode.client import BaseProvider
from Alincode.conversation import ConversationManager


class ChatLog(RichLog):
    """对话日志组件，支持流式输出和消息着色。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(
            highlight=True,
            markup=True,
            wrap=True,
            max_lines=10000,
            **kwargs,
        )
        self._stream_buffer = ""

    def start_stream(self) -> None:
        """开始流式输出——写入 AI 消息前缀。"""
        self._stream_buffer = ""
        self.write("[bold #5f87ff]●[/bold #5f87ff] ", scroll_end=True)

    def stream_token(self, token: str) -> None:
        """追加 token，遇到换行时刷新到 RichLog 实现逐行流式输出。"""
        self._stream_buffer += token
        if "\n" in self._stream_buffer:
            lines = self._stream_buffer.split("\n")
            for line in lines[:-1]:
                self.write(line, scroll_end=True)
            self._stream_buffer = lines[-1]

    def finish_stream(self) -> None:
        """结束流式输出，刷新剩余 buffer。"""
        if self._stream_buffer:
            self.write(self._stream_buffer, scroll_end=True)
        self._stream_buffer = ""

    def append_user(self, text: str) -> None:
        """追加用户消息（绿色 ▸ 前缀）。"""
        self.write(f"[bold #00d700]▸[/bold #00d700] {text}")

    def append_assistant(self, text: str) -> None:
        """追加完整 AI 回复（蓝色 ● 前缀）。"""
        self.write(f"[bold #5f87ff]●[/bold #5f87ff] {text}")

    def append_thinking(self, text: str) -> None:
        """追加 thinking 内容（灰色 💭 前缀）。"""
        self.write(f"[#767676 italic]💭 {text}[/]")

    def append_info(self, text: str) -> None:
        """追加系统信息（灰色 ── 前缀）。"""
        self.write(f"[#767676 italic]── {text}[/]")

    def append_error(self, text: str) -> None:
        """追加错误信息。"""
        self.write(f"[bold #ff5555]✗ {text}[/]")


class MessageInput(TextArea):
    """消息输入组件：Enter 发送，Alt+Enter 换行。"""

    BINDINGS = [
        Binding("enter", "submit_message", "Send", priority=True, show=False),
        Binding("alt+enter", "insert_line", "New Line", show=False),
    ]

    class Submitted(Message):
        """输入提交事件。"""
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def action_submit_message(self) -> None:
        """Enter 发送消息。"""
        text = self.text.strip()
        if text:
            self.post_message(self.Submitted(text))
        self.clear()

    def action_insert_line(self) -> None:
        """Alt+Enter 插入换行符。"""
        self.insert("\n")


class AlinCodeApp(App):
    """AlinCode 终端 AI 编程助手主应用。"""

    TITLE = "AlinCode"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Exit", show=True),
        Binding("ctrl+q", "quit", "Exit", show=False),
        Binding("pageup", "scroll_up", "Page Up", show=False),
        Binding("pagedown", "scroll_down", "Page Down", show=False),
        Binding("ctrl+home", "scroll_home", "Scroll Top", show=False),
        Binding("ctrl+end", "scroll_end", "Scroll Bottom", show=False),
    ]

    def __init__(self, provider: BaseProvider, model: str) -> None:
        super().__init__()
        self._provider = provider
        self._model = model
        self._conv = ConversationManager()
        self._chatting = False

    def compose(self) -> ComposeResult:
        """组装 UI 布局。"""
        yield Header(show_clock=False)
        yield Container(ChatLog(id="chat-log"))
        yield MessageInput(id="message-input", language="markdown")
        yield Footer()

    def on_mount(self) -> None:
        """启动后显示欢迎信息和状态。"""
        chat_log = self.query_one("#chat-log", ChatLog)
        model_info = f"{self._provider.provider_name} │ {self._model}"
        chat_log.append_info(f"══ AlinCode v0.2 ══  {model_info}  ══")
        self.sub_title = model_info

    # ── Keyboard actions ──────────────────────────────────────

    def action_scroll_up(self) -> None:
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.scroll_page_up()

    def action_scroll_down(self) -> None:
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.scroll_page_down()

    def action_scroll_home(self) -> None:
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.scroll_home()

    def action_scroll_end(self) -> None:
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.scroll_end()

    # ── Message handling ──────────────────────────────────────

    @on(MessageInput.Submitted)
    async def _on_input_submitted(self, event: MessageInput.Submitted) -> None:
        """处理用户输入。"""
        user_text = event.text.strip()
        chat_log = self.query_one("#chat-log", ChatLog)

        # 内置命令
        if user_text == "/exit":
            self.exit()
            return
        if user_text == "/clear":
            self._conv.clear()
            chat_log.append_info("对话历史已清空")
            return

        # 并发保护
        if self._chatting:
            chat_log.append_info("请等待当前回复完成...")
            return

        # 追加用户消息
        chat_log.append_user(user_text)
        self._conv.add_user(user_text)
        self.sub_title = f"{self._provider.provider_name} │ {self._model} │ 第 {self._conv.turn_count} 轮"

        # 异步调用 LLM
        self._chatting = True
        await self._do_chat(chat_log)

    async def _do_chat(self, chat_log: ChatLog) -> None:
        """调用 provider.chat() 流式获取回复。"""
        chat_log.start_stream()
        full_response = ""
        try:
            async for token in self._provider.chat(self._conv.messages, self._model):
                full_response += token
                chat_log.stream_token(token)
        except Exception as e:
            chat_log.append_error(f"错误: {e}")
        finally:
            chat_log.finish_stream()
            if full_response.strip():
                self._conv.add_assistant(full_response)
            self._chatting = False
