"""Team Manager:管理多个 Team 的生命周期 + Team 成员操作。

对应 spec F3-F10、F63-F66;plan.md「Manager」段。
两层锁:Manager._lock 保护 teams dict;Team._lock 保护 team.members。
跨进程并发(Pane 后端)由 reload_from_disk_locked 兜底(F19c/T3b)。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from Alincode.team.persistence import (
    atomic_write_json,
    read_json,
    reload_from_disk_locked,
    sanitize,
)
from Alincode.team.types import (
    BackendType,
    MemberExistsError,
    MemberNotFoundError,
    Team,
    TeamError,
    TeamHasActiveMembersError,
    TeammateInfo,
    TeamNotFoundError,
)

if TYPE_CHECKING:
    from Alincode.team.registry import AgentNameRegistry
    from Alincode.task.manager import Manager as TaskManager
    from Alincode.worktree.manager import Manager as WorktreeManager


# kill 回调类型:由 cli wire 注入,delete 时调
KillMemberFn = Callable[[TeammateInfo], Awaitable[None]]


class Manager:
    """管理多个 Team 的生命周期(F3-F7)。

    单 mewcode 进程内管理多个 Team(典型场景同时只有一个活跃 Team)。
    """

    def __init__(
        self,
        home_dir: str | Path = "",
        project_root: str | Path = "",
        wt_mgr: "WorktreeManager | None" = None,
        task_mgr: "TaskManager | None" = None,
        reg: "AgentNameRegistry | None" = None,
    ) -> None:
        self.home_dir = str(home_dir)
        self.project_root = str(project_root)
        self.wt_mgr = wt_mgr
        self.task_mgr = task_mgr
        self.reg = reg
        self.teams: dict[str, Team] = {}  # 按 sanitized_name 索引
        self._lock = asyncio.Lock()
        self._kill_member: KillMemberFn | None = None
        self._spawn_deps: Any = None  # SpawnDeps,由 set_spawn_deps 注入(T18)
        self.active_team: str = ""  # 当前活跃 Team sanitized_name(TeamCreate 设置)

        # 持久化根目录:<project_root>/.Alincode/team/(与 worktrees/sessions 平级)
        self._teams_root = os.path.join(self.project_root, ".Alincode", "team")
        Path(self._teams_root).mkdir(parents=True, exist_ok=True)

        # 扫描子目录还原 teams dict(F64)
        self._restore_from_disk()

    def set_kill_member(self, fn: KillMemberFn | None) -> None:
        """注入 kill 回调(由 cli wire 在 backend 就绪后注入)。"""
        self._kill_member = fn

    def set_spawn_deps(self, deps: Any) -> None:
        """注入 spawn 依赖(provider/registry/catalog 等,T18)。"""
        self._spawn_deps = deps

    def _restore_from_disk(self) -> None:
        """启动时扫描所有 Team 目录(F64)。

        解析失败的目录跳过并 stderr 警告。
        不自动恢复 in-process 队员(进程重启后状态丢失)。
        """
        root = Path(self._teams_root)
        for sub in root.iterdir():
            if not sub.is_dir():
                continue
            cfg = sub / "config.json"
            if not cfg.exists():
                continue
            try:
                data = read_json(cfg)
                team = Team.from_dict(data)
                team.fill_derived_paths(str(sub))
                # in-process 队员重启后视为空闲
                for m in team.members:
                    if m.name == "lead":
                        continue
                    if m.backend_type == BackendType.IN_PROCESS:
                        m.is_active = False
                self.teams[team.sanitized_name] = team
            except Exception as e:
                print(f"[team] 跳过损坏的 Team 目录 {sub}: {e}", file=sys.stderr)

    def get(self, name: str) -> Team | None:
        """按 sanitized name 查询 Team(F6)。"""
        sn = sanitize(name)
        return self.teams.get(sn)

    def list_(self) -> list[Team]:
        """列出所有 Team,按创建时间排序(F59)。"""
        return sorted(self.teams.values(), key=lambda t: t.created_at)

    async def create(self, name: str, description: str = "") -> Team:
        """创建 Team(F5)。

        1. sanitize + 同名冲突后缀 -2/-3
        2. 创建 config_dir + mailbox_dir
        3. 写 config.json(原子)
        4. 注册 Lead 成员
        5. 加入 teams dict
        """
        async with self._lock:
            sanitized = sanitize(name)
            if not sanitized:
                raise TeamError(f"团队名 '{name}' 经 sanitize 后为空")

            # 同名冲突:追加 -2 / -3 直到唯一(检查内存 + 磁盘)
            unique = sanitized
            idx = 2
            while unique in self.teams or os.path.isdir(
                os.path.join(self._teams_root, unique)
            ):
                unique = f"{sanitized}-{idx}"
                idx += 1
            sanitized = unique

            config_dir = os.path.join(self._teams_root, sanitized)
            mailbox_dir = os.path.join(config_dir, "mailbox")
            Path(config_dir).mkdir(parents=True, exist_ok=True)
            Path(mailbox_dir).mkdir(parents=True, exist_ok=True)

            # 后端检测:暂时硬编码 IN_PROCESS,T11 接 detect
            # detect() 会按 $TMUX / iTerm / tmux / in-process 优先级决定
            backend = self._detect_backend_cached()

            team = Team(
                name=name,
                sanitized_name=sanitized,
                lead_agent_id="lead",
                backend=backend,
                description=description,
                created_at=datetime.now(),
            )
            team.fill_derived_paths(config_dir)

            # 注册 Lead 成员(F5 step6)
            lead_member = TeammateInfo(
                name="lead",
                agent_id="lead",
                is_active=None,
                backend_type=backend,
            )
            team.members.append(lead_member)

            # 原子写 config.json
            atomic_write_json(team.config_path, team.to_dict())

            self.active_team = sanitized
            self.teams[sanitized] = team
            return team

    def _detect_backend_cached(self) -> BackendType:
        """检测后端类型(F14)。T11 写完后走真实 detect。"""
        try:
            from Alincode.team.backend.detect import detect

            return detect()
        except ImportError:
            return BackendType.IN_PROCESS

    async def delete(self, name: str, force: bool = False) -> None:
        """删除 Team(F7 + F66)。

        1. 持锁,找到 Team
        2. 非 force 时校验全员 is_active=False
        3. 对每个非 lead 成员:kill + 清 session + 清 worktree
        4. 删 config_dir
        5. 从 teams dict 移除
        """
        async with self._lock:
            sn = sanitize(name)
            team = self.teams.get(sn)
            if team is None:
                raise TeamNotFoundError(f"团队 '{name}' 不存在")

            # 持 Team._lock,reload 后校验活跃成员
            async with team._lock:
                await reload_from_disk_locked(team)
                if not force:
                    for m in team.members:
                        if m.name == "lead":
                            continue
                        if m.is_active is not False:  # None 或 True 都算活跃
                            raise TeamHasActiveMembersError(
                                f"团队 '{name}' 仍有活跃成员 {m.name},不能删除"
                            )
                # 拷贝一份成员列表用于后续清理(避免遍历时修改)
                members_to_clean = [m for m in team.members if m.name != "lead"]

            # 清理各成员资源(不持 Team._lock,避免长锁)
            for m in members_to_clean:
                # kill pane / cancel task(如果有注入回调)
                if self._kill_member is not None:
                    try:
                        await self._kill_member(m)
                    except Exception as e:
                        print(f"[team] kill {m.name} 失败: {e}", file=sys.stderr)
                # 删 session 目录
                if m.session_dir:
                    shutil.rmtree(m.session_dir, ignore_errors=True)
                # 删 worktree（用 slug 名,不是 branch 名）
                if self.wt_mgr is not None:
                    slug = f"team-{team.sanitized_name}/{m.name}"
                    try:
                        from Alincode.worktree.lifecycle import remove_wt

                        await remove_wt(self.wt_mgr, slug)
                    except Exception as e:
                        print(
                            f"[team] 删 worktree {slug} 失败: {e}",
                            file=sys.stderr,
                        )
                    # 兜底:清理 active dict（remove_wt 内部可能没清）
                    self.wt_mgr.active.pop(slug, None)

            # 删整个 Team 目录
            shutil.rmtree(team.config_dir, ignore_errors=True)
            # 从内存移除
            self.teams.pop(sn, None)

    # ---- Team 成员操作(F8-F10,T3b reload 兜底) ----

    async def add_member(self, team: Team, info: TeammateInfo) -> None:
        """添加成员(F8)。加锁后先 reload 再操作。"""
        async with team._lock:
            await reload_from_disk_locked(team)
            # 校验 name 在 Team 内唯一
            existing = team.member_by_name(info.name)
            if existing is not None:
                raise MemberExistsError(f"队员 '{info.name}' 在团队内已存在")
            team.members.append(info)
            atomic_write_json(team.config_path, team.to_dict())

    async def set_member_active(self, team: Team, name: str, active: bool) -> None:
        """设置成员活跃状态(F9)。加锁后先 reload 再操作。"""
        async with team._lock:
            await reload_from_disk_locked(team)
            m = team.member_by_name(name)
            if m is None:
                raise MemberNotFoundError(f"队员 '{name}' 不存在")
            m.is_active = active
            atomic_write_json(team.config_path, team.to_dict())

    async def remove_member(self, team: Team, name: str) -> None:
        """移除成员(F10)。加锁后先 reload 再操作。"""
        async with team._lock:
            await reload_from_disk_locked(team)
            m = team.member_by_name(name)
            if m is None:
                raise MemberNotFoundError(f"队员 '{name}' 不存在")
            team.members.remove(m)
            atomic_write_json(team.config_path, team.to_dict())

    # ---- Lead mailbox 轮询(T30b) ----

    async def poll_lead_mailboxes(self) -> list["LeadMessage"]:
        """遍历所有 Team 的 lead 邮箱,读未读消息并标 read(F41a/T30b)。

        返回 LeadMessage 列表,每条带 team_name / from / type / summary / content / time。
        """
        from Alincode.team.mailbox import Box

        results: list[LeadMessage] = []
        for team in self.list_():
            try:
                box = Box(team.mailbox_dir)
                indices, unread = await box.read_unread(team.lead_agent_id)
                if unread:
                    await box.mark_read(team.lead_agent_id, indices)
                    for msg in unread:
                        results.append(
                            LeadMessage(
                                team_name=team.name,
                                from_=msg.get("from", ""),
                                type=str(msg.get("type", "text")),
                                summary=msg.get("summary", ""),
                                content=msg.get("content", ""),
                                timestamp=msg.get("timestamp", 0),
                            )
                        )
            except Exception as e:
                print(f"[team] 轮询 {team.name} lead 邮箱失败: {e}", file=sys.stderr)
        return results

    # ---- TeamHook 实现(T18/T19) ----

    async def handle_task_done(self, agent_id: str) -> None:
        """T30: 队员任务完成时的 idle 通知回调。

        由 task.Manager.on_task_done 注册,在队员 run_to_completion 结束后触发。
        1. 用 registry 反查 member name
        2. 遍历所有 Team 找到该成员
        3. set_member_active(name, False)
        4. 向 Lead 邮箱写 idle_notification
        """
        from Alincode.team.mailbox import Box, Message, MessageType

        if self.reg is None:
            return
        member_name = self.reg.name_of(agent_id)
        if member_name is None:
            return

        for team in self.list_():
            m = team.member_by_name(member_name)
            if m is None:
                continue
            # 标记成员空闲
            try:
                await self.set_member_active(team, member_name, False)
            except Exception as e:
                print(f"[team] set_member_active 失败: {e}", file=sys.stderr)

            # 向 Lead 写 idle_notification
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
                print(f"[team] 写 idle_notification 失败: {e}", file=sys.stderr)
            break

    async def spawn_teammate(self, req: Any) -> str:
        """TeamHook:Team spawn 分支,委托给 spawn.py(T18)。"""
        from Alincode.team.spawn import spawn_teammate as _spawn

        return await _spawn(self, req)

    def is_teammate_context(self) -> tuple[str, str, bool]:
        """TeamHook:判断当前是否在队员上下文(F25 step2)。

        返回 (team_name, member_name, is_in_process)。
        不在队员上下文时返回 ("", "", False)。
        """
        from Alincode.team_hook import teammate_context

        tc = teammate_context()
        if tc is None:
            return ("", "", False)
        return (
            tc.team_name,
            tc.member_name,
            tc.backend_type == "in-process",
        )


@dataclass
class LeadMessage:
    """Lead 收到的队员消息(T30b)。"""

    team_name: str
    from_: str
    type: str
    summary: str
    content: str
    timestamp: int
