"""TUI 主控：Textual App，对话界面、Agent Loop、工具行渲染。"""

from __future__ import annotations

import asyncio
import time

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message as TuiMessage
from textual.widgets import Footer, Header, RichLog, TextArea, Static

from Alincode.agent import Agent, Mode, Phase as AgentPhase
from Alincode.client import BaseProvider
from Alincode.conversation import ConversationManager
from Alincode.prompts import SYSTEM_PROMPT, EXECUTE_DIRECTIVE
from Alincode.tools import Registry


# ── Streaming indicator widget ──────────────────────────────

class StreamIndicator(Static):
    """流式状态指示器——显示工具执行进度 / 思考中。"""
    pass


# ── Tool display tracking ────────────────────────────────────

class ToolDisplay:
    """正在执行中的工具状态。"""
    def __init__(self, name: str = "", args: str = "") -> None:
        self.name = name
        self.args = args
        self.started_at: float = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at


# ── ChatLog ──────────────────────────────────────────────────

class ChatLog(RichLog):
    """对话日志组件——流式输出 + 工具行 + 消息着色。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(highlight=True, markup=True, wrap=True, max_lines=10000, **kwargs)
        self._stream_buffer = ""
        self.can_focus = False  # 不抢输入框焦点

    # ── 流式输出 ──────────────────────────────────────

    def start_stream(self) -> None:
        self._stream_buffer = ""

    def stream_token(self, token: str) -> None:
        self._stream_buffer += token
        if "\n" in self._stream_buffer:
            lines = self._stream_buffer.split("\n")
            for line in lines[:-1]:
                self.write(line, scroll_end=True)
            self._stream_buffer = lines[-1]

    def finish_stream(self) -> None:
        if self._stream_buffer:
            self.write(self._stream_buffer, scroll_end=True)
        self._stream_buffer = ""

    # ── 消息行 ────────────────────────────────────────

    def append_user(self, text: str) -> None:
        self.write(f"[bold #00d700]▸[/] {text}")

    def append_tool_line(self, name: str, args: str) -> None:
        self.write(f"  [bold cyan]●[/] [bold]{name}({args})[/]")

    def append_tool_result(self, result: str, is_error: bool = False) -> None:
        style = "bold red" if is_error else "#888888"
        lines = result.strip().split("\n")
        MAX_LINES = 8
        preview = "\n".join(lines[:MAX_LINES])
        if len(lines) > MAX_LINES:
            preview += f"\n[dim]  … ({len(lines)} 行)[/]"
        for line in preview.split("\n"):
            self.write(f"   [{style}]⎿[/] [{style}]{line}[/]")

    def append_info(self, text: str) -> None:
        self.write(f"[#888888 italic]── {text}[/]")

    def append_error(self, text: str) -> None:
        self.write(f"[bold #ff5555]✗ {text}[/]")

    def append_notice(self, text: str) -> None:
        self.write(f"[#888888 italic]── {text}[/]")


# ── MessageInput ────────────────────────────────────────────

class MessageInput(TextArea):
    """单行输入框——Enter 发送，Alt+Enter 换行。"""

    BINDINGS = [
        Binding("enter", "submit_message", "Send", priority=True, show=False),
        Binding("alt+enter", "insert_line", "New Line", show=False),
    ]

    class Submitted(TuiMessage):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def action_submit_message(self) -> None:
        text = self.text.strip()
        if text:
            self.post_message(self.Submitted(text))
        self.clear()

    def action_insert_line(self) -> None:
        self.insert("\n")


# ── AlinCodeApp ─────────────────────────────────────────────

def _fmt_tok(n: int) -> str:
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def _fmt_dur(secs: float) -> str:
    if secs < 60:
        return f"{secs:.0f}s"
    m, s = divmod(int(secs), 60)
    return f"{m}m{s:02d}s"


class AlinCodeApp(App):
    TITLE = "AlinCode"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("ctrl+c", "cancel_or_quit", "Cancel/Exit", show=True),
        Binding("escape", "cancel_turn", "Cancel", show=False),
        Binding("pageup", "scroll_up", "PgUp", show=False),
        Binding("pagedown", "scroll_down", "PgDn", show=False),
        Binding("ctrl+home", "scroll_home", "Top", show=False),
        Binding("ctrl+end", "scroll_end", "End", show=False),
    ]

    def __init__(self, provider: BaseProvider, model: str, registry: Registry) -> None:
        super().__init__()
        self._provider = provider
        self._model = model
        self._tool_registry = registry
        self._conv = ConversationManager()
        self._chatting = False
        self._mode: Mode = Mode.NORMAL
        self._stream_task: asyncio.Task | None = None
        self._turn_cancel: asyncio.Event | None = None
        self._cur_tools: list[ToolDisplay] = []
        self._iter: int = 0
        self._usage_in: int = 0
        self._usage_out: int = 0
        self._refresh_timer: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield ChatLog(id="chat-log")
        yield StreamIndicator(id="stream-indicator")
        yield MessageInput(id="message-input")
        yield Footer()

    def on_mount(self) -> None:
        chat_log = self.query_one("#chat-log", ChatLog)
        model_info = f"{self._provider.provider_name} │ {self._model}"
        chat_log.append_info(f"══ AlinCode v0.3 ══ {model_info} ══")
        self._update_status()
        self._conv.add_system(SYSTEM_PROMPT)
        self._update_indicator()
        # 确保输入框获得焦点
        self.query_one("#message-input", TextArea).focus()

    # ── Status bar ────────────────────────────────────────

    def _update_status(self) -> None:
        parts = [self._provider.provider_name]
        if self._mode == Mode.PLAN:
            parts.append("[b #ffaa00]PLAN[/]")
        parts.append(self._model)
        toks = []
        if self._usage_in:
            toks.append(f"↑{_fmt_tok(self._usage_in)}")
        if self._usage_out:
            toks.append(f"↓{_fmt_tok(self._usage_out)}")
        if toks:
            parts.append(" ".join(toks) + " tok")
        if self._iter > 0:
            parts.append(f"轮 {self._iter}")
        self.sub_title = " │ ".join(parts)

    # ── Streaming indicator ──────────────────────────────

    def _update_indicator(self) -> None:
        """刷新流式状态指示器。"""
        indicator = self.query_one("#stream-indicator", StreamIndicator)
        if self._cur_tools:
            lines = []
            for td in self._cur_tools:
                lines.append(f"  [bold cyan]●[/] [bold]{td.name}({td.args})[/] [bold #ffaa00]Running… {_fmt_dur(td.elapsed)}[/]")
            indicator.update("\n".join(lines))
        elif self._chatting:
            msg = f"  [bold #5f87ff]●[/] Imagining… ({_fmt_dur(0)})"
            if self._iter > 0:
                msg += f" · 第 {self._iter} 轮"
            indicator.update(msg)
        else:
            indicator.update("")

    async def _indicator_loop(self) -> None:
        """定时刷新指示器（chatting 期间 250ms 一次）。"""
        while self._chatting:
            self._update_indicator()
            await asyncio.sleep(0.25)

    # ── Keyboard ──────────────────────────────────────────

    def action_cancel_or_quit(self) -> None:
        if self._chatting and self._turn_cancel:
            self._turn_cancel.set()
        else:
            self.exit()

    def action_cancel_turn(self) -> None:
        if self._chatting and self._turn_cancel:
            self._turn_cancel.set()

    def action_scroll_up(self) -> None:
        self.query_one("#chat-log", ChatLog).scroll_page_up()

    def action_scroll_down(self) -> None:
        self.query_one("#chat-log", ChatLog).scroll_page_down()

    def action_scroll_home(self) -> None:
        self.query_one("#chat-log", ChatLog).scroll_home()

    def action_scroll_end(self) -> None:
        self.query_one("#chat-log", ChatLog).scroll_end()

    # ── Message handling ─────────────────────────────────

    @on(MessageInput.Submitted)
    async def _on_input_submitted(self, event: MessageInput.Submitted) -> None:
        user_text = event.text.strip()
        chat_log = self.query_one("#chat-log", ChatLog)

        if user_text == "/exit":
            self.exit()
            return
        if user_text == "/clear":
            self._conv.clear()
            self._conv.add_system(SYSTEM_PROMPT)
            chat_log.append_info("对话历史已清空")
            return
        if user_text == "/tools":
            defs = self._tool_registry.definitions()
            rdefs = self._tool_registry.read_only_definitions()
            names = ", ".join(d.name for d in defs)
            rnames = ", ".join(d.name for d in rdefs)
            chat_log.append_info(f"全部({len(defs)}): {names}")
            chat_log.append_info(f"只读({len(rdefs)}): {rnames}")
            return
        if user_text == "/plan":
            self._mode = Mode.PLAN
            self._update_status()
            chat_log.append_info("[PLAN] 计划模式——仅只读工具可用。输入需求制定方案，完成后 /do 执行")
            return
        if user_text == "/do":
            self._mode = Mode.NORMAL
            self._update_status()
            chat_log.append_info("[DO] 执行模式——全部工具可用")
            self._conv.add_user(EXECUTE_DIRECTIVE)
            self._chatting = True
            self._start_agent(chat_log)
            return

        if self._chatting:
            chat_log.append_info("请等待当前回复完成...")
            return

        chat_log.append_user(user_text)
        self._conv.add_user(user_text)
        self._update_status()
        self._chatting = True
        self._start_agent(chat_log)

    def _start_agent(self, chat_log: ChatLog) -> None:
        self._turn_cancel = asyncio.Event()
        self._iter = 0
        self._cur_tools = []
        self._stream_task = asyncio.create_task(self._consume_events(chat_log))
        self._refresh_timer = asyncio.create_task(self._indicator_loop())

    async def _consume_events(self, chat_log: ChatLog) -> None:
        agent = Agent(self._provider, self._tool_registry, self._model)
        cur_reply = ""
        stream_active = False

        try:
            async for ev in agent.run(self._conv, mode=self._mode, cancel=self._turn_cancel):
                if ev.err:
                    chat_log.append_error(f"错误: {ev.err}")
                    break

                if ev.notice:
                    chat_log.append_notice(ev.notice)

                if ev.usage:
                    self._usage_in = ev.usage.input_tokens
                    self._usage_out = ev.usage.output_tokens
                    self._update_status()

                if ev.iter:
                    self._iter = ev.iter
                    self._update_status()

                if ev.text:
                    cur_reply += ev.text
                    # 始终流式输出文本（不管是否有工具在跑）
                    if not stream_active:
                        stream_active = True
                    chat_log.stream_token(ev.text)

                if ev.tool and ev.tool.phase == AgentPhase.START:
                    # 首个工具前：提交 preamble 到 RichLog
                    if cur_reply.strip() and not self._cur_tools:
                        if stream_active:
                            chat_log.finish_stream()
                            stream_active = False
                        cur_reply = ""
                    self._cur_tools.append(ToolDisplay(
                        name=ev.tool.name, args=ev.tool.args,
                    ))
                    self._update_indicator()

                if ev.tool and ev.tool.phase == AgentPhase.END:
                    # 提交工具行 + 结果到 RichLog
                    chat_log.append_tool_line(ev.tool.name, ev.tool.args)
                    chat_log.append_tool_result(
                        ev.tool.result, is_error=ev.tool.is_error,
                    )
                    # FIFO 弹出（事件按序到达，先 START 的先 END）
                    if self._cur_tools:
                        self._cur_tools.pop(0)
                    self._update_indicator()

                if ev.done:
                    if stream_active:
                        chat_log.finish_stream()
                        stream_active = False
                    self._cur_tools = []
                    self._iter = 0
                    self._update_indicator()
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            chat_log.append_error(f"异常: {e}")
        finally:
            if stream_active:
                chat_log.finish_stream()
            self._cur_tools = []
            self._iter = 0
            self._chatting = False
            self._stream_task = None
            self._turn_cancel = None
            self._update_indicator()
            self._update_status()
            if self._refresh_timer:
                self._refresh_timer.cancel()
