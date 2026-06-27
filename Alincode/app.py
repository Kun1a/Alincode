"""TUI 主控：Textual App — 逐字流式 + 工具行 + 累积渲染。"""

from __future__ import annotations

import asyncio
import time

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message as TuiMessage
from textual.widgets import Footer, Header, RichLog, TextArea, Static

from Alincode.agent import Agent, CompactPhase, CompactEvent, Phase as AgentPhase
from Alincode.client import BaseProvider
from Alincode.conversation import ConversationManager
from Alincode.permission import Mode, ApprovalRequest, Outcome
from Alincode.permission.engine import PermissionEngine
from Alincode.prompts import SYSTEM_PROMPT, EXECUTE_DIRECTIVE
from Alincode.runtime import SessionRuntime
from Alincode.tools import Registry


# ── Streaming text widget ─────────────────────────────────

class StreamText(Static):
    """流式文本区——每收到 token 用 update(accumulated_text) 刷新。"""
    pass


# ── Indicator widget ──────────────────────────────────────

class StreamIndicator(Static):
    """流式状态指示器——工具执行 / 思考中。"""
    pass


# ── Tool display ──────────────────────────────────────────

class ToolDisplay:
    def __init__(self, name: str = "", args: str = "") -> None:
        self.name = name
        self.args = args
        self.started_at: float = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at


# ── ChatLog ───────────────────────────────────────────────

