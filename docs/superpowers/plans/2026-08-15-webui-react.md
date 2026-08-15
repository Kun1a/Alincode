# AlinCode React WebUI 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在不改动 agent 核心循环、不删除 Textual TUI 的前提下，为 AlinCode 增加一个 React WebUI，Web 端与 TUI 共用同一个 `Agent.run()` 事件流。

**架构：** 把 `driver._amain` 的应用装配逻辑抽取为共享工厂（`bootstrap.py`），把「Agent + Conversation + Runtime + Writer」的会话级构造抽取为 `core_session.py`，TUI 与 Web 都从这两个模块取件。新增 `Alincode/web/` 包：FastAPI + WebSocket，用一个纯函数投影层（`protocol.py`）把多态 `Event` dataclass 转成 JSON 下行，权限审批通过 `request_id → asyncio.Future` 注册表把浏览器决定路由回 agent 内嵌的 Future。前端是 Vite + React + TypeScript 的事件流驱动聊天界面，用 useReducer 状态机把事件折叠成消息块。

**技术栈：** Python 3.13（后端不变）+ FastAPI + uvicorn（新增依赖）；React 18 + TypeScript + Vite + react-markdown（新增 `webui/` 目录）；测试沿用 pytest / pytest-asyncio（`asyncio_mode = "auto"`）。

---

## 背景事实（探索结论，实现时不可违背）

1. **事件流是单一多态 dataclass**（`Alincode/agent.py:87-97`）：`Event{text, tool, usage, iter, notice, done, err, approval, compact}`，由 `Agent.run(conv, mode, cancel) -> AsyncIterator[Event]` 产出，`agent.py:343-354` 持 `_run_lock` 单飞。
2. **权限闭环靠内嵌 Future**：`ApprovalRequest.respond`（`Alincode/permission/__init__.py:28-35`）是 `asyncio.Future`，agent 在 `agent.py:714-720` yield 后 `await` 它；UI 侧 `set_result(Outcome)` 唤醒。`Outcome` 取值 `ALLOW_ONCE / ALLOW_FOREVER / DENY_ONCE`。
3. **Event 不可直接序列化**：`approval` 携带活 Future、`err` 携带 Exception——必须有投影层。
4. **Agent 构造目前绑在 Textual App 里**（`app.py:237-250`），装配逻辑在 `driver.py:39-293`——共用事件流的前提是把这两处抽成共享模块。
5. **`askuser_dialog.py` / `plan_dialog.py` / `session_dialog.py` / `serialization.py` 均为空壳**——AskUser、Plan 审批事件在当前代码中不存在，本计划不涉及，仅在协议中预留扩展位。
6. **子 Agent / Team 事件不进入主事件流**（后台任务只折叠成状态、队员跑在独立进程）——本计划不展示子 agent 进度，文档中标注为后续工作。
7. 会话持久化是 `<workspace>/.Alincode/sessions/<id>/conversation.jsonl`；`list_sessions`（`session/list.py:24`）、`load_session`（`session/load.py:14`）、`Writer`（`session/writer.py:52`）可直接复用。
8. 依赖现状：无 fastapi；`starlette`/`uvicorn` 仅作为 mcp 的传递依赖存在于 uv.lock——需要显式声明。
9. 项目是 git 仓库；Python 3.13；测试命令 `uv run pytest` 或 `.venv\Scripts\python.exe -m pytest`。

## 范围与边界

**做：** 单用户本地 WebUI——新建会话、流式对话、工具行展示、权限审批卡片、取消本轮、会话列表与恢复、token/轮次状态栏。

**不做（TUI 独有，后续迭代）：** 斜杠命令全家桶（/plan /do /compact /remember /team /hooks）、Team 与协调器模式、子 agent 进度展示、AskUser/Plan 弹窗（后端尚不存在）、多浏览器标签同时操作同一会话（MVP 单连接接管）。

**安全边界：** 默认绑定 `127.0.0.1`；MVP 无鉴权——因为它能驱动真实工具执行，严禁用 `--host 0.0.0.0` 暴露到局域网，文档与 `--help` 中注明。

---

## 协议契约（前后端共享，任务 3 之前冻结）

### 下行（服务器 → 浏览器），每帧一个 JSON 对象

| type | 字段 | 来源 Event 字段 |
|---|---|---|
| `session.info` | `session_id, workspace, model, mode` | 连接建立时 |
| `history` | `blocks: Block[]` | 会话恢复成功后 |
| `text.delta` | `delta: str` | `ev.text` |
| `tool.start` | `name, args` | `ev.tool(phase=START)` |
| `tool.end` | `name, result, is_error` | `ev.tool(phase=END)` |
| `approval.request` | `request_id, tool_name, tool_args, reason` | `ev.approval`（Future 留在服务端注册表） |
| `approval.resolved` | `request_id, outcome` | 服务端回灌决定后 |
| `usage` | `input_tokens, output_tokens, cache_write, cache_read` | `ev.usage` |
| `iter` | `value: int` | `ev.iter` |
| `notice` | `text` | `ev.notice` |
| `compact` | `phase, before, after, error` | `ev.compact` |
| `turn.done` | — | `ev.done` |
| `turn.error` | `message` | `ev.err`（`str(err)`） |

工具事件不带 call_id（`ToolEvent` 本身没有）：前端用「最近一个同名 running 工具块」配对，与 TUI 的顺序语义一致。

### 上行（浏览器 → 服务器）

| type | 字段 | 语义 |
|---|---|---|
| `chat.send` | `text` | 用户消息（忙碌时服务端回 notice 拒绝） |
| `approval.respond` | `request_id, outcome`（`allow_once/allow_forever/deny_once`） | 唤醒对应 Future |
| `turn.cancel` | — | 置位本轮 `cancel: asyncio.Event` |
| `session.resume` | `session_id` | 重建会话并下发 `history` |

### REST

- `GET /api/health` → `{"ok": true}`
- `GET /api/sessions` → `SessionInfo[]`（复用 `list_sessions`）
- `GET /api/sessions/{id}/messages` → `Block[]`（历史投影，供未来无需 WS 的场景）

### Block（历史投影结构，前后端同形）

```ts
type Block =
  | { kind: "user"; content: string }
  | { kind: "assistant"; content: string }
  | { kind: "tool"; name: string; args: string; state: "running" | "done"; result?: string; isError?: boolean }
  | { kind: "notice"; text: string; tone: "info" | "error" };
```

---

## 文件结构

### 后端（Python）

| 文件 | 状态 | 职责 |
|---|---|---|
| `Alincode/bootstrap.py` | 新建 | 共享装配工厂：`AppContext` + `build_context()`，承接 `driver._amain:57-244` 的全部装配代码（原样搬移） |
| `Alincode/core_session.py` | 新建 | 会话级构造：`create_session()` 产出 `SessionBundle{agent, conv, runtime, writer}`；`make_replace_handler()` compact 回写 |
| `Alincode/web/__init__.py` | 新建 | 包标记 |
| `Alincode/web/protocol.py` | 新建 | `project_event()`：Event→下行消息列表；`project_messages()`：Message 列表→Block 列表 |
| `Alincode/web/session.py` | 新建 | `WebSession`：消费 `agent.run()`、审批注册表、outbox 队列、恢复会话 |
| `Alincode/web/server.py` | 新建 | FastAPI 应用工厂、REST、`/ws` 端点、静态挂载 `webui/dist`、`serve()` 入口 |
| `Alincode/driver.py` | 修改 | `_amain` 改为调用 `build_context()` + `create_session()`，TUI 行为不变 |
| `Alincode/app.py` | 修改 | `AlinCodeApp.__init__` 增加可选 `agent`/`conv` 参数，接受外部预构建（约 15 行 diff） |
| `Alincode/__main__.py` | 修改 | 增加 `--web [--host H] [--port P]` 分支 |
| `pyproject.toml` | 修改 | 依赖增加 `fastapi>=0.115`、`uvicorn>=0.30` |
| `tests/web/test_protocol.py` | 新建 | 投影纯函数单测 |
| `tests/web/test_session.py` | 新建 | WebSession 审批闭环（FakeProvider + FakeWriteTool） |
| `tests/web/test_server.py` | 新建 | REST + WebSocket 集成（FastAPI TestClient） |

### 前端（`webui/`，Vite + React + TS）

| 文件 | 职责 |
|---|---|
| `webui/package.json` `vite.config.ts` `tsconfig.json` `index.html` | 脚手架；dev 代理 `/api`、`/ws` → `127.0.0.1:8765` |
| `webui/src/lib/protocol.ts` | 与协议契约一一对应的 TS 类型（ServerMsg/ClientMsg/Block） |
| `webui/src/state/chatReducer.ts` | 纯 reducer：事件 → Block 列表 + 状态栏 |
| `webui/src/state/ChatContext.tsx` | Provider：WS 连接、rAF 节流的 text.delta 批量分发、send API |
| `webui/src/components/{ChatView,MessageList,UserBlock,AssistantBlock,ToolBlock,ApprovalCard,NoticeLine,Composer,StatusBar}.tsx` | UI 组件 |
| `webui/src/styles.css` | 全局样式（深色终端风） |

---

## 任务 1：抽取共享装配工厂 bootstrap.py

