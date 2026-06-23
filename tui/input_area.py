"""输入区：多行文本输入，Enter 发送 / Alt+Enter 换行。

prompt_toolkit 的 multiline Buffer 默认 Enter 是换行而非触发 accept_handler，
因此通过 eager 按键绑定拦截 Enter 来实现发送。
"""

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers.markup import MarkdownLexer


class InputArea:
    """输入区组件，多行文本输入。

    Enter 发送消息，Alt+Enter（Esc Enter）换行。
    """

    def __init__(self, on_submit) -> None:
        """
        Args:
            on_submit: 回调函数(text: str) -> None
        """
        self._on_submit = on_submit
        self._buffer = Buffer(multiline=True)
        self._control = BufferControl(
            buffer=self._buffer,
            lexer=PygmentsLexer(MarkdownLexer),
            input_processors=[],
            key_bindings=self._create_key_bindings(),
            focusable=True,
        )

    def _create_key_bindings(self) -> KeyBindings:
        """快捷键绑定。

        Enter（eager）：拦截发送，不在 Buffer 中插入换行。
        Alt+Enter：插入换行符。
        """
        kb = KeyBindings()

        @kb.add("enter", eager=True)
        def _(event):
            """Enter 发送消息。eager 确保在默认换行行为前执行。"""
            buffer = event.current_buffer
            text = buffer.text.strip()
            if text:
                self._on_submit(text)
            buffer.set_document(Document())

        @kb.add("escape", "enter", eager=True)
        def _(event):
            """Alt+Enter 换行。"""
            event.current_buffer.insert_text("\n")

        return kb

    def __pt_container__(self) -> Window:
        """返回 Window 容器。"""
        return Window(
            content=self._control,
            height=4,
            style="class:input-area",
            wrap_lines=True,
        )
