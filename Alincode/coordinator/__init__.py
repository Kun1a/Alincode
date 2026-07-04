"""Coordinator Mode 包(T24 / F52-F55)。

双锁机制:feature flag(coordinator_mode)与环境变量(MEWCODE_COORDINATOR_MODE)
同时为真才启用。启用后 Lead 工具集收窄为 COORDINATOR_ALLOWED_TOOLS
(剥夺 write_file/edit_file),并注入四阶段系统提示词。
"""

from __future__ import annotations

import os

# Coordinator Mode 允许工具白名单(F53)。
# 剥夺 write_file / edit_file,只保留调度、读类操作与 shell(用于 git merge)。
COORDINATOR_ALLOWED_TOOLS: list[str] = [
    "Agent",
    "TeamCreate",
    "TeamDelete",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
    "read_file",
    "glob",
    "grep",
    "bash",
]


def env_truthy(v: str) -> bool:
    """判断环境变量值是否为「真」(F52)。

    接受 "1" / "true" / "yes",大小写不敏感;其余(含空串/None)返回 False。
    """
    if not v:
        return False
    return v.strip().lower() in {"1", "true", "yes"}


def is_enabled(cfg) -> bool:  # type: ignore[no-untyped-def]
    """双锁判定 Coordinator Mode 是否启用(F52)。

    两把锁全开才生效:
    1. cfg.features.coordinator_mode 为 True(feature flag)
    2. 环境变量 MEWCODE_COORDINATOR_MODE 为 truthy

    用 getattr 兜底——cfg 可能无 features 字段(T25 未完成或旧配置)。
    """
    features = getattr(cfg, "features", None)
    if features is None:
        return False
    if not bool(getattr(features, "coordinator_mode", False)):
        return False
    return env_truthy(os.environ.get("MEWCODE_COORDINATOR_MODE", ""))


def allowed_tools() -> list[str]:
    """返回 Coordinator Mode 允许工具列表的拷贝(F53)。"""
    return list(COORDINATOR_ALLOWED_TOOLS)


def system_prompt_suffix() -> str:
    """Coordinator 系统提示词后缀(F55)。

    四阶段框架(Research / Synthesis / Implementation / Verification)
    + 「派完队员就停手等汇报」纪律段。

    纪律核心:派出 Agent/SendMessage 后禁止立刻自己用 read_file/glob/grep/bash
    探索;禁止 sleep/TaskList 凑时间;只在 Research 首次定位、Synthesis 读队员
    产出、Verification 收敛时才允许自己用读类工具。
    """
    return """

## Coordinator Mode

你现在是 Coordinator(协调者),负责四阶段协作流程:

### 阶段一:Research(调研)
- 定位问题范围,首次用 read_file/glob/grep 确认目标文件与入口
- 把探索任务拆成可独立执行的子任务,派给队员(Agent 工具)

### 阶段二:Synthesis(综合)
- 收齐队员汇报后,读队员产出的报告文件,综合结论
- 若信息不足,再派新队员补充探索

### 阶段三:Implementation(实现)
- 把实现任务派给队员,每名队员在独立 worktree 里干活
- 你只负责任务分配与依赖管理,不亲自写代码

### 阶段四:Verification(验证)
- 所有任务完成后,用 bash 跑 git merge 逐个合各队员分支
- 冲突用 read_file 查看、bash 解决;搞不定就 git merge --abort 保留 worktree 上报用户

## 派完队员就停手等汇报(纪律)

派出 Agent / SendMessage 后,**禁止**立刻调 read_file / glob / grep / bash 自己探索;
**禁止**用 sleep / TaskList 轮询凑时间。task.Manager 完成时会自然推送
<task-notification> reminder,你下一轮被唤醒后再继续。

派完队员后唯一该做的事:发一行总结「已派 N 名队员探索 X,等结果」,让本轮结束。

允许自己用 read_file/glob/grep/bash 的场景仅限:
1. Research 阶段第一次目标定位
2. Synthesis 阶段读**队员产出的报告文件**
3. Verification 阶段 git diff / git status 等收敛操作

其余时刻,把活派出去,等汇报。
"""