**文件：**
- 创建：`Alincode/bootstrap.py`
- 修改：`Alincode/driver.py:32-276`
- 测试：`tests/test_bootstrap.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_bootstrap.py
"""bootstrap 共享装配工厂冒烟测试。"""

import os
import pytest

from Alincode.bootstrap import build_context, resolve_config_path


@pytest.mark.asyncio
async def test_build_context_smoke(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "providers:\n"
        "  - name: fake\n"
        "    protocol: anthropic\n"
        "    model: test-model\n"
        "    base_url: http://localhost:9\n"
        "    api_key: sk-test\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / ".Alincode", exist_ok=True)

    ctx = await build_context(str(cfg))

    assert ctx.workspace == str(tmp_path.resolve())
    assert ctx.provider_cfg.model == "test-model"
    assert ctx.registry is not None
    assert ctx.engine is not None
    assert ctx.agent_tool is not None
    # read_file 是默认注册表成员
    names = [d.name for d in ctx.registry.definitions()]
    assert "read_file" in names


def test_resolve_config_path_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        resolve_config_path(None)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_bootstrap.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'Alincode.bootstrap'`

- [ ] **步骤 3：创建 bootstrap.py——原样搬移 driver.py:45-244 的装配代码**

把 `driver._amain` 中「配置发现 → provider/registry → MCP → 权限引擎 → 指令 → 记忆 → Skills → Hook → SubAgent → TaskManager → Worktree → AgentTool → Team wire → Coordinator 判定」整段（现 `driver.py:45-244`）**逐行原样搬入** `build_context()`，不改写任何语句，仅做三处结构性调整：(a) 配置发现逻辑抽出为 `resolve_config_path()`；(b) 被搬移代码中 `driver._amain` 里两处 `asyncio.create_task`（过期会话清理、worktree sweep）一并搬入；(c) 装配产物装进 `AppContext`。`runtime`/`writer`/`AlinCodeApp` 属于会话级，**不搬**，留在调用方（任务 2 处理）。

```python
"""应用装配工厂：provider/工具/权限/记忆/团队等共享装配（TUI 与 Web 共用）。"""

from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from Alincode.client import BaseProvider, create_provider
from Alincode.config import AppConfig, ConfigLoader, ProviderConfig, effective_context_window
from Alincode.instructions import Loader as InstructionsLoader
from Alincode.mcp import load_from_dict as mcp_from_dict, new_manager as mcp_new_manager
from Alincode.memory import Manager as MemoryManager
from Alincode.permission.engine import PermissionEngine, new_engine
from Alincode.skills.catalog import Catalog
from Alincode.tools import Registry, new_default_registry

DEFAULT_CONFIG_PATHS = [
    Path(".Alincode/config.yaml"),
    Path(".Alincode/skills/config.yaml"),
    Path("config.yaml"),
]


@dataclass
class AppContext:
    """共享装配产物。会话级组件（runtime/writer/agent/conv）由 core_session 构造。"""

    app_cfg: AppConfig
    provider_cfg: ProviderConfig
    provider: BaseProvider
    registry: Registry
    engine: PermissionEngine
    instruction_text: str
    memory_text: str
    memory_manager: MemoryManager
    workspace: str
    catalog: Catalog
    hook_engine: object          # hook.engine.Engine | None
    subagent_catalog: object
    task_mgr: object             # task.Manager
    wt_mgr: object | None        # worktree.Manager | None
    team_mgr: object             # team.Manager
    agent_tool: object           # tools.agent_tool.AgentTool
    team_commands: list
    mcp_mgr: object | None
    coordinator_enabled: bool = False


def resolve_config_path(config_path: str | None) -> str:
    """配置文件发现；找不到时打印指引并 SystemExit(1)。"""
    if config_path is not None:
        return config_path
    for p in DEFAULT_CONFIG_PATHS:
        if p.is_file():
            return str(p)
    print("错误: 找不到 config.yaml 配置文件")
    print("请复制 config.example.yaml 为 config.yaml 或 .Alincode/skills/config.yaml")
    raise SystemExit(1)


async def build_context(config_path: str | None = None) -> AppContext:
    """执行全部共享装配，返回 AppContext。代码主体搬自 driver._amain，不改语义。"""
    config_path = resolve_config_path(config_path)
    app_cfg = ConfigLoader.load(config_path)
    if not app_cfg.providers:
        print("错误: 配置文件中没有有效的 provider")
        raise SystemExit(1)

    provider_cfg = app_cfg.providers[0]
    provider = create_provider(provider_cfg)
    registry = new_default_registry()

    # ── 以下整段从 driver.py:67-244 原样搬入（MCP / 权限引擎 / 指令 / 记忆 /
    #    runtime 以外的会话清理任务 / Skills / Hook / SubAgent / TaskManager /
    #    Worktree / AgentTool / Team wire / Coordinator 判定），此处不重复粘贴，
    #    实施时逐行移动，变量名保持不变 ──
    ...

    return AppContext(
        app_cfg=app_cfg,
        provider_cfg=provider_cfg,
        provider=provider,
        registry=registry,
        engine=engine,
        instruction_text=instruction_text,
        memory_text=memory_text,
        memory_manager=mem_mgr,
        workspace=workspace,
        catalog=catalog,
        hook_engine=hook_engine,
        subagent_catalog=subagent_catalog,
        task_mgr=task_mgr,
        wt_mgr=wt_mgr,
        team_mgr=team_mgr,
        agent_tool=agent_tool,
        team_commands=team_commands,
        mcp_mgr=mcp_mgr,
        coordinator_enabled=coordinator_enabled,
    )


async def shutdown_context(ctx: AppContext) -> None:
    """关闭共享资源（MCP 连接等）。"""
    if ctx.mcp_mgr is not None:
        await ctx.mcp_mgr.close()
```

> 实施注意：搬移后 `driver.py` 顶部只保留 driver 自己仍用到的 import（`SessionRuntime`、`new_session_context` 等会话级依赖），其余 import 随代码迁入 `bootstrap.py`。

- [ ] **步骤 4：改造 driver._amain 调用 build_context**

`driver.py:_amain` 改为（TUI 专属部分保留）：

```python
async def _amain(config_path: str | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s", stream=sys.stderr)

    from Alincode.bootstrap import build_context, shutdown_context

    ctx = await build_context(config_path)

    # ── 会话运行时 / 写入器（会话级，TUI 单会话）──
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=new_session_context(ctx.workspace),
        context_window=effective_context_window(ctx.provider_cfg),
    )
    writer = SessionWriter(runtime.session.session_dir)

    app = AlinCodeApp(
        provider=ctx.provider,
        model=ctx.provider_cfg.model,
        registry=ctx.registry,
        engine=ctx.engine,
        runtime=runtime,
        instruction_text=ctx.instruction_text,
        memory_text=ctx.memory_text,
        writer=writer,
        memory_manager=ctx.memory_manager,
        workspace=ctx.workspace,
        catalog=ctx.catalog,
        hook_engine=ctx.hook_engine,
        task_mgr=ctx.task_mgr,
    )
    # 回填 parent 引用（与原 driver.py:262-263 相同）
    ctx.agent_tool.set_parent(app.agent)
    ctx.agent_tool.set_conv_getter(lambda: app._conv.messages)

    app.team_mgr = ctx.team_mgr
    app._team_commands = ctx.team_commands

    if ctx.coordinator_enabled:
        from Alincode import coordinator
        app.agent._allowed_tools = coordinator.allowed_tools()
        if app.agent.system_prompt:
            app.agent.system_prompt += coordinator.system_prompt_suffix()
        else:
            app.agent.system_prompt = coordinator.system_prompt_suffix()
        app.coordinator_mode = True

    try:
        await app.run_async()
    finally:
        await ctx.hook_engine.dispatch(
            HookEvent.SESSION_END,
            {
                "event": "event_end" if False else "session_end",
                "session_id": runtime.session.session_id,
                "cwd": ctx.workspace,
                "mode": "default",
            },
        ) if ctx.hook_engine else None
        writer.close()
        await shutdown_context(ctx)
```

> 注意：原 finally 块的 SessionEnd 派发逻辑照抄 `driver.py:281-293`（上面为示意，实施时保持原写法与判空方式）。

- [ ] **步骤 5：运行全部现有测试，确认 TUI 侧零回归**

运行：`uv run pytest tests/ -x -q`
预期：与改动前完全相同的通过集合（无新增失败）。

- [ ] **步骤 6：运行新测试验证通过**

运行：`uv run pytest tests/test_bootstrap.py -v`
预期：PASS

- [ ] **步骤 7：Commit**

```bash
git add Alincode/bootstrap.py Alincode/driver.py tests/test_bootstrap.py
git commit -m "refactor: 抽取共享装配工厂 bootstrap，TUI/Web 共用"
```

---

## 任务 2：抽取会话级构造 core_session.py（TUI/Web 共享）

