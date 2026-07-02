"""SubAgent 解析器测试（T3）。"""

import pytest

from Alincode.subagent.parser import parse_definition
from Alincode.subagent.definition import Source


def test_parse_basic():
    md = b"""---
name: test-agent
description: A test agent
---
You are a test agent.
"""
    d = parse_definition(md, "test.md", Source.USER)
    assert d.name == "test-agent"
    assert d.description == "A test agent"
    assert d.system_prompt == "You are a test agent."
    assert d.source == Source.USER


def test_parse_with_tools():
    md = b"""---
name: tool-agent
description: Has tools
tools:
  - read_file
  - grep
disallowedTools:
  - write_file
model: haiku
maxTurns: 10
---
Body.
"""
    d = parse_definition(md, "t.md", Source.PROJECT)
    assert d.tools == ["read_file", "grep"]
    assert d.disallowed_tools == ["write_file"]
    assert d.model == "haiku"
    assert d.max_turns == 10


def test_parse_dont_ask():
    md = b"""---
name: auto-agent
description: Auto approve
permissionMode: dontAsk
---
Body.
"""
    d = parse_definition(md, "a.md", Source.BUILTIN)
    assert d.dont_ask is True
    assert d.permission_mode == "default"


def test_parse_missing_name():
    md = b"""---
description: No name
---
Body.
"""
    with pytest.raises(ValueError, match="name"):
        parse_definition(md, "x.md", Source.BUILTIN)


def test_parse_missing_description():
    md = b"""---
name: no-desc
---
Body.
"""
    with pytest.raises(ValueError, match="description"):
        parse_definition(md, "x.md", Source.BUILTIN)


def test_parse_invalid_model_fallback(capsys):
    md = b"""---
name: bad-model
description: Bad model
model: gpt-4
---
Body.
"""
    d = parse_definition(md, "x.md", Source.USER)
    assert d.model == "inherit"
    captured = capsys.readouterr()
    assert "unknown model" in captured.err.lower()


def test_parse_invalid_permission_mode_fallback(capsys):
    md = b"""---
name: bad-mode
description: Bad mode
permissionMode: weirdMode
---
Body.
"""
    d = parse_definition(md, "x.md", Source.USER)
    assert d.permission_mode == "default"
    captured = capsys.readouterr()
    assert "unknown permissionmode" in captured.err.lower()


def test_parse_background():
    md = b"""---
name: bg-agent
description: Background agent
background: true
---
Body.
"""
    d = parse_definition(md, "x.md", Source.PROJECT)
    assert d.background is True


def test_parse_bom():
    md = b"\xef\xbb\xbf---\nname: bom-agent\ndescription: BOM test\n---\nBody."
    d = parse_definition(md, "x.md", Source.BUILTIN)
    assert d.name == "bom-agent"
