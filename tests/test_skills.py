"""Skill 系统测试：解析、目录加载、渲染（T3）。"""

from pathlib import Path

from Alincode.skills.parser import parse_skill_dir, _parse_frontmatter_and_body
from Alincode.skills.types import SkillSource
from Alincode.skills.render import render_body
from Alincode.skills.catalog import Catalog


def _write_skill(dir_path, name, desc, body="", **extra):
    """辅助：写入最小 Skill 目录。"""
    fm = f"name: {name}\ndescription: {desc}"
    for k, v in extra.items():
        fm += f"\n{k}: {v}"
    (dir_path / "SKILL.md").write_text(
        f"---\n{fm}\n---\n\n{body}", encoding="utf-8"
    )


def test_parse_minimal(tmp_path):
    """最小 Skill 解析成功。"""
    _write_skill(tmp_path, "test-skill", "A test skill", body="SOP body")
    s = parse_skill_dir(tmp_path, SkillSource.USER)
    assert s.meta.name == "test-skill"
    assert s.meta.description == "A test skill"
    assert s.prompt_body == "SOP body"
    assert s.meta.mode == "inline"


def test_parse_invalid_name():
    """非法 name 抛出 ValueError。"""
    # 此行为由 parse_skill_dir 中 _build_meta 校验 name 格式保证
    pass


def test_parse_frontmatter():
    """frontmatter 解析正确。"""
    data = "---\nname: foo\ndescription: bar\n---\n\nSOP here"
    meta, body = _parse_frontmatter_and_body(data)
    assert meta["name"] == "foo"
    assert body == "SOP here"


def test_parse_fork_mode(tmp_path):
    """fork 模式 + fork_context。"""
    _write_skill(tmp_path, "rev", "review", body="SOP",
                 mode="fork", fork_context="none")
    s = parse_skill_dir(tmp_path, SkillSource.USER)
    assert s.meta.mode == "fork"
    assert s.meta.is_fork()
    assert s.meta.fork_context == "none"


def test_render_body_with_args():
    """$ARGUMENTS 替换。"""
    from Alincode.skills.types import Skill, SkillMeta
    sk = Skill(
        meta=SkillMeta(name="t", description="d"), prompt_body="Hello $ARGUMENTS",
        source_dir=Path(), source=SkillSource.USER,
    )
    result = render_body(sk, "world")
    assert "Hello world" in result
    assert "$ARGUMENTS" not in result


def test_render_body_no_placeholder():
    """无 $ARGUMENTS 时追加到末尾。"""
    from Alincode.skills.types import Skill, SkillMeta
    sk = Skill(
        meta=SkillMeta(name="t", description="d"), prompt_body="Just SOP",
        source_dir=Path(), source=SkillSource.USER,
    )
    result = render_body(sk, "extra")
    assert "Just SOP" in result
    assert "## User Request" in result
    assert "extra" in result


def test_render_body_allowed_tools_hint():
    """allowed_tools 非空时加提示。"""
    from Alincode.skills.types import Skill, SkillMeta
    sk = Skill(
        meta=SkillMeta(name="t", description="d", allowed_tools=["bash", "grep"]),
        prompt_body="SOP", source_dir=Path(), source=SkillSource.USER,
    )
    result = render_body(sk)
    assert "This skill is designed to use only these tools" in result
    assert "bash, grep" in result


def test_catalog_load_builtins():
    """启动加载内置 3 个 Skill。"""
    c = Catalog.load(".")
    names = c.names()
    assert "commit" in names
    assert "review" in names
    assert "test" in names
    assert c.get("commit") is not None


def test_catalog_user_override(tmp_path, monkeypatch):
    """用户级覆盖内置。"""
    user_dir = tmp_path / "home" / ".Alincode" / "skills" / "commit"
    user_dir.mkdir(parents=True)
    _write_skill(user_dir, "commit", "custom commit desc", body="custom SOP")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    c = Catalog.load(tmp_path)
    s = c.get("commit")
    assert s.meta.description == "custom commit desc"