class ChatLog(RichLog):
    """对话日志——只做永久消息写入，不管流式。审批态接受方向键。"""

    BINDINGS = [
        Binding("up", "approve_up_in_log", "", show=False),
        Binding("down", "approve_down_in_log", "", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(highlight=True, markup=True, wrap=True, max_lines=10000, **kwargs)
        self.can_focus = False

    def action_approve_up_in_log(self) -> None:
        """转发给 App。"""
        if hasattr(self.app, '_pending_approval') and self.app._pending_approval:
            self.app.action_approve_up()

    def action_approve_down_in_log(self) -> None:
        if hasattr(self.app, '_pending_approval') and self.app._pending_approval:
            self.app.action_approve_down()

    def append_user(self, text: str) -> None:
        self.write("")
        self.write(f"[bold #00d700]▶[/] [bold #ffffff]{text}[/]")
        self.write("")

    def append_tool_line(self, name: str, args: str) -> None:
        self.write(f"  [bold cyan]⚙[/] [bold #00afaf]{name}[/] [dim]{args}[/]")

    def append_tool_result(self, result: str, is_error: bool = False) -> None:
        style = "bold #ff5555" if is_error else "#888888"
        lines = result.strip().split("\n")
        preview = "\n".join(lines[:8])
        if len(lines) > 8:
            preview += f"\n[dim]  … ({len(lines)} 行)[/]"
        first = True
        for line in preview.split("\n"):
            prefix = "   [bold #888888]⤷[/]" if first else "    "
            self.write(f"{prefix} [{style}]{line}[/]")
            first = False

    def append_markdown_block(self, text: str) -> None:
        """把 Markdown 文本作为富内容写入 RichLog。"""
        from rich.markdown import Markdown
        self.write(Markdown(text))

    def append_info(self, text: str) -> None:
        self.write(f"[#767676 italic]── {text}[/]")

    def append_error(self, text: str) -> None:
        self.write(f"[bold #ff5555]✗ {text}[/]")

    def append_notice(self, text: str) -> None:
        self.write(f"[#767676 italic]── {text}[/]")


# ── MessageInput ─────────────────────────────────────────

class MessageInput(TextArea):
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


# ── Helpers ──────────────────────────────────────────────

def _fmt_tok(n: int) -> str:
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)

def _fmt_dur(secs: float) -> str:
    if secs < 1:
        return "<1s"
    if secs < 60:
        return f"{secs:.0f}s"
    m, s = divmod(int(secs), 60)
    return f"{m}m{s:02d}s"


# ── AlinCodeApp ──────────────────────────────────────────

# ── Compact 系统消息格式化 ──────────────────────────

def format_compact_notice(ev: CompactEvent) -> str:
    """按 phase 渲染压缩状态提示（自动/紧急/手动三条路径共用）。"""
    if ev.phase == CompactPhase.BEFORE_AUTO:
        return "正在压缩上下文..."
    if ev.phase == CompactPhase.BEFORE_EMERGENCY:
        return "上下文撞墙，自动压缩中..."
    if ev.phase in (CompactPhase.AFTER_AUTO, CompactPhase.AFTER_EMERGENCY):
        if ev.err:
            return f"压缩失败：{ev.err}"
        return f"已压缩，token 从 {ev.before} 降至 {ev.after}"
    return ""


class AlinCodeApp(App):
    TITLE = "AlinCode"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("ctrl+c", "cancel_or_quit", "Cancel/Exit", show=True),
        Binding("escape", "cancel_turn", "Cancel", show=False),
        Binding("ctrl+p", "cycle_mode", "Mode", show=False, priority=True),
        Binding("1", "approve_1", "", show=False),
        Binding("2", "approve_2", "", show=False),
        Binding("3", "approve_3", "", show=False),
        Binding("up", "approve_up", "", show=False),
        Binding("down", "approve_down", "", show=False),
        Binding("space", "approve_enter", "", show=False),
        Binding("pageup", "scroll_up", "PgUp", show=False),
        Binding("pagedown", "scroll_down", "PgDn", show=False),
        Binding("ctrl+home", "scroll_home", "Top", show=False),
        Binding("ctrl+end", "scroll_end", "End", show=False),
    ]

    def __init__(self, provider: BaseProvider, model: str, registry: Registry,
                 engine: PermissionEngine | None = None,
                 runtime: SessionRuntime | None = None) -> None:
        super().__init__()
        self._provider = provider
        self._model = model
        self._tool_registry = registry
        self._engine = engine or PermissionEngine()
        self.runtime = runtime or SessionRuntime()
        self.agent = Agent(
            provider=provider, registry=registry, model=model,
            version="0.3.0", engine=self._engine,
            runtime=self.runtime,
        )
        self._conv = ConversationManager()
        self._chatting = False
        self._mode: Mode = Mode.DEFAULT
        self._stream_task: asyncio.Task | None = None
        self._turn_cancel: asyncio.Event | None = None
        self._cur_tools: list[ToolDisplay] = []
        self._iter: int = 0
        self._usage_in: int = 0
        self._usage_out: int = 0
        self._refresh_timer: asyncio.Task | None = None
        self._stream_started_at: float = 0.0
        self._pending_approval: ApprovalRequest | None = None
        self._approve_cursor: int = 0  # 0=允许本次, 1=永久允许, 2=拒绝本次

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield ChatLog(id="chat-log")
        yield StreamText(id="stream-text")
        yield StreamIndicator(id="stream-indicator")
        yield MessageInput(id="message-input")
        yield Static(id="quick-bar")
        yield Footer()

    def on_mount(self) -> None:
        chat_log = self.query_one("#chat-log", ChatLog)
        model_info = f"{self._provider.provider_name} │ {self._model}"
        chat_log.write("")
        chat_log.write("[bold #00afaf]"
            "           ⣀⣀⣀⣀\n"
            "         ⢀⣿⣿⣿⣿⣿⡀\n"
            "        ⢰⣿⣿⣿⣿⣿⣿⣿⡆\n"
            "        ⣸⣿⣿⣿⣿⣿⣿⣿⣇\n"
            "       ⢰⣿⣿⠉   ⠉⣿⣿⡆\n"
            "       ⣿⣿⣿⡀   ⣿⣿⣿\n"
            "      ⢠⣿⣿⣿⣿⣿⣿⣿⣿⡄\n"
            "      ⣼⣿⡟⠉⠉⠉⠉⢻⣿⣧\n"
            "      ⣿⣿⡇       ⢸⣿⣿\n"
            "      ⠻⢿⣿⣤⣀⣀⣤⣿⡿⠟\n"
            "         ⠉⠉⠉⠉⠉⠉"
            "[/]")
        chat_log.write("")
        chat_log.append_info(f"[bold #ffaa00]AlinCode[/] v0.3 │ {model_info}")
        chat_log.write("")
        self._update_status()
        self._conv.add_system(SYSTEM_PROMPT)
        self._update_indicator()
        # MCP 工具统计
        all_tools = self._tool_registry.definitions()
        mcp_tools = [d for d in all_tools if d.name.startswith("mcp__")]
        if mcp_tools:
            servers = len({t.name.split("__")[1] for t in mcp_tools})
            chat_log.append_info(
                f"Connected to {servers} MCP server(s), "
                f"{len(mcp_tools)} tool(s) registered"
            )
        self._update_quick_bar()
        self.query_one("#message-input", TextArea).focus()

    def _stream_widget(self) -> StreamText:
        return self.query_one("#stream-text", StreamText)

    # ── Status ──────────────────────────────────────────

    def _update_quick_bar(self) -> None:
        """更新输入框下的快捷栏：模式切换 + 模型名。"""
        bar = self.query_one("#quick-bar", Static)
        modes = [
            ("default", "Default"),
            ("acceptEdits", "AcceptEdits"),
            ("plan", "Plan"),
            ("bypass", "Bypass"),
        ]
        parts = ["[bold]权限模式:[/]"]
        for val, label in modes:
            mode_key = {"default": Mode.DEFAULT, "acceptEdits": Mode.ACCEPT_EDITS,
                        "plan": Mode.PLAN, "bypass": Mode.BYPASS}[val]
            if self._mode == mode_key:
                parts.append(f" [bold white on #5f87ff] {label} [/]")
            else:
                parts.append(f" [dim]{label}[/]")
        parts.append(f"    [dim]模型: {self._model}[/]")
        parts.append("    [dim]Ctrl+P 切换模式[/]")
        bar.update("".join(parts))

    def _update_status(self) -> None:
        mode_labels = {
            Mode.DEFAULT: "DEFAULT",
            Mode.ACCEPT_EDITS: "ACCEPT EDITS",
            Mode.PLAN: "PLAN",
            Mode.BYPASS: "BYPASS",
        }
        label = mode_labels.get(self._mode, str(self._mode.value))
        parts = [f"[bold #ffaa00]{label}[/]"]
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

    # ── Indicator ───────────────────────────────────────

    def _elapsed_since_stream_start(self) -> float:
        if self._stream_started_at == 0:
            return 0
        return time.monotonic() - self._stream_started_at

    def _update_indicator(self) -> None:
        try:
            indicator = self.query_one("#stream-indicator", StreamIndicator)
        except Exception:
            return  # widget 可能已销毁（关闭时）
        if self._pending_approval:
            ap = self._pending_approval
            c = self._approve_cursor
            opts = [
                ("[1] 允许本次", "#00d700"),
                ("[2] 永久允许", "#ffaa00"),
                ("[3] 拒绝本次", "#ff5555"),
            ]
            lines = []
            for i, (label, color) in enumerate(opts):
                if i == c:
                    lines.append(f"  [bold white on {color}]  {label}  [/]")
                else:
                    lines.append(f"  [{color}]  {label}  [/]")
            indicator.update(
                f"[bold #ffaa00]🔒 待批准: {ap.tool_name}({ap.tool_args})[/]\n"
                + "\n".join(lines)
                + "\n[dim]↑↓ 选择  空格 确认  1/2/3 快捷  Esc 拒绝[/]"
            )
        elif self._cur_tools:
            lines = []
            for td in self._cur_tools:
                lines.append(
                    f"  [bold cyan]⚙[/] [bold #00afaf]{td.name}[/]"
                    f"[dim]({td.args})[/] [bold #ffaa00]Running… {_fmt_dur(td.elapsed)}[/]"
                )
            indicator.update("\n".join(lines))
        elif self._chatting:
            dur = _fmt_dur(self._elapsed_since_stream_start())
            msg = f"  [bold #5f87ff]●[/] Imagining… ({dur})"
            if self._iter > 0:
                msg += f" · 第 {self._iter} 轮"
            indicator.update(msg)
        else:
            indicator.update("")

    async def _indicator_loop(self) -> None:
        while self._chatting:
            self._update_indicator()
            await asyncio.sleep(0.25)

    # ── Keyboard ────────────────────────────────────────

    def action_cancel_or_quit(self) -> None:
        if self._pending_approval:
            self._approve(Outcome.DENY_ONCE)
        elif self._chatting and self._turn_cancel:
            self._turn_cancel.set()
        else:
            self.exit()

    def action_cycle_mode(self) -> None:
        """Shift+Tab：循环切换权限模式。"""
        order = [Mode.DEFAULT, Mode.ACCEPT_EDITS, Mode.PLAN, Mode.BYPASS]
        idx = order.index(self._mode) if self._mode in order else 0
        self._mode = order[(idx + 1) % len(order)]
        self._update_status()
        chat_log = self.query_one("#chat-log", ChatLog)
        mode_labels = {
            Mode.DEFAULT: "DEFAULT — 只读放行，写/执行需确认",
            Mode.ACCEPT_EDITS: "ACCEPT EDITS — 文件写放行，命令执行需确认",
            Mode.PLAN: "PLAN — 仅只读工具，产出计划",
            Mode.BYPASS: "BYPASS — 全部放行（黑名单/沙箱除外）",
        }
        chat_log.append_info(f"权限模式: {mode_labels.get(self._mode, '')}")
        self._update_quick_bar()

    def _approve(self, outcome: Outcome) -> None:
        """用户做出审批选择。"""
        if self._pending_approval and self._pending_approval.respond:
            if not self._pending_approval.respond.done():
                self._pending_approval.respond.set_result(outcome)
            chat_log = self.query_one("#chat-log", ChatLog)
            labels = {Outcome.ALLOW_ONCE: "允许本次", Outcome.ALLOW_FOREVER: "永久允许",
                      Outcome.DENY_ONCE: "拒绝本次"}
            chat_log.append_info(f"→ {labels.get(outcome, str(outcome))}")
        self._pending_approval = None
        self._approve_cursor = 0
        chat_log = self.query_one("#chat-log", ChatLog)
        chat_log.can_focus = False  # 恢复不可聚焦
        self.query_one("#message-input", TextArea).focus()
        self._update_indicator()

    def action_approve_1(self) -> None:
        if self._pending_approval:
            self._approve(Outcome.ALLOW_ONCE)

    def action_approve_2(self) -> None:
        if self._pending_approval:
            self._approve(Outcome.ALLOW_FOREVER)

    def action_approve_3(self) -> None:
        if self._pending_approval:
            self._approve(Outcome.DENY_ONCE)

    def action_approve_up(self) -> None:
        if self._pending_approval:
            self._approve_cursor = (self._approve_cursor - 1) % 3
            self._update_indicator()

    def action_approve_down(self) -> None:
        if self._pending_approval:
            self._approve_cursor = (self._approve_cursor + 1) % 3
            self._update_indicator()

    def action_approve_enter(self) -> None:
        if self._pending_approval:
            outcomes = [Outcome.ALLOW_ONCE, Outcome.ALLOW_FOREVER, Outcome.DENY_ONCE]
            self._approve(outcomes[self._approve_cursor])

    def action_cancel_turn(self) -> None:
        if self._chatting and self._turn_cancel:
            self._turn_cancel.set()
        if self._pending_approval:
            self._approve(Outcome.DENY_ONCE)

    def action_scroll_up(self) -> None:
        self.query_one("#chat-log", ChatLog).scroll_page_up()
    def action_scroll_down(self) -> None:
        self.query_one("#chat-log", ChatLog).scroll_page_down()
    def action_scroll_home(self) -> None:
        self.query_one("#chat-log", ChatLog).scroll_home()
    def action_scroll_end(self) -> None:
        self.query_one("#chat-log", ChatLog).scroll_end()

    # ── Commands ─────────────────────────────────────────

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
            chat_log.append_info(f"全部({len(defs)}): {', '.join(d.name for d in defs)}")
            chat_log.append_info(f"只读({len(rdefs)}): {', '.join(d.name for d in rdefs)}")
            return
        if user_text == "/plan":
            self._mode = Mode.PLAN
            self._update_status()
            self._update_quick_bar()
            chat_log.append_info("[PLAN] 计划模式——仅只读工具可用。完成后 /do 执行")
            return
        if user_text == "/do":
            self._mode = Mode.DEFAULT
            self._update_status()
            self._update_quick_bar()
            chat_log.append_info("[DO] 执行模式——全部工具可用")
            self._conv.add_user(EXECUTE_DIRECTIVE)
            self._chatting = True
            self._start_agent(chat_log)
            return
        if user_text == "/compact":
            if self._chatting:
                chat_log.append_info("请等待当前回复完成后再压缩...")
                return
            # 在后台触发压缩
            asyncio.create_task(self._do_compact(chat_log))
            return

        # 未知斜杠命令
        if user_text.startswith("/"):
            chat_log.append_info(
                f"未知命令: {user_text}，可用命令: /exit /plan /do /compact /tools /clear"
            )
            return

        if self._chatting:
            chat_log.append_info("请等待当前回复完成...")
            return

        chat_log.append_user(user_text)
        self._conv.add_user(user_text)
        self._update_status()
        self._chatting = True
        self._update_quick_bar()
        self._start_agent(chat_log)

    async def _do_compact(self, chat_log: ChatLog) -> None:
        """后台执行 /compact：调 agent.run_force_compact 并显示结果。"""
        try:
            defs = self._tool_registry.definitions()
            before, after = await self.agent.run_force_compact(self._conv, defs)
            ev = CompactEvent(phase=CompactPhase.AFTER_AUTO, before=before, after=after)
            chat_log.append_notice(format_compact_notice(ev))
        except Exception as exc:
            ev = CompactEvent(phase=CompactPhase.AFTER_AUTO, before=0, after=0, err=exc)
            chat_log.append_notice(format_compact_notice(ev))

    def _start_agent(self, chat_log: ChatLog) -> None:
        self._turn_cancel = asyncio.Event()
        self._iter = 0
        self._cur_tools = []
        self._stream_started_at = time.monotonic()
        self._stream_widget().update("")
        self._stream_task = asyncio.create_task(self._consume_events(chat_log))
        self._refresh_timer = asyncio.create_task(self._indicator_loop())

    async def _consume_events(self, chat_log: ChatLog) -> None:
        accumulated = ""
        stream_widget = self._stream_widget()

        def _commit_to_log(text: str) -> None:
            """把累积文本固化到 RichLog（Markdown 渲染）。"""
            if not text.strip():
                return
            chat_log.write("")  # 空行
            chat_log.write("[bold #5f87ff]●[/] ", scroll_end=True)
            from rich.markdown import Markdown
            chat_log.write(Markdown(text.strip()))

        try:
            async for ev in self.agent.run(self._conv, mode=self._mode, cancel=self._turn_cancel):
                if ev.compact:
                    # 上下文压缩状态事件（不写入 conversation）
                    notice = format_compact_notice(ev.compact)
                    chat_log.append_notice(notice)
                    continue

                if ev.err:
                    _commit_to_log(accumulated)
                    accumulated = ""
                    stream_widget.update("")
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
                    accumulated += ev.text
                    # ★ 核心：累积文本 → 替换式刷新（不产生重复条目）
                    stream_widget.update(
                        "[bold #5f87ff]●[/] " + accumulated
                    )

                if ev.tool and ev.tool.phase == AgentPhase.START:
                    # 工具调用前：固化 preamble 到 RichLog
                    _commit_to_log(accumulated)
                    accumulated = ""
                    stream_widget.update("")
                    self._cur_tools.append(ToolDisplay(
                        name=ev.tool.name, args=ev.tool.args,
                    ))
                    self._update_indicator()

                if ev.tool and ev.tool.phase == AgentPhase.END:
                    chat_log.append_tool_line(ev.tool.name, ev.tool.args)
                    chat_log.append_tool_result(
                        ev.tool.result, is_error=ev.tool.is_error,
                    )
                    if self._cur_tools:
                        self._cur_tools.pop(0)
                    self._update_indicator()

                if ev.approval:
                    # 人在回路——显示交互式审批提示
                    self._pending_approval = ev.approval
                    self._approve_cursor = 0
                    chat_log.can_focus = True
                    chat_log.focus()
                    approval = ev.approval
                    chat_log.write("")
                    chat_log.write(
                        f"[bold #ffaa00]━━━ 权限确认 ━━━[/]\n"
                        f"  工具: [bold]{approval.tool_name}({approval.tool_args})[/]\n"
                        f"  原因: {approval.reason}\n\n"
                        f"  [bold on #00d700 #ffffff]  [1] 允许本次        [/]\n"
                        f"  [bold #ffaa00]  [2] 永久允许        [/]\n"
                        f"  [bold #ff5555]  [3] 拒绝本次        [/]\n"
                        f"  [dim]↑↓ 选择  空格 确认  Esc 拒绝[/]"
                    )
                    chat_log.write("")
                    self._update_indicator()

                if ev.done:
                    _commit_to_log(accumulated)
                    accumulated = ""
                    stream_widget.update("")
                    self._cur_tools = []
                    self._iter = 0
                    self._update_indicator()
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            chat_log.append_error(f"异常: {e}")
        finally:
            accumulated = accumulated  # no-op
            stream_widget.update("")
            self._cur_tools = []
            self._iter = 0
            self._chatting = False
            self._stream_task = None
            self._turn_cancel = None
            self._stream_started_at = 0
            self._update_indicator()
            self._update_status()
            self._update_quick_bar()
            if self._refresh_timer:
                self._refresh_timer.cancel()
