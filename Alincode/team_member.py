"""队员自治循环(T29 / F43-F46)。

Pane 后端(tmux/iterm2)spawn 队员时,在独立终端里启动:
    python -m Alincode --team-member --team <name> --member <name> \
        --agent-id <id> --worktree <path> --agent-type <type> \
        --model <model> --session-dir <path> [--plan-mode]

主循环:
1. 读未读消息 → 分流(text 拼 task / plan_approval / shutdown_request)
2. run_to_completion 执行任务
3. 通知 Lead idle(set_member_active(False) + mailbox.write idle_notification)
4. 等下一条消息(stdin reader 唤醒)
5. 检测 mailbox 目录消失 → 优雅退出
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


async def run_team_member(args: argparse.Namespace) -> None:
    """队员自治循环主入口(T29)。

    从 CLI 参数构造依赖,进入消息驱动的主循环。
    """
    # ── chdir 到 worktree ──
    if args.worktree:
        os.chdir(args.worktree)

    # ── 加载配置 ──
    from Alincode.config import ConfigLoader, effective_context_window
    from Alincode.client import create_provider

    config_path = args.config
    if config_path is None:
        for p in [Path(".Alincode/config.yaml"), Path("config.yaml")]:
            if p.is_file():
                config_path = str(p)
                break
        if config_path is None:
            print("错误: 找不到 config.yaml 配置文件", file=sys.stderr)
            raise SystemExit(1)

    app_cfg = ConfigLoader.load(config_path)
    if not app_cfg.providers:
        print("错误: 配置文件中没有有效的 provider", file=sys.stderr)
        raise SystemExit(1)

    provider_cfg = app_cfg.providers[0]
    provider = create_provider(provider_cfg)

    # ── 构造工具 registry ──
    from Alincode.tools import new_default_registry

    registry = new_default_registry()

    # ── 权限引擎 ──
    workspace = str(Path.cwd().resolve())
    from Alincode.permission.engine import new_engine

    engine, _err = new_engine(workspace)

    # ── Skills 加载 ──
    from Alincode.skills.catalog import Catalog

    catalog = Catalog.load(workspace)

    from Alincode.skills.load_skill import LoadSkillTool
    from Alincode.runtime import SessionRuntime

    load_skill = LoadSkillTool(catalog, SessionRuntime().active_skills, registry)
    registry.register(load_skill)

    # ── SubAgent Catalog ──
    from Alincode.subagent import load_catalog as subagent_load_catalog

    subagent_catalog = subagent_load_catalog(workspace)

    # ── Task Manager(队员不需要完整的 task_mgr,但 Agent 工具依赖) ──
    from Alincode.task import Manager as TaskManager

    task_mgr = TaskManager()

    # ── Team Manager(读 team 配置 + mailbox) ──
    user_home = os.path.expanduser("~")
    from Alincode.team import Manager as TeamManager
    from Alincode.team.registry import AgentNameRegistry

    name_reg = AgentNameRegistry()
    task_mgr.set_name_registry(name_reg)
    team_mgr = TeamManager(
        home_dir=user_home,
        project_root=workspace,
        wt_mgr=None,
        task_mgr=task_mgr,
        reg=name_reg,
    )

    # ── 构造队员独立工具集（per-team，不注册到全局 registry）──
    from Alincode.tools.teammate_tools import build_teammate_tools

    teammate_registry = build_teammate_tools(
        parent_registry=registry,
        team_manager=team_mgr,
        team_name=args.team,
        agent_id=args.agent_id,
        agent_name=args.member,
        backend_type="pane",
        definition=None,
    )

    # ── 解析角色定义 ──
    if args.agent_type:
        defi = subagent_catalog.resolve(args.agent_type)
        if defi is None:
            print(f"错误: 未知 agent_type: {args.agent_type}", file=sys.stderr)
            raise SystemExit(1)
    else:
        defi = subagent_catalog.fork_definition()

    # ── 计算 allowed tools（简化 filter，无 teammate 分支）──
    from Alincode.tool.filter import FilterParams, apply_agent_tool_filter

    all_names = [d.name for d in teammate_registry.definitions()]
    allowed = apply_agent_tool_filter(
        FilterParams(
            all_tools=all_names,
            source=int(getattr(defi, "source", 0)),
            allowed=getattr(defi, "tools", None) or [],
            disallowed=getattr(defi, "disallowed_tools", None) or [],
        )
    )

    # ── 构造 Agent ──
    from Alincode.agent import Agent
    from Alincode.runtime import SessionRuntime
    from Alincode.compact.state import (
        ContentReplacementState,
        RecoveryState,
        AutoCompactTrackingState,
        new_session_context,
    )
    from Alincode.team.spawn import (
        team_system_prompt_suffix,
        build_team_context_reminder,
    )

    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=new_session_context(workspace),
        context_window=effective_context_window(provider_cfg),
    )

    model = args.model or (
        defi.model if defi.model != "inherit" else provider_cfg.model
    )
    sys_prompt = (defi.system_prompt or "") + team_system_prompt_suffix()

    agent = Agent(
        provider=provider,
        registry=teammate_registry,
        model=model,
        version="0.3.0",
        engine=engine,
        runtime=runtime,
        system_prompt=sys_prompt,
        max_turns=defi.max_turns,
        permission_mode="plan" if args.plan_mode else defi.permission_mode,
        dont_ask=True,
        allowed_tools=allowed,
    )

    # ── 取 Team ──
    team = team_mgr.get(args.team)
    if team is None:
        print(f"错误: 团队 '{args.team}' 不存在", file=sys.stderr)
        raise SystemExit(1)

    # ── 构造 TeammateContext ──
    from Alincode.team_hook import TeammateContext, set_teammate_context
    from Alincode.team.mailbox import Box
    from Alincode.team.spawn import _make_read_unread, _make_mark_read

    box = Box(team.mailbox_dir)
    member_name = args.member
    agent_id = args.agent_id

    # 权限模式切换回调(T32)
    def _set_permission_mode(mode: str) -> None:
        agent.permission_mode = mode

    teammate_ctx = TeammateContext(
        team_name=team.name,
        member_name=member_name,
        agent_id=agent_id,
        worktree_path=args.worktree or "",
        backend_type="pane",
        read_unread=_make_read_unread(box),
        mark_read=_make_mark_read(box),
        set_permission_mode=_set_permission_mode,
    )

    # ── 构造初始对话 + team-context reminder ──
    from Alincode.conversation import ConversationManager

    conv = ConversationManager()

    members_info = [(m.name, m.agent_id) for m in team.members]
    ctx_reminder = build_team_context_reminder(
        team.name, member_name, agent_id, args.worktree or "", members_info
    )
    conv.add_system(ctx_reminder)

    # ── 注入 TeammateContext ──
    token = set_teammate_context(teammate_ctx)

    # ── 注册到 NameRegistry ──
    name_reg.register(member_name, agent_id)

    # ── 标记成员活跃 ──
    await team_mgr.set_member_active(team, member_name, True)

    # ── stdin reader asyncio task ──
    wake_event = asyncio.Event()

    async def _stdin_reader():
        """读 stdin 每一行就 wake_event.set()。"""
        loop = asyncio.get_event_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break  # EOF
                wake_event.set()
            except Exception:
                break

    stdin_task = asyncio.create_task(_stdin_reader())

    # ── 主循环 ──
    print(f"[team-member] {member_name} 已就绪,等待消息...", file=sys.stderr)

    try:
        while True:
            # 检测 mailbox 目录消失 → 优雅退出
            if not os.path.isdir(team.mailbox_dir):
                print("[team-member] mailbox 目录消失,退出。", file=sys.stderr)
                break

            # 读未读消息
            indices, messages = await teammate_ctx.read_unread()
            if messages:
                await teammate_ctx.mark_read(indices)

                # 分流消息
                task_text = ""
                has_shutdown = False
                for msg in messages:
                    if msg.type == "shutdown_request":
                        has_shutdown = True
                        print(
                            f"[team-member] 收到 shutdown_request from {msg.from_}",
                            file=sys.stderr,
                        )
                        continue
                    if msg.type == "plan_approval_response":
                        # T32: Plan 审批由 ingest_team_mailbox 在 Loop 内处理
                        # 这里把审批结果拼入 task_text 让模型知道
                        payload = msg.payload or {}
                        if payload.get("approve"):
                            task_text += f"\n[plan-approved] {msg.summary}\n"
                        else:
                            feedback = payload.get("feedback", "")
                            task_text += (
                                f"\n[plan-rejected] {msg.summary}\n反馈: {feedback}\n"
                            )
                        continue
                    # text 消息:拼入 task
                    if msg.content:
                        task_text += msg.content + "\n"

                if has_shutdown:
                    # 回复 shutdown_response 给 Lead
                    from Alincode.team.mailbox import Message, MessageType

                    await box.write(
                        "lead",
                        Message(
                            from_=member_name,
                            to="lead",
                            type=MessageType.SHUTDOWN_RESPONSE,
                            summary=f"队员 {member_name} 已退出",
                            content=f"队员 {member_name} 已优雅退出。",
                        ),
                    )
                    break

                if task_text.strip():
                    # 执行任务
                    print(
                        f"[team-member] {member_name} 开始执行任务...", file=sys.stderr
                    )
                    events: asyncio.Queue = asyncio.Queue(maxsize=64)
                    try:
                        result = await agent.run_to_completion(
                            conv, task_text.strip(), events
                        )
                        print(
                            f"[team-member] {member_name} 任务完成: {result[:100]}...",
                            file=sys.stderr,
                        )
                    except Exception as e:
                        print(
                            f"[team-member] {member_name} 任务异常: {e}",
                            file=sys.stderr,
                        )

                    # 通知 Lead idle
                    await _notify_lead_idle(team_mgr, team, member_name, agent_id)

                    # 标记成员空闲
                    try:
                        await team_mgr.set_member_active(team, member_name, False)
                    except Exception:
                        pass

            # 等下一条消息
            wake_event.clear()
            await wake_event.wait()
            # 被唤醒后回到循环顶部读消息

    except asyncio.CancelledError:
        pass
    finally:
        stdin_task.cancel()
        from Alincode.team_hook import reset_teammate_context

        reset_teammate_context(token)
        # 标记成员空闲
        try:
            await team_mgr.set_member_active(team, member_name, False)
        except Exception:
            pass
        print(f"[team-member] {member_name} 已退出。", file=sys.stderr)


async def _notify_lead_idle(team_mgr, team, member_name: str, agent_id: str) -> None:
    """向 Lead 邮箱写 idle_notification(T30)。"""
    from Alincode.team.mailbox import Box, Message, MessageType

    try:
        box = Box(team.mailbox_dir)
        await box.write(
            team.lead_agent_id,
            Message(
                from_=member_name,
                to="lead",
                type=MessageType.IDLE_NOTIFICATION,
                summary=f"队员 {member_name} 已完成任务",
                content=f"队员 {member_name} (agent_id={agent_id}) 已完成当前任务,进入空闲状态。",
            ),
        )
    except Exception as e:
        print(f"[team-member] 写 idle_notification 失败: {e}", file=sys.stderr)


def parse_team_member_args(argv: list[str]) -> argparse.Namespace:
    """解析队员 CLI 参数。"""
    parser = argparse.ArgumentParser(description="AlinCode 队员自治循环")
    parser.add_argument("--team-member", action="store_true", help="启用队员模式")
    parser.add_argument("--team", required=True, help="团队名")
    parser.add_argument("--member", required=True, help="队员名")
    parser.add_argument("--agent-id", required=True, help="Agent ID")
    parser.add_argument("--session-dir", default="", help="会话目录")
    parser.add_argument("--worktree", default="", help="Worktree 路径")
    parser.add_argument("--agent-type", default="", help="SubAgent 类型")
    parser.add_argument("--model", default="", help="模型覆盖")
    parser.add_argument("--plan-mode", action="store_true", help="是否需要 Plan 模式")
    parser.add_argument("--config", default=None, help="配置文件路径")
    return parser.parse_args(argv)


def is_team_member_mode(argv: list[str]) -> bool:
    """检查 CLI 参数是否包含 --team-member。"""
    return "--team-member" in argv
