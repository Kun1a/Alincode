"""项目指令加载测试：三层加载、@include 展开、嵌套/环路/逃逸（T3）。"""


from Alincode.instructions import Loader


def test_load_empty(tmp_path):
    """三层都没有文件 → 返回空字符串。"""
    loader = Loader(project_root=str(tmp_path), user_home=str(tmp_path))
    assert loader.load() == ""


def test_single_layer(tmp_path):
    """只有项目根 MEWCODE.md 有内容。"""
    (tmp_path / "MEWCODE.md").write_text("project rules", encoding="utf-8")
    loader = Loader(project_root=str(tmp_path), user_home=str(tmp_path))
    result = loader.load()
    assert "project rules" in result


def test_include_expand(tmp_path):
    """@include 正常展开。"""
    (tmp_path / "MEWCODE.md").write_text("main\n@include rules.md\nend", encoding="utf-8")
    (tmp_path / "rules.md").write_text("rule content", encoding="utf-8")
    loader = Loader(project_root=str(tmp_path), user_home=str(tmp_path))
    result = loader.load()
    assert "rule content" in result
    assert "@include" not in result


def test_include_depth_limit(tmp_path):
    """6 层嵌套 → 第 6 层不展开。"""
    for i, name in enumerate(["a.md", "b.md", "c.md", "d.md", "e.md", "f.md"]):
        nxt = ["b.md", "c.md", "d.md", "e.md", "f.md", None][i]
        content = f"@include {nxt}" if nxt else "leaf"
        (tmp_path / name).write_text(content, encoding="utf-8")
    (tmp_path / "MEWCODE.md").write_text("@include a.md", encoding="utf-8")
    loader = Loader(project_root=str(tmp_path), user_home=str(tmp_path))
    result = loader.load()
    assert "超过最大嵌套深度" in result


def test_include_circular(tmp_path):
    """A include B, B include A → 环路检测。"""
    (tmp_path / "a.md").write_text("@include b.md", encoding="utf-8")
    (tmp_path / "b.md").write_text("@include a.md", encoding="utf-8")
    (tmp_path / "MEWCODE.md").write_text("@include a.md", encoding="utf-8")
    loader = Loader(project_root=str(tmp_path), user_home=str(tmp_path))
    result = loader.load()
    assert "检测到环路" in result


def test_include_escape(tmp_path):
    """路径逃逸 → 不加载。"""
    (tmp_path / "MEWCODE.md").write_text("@include ../outside.md", encoding="utf-8")
    loader = Loader(project_root=str(tmp_path), user_home=str(tmp_path))
    result = loader.load()
    assert "路径超出允许范围" in result


def test_include_binary(tmp_path):
    """二进制文件 → 跳过。"""
    (tmp_path / "a.md").write_bytes(b"\x00\x01\x02")
    (tmp_path / "MEWCODE.md").write_text("@include a.md", encoding="utf-8")
    loader = Loader(project_root=str(tmp_path), user_home=str(tmp_path))
    result = loader.load()
    assert "二进制格式" in result