**文件：**
- 创建：`Alincode/core_session.py`
- 修改：`Alincode/app.py:196-262`（`AlinCodeApp.__init__` 增加可选 agent/conv 参数）
- 修改：`Alincode/driver.py`（改用 `create_session()`）
- 测试：`tests/test_core_session.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/test_core_session.py
"""core_session：会话级组件构造（不依赖真实 provider 网络）。"""

import os
import pytest

from Alincode.bootstrap import AppContext
from Alincode.config import AppConfig, ProviderConfig
from Alincode.conversation import ROLE_USER
from Alincode.core_session import create_session, make_replace_handler
from Alincode.permission.engine import PermissionEngine
from Alincode.tools import new_default_registry


def _fake_ctx(tmp_path) -> AppContext:
    return AppContext(
        app_cfg=AppConfig(),
        provider_cfg=ProviderConfig(name="fake", protocol="anthropic",
                                     model="m", base_url="", api_key=""),
        provider=None,            # create_session 不触碰 provider 网络层
        registry=new_default_registry(),
        engine=PermissionEngine(),
        instruction_text="",
        memory_text="",
        memory_manager=None,
        workspace=str(tmp_path),
        catalog=None,
        hook_engine=None,
        subagent_catalog=None,
        task_mgr=None,
        wt_mgr=None,
        team_mgr=None,
        agent_tool=None,
        team_commands=[],
        mcp_mgr=None,
    )


def test_create_session_new(tmp_path):
    bundle = create_session(_fake_ctx(tmp_path))
    assert bundle.agent is not None
    assert bundle.runtime.session.session_id
    assert os.path.isfile(os.path.join(bundle.runtime.session.session_dir, "conversation.jsonl"))
    bundle.writer.close()


def test_create_session_resume_keeps_history(tmp_path):
    ctx = _fake_ctx(tmp_path)
    b1 = create_session(ctx)
    b1.conv.add_user("你好")
    sid = b1.runtime.session.session_id
    b1.writer.close()

    b2 = create_session(ctx, resume_id=sid)
    assert b2.runtime.session.session_id == sid
    assert any(m.role == ROLE_USER and m.content == "你好" for m in b2.conv.messages)
    b2.writer.close()


def test_replace_handler_writes_compact_marker(tmp_path):
    b = create_session(_fake_ctx(tmp_path))
    handler = make_replace_handler(b.writer)
    handler(b.conv.messages)
    b.writer.close()
    raw = open(os.path.join(b.runtime.session.session_dir, "conversation.jsonl"),
               encoding="utf-8").read()
    assert '"type": "compact"' in raw
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_core_session.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'Alincode.core_session'`

- [ ] **步骤 3：实现 core_session.py**

Agent/Conversation 构造参数与 `app.py:234-250` 完全一致，保证两条路径行为相同：

```python
"""会话级组件构造（TUI/Web 共享）：Agent + Conversation + Runtime + Writer。

注意：不注入 system prompt——TUI 在 on_mount 注入（app.py:385），
WebSession 在 open() 时注入，避免双份。
"""

from __future__ import annotations

from dataclasses import dataclass

from Alincode.agent import Agent
from Alincode.bootstrap import AppContext
from Alincode.compact.state import (
    AutoCompactTrackingState,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
    open_session_context,
)
from Alincode.config import effective_context_window
from Alincode.conversation import ConversationManager
from Alincode.runtime import SessionRuntime
from Alincode.session import Writer as SessionWriter
from Alincode.session.load import load_session


@dataclass
class SessionBundle:
    agent: Agent
    conv: ConversationManager
    runtime: SessionRuntime
    writer: SessionWriter

    @property
    def session_id(self) -> str:
        return self.runtime.session.session_id


def make_replace_handler(writer: SessionWriter):
    """Conversation 替换回调：compact 标记 + 全量重写（搬自 app.py:264-268）。"""

    def _on_conv_replace(msgs: list) -> None:
        writer.write_compact_marker()
        writer.append_all(msgs)

    return _on_conv_replace


def create_session(
    ctx: AppContext,
    resume_id: str | None = None,
) -> SessionBundle:
    """构造一个会话的全部组件。resume_id 非空时从 JSONL 恢复消息。"""
    if resume_id:
        session_ctx = open_session_context(ctx.workspace, resume_id)
    else:
        session_ctx = new_session_context(ctx.workspace)

    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=session_ctx,
        context_window=effective_context_window(ctx.provider_cfg),
    )
    if ctx.hook_engine:
        runtime.hook_engine = ctx.hook_engine

    writer = SessionWriter(session_ctx.session_dir)

    msgs = load_session(session_ctx.session_dir) if resume_id else []
    conv = ConversationManager.from_messages(
        msgs,
        on_append=writer.append,
        on_replace=make_replace_handler(writer),
    ) if msgs else ConversationManager(
        on_append=writer.append,
        on_replace=make_replace_handler(writer),
    )

    agent = Agent(
        provider=ctx.provider, registry=ctx.registry, model=ctx.provider_cfg.model,
        version="0.3.0", engine=ctx.engine,
        runtime=runtime,
        memory_manager=ctx.memory_manager,
        instruction_text=ctx.instruction_text,
        memory_text=ctx.memory_text,
        skills_catalog=ctx.catalog,
        hook_engine=ctx.hook_engine,
    )

    # 子 Agent 工具回填（对应 driver.py:262-263 的 per-agent wire）
    if ctx.agent_tool is not None:
        ctx.agent_tool.set_parent(agent)
        ctx.agent_tool.set_conv_getter(lambda: conv.messages)

    return SessionBundle(agent=agent, conv=conv, runtime=runtime, writer=writer)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/test_core_session.py -v`
预期：PASS

- [ ] **步骤 5：改造 app.py 接受预构建的 agent/conv**

`AlinCodeApp.__init__`（`app.py:196` 起）新增两个可选参数，仅在未提供时走原构造路径：

```python
    def __init__(self,
                 provider: BaseProvider,
                 model: str = "",
                 registry: Registry | None = None,
                 engine: PermissionEngine | None = None,
                 runtime: SessionRuntime | None = None,
                 instruction_text: str = "",
                 memory_text: str = "",
                 writer: SessionWriter | None = None,
                 memory_manager: "MemoryManager | None" = None,
                 workspace: str = "",
                 catalog: "Catalog | None" = None,
                 hook_engine: "HookEngine | None" = None,
                 task_mgr: "object | None" = None,
                 agent: "Agent | None" = None,          # 新增
                 conv: "ConversationManager | None" = None,  # 新增
                 ) -> None:
        ...
        # Conversation 回调 → Writer（原 app.py:234-239，仅在未提供 conv 时执行）
        if conv is None:
            on_append = writer.append if writer else None
            on_replace = self._on_conv_replace if writer else None
            conv = ConversationManager(on_append=on_append, on_replace=on_replace)
        self._conv = conv

        # Agent（原 app.py:241-250，仅在未提供时执行）
        if agent is None:
            agent = Agent(
                provider=provider, registry=registry, model=model,
                version="0.3.0", engine=self._engine,
                runtime=self.runtime,
                memory_manager=memory_manager,
                instruction_text=instruction_text,
                memory_text=memory_text,
                skills_catalog=catalog,
                hook_engine=hook_engine,
            )
        self.agent = agent
        ...  # 其余字段初始化保持不变
```

- [ ] **步骤 6：driver.py 改用 create_session**

把任务 1 步骤 4 中手工构造 runtime/writer 的段落替换为：

```python
    from Alincode.core_session import create_session

    bundle = create_session(ctx)
    runtime, writer = bundle.runtime, bundle.writer

    app = AlinCodeApp(
        provider=ctx.provider,
        model=ctx.provider_cfg.model,
        registry=ctx.registry,
        engine=ctx.engine,
        runtime=runtime,
        instruction_text=ctx.instruction_text,
        memory_text=ctx.memory_text,
        writer=writer,
        memory_manager=ctx.memory_manager,
        workspace=ctx.workspace,
        catalog=ctx.catalog,
        hook_engine=ctx.hook_engine,
        task_mgr=ctx.task_mgr,
        agent=bundle.agent,
        conv=bundle.conv,
    )
    # 注意：agent_tool 回填已由 create_session 完成，删除 driver 里原来的两行
```

- [ ] **步骤 7：全量回归**

运行：`uv run pytest tests/ -x -q`
预期：全部通过；手工冒烟：`uv run alincode`（或 `.venv\Scripts\python.exe -m Alincode`）启动 TUI，发一句话，确认流式/工具行/审批与改动前一致。

- [ ] **步骤 8：Commit**

```bash
git add Alincode/core_session.py Alincode/app.py Alincode/driver.py tests/test_core_session.py
git commit -m "refactor: 抽取 core_session 会话级构造，TUI 接受预构建 agent/conv"
```

---

## 任务 3：事件投影层 web/protocol.py

**文件：**
- 创建：`Alincode/web/__init__.py`（内容：`"""AlinCode WebUI 后端：FastAPI + WebSocket。"""`）
- 创建：`Alincode/web/protocol.py`
- 测试：`tests/web/__init__.py`（空文件）、`tests/web/test_protocol.py`

- [ ] **步骤 1：编写失败的测试**

