"""SubAgent 机制：Agent 角色定义与 Catalog。"""

from Alincode.subagent.definition import Definition, Source
from Alincode.subagent.parser import parse_definition, parse_file, parse_frontmatter_and_body
from Alincode.subagent.catalog import Catalog, load_catalog
from Alincode.subagent.embed import builtin_definitions

__all__ = [
    "Definition", "Source",
    "parse_definition", "parse_file", "parse_frontmatter_and_body",
    "Catalog", "load_catalog",
    "builtin_definitions",
]
