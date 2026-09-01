# tests/test_core_session.py
"""core_session：会话级组件构造（不依赖真实 provider 网络）。"""

import os

from Alincode.bootstrap import AppContext
from Alincode.config import AppConfig, ProviderConfig
from Alincode.conversation import ROLE_USER
from Alincode.core_session import create_session, make_replace_handler
from Alincode.permission.engine import PermissionEngine
from Alincode.tools import Registry, Result


class _FakeLoadSkill:
    """最小 Tool 协议实现，用于验证 active_skills 重绑定。"""

    def __init__(self) -> None:
        self._active = None

    def name(self) -> str:
        return "load_skill"

    def description(self) -> str:
        return ""

    def parameters(self) -> dict:
        return {}

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, args: str) -> Result:
        return Result(content="")


def _fake_ctx(tmp_path) -> AppContext:
    return AppContext(
        app_cfg=AppConfig(),
        provider_cfg=ProviderConfig(name="fake", protocol="anthropic",
                                     model="m", base_url="http://localhost:9",
                                     api_key="sk-test"),
        provider=None,            # create_session 不触碰 provider 网络层
        registry=new_registry_with_load_skill(),
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


def new_registry_with_load_skill() -> Registry:
    reg = Registry()
    reg.register(_FakeLoadSkill())
    return reg


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


def test_load_skill_active_rebind_to_session_runtime(tmp_path):
    ctx = _fake_ctx(tmp_path)
    fake_ls = ctx.registry.get("load_skill")
    bundle = create_session(ctx)
    assert fake_ls._active is bundle.runtime.active_skills
    bundle.writer.close()


def test_create_session_can_store_history_outside_agent_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    session_root = tmp_path / "profile" / "sessions"
    workspace.mkdir()
    ctx = _fake_ctx(workspace)

    bundle = create_session(ctx, session_root=session_root)

    assert bundle.runtime.session.session_dir.startswith(str(session_root))
    assert not (workspace / ".Alincode" / "sessions").exists()
    bundle.writer.close()