```python
# tests/web/test_protocol.py
"""Event→JSON 投影与历史消息投影的纯函数测试。"""

from Alincode.agent import CompactEvent, CompactPhase, Event, Phase, ToolEvent
from Alincode.conversation import Message, ToolCall, ToolResult, Usage
from Alincode.permission import ApprovalRequest, Verdict
from Alincode.web.protocol import project_event, project_messages


def test_text_delta():
    assert project_event(Event(text="你好"), {}) == [
        {"type": "text.delta", "delta": "你好"}
    ]


def test_tool_start_end():
    start = Event(tool=ToolEvent(name="bash", args='{"cmd":"ls"}', phase=Phase.START))
    end = Event(tool=ToolEvent(name="bash", phase=Phase.END, result="ok", is_error=False))
    assert project_event(start, {}) == [
        {"type": "tool.start", "name": "bash", "args": '{"cmd":"ls"}'}
    ]
    assert project_event(end, {}) == [
        {"type": "tool.end", "name": "bash", "result": "ok", "is_error": False}
    ]


def test_approval_registers_future_and_is_not_serialized():
    import asyncio

    async def _run():
        fut = asyncio.get_event_loop().create_future()
        req = ApprovalRequest(tool_name="write_file", tool_args='{"path":"x"}',
                              reason="write outside root", verdict=Verdict.ASK, respond=fut)
        registry: dict = {}
        msgs = project_event(Event(approval=req), registry)
        assert len(msgs) == 1
        m = msgs[0]
        assert m["type"] == "approval.request"
        assert m["tool_name"] == "write_file"
        assert "respond" not in str(m)          # Future 绝不进入 JSON
        assert registry[m["request_id"]] is req

    asyncio.run(_run())


def test_err_and_done_project_to_strings():
    ev = Event(err=RuntimeError("boom"), notice="出错", done=True)
    types = [m["type"] for m in project_event(ev, {})]
    assert types == ["turn.error", "notice", "turn.done"]
    msgs = project_event(ev, {})
    assert msgs[0]["message"] == "boom"


def test_usage_iter_compact():
    ev = Event(usage=Usage(input_tokens=10, output_tokens=5, cache_write=1, cache_read=2),
               iter=3,
               compact=CompactEvent(phase=CompactPhase.AFTER_AUTO, before=100, after=40))
    msgs = project_event(ev, {})
    assert {"type": "compact", "phase": "after_auto", "before": 100, "after": 40,
            "error": ""} in msgs
    assert {"type": "usage", "input_tokens": 10, "output_tokens": 5,
            "cache_write": 1, "cache_read": 2} in msgs
    assert {"type": "iter", "value": 3} in msgs


def test_project_messages_pairs_tool_calls_with_results():
    msgs = [
        Message(role="user", content="写个文件"),
        Message(role="assistant", content="",
                tool_calls=[ToolCall(id="t1", name="write_file", input='{"path":"a.txt"}')]),
        Message(role="tool",
                tool_results=[ToolResult(tool_call_id="t1", content="written", is_error=False)]),
        Message(role="assistant", content="完成了"),
    ]
    blocks = project_messages(msgs)
    assert blocks[0] == {"kind": "user", "content": "写个文件"}
    assert blocks[1]["kind"] == "tool"
    assert blocks[1]["state"] == "done"
    assert blocks[1]["result"] == "written"
    assert blocks[2] == {"kind": "assistant", "content": "完成了"}
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/web/test_protocol.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'Alincode.web'`

- [ ] **步骤 3：实现 protocol.py**

```python
"""协议投影层：多态 Event → WebSocket JSON（纯函数，无 IO）。

Event 携带不可序列化成员（ApprovalRequest.respond 是活 Future、err 是 Exception），
本层负责安全投影：approval 用 request_id 替代 Future 并登记到注册表，
err 转 str。投影顺序与 TUI 的分支处理顺序一致（app.py:865-947）。
"""

from __future__ import annotations

import itertools

from Alincode.agent import Event, Phase
from Alincode.conversation import Message
from Alincode.permission import ApprovalRequest

_request_counter = itertools.count(1)

USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_write", "cache_read")


def project_event(ev: Event, approvals: dict[str, ApprovalRequest]) -> list[dict]:
    """Event → 下行消息列表（多数情况 1 条；err+notice+done 组合会多于 1 条）。"""
    out: list[dict] = []

    if ev.compact is not None:
        c = ev.compact
        out.append({
            "type": "compact",
            "phase": c.phase.value,
            "before": c.before,
            "after": c.after,
            "error": str(c.err) if c.err else "",
        })
    if ev.err is not None:
        out.append({"type": "turn.error", "message": str(ev.err)})
    if ev.notice:
        out.append({"type": "notice", "text": ev.notice})
    if ev.usage is not None:
        out.append({"type": "usage",
                    **{f: getattr(ev.usage, f) for f in USAGE_FIELDS}})
    if ev.iter:
        out.append({"type": "iter", "value": ev.iter})
    if ev.text:
        out.append({"type": "text.delta", "delta": ev.text})
    if ev.tool is not None:
        t = ev.tool
        if t.phase is Phase.START:
            out.append({"type": "tool.start", "name": t.name, "args": t.args})
        else:
            out.append({"type": "tool.end", "name": t.name,
                        "result": t.result, "is_error": t.is_error})
    if ev.approval is not None:
        rid = f"a{next(_request_counter)}"
        approvals[rid] = ev.approval
        out.append({
            "type": "approval.request",
            "request_id": rid,
            "tool_name": ev.approval.tool_name,
            "tool_args": ev.approval.tool_args,
            "reason": ev.approval.reason,
        })
    if ev.done:
        out.append({"type": "turn.done"})
    return out


def project_messages(msgs: list[Message]) -> list[dict]:
    """历史 Message 列表 → Block 列表（与前端 Block 类型同形）。"""
    blocks: list[dict] = []
    pending: dict[str, dict] = {}
    for m in msgs:
        if m.role == "user":
            blocks.append({"kind": "user", "content": m.content})
        elif m.role == "assistant":
            if m.content:
                blocks.append({"kind": "assistant", "content": m.content})
            for tc in m.tool_calls or []:
                b = {"kind": "tool", "name": tc.name, "args": tc.input,
                     "state": "running"}
                pending[tc.id] = b
                blocks.append(b)
        elif m.tool_results:
            for tr in m.tool_results:
                b = pending.get(tr.tool_call_id)
                if b is not None:
                    b["state"] = "done"
                    b["result"] = tr.content[:500]
                    b["isError"] = tr.is_error
    return blocks
```

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/web/test_protocol.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add Alincode/web/__init__.py Alincode/web/protocol.py tests/web/
git commit -m "feat(web): 事件投影层 protocol——Event 到 WebSocket JSON"
```

---

## 任务 4：WebSession——事件流消费与审批闭环

**文件：**
- 创建：`Alincode/web/session.py`
- 测试：`tests/web/test_session.py`

设计要点：

- 每个 WebSocket 连接对应一个 `WebSession`，内部持有独立 `SessionBundle`（因此拥有独立 Agent 与 `_run_lock`，多连接互不阻塞）。
- 所有下行消息先进 `outbox: asyncio.Queue`，由服务端单一 pump 协程发送——避免消费任务与请求处理并发写 socket。
- 审批：`project_event` 把 Future 登记到 `self._approvals[request_id]`；上行 `approval.respond` 查表 `set_result(Outcome)`，与 `app.py:536-540` 的 TUI 回传等价。
- 忙碌保护对应 TUI 的 `_chatting`（`app.py:695-697`）：忙碌时 `chat.send` 回 notice 拒绝。

- [ ] **步骤 1：编写失败的测试**

```python
# tests/web/test_session.py
"""WebSession：事件消费 + 审批闭环（FakeProvider 驱动真实 Agent 循环）。"""

import asyncio
import pytest

from Alincode.bootstrap import AppContext
from Alincode.config import AppConfig, ProviderConfig
from Alincode.conversation import StreamEvent, ToolCall
from Alincode.permission.engine import new_engine
from Alincode.tools import Registry
from Alincode.web.session import WebSession

# 复用 tests/test_agent.py 的 Fake 设施
from tests.test_agent import FakeProvider, FakeWriteTool


def _ctx(tmp_path, provider, registry) -> AppContext:
    engine, _ = new_engine(str(tmp_path))
    return AppContext(
        app_cfg=AppConfig(),
        provider_cfg=ProviderConfig(name="fake", protocol="anthropic",
                                     model="m", base_url="", api_key=""),
        provider=provider, registry=registry, engine=engine,
        instruction_text="", memory_text="", memory_manager=None,
        workspace=str(tmp_path), catalog=None, hook_engine=None,
        subagent_catalog=None, task_mgr=None, wt_mgr=None, team_mgr=None,
        agent_tool=None, team_commands=[], mcp_mgr=None,
    )


async def _collect_until(ws: WebSession, stop_type: str, timeout=5.0) -> list[dict]:
    got = []
    async def _pump():
        while True:
            m = await ws.outbox.get()
            got.append(m)
            if m["type"] == stop_type:
                return
    await asyncio.wait_for(_pump(), timeout)
    return got


@pytest.mark.asyncio
async def test_plain_text_turn(tmp_path):
    provider = FakeProvider([[StreamEvent(text="你好！"), StreamEvent(done=True)]])
    ws = WebSession(_ctx(tmp_path, provider, Registry()))
    await ws.open()
    await ws.send_user("在吗")
    msgs = await _collect_until(ws, "turn.done")
    types = [m["type"] for m in msgs]
    assert "text.delta" in types and types[-1] == "turn.done"
    assert not ws.busy


