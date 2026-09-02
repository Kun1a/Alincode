"""Profile 的模型配置、密钥和预算服务。"""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Iterable

from Alincode.config import ProviderConfig
from Alincode.profile.secrets import protect, unprotect
from Alincode.profile.store import ProfileStore


class ProfileService:
    """在 Profile 目录内管理敏感配置和用量。"""

    def __init__(self, store: ProfileStore) -> None:
        self._store = store

    def save_provider(
        self, profile_id: str, *, protocol: str, model: str, base_url: str, api_key: str
    ) -> None:
        profile_dir = self._store.profile_dir(profile_id)
        (profile_dir / "api_key.bin").write_bytes(protect(api_key))
        self._write_json(profile_dir / "provider.json", {
            "protocol": protocol,
            "model": model,
            "base_url": base_url,
        })

    def provider_summary(self, profile_id: str) -> dict[str, str]:
        profile_dir = self._store.profile_dir(profile_id)
        config = self._read_json(profile_dir / "provider.json")
        return {**config, "api_key": _mask_key(self.provider_key(profile_id))}

    def provider_key(self, profile_id: str) -> str:
        return unprotect((self._store.profile_dir(profile_id) / "api_key.bin").read_bytes())

    def provider_config(self, profile_id: str) -> ProviderConfig:
        """仅在内存中还原当前 Profile 的 Provider 配置。"""
        config = self._read_json(self._store.profile_dir(profile_id) / "provider.json")
        return ProviderConfig(
            name=profile_id,
            protocol=config["protocol"],
            model=config["model"],
            base_url=config["base_url"],
            api_key=self.provider_key(profile_id),
        )

    def save_mcp_servers(self, profile_id: str, servers: dict) -> None:
        """保存不含密钥的 MCP Server 定义，敏感环境变量暂不由 Web UI 管理。"""
        if not isinstance(servers, dict):
            raise ValueError("MCP Server 配置格式错误")
        normalized: dict[str, dict[str, str | list[str]]] = {}
        for name, config in servers.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(config, dict):
                raise ValueError("MCP Server 配置格式错误")
            server_type = config.get("type")
            if server_type not in ("stdio", "http"):
                raise ValueError("MCP Server 类型必须是 stdio 或 http")
            entry: dict[str, str | list[str]] = {"type": server_type}
            if server_type == "stdio":
                command = config.get("command")
                args = config.get("args", [])
                if not isinstance(command, str) or not command.strip() or not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                    raise ValueError("stdio MCP Server 需要命令和字符串参数列表")
                entry.update(command=command.strip(), args=args)
            else:
                url = config.get("url")
                if not isinstance(url, str) or not url.strip():
                    raise ValueError("HTTP MCP Server 需要 URL")
                entry["url"] = url.strip()
            normalized[name.strip()] = entry
        self._write_json(self._store.profile_dir(profile_id) / "mcp.json", normalized)

    def mcp_servers(self, profile_id: str) -> dict:
        path = self._store.profile_dir(profile_id) / "mcp.json"
        return self._read_json(path) if path.is_file() else {}

    def set_budget(self, profile_id: str, budget: int) -> None:
        if budget < 0:
            raise ValueError("预算不能为负数")
        status = self._usage(profile_id)
        status["budget"] = budget
        self._write_usage(profile_id, status)

    def set_workspace(self, profile_id: str, workspace: str | Path) -> None:
        """兼容旧接口：保存并切换到指定项目目录。"""
        current = self.workspaces(profile_id)
        self.save_workspaces(profile_id, [*current["paths"], workspace], active_path=workspace)

    def workspace(self, profile_id: str) -> str | None:
        """返回当前项目目录；尚未设置时为 None。"""
        return self.workspaces(profile_id)["active_path"] or None

    def workspaces(self, profile_id: str) -> dict[str, list[str] | str]:
        """返回 Profile 的项目目录列表，并兼容旧版单目录数据。"""
        profile_dir = self._store.profile_dir(profile_id)
        path = profile_dir / "workspaces.json"
        if path.is_file():
            data = self._read_json(path)
            paths = data.get("paths", [])
            active_path = data.get("active_path", "")
            if isinstance(paths, list) and all(isinstance(item, str) for item in paths) and isinstance(active_path, str):
                return {"paths": paths, "active_path": active_path}
        legacy = profile_dir / "workspace.json"
        if legacy.is_file():
            workspace = self._read_json(legacy).get("path", "")
            if isinstance(workspace, str) and workspace:
                return {"paths": [workspace], "active_path": workspace}
        return {"paths": [], "active_path": ""}

    def save_workspaces(
        self, profile_id: str, workspaces: Iterable[str | Path], *, active_path: str | Path,
    ) -> dict[str, list[str] | str]:
        """保存去重后的项目目录列表，并指定其中一个为当前目录。"""
        paths: list[str] = []
        for workspace in workspaces:
            resolved = self._validated_workspace(workspace)
            if resolved not in paths:
                paths.append(resolved)
        active = self._validated_workspace(active_path)
        if active not in paths:
            paths.append(active)
        data = {"paths": paths, "active_path": active}
        self._write_json(self._store.profile_dir(profile_id) / "workspaces.json", data)
        return data

    @staticmethod
    def _validated_workspace(workspace: str | Path) -> str:
        path = Path(workspace).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("项目目录不存在或不是目录")
        return str(path)

    def record_usage(self, profile_id: str, *, input_tokens: int, output_tokens: int) -> None:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token 用量不能为负数")
        status = self._usage(profile_id)
        status["input_tokens"] += input_tokens
        status["output_tokens"] += output_tokens
        self._write_usage(profile_id, status)

    def budget_status(self, profile_id: str) -> dict[str, int | bool]:
        status = self._usage(profile_id)
        used = status["input_tokens"] + status["output_tokens"]
        return {
            **status,
            "used_tokens": used,
            "blocked": bool(status["budget"] and used >= status["budget"]),
        }

    def _usage(self, profile_id: str) -> dict[str, int]:
        path = self._store.profile_dir(profile_id) / "usage.json"
        if not path.is_file():
            return {"budget": 0, "input_tokens": 0, "output_tokens": 0}
        return self._read_json(path)

    def _write_usage(self, profile_id: str, status: dict[str, int]) -> None:
        self._write_json(self._store.profile_dir(profile_id) / "usage.json", status)

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        ProfileStore._write_json(path, data)


def _mask_key(api_key: str) -> str:
    """显示最少尾部字符，避免界面和 API 泄露完整密钥。"""
    if len(api_key) <= 6:
        return "••••"
    prefix = api_key[:3] if api_key.startswith("sk-") else ""
    return f"{prefix}••••{api_key[-4:]}"
