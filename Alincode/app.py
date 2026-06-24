"""TUI 主控：Textual App，管理对话界面和组件交互。"""

from __future__ import annotations

import asyncio
import time

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message as TuiMessage
from textual.widgets import Footer, Header, RichLog, TextArea

from Alincode.agent import Agent, Phase as AgentPhase
from Alincode.client import BaseProvider
from Alincode.conversation import ConversationManager
from Alincode.prompts import SYSTEM_PROMPT
from Alincode.tools import Registry


# ── Tool display tracking ────────────────────────────────────

class ToolDisplay:
    """正在执行中的工具状态（供流式渲染）。"""
    def __init__(self, name: str = "", args: str = "") -> None:
        self.name = name
        self.args = args
        self.started_at: float = time.monotonic()


# ── ChatLog ──────────────────────────────────────────────────

class ChatLog(RichLog):
    """对话日志组件，支持流式输出、工具行和消息着色。"""

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
        """追加 token，遇到换行时刷新到 RichLog。"""
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

    def append_tool_line(self, name: str, args: str) -> None:
        """追加工具调用行（青色 ● 工具名(参数)）。"""
        self.write(f"[bold cyan]●[/bold cyan] [bold]{name}({args})[/bold]")

    def append_tool_result(self, result: str, is_error: bool = False) -> None:
        """追加工具结果摘要（缩进的 ⎿ 前缀）。"""
        style = "red" if is_error else "#888888"
        lines = result.strip().split("\n")
        MAX_LINES = 8
        preview = "\n".join(lines[:MAX_LINES])
        if len(lines) > MAX_LINES:
            preview += f"\n[dim]  … ({len(lines)} 行，结果已截断)[/]"
        self.write(f"[{style}]  ⎿ {preview}[/]")

    def append_thinking(self, text: str) -> None:
        """追加 thinking 内容（灰色 💭 前缀）。"""
        self.write(f"[#767676 italic]💭 {text}[/]")

    def append_info(self, text: str) -> None:
        """追加系统信息（灰色 ── 前缀）。"""
        self.write(f"[#767676 italic]── {text}[/]")

    def append_error(self, text: str) -> None:
        """追加错误信息。"""
        self.write(f"[bold #ff5555]✗ {text}[/]")


# ── MessageInput ────────────────────────────────────────────

class MessageInput(TextArea):
    """消息输入组件：Enter 发送，Alt+Enter 换行。"""

    BINDINGS = [
        Binding("enter", "submit_message", "Send", priority=True, show=False),
        Binding("alt+enter", "insert_line", "New Line", show=False),
    ]

    class Submitted(TuiMessage):
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


# ── AlinCodeApp ─────────────────────────────────────────────

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

    def __init__(self, provider: BaseProvider, model: str, registry: Registry) -> None:
        super().__init__()
        self._provider = provider
        self._model = model
        self._tool_registry = registry
        self._conv = ConversationManager()
        self._chatting = False
        self._cur_tool: ToolDisplay | None = None

    def compose(self) -> ComposeResult:
        """组装 UI 布局。"""
        yield Header(show_clock=False)
        yield Container(ChatLog(id="chat-log"))
        yield MessageInput(id="message-input", language="markdown")
        yield Footer()

    def on_mount(self) -> None:
        """启动后显示欢迎信息和状态，注入系统提示词。"""
        chat_log = self.query_one("#chat-log", ChatLog)
        model_info = f"{self._provider.provider_name} │ {self._model}"
        chat_log.append_info(f"══ AlinCode v0.2 ══  {model_info}  ══")
        self.sub_title = model_info

        # 注入系统提示词
        self._conv.add_system(SYSTEM_PROMPT)

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
            # 重新注入系统提示词
            self._conv.add_system(SYSTEM_PROMPT)
            chat_log.append_info("对话历史已清空")
            return
        if user_text == "/tools":
            defs = self._tool_registry.definitions()
            chat_log.append_info("已注册工具: " + ", ".join(d.name for d in defs))
            return

        # 并发保护
        if self._chatting:
            chat_log.append_info("请等待当前回复完成...")
            return

        # 追加用户消息
        chat_log.append_user(user_text)
        self._conv.add_user(user_text)
        self.sub_title = (
            f"{self._provider.provider_name} │ {self._model} │ 第 {self._conv.turn_count} 轮"
        )

        # 启动 agent 流式处理
        self._chatting = True
        await self._consume_agent_events(chat_log)

    async def _consume_agent_events(self, chat_log: ChatLog) -> None:
        """驱动 Agent.run() 异步流，分派渲染事件。"""
        agent = Agent(self._provider, self._tool_registry, self._model)
        cur_reply = ""

        try:
            async for ev in agent.run(self._conv):
                if ev.err:
                    chat_log.append_error(f"错误: {ev.err}")
                    self._finish_turn(chat_log, cur_reply)
                    return

                if ev.text:
                    cur_reply += ev.text
                    # 动态区显示：流式输出到 RichLog
                    if not self._cur_tool:
                        if not hasattr(self, "_stream_started"):
                            self._stream_started = True
                            chat_log.start_stream()
                        chat_log.stream_token(ev.text)

                if ev.tool and ev.tool.phase == AgentPhase.START:
                    # 先提交 preamble
                    if cur_reply.strip():
                        if hasattr(self, "_stream_started"):
                            chat_log.finish_stream()
                            delattr(self, "_stream_started")
                        cur_reply = ""
                    self._cur_tool = ToolDisplay(
                        name=ev.tool.name,
                        args=ev.tool.args,
                    )

                if ev.tool and ev.tool.phase == AgentPhase.END:
                    # 提交工具行 + 结果
                    chat_log.append_tool_line(ev.tool.name, ev.tool.args)
                    chat_log.append_tool_result(
                        ev.tool.result,
                        is_error=ev.tool.is_error,
                    )
                    self._cur_tool = None

                if ev.done:
                    self._finish_turn(chat_log, cur_reply)
                    cur_reply = ""
                    return

        except asyncio.CancelledError:
            pass
        except Exception as e:
            chat_log.append_error(f"异常: {e}")
            self._finish_turn(chat_log, cur_reply)

    def _finish_turn(self, chat_log: ChatLog, cur_reply: str) -> None:
        """结束本轮：提交剩余文本，清理状态。"""
        if hasattr(self, "_stream_started"):
            chat_log.finish_stream()
            delattr(self, "_stream_started")
        self._cur_tool = None
        self._chatting = False