@pytest.mark.asyncio
async def test_approval_roundtrip_deny(tmp_path):
    # 第一轮：模型要求调用写工具（DEFAULT 模式下写操作触发 ASK）；
    # 第二轮：拒绝后模型收到错误结果并收尾。
    provider = FakeProvider([
        [StreamEvent(tool_calls=[ToolCall(id="t1", name="write_file", input='{"x":"1"}')])],
        [StreamEvent(text="已取消"), StreamEvent(done=True)],
    ])
    registry = Registry()
    registry.register(FakeWriteTool())
    ws = WebSession(_ctx(tmp_path, provider, registry))
    await ws.open()
    await ws.send_user("写个文件")

    req = await asyncio.wait_for(_next_of(ws, "approval.request"), 5.0)
    assert req["tool_name"] == "write_file"
    ws.respond_approval(req["request_id"], "deny_once")

    msgs = await _collect_until(ws, "turn.done")
    resolved = [m for m in msgs if m["type"] == "approval.resolved"]
    assert resolved and resolved[0]["outcome"] == "deny_once"
    tool_ends = [m for m in msgs if m["type"] == "tool.end"]
    assert tool_ends and tool_ends[0]["is_error"] is True


async def _next_of(ws: WebSession, want: str) -> dict:
    while True:
        m = await ws.outbox.get()
        if m["type"] == want:
            return m
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/web/test_session.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'Alincode.web.session'`

- [ ] **步骤 3：实现 session.py**

```python
"""WebSession：单个浏览器会话 = 一个 SessionBundle + 事件流消费协程。

与 TUI 的关系：消费的是同一个 Agent.run() 异步事件流，
本类等价于 app.py 中 _start_agent/_consume_events/_approve 的 Web 形态。
"""

from __future__ import annotations

import asyncio
import os

from Alincode.bootstrap import AppContext
from Alincode.core_session import SessionBundle, create_session
from Alincode.conversation import Message
from Alincode.hook.event import Event as HookEvent
from Alincode.permission import ApprovalRequest, Mode, Outcome
from Alincode.prompts import SYSTEM_PROMPT
from Alincode.web.protocol import project_event, project_messages

OUTCOME_MAP = {
    "allow_once": Outcome.ALLOW_ONCE,
    "allow_forever": Outcome.ALLOW_FOREVER,
    "deny_once": Outcome.DENY_ONCE,
}


class WebSession:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx
        self.bundle: SessionBundle = create_session(ctx)
        self.outbox: asyncio.Queue[dict] = asyncio.Queue()
        self._approvals: dict[str, ApprovalRequest] = {}
        self._turn_task: asyncio.Task | None = None
        self._cancel = asyncio.Event()
        self._mode = Mode.DEFAULT
        self.busy = False
        self._closed = False

    # ── 生命周期 ──────────────────────────────────────

    async def open(self) -> None:
        self.bundle.conv.add_system(SYSTEM_PROMPT)   # 对应 app.py:385
        await self._emit({
            "type": "session.info",
            "session_id": self.bundle.session_id,
            "workspace": self._ctx.workspace,
            "model": self._ctx.provider_cfg.model,
            "mode": self._mode.value,
        })
        await self._dispatch(HookEvent.SESSION_START)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._turn_task and not self._turn_task.done():
            self._cancel.set()
            self._turn_task.cancel()
        await self._dispatch(HookEvent.SESSION_END)
        self.bundle.writer.close()

    # ── 上行消息分发 ──────────────────────────────────

    async def handle(self, data: dict) -> None:
        t = data.get("type")
        if t == "chat.send":
            await self.send_user(str(data.get("text", "")))
        elif t == "approval.respond":
            self.respond_approval(str(data.get("request_id", "")),
                                  str(data.get("outcome", "")))
        elif t == "turn.cancel":
            self.cancel_turn()
        elif t == "session.resume":
            await self.resume(str(data.get("session_id", "")))
        else:
            await self._emit({"type": "notice", "text": f"未知消息类型: {t}"})

    # ── 用户消息 → 新轮次（对应 app.py:695-718）──────

    async def send_user(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.busy:
            await self._emit({"type": "notice", "text": "请等待当前回复完成..."})
            return

        if self._ctx.hook_engine is not None:
            result = await self._ctx.hook_engine.dispatch(
                HookEvent.USER_PROMPT_SUBMIT,
                {"event": HookEvent.USER_PROMPT_SUBMIT.value,
                 "session_id": self.bundle.session_id,
                 "cwd": self._ctx.workspace, "mode": self._mode.value,
                 "prompt": text},
            )
            if result.blocked:
                await self._emit({"type": "notice",
                                  "text": f"[hook {result.blocking_hook_id}] {result.reason}"})
                return
            self.bundle.runtime.append_reminders(result.injected_prompts)

        self.bundle.conv.add_user(text)
        await self._emit({"kind": "user", "type": "history.append",
                          "block": {"kind": "user", "content": text}})
        self.busy = True
        self._cancel = asyncio.Event()
        self._turn_task = asyncio.create_task(self._run_turn())

    async def _run_turn(self) -> None:
        """消费 agent.run() 事件流——与 TUI 共享的同一事件源。"""
        try:
            async for ev in self.bundle.agent.run(
                self.bundle.conv, mode=self._mode, cancel=self._cancel
            ):
                for msg in project_event(ev, self._approvals):
                    await self._emit(msg)
                if ev.err is not None or ev.done:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:  # 兜底：循环本身崩溃也要告知前端
            await self._emit({"type": "turn.error", "message": str(e)})
        finally:
            self.busy = False

    # ── 审批回传（对应 app.py:536-540）────────────────

    def respond_approval(self, request_id: str, outcome: str) -> None:
        req = self._approvals.pop(request_id, None)
        if req is None or req.respond is None or req.respond.done():
            return
        result = OUTCOME_MAP.get(outcome, Outcome.DENY_ONCE)
        req.respond.set_result(result)
        asyncio.create_task(self._emit({
            "type": "approval.resolved", "request_id": request_id,
            "outcome": result.value,
        }))

    def cancel_turn(self) -> None:
        self._cancel.set()

    # ── 会话恢复（对应 app.py:753-839 的精简版）──────

    async def resume(self, session_id: str) -> None:
        if self.busy:
            await self._emit({"type": "notice", "text": "请等待当前任务完成..."})
            return
        session_dir = os.path.join(self._ctx.workspace, ".Alincode", "sessions", session_id)
        if not os.path.isdir(session_dir):
            await self._emit({"type": "notice", "text": f"会话 {session_id} 不存在。"})
            return
        old = self.bundle
        self.bundle = create_session(self._ctx, resume_id=session_id)
        old.writer.close()
        await self._emit({
            "type": "history",
            "session_id": session_id,
            "blocks": project_messages(self.bundle.conv.messages),
        })

    # ── 内部 ──────────────────────────────────────────

    async def _emit(self, msg: dict) -> None:
        await self.outbox.put(msg)

    async def _dispatch(self, event: HookEvent) -> None:
        if self._ctx.hook_engine is None:
            return
        result = await self._ctx.hook_engine.dispatch(event, {
            "event": event.value,
            "session_id": self.bundle.session_id,
            "cwd": self._ctx.workspace,
            "mode": self._mode.value,
        })
        if event is HookEvent.SESSION_START:
            self.bundle.runtime.append_reminders(result.injected_prompts)
```

> MVP 简化说明：恢复会话不做「超 6 小时过时提示」与「超限自动压缩」（`app.py:774-812`）——agent 运行期的 `manage_context` 仍会自动兜底压缩；这两项列为后续迭代。

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/web/test_session.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add Alincode/web/session.py tests/web/test_session.py
git commit -m "feat(web): WebSession——消费共享事件流并闭环权限审批"
```

---

## 任务 5：FastAPI 服务与 --web 入口

**文件：**
- 创建：`Alincode/web/server.py`
- 修改：`Alincode/__main__.py`
- 修改：`pyproject.toml`（依赖）
- 测试：`tests/web/test_server.py`

- [ ] **步骤 1：显式声明依赖**

`pyproject.toml` 的 `dependencies` 追加：

```toml
    "fastapi>=0.115",
    "uvicorn>=0.30",
```

运行：`uv sync`
预期：安装成功（starlette/uvicorn 此前已作为 mcp 传递依赖存在，此步是显式化）。

- [ ] **步骤 2：编写失败的测试**

```python
# tests/web/test_server.py
"""REST + WebSocket 集成测试（FastAPI TestClient，不起真实端口）。"""

import os
import json
import pytest
from fastapi.testclient import TestClient

from Alincode.bootstrap import AppContext
from Alincode.config import AppConfig, ProviderConfig
from Alincode.conversation import StreamEvent
from Alincode.tools import Registry
from Alincode.web.server import create_app

from tests.test_agent import FakeProvider


def _ctx(tmp_path, provider) -> AppContext:
    from Alincode.permission.engine import PermissionEngine
    return AppContext(
        app_cfg=AppConfig(),
        provider_cfg=ProviderConfig(name="fake", protocol="anthropic",
                                     model="m", base_url="", api_key=""),
        provider=provider, registry=Registry(), engine=PermissionEngine(),
        instruction_text="", memory_text="", memory_manager=None,
        workspace=str(tmp_path), catalog=None, hook_engine=None,
        subagent_catalog=None, task_mgr=None, wt_mgr=None, team_mgr=None,
        agent_tool=None, team_commands=[], mcp_mgr=None,
    )


def test_health_and_sessions(tmp_path):
    # 造一个历史会话目录
    sdir = tmp_path / ".Alincode" / "sessions" / "20260815-000000-ab"
    sdir.mkdir(parents=True)
    (sdir / "conversation.jsonl").write_text(
        json.dumps({"role": "user", "content": "旧话题", "ts": 1}) + "\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(_ctx(tmp_path, FakeProvider([[]]))))
    assert client.get("/api/health").json() == {"ok": True}
    sessions = client.get("/api/sessions").json()
    assert sessions and sessions[0]["id"] == "20260815-000000-ab"
    blocks = client.get("/api/sessions/20260815-000000-ab/messages").json()
    assert blocks[0] == {"kind": "user", "content": "旧话题"}


def test_ws_full_turn(tmp_path):
    provider = FakeProvider([[StreamEvent(text="嗨"), StreamEvent(done=True)]])
    client = TestClient(create_app(_ctx(tmp_path, provider)))
    with client.websocket_connect("/ws") as conn:
        info = conn.receive_json()
        assert info["type"] == "session.info"
        conn.send_json({"type": "chat.send", "text": "在吗"})
        got = []
        for _ in range(20):
            m = conn.receive_json()
            got.append(m["type"])
            if m["type"] == "turn.done":
                break
        assert "text.delta" in got
```

- [ ] **步骤 3：运行测试验证失败**

运行：`uv run pytest tests/web/test_server.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'Alincode.web.server'`

- [ ] **步骤 4：实现 server.py**

```python
"""FastAPI 应用工厂 + WebSocket 端点 + 静态前端挂载。"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from Alincode.bootstrap import AppContext, build_context, shutdown_context
from Alincode.session.list import list_sessions
from Alincode.session.load import load_session
from Alincode.web.protocol import project_messages
from Alincode.web.session import WebSession

WEBUI_DIST = Path(__file__).resolve().parents[2] / "webui" / "dist"


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="AlinCode WebUI")
    sessions_dir = os.path.join(ctx.workspace, ".Alincode", "sessions")

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/api/sessions")
    async def sessions() -> list[dict]:
        return [
            {"id": s.id, "title": s.title, "model": s.model, "size": s.size,
             "modified_at": s.modified_at.isoformat()}
            for s in list_sessions(sessions_dir)
        ]

    @app.get("/api/sessions/{session_id}/messages")
    async def session_messages(session_id: str) -> list[dict]:
        sdir = os.path.join(sessions_dir, session_id)
        if not os.path.isdir(sdir):
            return []
        return project_messages(load_session(sdir))

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        session = WebSession(ctx)

        async def _pump() -> None:
            """唯一写 socket 的协程：outbox → 浏览器。"""
            while True:
                msg = await session.outbox.get()
                await ws.send_json(msg)

        pump = asyncio.create_task(_pump())
        await session.open()
        try:
            while True:
                data = await ws.receive_json()
                await session.handle(data)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await session.close()
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump

    # 静态前端（构建后）。dist 不存在时给提示页，避免 404 困惑。
    if WEBUI_DIST.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(WEBUI_DIST), html=True), name="ui")
    else:
        @app.get("/")
        async def index_hint() -> str:
            return ("AlinCode 后端已启动，但前端尚未构建。"
                    "请执行 cd webui && npm install && npm run build，"
                    "或使用 npm run dev 走 Vite 开发服务器（代理已配置）。")

    return app


def serve(config_path: str | None = None,
          host: str = "127.0.0.1", port: int = 8765) -> None:
    """同步入口：python -m Alincode --web。"""
    if host not in ("127.0.0.1", "localhost"):
        print("警告: WebUI 可驱动真实工具执行且 MVP 无鉴权，"
              "绑定非本机地址有安全风险！")

    async def _main() -> None:
        ctx = await build_context(config_path)
        app = create_app(ctx)
        cfg = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(cfg)
        try:
            await server.serve()
        finally:
            await shutdown_context(ctx)

    asyncio.run(_main())
```

- [ ] **步骤 5：实现 __main__.py 的 --web 分支**

```python
"""AlinCode 入口 — 使用 `python -m Alincode` 启动。"""

import sys


def main() -> None:
    if "--web" in sys.argv:
        argv = [a for a in sys.argv[1:] if a != "--web"]
        host, port, config_path = "127.0.0.1", 8765, None
        i = 0
        while i < len(argv):
            if argv[i] == "--host":
                host = argv[i + 1]; i += 2
            elif argv[i] == "--port":
                port = int(argv[i + 1]); i += 2
            else:
                config_path = argv[i]; i += 1
        from Alincode.web.server import serve
        serve(config_path=config_path, host=host, port=port)
        return
    from Alincode.driver import run
    run()


if __name__ == "__main__":
    main()
```

- [ ] **步骤 6：运行测试验证通过**

运行：`uv run pytest tests/web/ -v`
预期：全部 PASS

- [ ] **步骤 7：Commit**

```bash
git add Alincode/web/server.py Alincode/__main__.py pyproject.toml uv.lock tests/web/test_server.py
git commit -m "feat(web): FastAPI 服务 + WebSocket 端点 + --web 启动入口"
```

---

## 任务 6：前端脚手架（Vite + React + TS）

**文件：**
- 创建：`webui/package.json`、`webui/vite.config.ts`、`webui/tsconfig.json`、`webui/index.html`、`webui/src/main.tsx`、`webui/src/App.tsx`、`webui/src/styles.css`

- [ ] **步骤 1：创建 package.json**

```json
{
  "name": "alincode-webui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-markdown": "^9.0.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "typescript": "~5.6.2",
    "vite": "^5.4.11"
  }
}
```

- [ ] **步骤 2：创建 vite.config.ts（开发代理指向后端 8765）**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
});
```

- [ ] **步骤 3：创建 tsconfig.json 与 index.html**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "noEmit": true,
    "isolatedModules": true
  },
  "include": ["src"]
}
```

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AlinCode</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **步骤 4：安装依赖并验证脚手架**

