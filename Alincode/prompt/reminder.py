"""运行中补充消息：system_reminder + plan_reminder（F6/AC8）。"""


EXECUTE_DIRECTIVE = "现在开始按上述计划执行。你可以使用全部工具了。"


def system_reminder(text: str) -> str:
    """用 `<system-reminder>` 标签包裹补充指令，不污染缓存。

    模型不把它当用户提问回复，仅据此调整行为（F6/AC8）。
    """
    return f"<system-reminder>\n{text}\n</system-reminder>"


PLAN_FULL = system_reminder(
    "当前处于【计划模式】——你只能使用只读工具（read_file、glob、grep）。\n"
    "请分析需求、调研代码、制定清晰方案。只输出计划文本，不修改任何文件、不执行命令。"
)

PLAN_LITE = system_reminder(
    "【计划模式】继续——仅用只读工具。"
)


def plan_reminder(iteration: int) -> str:
    """按轮次返回完整或精简版计划提醒（F7/AC9）。

    - iter == 1：完整版
    - 每 4 轮（iter-1 % 4 == 0）：完整版
    - 其余轮次：精简版
    """
    if iteration == 1 or (iteration - 1) % 4 == 0:
        return PLAN_FULL
    return PLAN_LITE
