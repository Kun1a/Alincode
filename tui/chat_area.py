"""对话区：只读 Buffer + 自定义 Lexer 实现消息着色。"""

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.lexers import Lexer


class ChatLexer(Lexer):
    """对话区自定义词法高亮器——根据行前缀着色。

    前缀规则：
    - "▸ " 开头 → 绿色（用户）
    - "● " 开头 → 蓝色（AI）
    - "💭 " 或 "[THINKING]" 开头 → 灰色（思考）
    - "── " 开头 → 灰色（系统信息）
    """

    def lex_document(self, document: Document):
        """返回一个函数：get_line(line_index) -> [(style, text)]。"""

        def get_line(line_index: int) -> list:
            line = document.lines[line_index]
            if line.startswith("▸ "):
                return [
                    ("class:user-prefix", "▸ "),
                    ("", line[2:]),
                ]
            elif line.startswith("● "):
                return [
                    ("class:assistant-prefix", "● "),
                    ("", line[2:]),
                ]
            elif line.startswith("💭 ") or line.startswith("[THINKING]"):
                return [("class:thinking-text", line)]
            elif line.startswith("── ") or line.startswith("══ "):
                return [("class:info-text", line)]
            else:
                return [("", line)]

        return get_line


class ChatArea:
    """对话区组件，管理对话消息的追加和流式显示。"""

    def __init__(self) -> None:
        self._buffer = Buffer(
            multiline=True,
            document=Document(),
        )
        self._lexer = ChatLexer()
        self._control = BufferControl(
            buffer=self._buffer,
            lexer=self._lexer,
            input_processors=[],
            focusable=False,
        )

    def _append_text(self, text: str) -> None:
        """向 buffer 末尾追加一行文本。"""
        buf = self._buffer
        prefix = "\n" if buf.text else ""
        buf.cursor_position = len(buf.text)
        buf.insert_text(prefix + text)

    def _append_to_last_line(self, token: str) -> None:
        """向 buffer 最后一行追加 token（不换行）。"""
        buf = self._buffer
        buf.cursor_position = len(buf.text)
        buf.insert_text(token)

    def append_user(self, text: str) -> None:
        """追加用户消息（绿色 ▸ 前缀）。"""
        self._append_text(f"▸ {text}")

    def append_assistant(self, text: str) -> None:
        """追加 AI 回复（蓝色 ● 前缀）。"""
        self._append_text(f"● {text}")

    def append_thinking(self, text: str) -> None:
        """追加 thinking 内容（灰色 💭 前缀）。"""
        self._append_text(f"💭 {text}")

    def append_info(self, text: str) -> None:
        """追加系统信息（灰色 ── 前缀）。"""
        self._append_text(f"── {text}")

    def start_stream(self) -> None:
        """开始流式输出，写入 AI 前缀。"""
        buf = self._buffer
        prefix = "\n● " if buf.text else "● "
        buf.cursor_position = len(buf.text)
        buf.insert_text(prefix)

    def stream_token(self, token: str) -> None:
        """追加 token 到当前流式行。"""
        self._append_to_last_line(token)

    def finish_stream(self) -> None:
        """结束流式输出（当前行已完整，下一行自然追加）。"""
        pass

    def scroll_up(self, lines: int = 3) -> None:
        """向上滚动。"""
        self._window.vertical_scroll += lines

    def scroll_down(self, lines: int = 3) -> None:
        """向下滚动。"""
        vs = self._window.vertical_scroll
        self._window.vertical_scroll = max(0, vs - lines)

    def scroll_to_bottom(self) -> None:
        """滚回最底部。"""
        self._window.vertical_scroll = 0

    @property
    def control(self) -> BufferControl:
        return self._control

    def __pt_container__(self) -> Window:
        """返回可滚动的 Window 容器。"""
        self._window = Window(
            content=self._control,
            wrap_lines=True,
            always_hide_cursor=True,
            allow_scroll_beyond_bottom=True,
        )
        return self._window