运行：`cd webui && npm install && npm run build`
预期：构建成功（此时 src 只有占位 App，任务 7-9 填充）。

- [ ] **步骤 5：Commit**

```bash
git add webui/package.json webui/vite.config.ts webui/tsconfig.json webui/index.html
git commit -m "feat(webui): Vite + React + TS 脚手架与后端代理"
```

---

## 任务 7：协议类型与聊天状态机

**文件：**
- 创建：`webui/src/lib/protocol.ts`
- 创建：`webui/src/state/chatReducer.ts`
- 测试：`webui/src/state/chatReducer.test.ts`（可选：`npm i -D vitest` 后运行；不装也可，靠任务 10 e2e 兜底）

- [ ] **步骤 1：编写 protocol.ts——与协议契约逐字对应**

```ts
// webui/src/lib/protocol.ts

export type Block =
  | { kind: "user"; content: string }
  | { kind: "assistant"; content: string; streaming?: boolean }
  | { kind: "tool"; name: string; args: string; state: "running" | "done"; result?: string; isError?: boolean }
  | { kind: "approval"; requestId: string; toolName: string; toolArgs: string; reason: string; state: "pending" | "resolved"; outcome?: string }
  | { kind: "notice"; text: string; tone: "info" | "error" };

export type ServerMsg =
  | { type: "session.info"; session_id: string; workspace: string; model: string; mode: string }
  | { type: "history"; session_id: string; blocks: Block[] }
  | { type: "history.append"; block: Block }
  | { type: "text.delta"; delta: string }
  | { type: "tool.start"; name: string; args: string }
  | { type: "tool.end"; name: string; result: string; is_error: boolean }
  | { type: "approval.request"; request_id: string; tool_name: string; tool_args: string; reason: string }
  | { type: "approval.resolved"; request_id: string; outcome: string }
  | { type: "usage"; input_tokens: number; output_tokens: number; cache_write: number; cache_read: number }
  | { type: "iter"; value: number }
  | { type: "notice"; text: string }
  | { type: "compact"; phase: string; before: number; after: number; error: string }
  | { type: "turn.done" }
  | { type: "turn.error"; message: string };

export type ClientMsg =
  | { type: "chat.send"; text: string }
  | { type: "approval.respond"; request_id: string; outcome: "allow_once" | "allow_forever" | "deny_once" }
  | { type: "turn.cancel" }
  | { type: "session.resume"; session_id: string };
```

- [ ] **步骤 2：编写 chatReducer.ts**

