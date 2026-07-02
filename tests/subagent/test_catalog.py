"""SubAgent Catalog 测试（T7）。"""

from pathlib import Path

from Alincode.subagent.catalog import load_catalog
from Alincode.subagent.definition import Source


def test_builtin_defs():
    c = load_catalog(".")
    names = [d.name for d in c.list()]
    assert "general-purpose" in names
    assert "Explore" in names
    assert "Plan" in names


def test_resolve_builtin():
    c = load_catalog(".")
    d = c.resolve("Explore")
    assert d is not None
    assert d.model == "haiku"
    assert "write_file" in d.disallowed_tools


def test_fork_definition():
    c = load_catalog(".")
    fd = c.fork_definition()
    assert fd.is_fork() is True
    assert fd.name == "__fork__"


def test_project_override(tmp_path, monkeypatch):
    """项目级覆盖内置 definition。"""
    # 防止测试环境加载真实 HOME
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fake_home")

    agents_dir = tmp_path / ".Alincode" / "agents"
    agents_dir.mkdir(parents=True)

    (agents_dir / "explore.md").write_text("""---
name: Explore
description: Project-level Explore override
maxTurns: 10
---
Project explore body.
""", encoding="utf-8")

    c = load_catalog(str(tmp_path))
    d = c.resolve("Explore")
    assert d is not None
    assert d.source == Source.PROJECT
    assert d.max_turns == 10
    assert d.system_prompt == "Project explore body."


def test_load_error_skipped(tmp_path, monkeypatch, capsys):
    """非法文件跳过，其他正常。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "fake_home")

    agents_dir = tmp_path / ".Alincode" / "agents"
    agents_dir.mkdir(parents=True)

    (agents_dir / "bad.md").write_text("no frontmatter", encoding="utf-8")
    (agents_dir / "good.md").write_text("""---
name: good-one
description: Good agent
---
Good body.
""", encoding="utf-8")

    c = load_catalog(str(tmp_path))
    assert c.resolve("good-one") is not None
    captured = capsys.readouterr()
    assert "parse error" in captured.err.lower() or "missing frontmatter" in captured.err.lower()
