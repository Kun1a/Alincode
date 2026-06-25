"""向后兼容 shim——从 prompt/ 包导出所有符号。"""

from Alincode.prompt import assemble_system, PLAN_FULL, EXECUTE_DIRECTIVE

# 保留旧引用（向后兼容——旧代码可能 import）
SYSTEM_PROMPT = assemble_system()
PLAN_MODE_REMINDER = PLAN_FULL

# 通过显式引用抑制 F401
__all__ = [
    "SYSTEM_PROMPT",
    "PLAN_MODE_REMINDER",
    "EXECUTE_DIRECTIVE",
    "assemble_system",
    "PLAN_FULL",
]
