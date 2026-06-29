"""LoadSkill 工具实现（T14）。"""

from __future__ import annotations

import json

from Alincode.skills.active import ActiveSkills
from Alincode.skills.render import render_body
from Alincode.tools import Result


class LoadSkillTool:
    """系统工具：加载 Skill 的完整 SOP 并注册专属工具。"""

    def __init__(self, catalog, active: ActiveSkills, registry) -> None:
        self._catalog = catalog
        self._active = active
        self._registry = registry

    def name(self) -> str:
        return "load_skill"

    def description(self) -> str:
        return (
            "加载一个 Skill 的完整 SOP 指令和专属工具。"
            "先用 Available Skills 列表确认 Skill 名称，再调用此工具激活。"
        )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要激活的 Skill 名称",
                },
            },
            "required": ["name"],
        }

    @property
    def read_only(self) -> bool:
        return True

    @property
    def is_system(self) -> bool:
        return True

    async def execute(self, args: str) -> Result:
        params = json.loads(args) if args.strip() else {}
        name = params.get("name", "").strip()
        if not name:
            return Result(content="缺少参数: name", is_error=True)

        skill = self._catalog.get(name)
        if skill is None:
            return Result(content=f"未知 Skill: {name}", is_error=True)

        # 重读最新 SKILL.md
        try:
            skill_md = skill.source_dir / "SKILL.md"
            if skill_md.is_file():
                from Alincode.skills.parser import _parse_frontmatter_and_body
                _, body = _parse_frontmatter_and_body(skill_md.read_text(encoding="utf-8"))
                skill.prompt_body = body
        except Exception:
            pass  # 回退到缓存版本

        # 渲染并激活
        rendered = render_body(skill)
        self._active.activate(name, rendered)

        # 注册专属工具
        registered = 0
        for ts in skill.tool_specs:
            try:
                self._registry.register(SkillToolAdapter(ts))
                registered += 1
            except Exception:
                pass  # 重复注册静默跳过

        return Result(
            content=(
                f"Skill {name} 已激活。SOP 已钉入环境上下文。"
                + (f" {registered} 个专属工具已注册。" if registered else "")
            ),
            is_error=False,
        )


class SkillToolAdapter:
    """将 ToolSpec 适配为 Tool 协议（asyncio subprocess）。"""

    def __init__(self, spec) -> None:
        self._spec = spec

    def name(self) -> str:
        return self._spec.name

    def description(self) -> str:
        return self._spec.description

    def parameters(self) -> dict:
        return self._spec.input_schema

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, args: str) -> Result:
        import asyncio
        cmd = self._spec.command
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._spec.base_dir),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=args.encode("utf-8")),
                timeout=30,
            )
            if proc.returncode != 0:
                return Result(
                    content=f"工具退出码 {proc.returncode}: {stderr.decode('utf-8', errors='replace')}",
                    is_error=True,
                )
            return Result(content=stdout.decode("utf-8", errors="replace"))
        except asyncio.TimeoutError:
            return Result(content="工具执行超时 (30s)", is_error=True)
        except Exception as e:
            return Result(content=f"工具执行失败: {e}", is_error=True)
