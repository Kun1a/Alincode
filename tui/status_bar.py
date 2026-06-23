"""状态栏：顶栏显示 provider、模型、会话轮数。"""

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl


class StatusBar:
    """顶栏组件，显示连接信息和会话统计。"""

    def __init__(self) -> None:
        self._provider = ""
        self._model = ""
        self._turns = 0
        self._control = FormattedTextControl(self._render)

    def set_info(self, provider: str, model: str) -> None:
        """设置 provider 和模型信息。"""
        self._provider = provider
        self._model = model

    def update_turn_count(self, n: int) -> None:
        """更新对话轮数。"""
        self._turns = n

    def _render(self) -> list:
        """生成 FormattedText 列表。"""
        return [
            ("class:status-bar.label", " MewCode "),
            ("class:status-bar", "│ "),
            ("class:status-bar.value", f"{self._provider} "),
            ("class:status-bar", "│ "),
            ("class:status-bar.value", f"{self._model} "),
            ("class:status-bar", "│ "),
            ("class:status-bar.value", f"第 {self._turns} 轮 "),
        ]

    def __pt_container__(self) -> Window:
        """返回 prompt_toolkit Window 容器。"""
        return Window(content=self._control, height=1, style="class:status-bar")