```ts
// webui/src/state/chatReducer.ts
import type { Block, ServerMsg } from "../lib/protocol";

export interface ChatState {
  blocks: Block[];
  busy: boolean;
  connected: boolean;
  sessionId: string;
  inputTokens: number;
  outputTokens: number;
  iter: number;
}

export const initialChatState: ChatState = {
  blocks: [], busy: false, connected: false, sessionId: "",
  inputTokens: 0, outputTokens: 0, iter: 0,
};

/** 把流式增量折叠进最后一个 assistant 块；否则新开一块。 */
function pushDelta(blocks: Block[], delta: string): Block[] {
  const last = blocks[blocks.length - 1];
  if (last && last.kind === "assistant" && last.streaming) {
    return [...blocks.slice(0, -1), { ...last, content: last.content + delta }];
  }
  return [...blocks, { kind: "assistant", content: delta, streaming: true }];
}

/** 收尾最后一个流式块（tool.start / turn.done / turn.error 前调用）。 */
function seal(blocks: Block[]): Block[] {
  const last = blocks[blocks.length - 1];
  if (last && last.kind === "assistant" && last.streaming) {
    return [...blocks.slice(0, -1), { ...last, streaming: false }];
  }
  return blocks;
}

export function chatReducer(state: ChatState, msg: ServerMsg): ChatState {
  switch (msg.type) {
    case "session.info":
      return { ...state, connected: true, sessionId: msg.session_id };
    case "history":
      return { ...state, blocks: msg.blocks, busy: false, sessionId: msg.session_id };
    case "history.append":
      return { ...state, blocks: [...state.blocks, msg.block] };
    case "text.delta":
      return { ...state, blocks: pushDelta(state.blocks, msg.delta) };
    case "tool.start":
      return {
        ...state,
        blocks: [...seal(state.blocks),
                 { kind: "tool", name: msg.name, args: msg.args, state: "running" }],
      };
    case "tool.end": {
      // 配对策略：最近一个同名 running 工具块（与 TUI 顺序语义一致）
      const blocks = seal(state.blocks);
      for (let i = blocks.length - 1; i >= 0; i--) {
        const b = blocks[i];
        if (b.kind === "tool" && b.name === msg.name && b.state === "running") {
          const done: Block = { ...b, state: "done", result: msg.result, isError: msg.is_error };
          return { ...state, blocks: [...blocks.slice(0, i), done, ...blocks.slice(i + 1)] };
        }
      }
      return { ...state, blocks: [...blocks,
        { kind: "tool", name: msg.name, args: "", state: "done", result: msg.result, isError: msg.is_error }] };
    }
    case "approval.request":
      return {
        ...state,
        blocks: [...seal(state.blocks),
                 { kind: "approval", requestId: msg.request_id, toolName: msg.tool_name,
                   toolArgs: msg.tool_args, reason: msg.reason, state: "pending" }],
      };
    case "approval.resolved":
      return {
        ...state,
        blocks: state.blocks.map((b) =>
          b.kind === "approval" && b.requestId === msg.request_id
            ? { ...b, state: "resolved", outcome: msg.outcome }
            : b),
      };
    case "usage":
      return { ...state, inputTokens: msg.input_tokens, outputTokens: msg.output_tokens };
    case "iter":
      return { ...state, iter: msg.value };
    case "notice":
      return { ...state, blocks: [...state.blocks, { kind: "notice", text: msg.text, tone: "info" }] };
    case "compact":
      return {
        ...state,
        blocks: [...state.blocks, {
          kind: "notice", tone: "info",
          text: msg.error ? `上下文压缩失败: ${msg.error}`
                           : `上下文压缩 ${msg.phase}: ${msg.before} → ${msg.after} tokens`,
        }],
      };
    case "turn.error":
      return {
        ...state, busy: false,
        blocks: [...seal(state.blocks), { kind: "notice", text: msg.message, tone: "error" }],
      };
    case "turn.done":
      return { ...state, busy: false, blocks: seal(state.blocks) };
    default:
      return state;
  }
}
```

- [ ] **步骤 3：本地手工核对 reducer 关键路径（无测试框架时的最低验证）**

运行：`cd webui && npx tsc --noEmit`
预期：无类型错误。（若安装了 vitest，可为 `pushDelta/seal/tool.end 配对` 三个路径补单测。）

- [ ] **步骤 4：Commit**

```bash
git add webui/src/lib/protocol.ts webui/src/state/chatReducer.ts
git commit -m "feat(webui): 协议类型与聊天状态机 reducer"
```

---

## 任务 8：WebSocket 连接层与 ChatContext

**文件：**
- 创建：`webui/src/state/ChatContext.tsx`

设计要点（应用 React 最佳实践规则）：

- **text.delta 节流**：高频增量先累积到 `bufferRef`，用 `requestAnimationFrame` 每帧一次性 dispatch（对应 `rerender-use-ref-transient-values` + `rerender-transitions`，避免每个 token 一次渲染）。
- 其余低频消息直接 dispatch。
- 发送 API 通过 context 暴露 `sendText / respondApproval / cancelTurn / resumeSession`。

- [ ] **步骤 1：实现 ChatContext.tsx**

```tsx
// webui/src/state/ChatContext.tsx
import {
  createContext, useContext, useEffect, useMemo, useReducer, useRef,
  type ReactNode,
} from "react";
import type { ClientMsg, ServerMsg } from "../lib/protocol";
import { chatReducer, initialChatState, type ChatState } from "./chatReducer";

interface ChatApi {
  state: ChatState;
  sendText: (text: string) => void;
  respondApproval: (requestId: string, outcome: "allow_once" | "allow_forever" | "deny_once") => void;
  cancelTurn: () => void;
  resumeSession: (sessionId: string) => void;
}

const ChatContext = createContext<ChatApi | null>(null);

function wsUrl(): string {
  const proto = location.protocol === "https:" ? "wss://" : "ws://";
  return `${proto}${location.host}/ws`;
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const wsRef = useRef<WebSocket | null>(null);
  const bufferRef = useRef("");       // text.delta 帧内累积
  const rafRef = useRef(0);

  const send = (msg: ClientMsg) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  };

  useEffect(function connectWebSocket() {
    const ws = new WebSocket(wsUrl());
    wsRef.current = ws;

    ws.onmessage = (e: MessageEvent<string>) => {
      const msg = JSON.parse(e.data) as ServerMsg;
      if (msg.type === "text.delta") {
        bufferRef.current += msg.delta;
        if (!rafRef.current) {
          rafRef.current = requestAnimationFrame(function flushDeltaBuffer() {
            rafRef.current = 0;
            if (bufferRef.current) {
              dispatch({ type: "text.delta", delta: bufferRef.current });
              bufferRef.current = "";
            }
          });
        }
        return;
      }
      dispatch(msg);
      if (msg.type === "chat.busy") { /* 预留：服务端忙碌标记 */ }
    };
    ws.onclose = () => dispatch({ type: "session.info", session_id: "", workspace: "", model: "", mode: "" } as ServerMsg);

    return function cleanupWebSocket() {
      cancelAnimationFrame(rafRef.current);
      ws.close();
    };
  }, []);

  const api = useMemo<ChatApi>(() => ({
    state,
    sendText: (text) => {
      dispatch({ type: "history.append", block: { kind: "user", content: text } });
      dispatch({ type: "iter", value: state.iter }); // busy 由首个事件驱动；此处乐观置位
      send({ type: "chat.send", text });
    },
    respondApproval: (requestId, outcome) => send({ type: "approval.respond", request_id: requestId, outcome }),
    cancelTurn: () => send({ type: "turn.cancel" }),
    resumeSession: (sessionId) => send({ type: "session.resume", session_id: sessionId }),
  }), [state]);

  return <ChatContext.Provider value={api}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatApi {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat 必须在 ChatProvider 内使用");
  return ctx;
}
```

> 说明：`busy` 的置位——`chat.send` 后第一个下行事件到来前，UI 依据本地 `sendText` 即可禁用输入框；实现上在 `sendText` 里额外 dispatch 一条 `{type:"iter", value}` 不够干净，实施时改为给 reducer 增加一个本地动作 `LOCAL_BUSY`（类型定义里补 `| { type: "__local.busy" }`），这是唯一允许的前端私有动作。

- [ ] **步骤 2：类型检查**

运行：`cd webui && npx tsc --noEmit`
预期：无错误

- [ ] **步骤 3：Commit**

```bash
git add webui/src/state/ChatContext.tsx
git commit -m "feat(webui): WebSocket 连接层与 ChatContext（rAF 节流流式增量）"
```

---

## 任务 9：UI 组件

**文件：**
- 创建：`webui/src/components/ChatView.tsx`、`MessageList.tsx`、`UserBlock.tsx`、`AssistantBlock.tsx`、`ToolBlock.tsx`、`ApprovalCard.tsx`、`NoticeLine.tsx`、`Composer.tsx`、`StatusBar.tsx`
- 创建：`webui/src/App.tsx`（组装）、`webui/src/styles.css`
- 创建：`webui/src/main.tsx`

视觉基调：深色终端风（背景 #0d1117、正文 #e6edf3、等宽字体栈），与 TUI 的青色工具行（`#00afff` 对应 `#4cc2ff`）呼应。样式集中在 `styles.css`，组件不引入 UI 组件库（YAGNI；后续需要再上 shadcn）。

应用的 React 规则：`AssistantBlock` 用 `memo` 包裹（`rerender-memo`，流式期间只有最后一块在变）；react-markdown 通过 `React.lazy` 动态导入（`bundle-conditional`，Markdown 解析不进入首屏关键路径——对应 TUI「Markdown 只在固化时渲染一次」的语义：流式中渲染纯文本，`streaming` 结束后才走 Markdown）；消息列表项用 `content-visibility: auto`（`rendering-content-visibility`）。

- [ ] **步骤 1：实现各组件（代码）**

```tsx
// webui/src/components/AssistantBlock.tsx
import { lazy, memo, Suspense } from "react";
import type { Block } from "../lib/protocol";

const Markdown = lazy(() => import("react-markdown"));

export const AssistantBlock = memo(function AssistantBlock(
  { block }: { block: Extract<Block, { kind: "assistant" }> },
) {
  if (block.streaming) {
    // 流式中：纯文本（与 TUI StreamText 行为一致）
    return <div className="msg assistant streaming">● {block.content}</div>;
  }
  return (
    <div className="msg assistant">
      <Suspense fallback={<pre className="md-fallback">{block.content}</pre>}>
        <Markdown>{block.content}</Markdown>
      </Suspense>
    </div>
  );
});
```

