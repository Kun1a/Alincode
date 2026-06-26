"""配置加载：三层 YAML 文件（本地 > 项目 > 用户）+ 降级安全默认（F4/N5/AC6）。"""

from __future__ import annotations

from pathlib import Path
import yaml

from Alincode.permission import RuleRecord, Mode

# 配置文件名
SETTINGS_FILE = "settings.yaml"
LOCAL_SETTINGS_FILE = "settings.local.yaml"
# 项目级（在项目根下）
PROJECT_DIR = ".Alincode"


def load_rules(project_root: str) -> list[RuleRecord]:
    """加载三层 YAML 权限规则（用户→项目→本地），越靠近项目优先级越高。

    返回规则列表，本地层在前、项目层在中、用户层在后。
    加载失败降级：不抛异常、不中断（N5）。
    """
    user_dir = _user_config_dir()
    project_dir = Path(project_root) / PROJECT_DIR

    # 从远到近加载（用户 → 项目 → 本地），后加载的排在前面 → 优先级更高
    sources = [
        (user_dir / SETTINGS_FILE, "user"),
        (project_dir / SETTINGS_FILE, "project"),
        (project_dir / LOCAL_SETTINGS_FILE, "local"),
    ]

    all_rules: list[RuleRecord] = []

    for file_path, source_name in sources:
        try:
            data = _load_yaml(str(file_path))
            if data:
                perms = data.get("permissions", {})
                for entry in perms.get("deny", []):
                    tool, pattern = _parse_entry(entry)
                    if tool:
                        all_rules.append(RuleRecord(tool=tool, pattern=pattern, verdict="deny", source=source_name))
                for entry in perms.get("allow", []):
                    tool, pattern = _parse_entry(entry)
                    if tool:
                        all_rules.append(RuleRecord(tool=tool, pattern=pattern, verdict="allow", source=source_name))
        except Exception:
            # 格式非法 → 跳过该文件（N5）
            continue

    return all_rules


def load_default_mode(project_root: str) -> Mode | None:
    """按 本地 > 项目 > 用户 优先级加载 default_mode。

    返回 Mode 枚举值或 None（皆无时）。
    """
    user_dir = _user_config_dir()
    project_dir = Path(project_root) / PROJECT_DIR

    sources = [
        (project_dir / LOCAL_SETTINGS_FILE, "local"),
        (project_dir / SETTINGS_FILE, "project"),
        (user_dir / SETTINGS_FILE, "user"),
    ]

    mode_map = {
        "default": Mode.DEFAULT,
        "acceptedits": Mode.ACCEPT_EDITS,
        "plan": Mode.PLAN,
        "bypass": Mode.BYPASS,
    }

    for file_path, _ in sources:
        try:
            data = _load_yaml(str(file_path))
            if data and "default_mode" in data:
                val = str(data["default_mode"]).strip().lower()
                if val in mode_map:
                    return mode_map[val]
        except Exception:
            continue

    return None  # 皆无 → 上游默认 DEFAULT


def save_allow_rule(tool_friendly: str, args_str: str, project_root: str) -> bool:
    """将精确 allow 规则写入本地配置层（永久放行 AC10）。

    Args:
        tool_friendly: 友好工具名（如 "Bash"）
        args_str: 精确参数值（如 "git status"）
        project_root: 项目根

    Returns:
        True 写入成功，False 失败
    """
    from Alincode.permission.rules import _extract_match_value
    tool_name_map = {"Read": "read_file", "Write": "write_file", "Edit": "edit_file",
                      "Bash": "bash", "Glob": "glob", "Grep": "grep"}
    internal_name = tool_name_map.get(tool_friendly, tool_friendly)
    match_val = _extract_match_value(internal_name, args_str)
    if not match_val:
        return False

    entry = f"{tool_friendly}({match_val})"

    try:
        local_path = Path(project_root) / PROJECT_DIR / LOCAL_SETTINGS_FILE
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if local_path.exists():
            data = _load_yaml(str(local_path)) or {}
        else:
            data = {}

        data.setdefault("permissions", {}).setdefault("allow", [])
        allows = data["permissions"]["allow"]
        if entry not in allows:
            allows.append(entry)

        with open(local_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
        return True
    except Exception:
        return False


def _user_config_dir() -> Path:
    """用户级配置目录。"""
    return Path.home() / ".alincode"


def _load_yaml(path: str) -> dict | None:
    """加载 YAML 文件，不存在返回 None，格式非法抛异常。"""
    file_path = Path(path)
    if not file_path.is_file():
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_entry(entry: str) -> tuple[str, str]:
    """解析规则条目如 "Bash(git *)" → ("Bash", "git *")。"""
    import re
    m = re.match(r"^(\w+)\((.+)\)$", entry.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return "", ""
