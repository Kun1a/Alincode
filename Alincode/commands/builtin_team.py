"""Team slash 命令(/team list/info/delete/kill)— T27 / F59-F62。

遵循 commands 包的本地命令注册模式:每个命令是一个 Command dataclass,
带 name / description / kind / handler;register(team_mgr) 返回命令列表
供 App 注入。team_mgr 通过闭包注入(命令类构造函数或闭包均可,此处用闭包)。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from Alincode.team.manager import Manager


class Kind(str, Enum):
    """命令类型(T27)。"""

    LOCAL = "local"  # 本地命令:在 TUI 内直接执行,不走 LLM
    REMOTE = "remote"  # 远程命令:转交 LLM 处理


# handler 签名:async (args: str) -> str;args 为命令名之后的剩余文本
CommandHandler = Callable[[str], Awaitable[str]]


@dataclass
class Command:
    """本地命令定义。

    name: 完整命令名(如 "/team list")。
    description: 一句话描述。
    kind: LOCAL 或 REMOTE。
    handler: 异步处理函数,接收命令后的参数文本,返回输出字符串。
    """

    name: str
    description: str
    kind: Kind = Kind.LOCAL
    handler: CommandHandler | None = None


def register(team_mgr: "Manager") -> list[Command]:
    """注册 /team 系列命令,返回命令列表(F59-F62)。

    team_mgr 通过闭包注入各 handler,避免全局状态。
    """

    async def cmd_list(_args: str) -> str:
        """列出所有团队(F59)。"""
        teams = team_mgr.list_()
        if not teams:
            return "没有团队。先用 TeamCreate 创建一个。"
        lines: list[str] = []
        for t in teams:
            members = t.members
            total = len(members)
            active = sum(
                1
                for m in members
                if m.is_active is not False  # None 或 True 都算活跃
            )
            lines.append(
                f"{t.name}  {t.backend}  {total} 成员  [{active}/{total}] 活跃"
            )
        return "\n".join(lines)

    async def cmd_info(args: str) -> str:
        """展示团队详情(F60)。"""
        name = args.strip()
        if not name:
            return "用法: /team info <name>"
        team = team_mgr.get(name)
        if team is None:
            return f"团队 '{name}' 不存在"
        lines: list[str] = [
            f"团队: {team.name}",
            f"后端: {team.backend}",
            f"配置路径: {team.config_path}",
            f"描述: {team.description or '(无)'}",
            "",
            "成员:",
        ]
        for m in team.members:
            active_tag = "活跃" if m.is_active is not False else "空闲"
            lines.append(
                f"  - {m.name}  agent_id={m.agent_id}  "
                f"backend={m.backend_type}  worktree={m.worktree_path or '(无)'}  "
                f"is_active={active_tag}"
            )
        return "\n".join(lines)

    async def cmd_delete(args: str) -> str:
        """删除团队(F61)。"""
        parts = args.strip().split()
        if not parts:
            return "用法: /team delete <name> [--force]"
        force = "--force" in parts
        name = parts[0]
        try:
            await team_mgr.delete(name, force=force)
            return f"团队 '{name}' 已删除"
        except Exception as e:  # noqa: BLE001 - 命令层兜底,把异常转成用户可读消息
            return f"删除失败: {e}"

    async def cmd_kill(args: str) -> str:
        """终止队员(F62)。"""
        member_name = args.strip()
        if not member_name:
            return "用法: /team kill <member>"
        # 查 member 所属 team
        found_team: Any = None
        found_member: Any = None
        for t in team_mgr.list_():
            m = t.member_by_name(member_name)
            if m is not None:
                found_team = t
                found_member = m
                break
        if found_team is None or found_member is None:
            return f"队员 '{member_name}' 不属于任何团队"
        # 调 backend.kill 终止 pane / cancel task
        try:
            from Alincode.team.backend import new_backend

            backend = new_backend(found_member.backend_type, task_mgr=team_mgr.task_mgr)
            await backend.kill(found_member.pane_id, found_member.agent_id)
        except Exception:  # noqa: BLE001 - best-effort kill,失败不阻断 remove_member
            pass
        # 从 team 移除该成员
        try:
            await team_mgr.remove_member(found_team, member_name)
            return f"队员 '{member_name}' 已终止并移除"
        except Exception as e:  # noqa: BLE001
            return f"移除失败: {e}"

    return [
        Command(
            name="/team list",
            description="列出所有团队",
            handler=cmd_list,
        ),
        Command(
            name="/team info",
            description="展示团队详情(成员/后端/配置路径)",
            handler=cmd_info,
        ),
        Command(
            name="/team delete",
            description="删除团队(可选 --force)",
            handler=cmd_delete,
        ),
        Command(
            name="/team kill",
            description="终止并移除指定队员",
            handler=cmd_kill,
        ),
    ]