```tsx
// webui/src/components/ToolBlock.tsx
import type { Block } from "../lib/protocol";

export function ToolBlock({ block }: { block: Extract<Block, { kind: "tool" }> }) {
  return (
    <details className="msg tool" open={block.state === "running"}>
      <summary>
        <span className="tool-icon">⚙</span> {block.name}
        {block.state === "running" ? <span className="tool-running"> Running…</span> : null}
        {block.isError ? <span className="tool-error"> 失败</span> : null}
      </summary>
      {block.args ? <pre className="tool-args">{block.args}</pre> : null}
      {block.result ? <pre className="tool-result">{block.result}</pre> : null}
    </details>
  );
}
```

```tsx
// webui/src/components/ApprovalCard.tsx
import type { Block } from "../lib/protocol";
import { useChat } from "../state/ChatContext";

const OUTCOMES = [
  ["allow_once", "允许本次"],
  ["allow_forever", "永久允许"],
  ["deny_once", "拒绝"],
] as const;

export function ApprovalCard({ block }: { block: Extract<Block, { kind: "approval" }> }) {
  const { respondApproval } = useChat();
  return (
    <div className={`msg approval ${block.state}`}>
      <div className="approval-title">需要授权：{block.toolName}</div>
      <pre className="approval-args">{block.toolArgs}</pre>
      {block.reason ? <div className="approval-reason">{block.reason}</div> : null}
      {block.state === "pending" ? (
        <div className="approval-actions">
          {OUTCOMES.map(([value, label]) => (
            <button key={value} onClick={() => respondApproval(block.requestId, value)}>
              {label}
            </button>
          ))}
        </div>
      ) : (
        <div className="approval-outcome">已处理：{block.outcome}</div>
      )}
    </div>
  );
}
```

```tsx
// webui/src/components/MessageList.tsx
import { useEffect, useRef } from "react";
import type { Block } from "../lib/protocol";
import { AssistantBlock } from "./AssistantBlock";
import { ToolBlock } from "./ToolBlock";
import { ApprovalCard } from "./ApprovalCard";

export function MessageList({ blocks }: { blocks: Block[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(function scrollToBottom() {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [blocks]);

  return (
    <div className="message-list">
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "user":
            return <div key={i} className="msg user">{b.content}</div>;
          case "assistant":
            return <AssistantBlock key={i} block={b} />;
          case "tool":
            return <ToolBlock key={i} block={b} />;
          case "approval":
            return <ApprovalCard key={i} block={b} />;
          case "notice":
            return <div key={i} className={`msg notice ${b.tone}`}>{b.text}</div>;
        }
      })}
      <div ref={endRef} />
    </div>
  );
}
```

```tsx
// webui/src/components/Composer.tsx
import { useState } from "react";
import { useChat } from "../state/ChatContext";

export function Composer() {
  const { state, sendText, cancelTurn } = useChat();
  const [text, setText] = useState("");

  const submit = () => {
    const t = text.trim();
    if (!t || state.busy) return;
    sendText(t);
    setText("");
  };

  return (
    <div className="composer">
      <textarea
        value={text}
        placeholder="输入消息，Enter 发送，Shift+Enter 换行"
        rows={3}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      {state.busy
        ? <button onClick={cancelTurn}>取消</button>
        : <button onClick={submit} disabled={!text.trim()}>发送</button>}
    </div>
  );
}
```

```tsx
// webui/src/components/StatusBar.tsx
import { useChat } from "../state/ChatContext";

export function StatusBar() {
  const { state } = useChat();
  return (
    <div className="status-bar">
      <span>{state.connected ? "已连接" : "未连接"}</span>
      <span>会话 {state.sessionId || "—"}</span>
      <span>↑{state.inputTokens} ↓{state.outputTokens}</span>
      {state.iter > 0 ? <span>轮 {state.iter}</span> : null}
      {state.busy ? <span className="busy">运行中…</span> : null}
    </div>
  );
}
```

```tsx
// webui/src/components/ChatView.tsx
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";
import { StatusBar } from "./StatusBar";
import { useChat } from "../state/ChatContext";

export function ChatView() {
  const { state } = useChat();
  return (
    <div className="chat-view">
      <StatusBar />
      <MessageList blocks={state.blocks} />
      <Composer />
    </div>
  );
}
```

```tsx
// webui/src/App.tsx
import { ChatProvider } from "./state/ChatContext";
import { ChatView } from "./components/ChatView";

export default function App() {
  return (
    <ChatProvider>
      <ChatView />
    </ChatProvider>
  );
}
```

```tsx
// webui/src/main.tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`styles.css` 要点（完整文件实施时补齐）：`body` 深色底 `#0d1117`、等宽字体栈 `ui-monospace, "Cascadia Mono", Consolas, monospace`；`.message-list` 用 `content-visibility: auto; contain-intrinsic-size: 0 60px` 于 `.msg`；`.tool summary` 青色 `#4cc2ff`；`.approval` 黄色描边卡片；`.notice.error` 红色；`.status-bar` 底部固定、暗灰分隔线。

- [ ] **步骤 2：构建验证**

运行：`cd webui && npm run build`
预期：构建成功，产物在 `webui/dist/`

- [ ] **步骤 3：Commit**

```bash
git add webui/src/
git commit -m "feat(webui): 聊天视图组件——消息流/工具行/审批卡片/输入区/状态栏"
```

---

## 任务 10：端到端验证与文档

**文件：**
- 修改：`README.md`（新增 WebUI 使用说明）

- [ ] **步骤 1：后端全量测试**

运行：`uv run pytest tests/ -q`
预期：全部通过（含既有 TUI 相关测试——验证「TUI 保留不删、行为不变」）。

- [ ] **步骤 2：构建前端并启动服务**

运行：
```bash
cd webui && npm run build && cd ..
.venv\Scripts\python.exe -m Alincode --web --port 8765
```

- [ ] **步骤 3：手工 e2e 检查清单（浏览器打开 http://127.0.0.1:8765）**

1. 状态栏显示「已连接」与会话 ID；
2. 发送一条真实请求（如「读取 README.md 并总结」），观察：流式逐字输出 → 工具行（read_file Running… → 完成、可展开参数/结果）→ Markdown 渲染的最终回复；
3. 触发一次需要授权的操作（如「创建一个文件 test.txt」），确认审批卡片出现、三个按钮可用；分别验证「允许本次」与「拒绝」路径（拒绝后应看到 is_error 工具行与模型收尾）；
4. 长任务中点击「取消」，确认本轮终止；
5. 刷新页面后 `GET /api/sessions` 能看到刚才的会话；新连接发 `session.resume`（或在 UI 中调用 resumeSession）能恢复历史；
6. 对照 TUI：`python -m Alincode` 启动原 TUI，确认体验与改造前一致（回归确认）。

- [ ] **步骤 4：更新 README 并 Commit**

README 增加「WebUI」小节：启动命令、开发模式（`cd webui && npm run dev` + 后端 `--web`）、安全注意事项（仅本机绑定）。

```bash
git add README.md
git commit -m "docs: WebUI 使用说明"
```

---

## 自检结果

**1. 规格覆盖度：** 用户需求 = ① TUI 保留不删 → 任务 1/2 全部为抽取式重构，TUI 路径有回归测试与手工冒烟；② Web 与 TUI 共用同一 agent 事件流 → 两条路径都消费 `Agent.run()`（TUI 经 `app.py:_consume_events`，Web 经 `WebSession._run_turn`），agent.py 零改动；③ React 前端 → 任务 6-9。协议契约、审批闭环、会话恢复、取消均已覆盖。未覆盖（已在范围边界声明）：斜杠命令、Team、子 agent 进度、AskUser/Plan（后端不存在）。

**2. 占位符扫描：** bootstrap 任务中的搬移段以「逐行移动 + 行号 + 变量名不变」指令表达，因 200 行原代码复制进计划无增量信息且易漂移——实施时以 `driver.py:67-244` 原文为准；其余代码步骤均为完整可运行代码。styles.css 给出了设计要点而非全量 CSS——属于纯样式文件，不构成逻辑占位。

**3. 类型一致性：** `SessionBundle`（任务 2）在任务 4/5 中字段引用一致；`project_event(ev, approvals)` 两参数签名在任务 3 定义、任务 4 调用一致；`Outcome` 字符串映射 `allow_once/allow_forever/deny_once` 在协议契约、`OUTCOME_MAP`、前端 `ClientMsg` 三处一致；`Block` 形状前后端同形（`isError` 驼峰、`is_error` 蛇形分别用于 Block 与下行 tool.end，已在 reducer 的 `tool.end` 分支正确转换）。

## 风险与对策

| 风险 | 对策 |
|---|---|
| `_run_lock` 单飞：同一 WebSession 连发 | `busy` 保护 + 前端禁用输入框，与 TUI `_chatting` 等价 |
| WebSocket 并发写 | outbox 队列 + 单一 pump 协程 |
| Windows 上 uvicorn 信号处理 | uvicorn 官方支持 Windows；Ctrl+C 走 KeyboardInterrupt，无自定义信号 |
| 浏览器刷新丢失进行中的轮次 | MVP 接受（agent 循环随 WS 断开被 cancel）；JSONL 持久化保证消息不丢 |
| dist 未构建时访问 / | 返回中文提示页，不报 404 |
