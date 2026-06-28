"""记忆系统测试：索引加载、笔记 CRUD、截断（T15）。"""

import os

from Alincode.memory.types import UpdateAction
from Alincode.memory.store import Store
from Alincode.memory.manager import Manager
from Alincode.memory.prompts import MEMORY_UPDATE_PROMPT


def test_store_load_empty_index(tmp_path):
    """无 MEMORY.md → 返回空字符串。"""
    store = Store(str(tmp_path))
    store.ensure_dir()
    assert store.load_index() == ""


def test_store_create_note(tmp_path):
    """创建笔记 → 文件存在 + 索引更新。"""
    store = Store(str(tmp_path))
    store.ensure_dir()
    act = UpdateAction(
        action="create", level="project",
        type="project_knowledge", title="API规范",
        slug="api_conventions", content="使用 RESTful 风格。",
    )
    store.apply([act])
    # 文件存在
    files = os.listdir(str(tmp_path))
    md_files = [f for f in files if f.endswith(".md") and f != "MEMORY.md"]
    assert len(md_files) == 1
    # 索引已更新
    index = store.load_index()
    assert "API规范" in index


def test_store_delete_note(tmp_path):
    """删除笔记 → 文件消失。"""
    store = Store(str(tmp_path))
    store.ensure_dir()
    fn = "project_knowledge_test_slug.md"
    filepath = os.path.join(str(tmp_path), fn)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("---\ntype: project_knowledge\ntitle: Test\n---\n\ncontent")
    act = UpdateAction(action="delete", level="project", filename=fn)
    store.apply([act])
    assert not os.path.exists(filepath)


def test_manager_load_index_empty(tmp_path):
    """两级都无索引 → 返回空。"""
    mgr = Manager(
        project_dir=str(tmp_path / "proj"),
        user_dir=str(tmp_path / "user"),
    )
    assert mgr.load_index() == ""


def test_manager_load_index_truncate(tmp_path, monkeypatch):
    """超 25KB 截断。"""
    import Alincode.memory.manager as mgr_mod
    monkeypatch.setattr(mgr_mod._store_module, "INDEX_MAX_BYTES", 50)
    proj_dir = str(tmp_path / "proj")
    os.makedirs(proj_dir, exist_ok=True)
    with open(os.path.join(proj_dir, "MEMORY.md"), "w", encoding="utf-8") as f:
        f.write("A" * 200)
    mgr = Manager(project_dir=proj_dir, user_dir=str(tmp_path / "user"))
    result = mgr.load_index()
    # 截断后大小 ≤ 限制 + truncated 标注
    assert len(result.encode("utf-8")) <= 80


def test_prompt_structure():
    """Prompt 模板包含关键结构。"""
    assert "user_preference" in MEMORY_UPDATE_PROMPT
    assert "correction_feedback" in MEMORY_UPDATE_PROMPT
    assert "{conversation}" in MEMORY_UPDATE_PROMPT
