"""上下文管理全部硬编码常量（不暴露为配置项）。"""

# ── 第 1 层：单条与单轮工具结果预防性压缩 ──────────
# 单条工具结果落盘阈值：超过此字节数的工具结果会被存盘
SINGLE_RESULT_LIMIT = 50000
# 单条 RoleTool 消息内工具结果聚合阈值：消息内剩余结果字节合计超过此值继续落盘
MESSAGE_AGGREGATE_LIMIT = 200000

# ── 第 2 层：LLM 全量摘要 ──────────────────────────
# 给摘要 LLM 输出预留的 token 空间
SUMMARY_RESERVE = 20000
# 自动触发的额外安全余量：防估算误差与单轮波动
AUTO_SAFETY_MARGIN = 13000
# 手动触发的安全余量：只用来判断摘要请求本身能不能塞下
MANUAL_SAFETY_MARGIN = 3000

# ── 恢复段：最近读过的文件快照 ──────────────────
# 恢复段最多展示几个文件
RECOVERY_FILE_LIMIT = 5
# 单个文件快照的 token 上限：超出时保留头部、截掉尾部
RECOVERY_TOKENS_PER_FILE = 5000

# ── 近期原文保留 ────────────────────────────────
# 摘要后保留近期原文的 token 下界（两个下界都满足后才停手）
RECENT_KEEP_TOKENS = 10000
# 摘要后保留近期原文的条数下界
RECENT_KEEP_MESSAGES = 5

# ── 熔断 ────────────────────────────────────────
# 自动摘要连续失败多少次后停止自动触发（进入熔断状态）
MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES = 3

# ── 摘要请求自身 PTL 重试 ─────────────────────────
# 前 N 次直接重试：每次丢最旧的 1 组
PTL_RETRY_LIMIT = 3
# 超过 PTL_RETRY_LIMIT 后每次按比例丢消息组
PTL_DROP_PERCENTAGE = 0.2

# ── Token 估算 ──────────────────────────────────
# 字符→token 估算比（英文+代码混合场景经验值）
ESTIMATE_CHARS_PER_TOKEN = 3.5

# ── 预览体构造 ──────────────────────────────────
# 预览体头部字节数上限
PREVIEW_HEAD_BYTES = 2048
# 预览体头部行数上限
PREVIEW_HEAD_LINES = 20
