"""spawn_teammate 主流程(T18)。

对应 spec F25、plan.md「Agent(team_name=...) spawn 路径」段。
被 AgentTool 通过 TeamHook 委托调用。
Manager 持 SpawnDeps(provider/registry/catalog 等)由 cli wire 注入。
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Alincode.team.backend import SpawnRequest, new_backend
from Alincode.team.mailbox import Box, Message, MessageType
from Alincode.team.types import TeammateInfo
from Alincode.team_hook import IncomingMessage, TeammateContext
from Alincode.tool.filter import FilterParams, apply_agent_tool_filter

if TYPE_CHECKING:
    from Alincode.team.manager import Manager
    from Alincode.team_hook import TeamSpawnRequest


@dataclass
class SpawnDeps:
    """spawn_teammate 需要的外部依赖,由 cli wire 注入。"""

    provider: Any = None  # LLM provider
    registry: Any = None  # tool registry
    catalog: Any = None  # subagent Catalog
    engine: Any = None  # PermissionEngine
    hook_engine: Any = None
    model: str = ""
    version: str = ""


# ---- 辅助函数 ----


def team_system_prompt_suffix() -> str:
    """队员系统提示词附录(F39)。"""
    return """

IMPORTANT: You are running as an agent in a team.
Just writing a response in text is not visible to others
on your team - you MUST use the SendMessage tool.
The user interacts primarily with the team lead.
Your work is coordinated through the task system
and teammate messaging.
"""


def build_team_context_reminder(
    team_name: str,
    member_name: str,
    agent_id: str,
    worktree_path: str,
    members: list[tuple[str, str]] | None = None,
) -> str:
    """构造 <team-context> reminder(F40)。"""
    members_str = ""
    if members:
        members_str = ", ".join(f"{n}({r})" for n, r in members)
    return (
        f"<team-context>\n"
        f"team: {team_name}\n"
        f"你的成员名: {member_name}\n"
        f"你的 agent_id: {agent_id}\n"
        f"worktree 目录: {worktree_path}\n"
        f"当前团队成员: {members_str}\n"
        f"</team-context>"
    )


def truncate_for_summary(text: str, max_words: int = 8) -> str:
    """从 prompt 生成 summary(5-10 词)。"""
    words = text.split()[:max_words]
    return " ".join(words)


def _new_session_dir(project_root: str) -> str:
    """申请 session 目录(复用 .Alincode/sessions/ 格式)。"""
    sid = secrets.token_hex(8)
    d = os.path.join(project_root, ".Alincode", "sessions", sid)
    Path(d).mkdir(parents=True, exist_ok=True)
    return d


# ---- spawn_teammate 主流程 ----


async def spawn_teammate(mgr: "Manager", req: "TeamSpawnRequest") -> str:
    """Team spawn 分支(F25)。

    返回 JSON 字符串(member_name/agent_id/worktree/backend/pane_id)。
    """
    from Alincode.team.types import InProcessTeammateNoSpawnError, TeamNotFoundError

    # 1. 取 Team
    team = mgr.get(req.team_name)
    if team is None:
        raise TeamNotFoundError(f"团队 '{req.team_name}' 不存在")

    # 2. 校验调用者权限
    from Alincode.team_hook import teammate_context

    tc = teammate_context()
    if tc is not None and tc.backend_type == "in-process":
        # in-process 队员不许再 spawn(F19)
        raise InProcessTeammateNoSpawnError("in-process 队员不能再 spawn Team 队员")

    # 3. 解析 SubAgentDefinition
    deps = mgr._spawn_deps
    if deps is None or deps.catalog is None:
        raise RuntimeError("spawn deps 未注入(需 cli wire 调 set_spawn_deps)")

    if req.subagent_type:
        defi = deps.catalog.resolve(req.subagent_type)
        if defi is None:
            return json.dumps(
                {"error": f"未知 subagent_type: {req.subagent_type}"},
                ensure_ascii=False,
            )
    else:
        defi = deps.catalog.fork_definition()

    # 4. 创建 worktree
    slug = f"team-{team.sanitized_name}/{req.member_name}"
    worktree_path = ""
    branch = ""
    if mgr.wt_mgr is not None:
        try:
            from Alincode.worktree.create import create as create_wt

            wt = await create_wt(mgr.wt_mgr, slug, "HEAD", False)
            worktree_path = wt.path
            branch = wt.branch
        except Exception as e:
            return json.dumps({"error": f"worktree 创建失败: {e}"}, ensure_ascii=False)

    # 5. 申请 session_dir
    session_dir = _new_session_dir(mgr.project_root)

    # 6. 预生成 agent_id
    pre_agent_id = f"agent-{secrets.token_hex(7)}"

    # 7. 构造队员独立工具集（per-team Registry，排除 Lead 专属工具）
    from Alincode.tools.teammate_tools import build_teammate_tools

    teammate_registry = build_teammate_tools(
        parent_registry=deps.registry,
        team_manager=mgr,
        team_name=team.name,
        agent_id=pre_agent_id,
        agent_name=req.member_name,
        backend_type=str(team.backend),
        definition=defi,
    )

    # 8. 计算 allowed tools（简化 filter，无 teammate 分支）
    all_names = [d.name for d in teammate_registry.definitions()]
    allowed = apply_agent_tool_filter(
        FilterParams(
            all_tools=all_names,
            source=int(getattr(defi, "source", 0)),
            allowed=getattr(defi, "tools", None) or [],
            disallowed=getattr(defi, "disallowed_tools", None) or [],
        )
    )

    # 9. system_prompt
    sys_prompt = (defi.system_prompt or "") + team_system_prompt_suffix()

    # 10. 构造 SpawnRequest
    spawn_req = SpawnRequest(
        team_name=team.name,
        member_name=req.member_name,
        agent_id=pre_agent_id,
        worktree_path=worktree_path,
        session_dir=session_dir,
        agent_type=req.subagent_type,
        model=req.model or (defi.model if defi.model != "inherit" else ""),
        initial_prompt=req.prompt,
        plan_mode_required=req.plan_mode_required,
    )

    # 11. 按后端分流
    is_in_process = team.backend == "in-process"

    if is_in_process:
        # in-process:构造 sub_agent + sub_conv + TeammateContext
        from Alincode.agent import Agent
        from Alincode.conversation import ConversationManager
        from Alincode.runtime import SessionRuntime

        sub_runtime = SessionRuntime(context_window=200000)
        sub_agent = Agent(
            provider=deps.provider,
            registry=teammate_registry,
            model=spawn_req.model or deps.model,
            version=deps.version,
            engine=deps.engine,
            runtime=sub_runtime,
            system_prompt=sys_prompt,
            max_turns=defi.max_turns,
            permission_mode="plan" if req.plan_mode_required else "bypassPermissions",
            dont_ask=True,  # F39a: 队员强制 dont_ask
            hook_engine=deps.hook_engine,
            allowed_tools=allowed,
        )

        sub_conv = ConversationManager()  # 定义式:空对话

        # 注入 team-context reminder
        members_info = [(m.name, m.agent_id) for m in team.members]
        ctx_reminder = build_team_context_reminder(
            team.name, req.member_name, pre_agent_id, worktree_path, members_info
        )
        sub_conv.add_system(ctx_reminder)

        # 构造 TeammateContext(闭包动态读 tc.agent_id)
        box = Box(team.mailbox_dir)

        teammate_ctx = TeammateContext(
            team_name=team.name,
            member_name=req.member_name,
            agent_id=pre_agent_id,
            worktree_path=worktree_path,
            backend_type="in-process",
            read_unread=_make_read_unread(box),
            mark_read=_make_mark_read(box),
        )

        # 注入到 sub_agent 的 context(通过 contextvars,在 launch 的 task 里生效)
        spawn_req.sub_agent = sub_agent
        spawn_req.conv = sub_conv
        spawn_req.task_mgr = mgr.task_mgr

        # backend.spawn
        backend = new_backend(team.backend, task_mgr=mgr.task_mgr)
        pane_id, agent_id = await backend.spawn(spawn_req)

        # in-process:agent_id = task_id,更新 TeammateContext
        teammate_ctx.agent_id = agent_id
        # 注入 contextvars(在 task 已启动后,下一个 context copy 生效)
        # 注意:contextvars 在 asyncio task 间隔离,这里 set 在当前 context
        # task 内的 context copy 不会看到。需要 task 内自己 set。
        # 简化:in-process 队员的 mailbox 读取由 T20 的 Loop 注入处理
    else:
        # Pane 后端:预写 mailbox 初始任务(F13)
        box = Box(team.mailbox_dir)
        await box.write(
            pre_agent_id,
            Message(
                from_="lead",
                to=req.member_name,
                type=MessageType.TEXT,
                summary=truncate_for_summary(req.prompt),
                content=req.prompt,
            ),
        )

        # backend.spawn
        backend = new_backend(team.backend)
        pane_id, agent_id = await backend.spawn(spawn_req)

    # 12. 注册到 AgentNameRegistry
    if mgr.reg is not None:
        mgr.reg.register(req.member_name, agent_id)

    # 13. 构造 TeammateInfo 加入 team.members
    info = TeammateInfo(
        name=req.member_name,
        agent_id=agent_id,
        agent_type=req.subagent_type,
        model=spawn_req.model,
        worktree_path=worktree_path,
        branch=branch,
        backend_type=team.backend,
        pane_id=pane_id,
        is_active=None,
        plan_mode_required=req.plan_mode_required,
        session_dir=session_dir,
    )
    await mgr.add_member(team, info)

    # 14. 返回 JSON
    return json.dumps(
        {
            "member_name": req.member_name,
            "agent_id": agent_id,
            "worktree": worktree_path,
            "backend": str(team.backend),
            "pane_id": pane_id,
        },
        ensure_ascii=False,
    )


def _make_read_unread(box: Box):
    """构造 read_unread 闭包,动态读 tc.agent_id。"""
    from Alincode.team_hook import teammate_context

    async def read_unread():
        tc = teammate_context()
        if tc is None:
            return [], []
        indices, raw = await box.read_unread(tc.agent_id)
        msgs = [
            IncomingMessage(
                from_=r.get("from", ""),
                type=r.get("type", "text"),
                summary=r.get("summary", ""),
                content=r.get("content", ""),
                timestamp=r.get("timestamp", 0),
                payload=r.get("payload"),
            )
            for r in raw
        ]
        return indices, msgs

    return read_unread


def _make_mark_read(box: Box):
    """构造 mark_read 闭包,动态读 tc.agent_id。"""
    from Alincode.team_hook import teammate_context

    async def mark_read(indices: list[int]):
        tc = teammate_context()
        if tc is None:
            return
        await box.mark_read(tc.agent_id, indices)

    return mark_read
