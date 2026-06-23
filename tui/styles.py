"""配色方案：Claude Code 风格暗色主题。"""

from prompt_toolkit.styles import Style


# 颜色常量，供代码引用
GREEN = "#00d700"
BLUE = "#5f87ff"
GRAY = "#767676"
WHITE = "#d0d0d0"
DARK_BG = "#1a1a1a"
YELLOW = "#ffd700"
CYAN = "#00d7d7"

style = Style.from_dict({
    # 顶栏
    "status-bar": f"bg:{DARK_BG} fg:{GRAY}",
    "status-bar.label": f"fg:{CYAN} bold",
    "status-bar.value": f"fg:{WHITE}",

    # 消息前缀
    "user-prefix": f"fg:{GREEN} bold",
    "assistant-prefix": f"fg:{BLUE} bold",
    "thinking-prefix": f"fg:{GRAY}",
    "thinking-text": f"fg:{GRAY} italic",
    "info-text": f"fg:{GRAY}",

    # 输入区
    "input-area": f"bg:#2a2a2a",
    "input-area.prompt": f"fg:{GREEN} bold",

    # 代码高亮（pygments token → style）
    "pygments.literal": f"fg:{YELLOW}",
    "pygments.keyword": f"fg:{BLUE} bold",
    "pygments.comment": f"fg:{GRAY} italic",
    "pygments.string": f"fg:{GREEN}",
    "pygments.number": f"fg:{CYAN}",
    "pygments.operator": f"fg:{WHITE}",
})
