"""Profile 的模型配置、密钥和预算服务。"""

from __future__ import annotations

import json
from pathlib import Path

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

    def set_budget(self, profile_id: str, budget: int) -> None:
        if budget < 0:
            raise ValueError("预算不能为负数")
        status = self._usage(profile_id)
        status["budget"] = budget
        self._write_usage(profile_id, status)

    def set_workspace(self, profile_id: str, workspace: str | Path) -> None:
        """保存 Profile 的项目目录，只接受已存在的目录。"""
        path = Path(workspace).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("项目目录不存在或不是目录")
        self._write_json(self._store.profile_dir(profile_id) / "workspace.json", {
            "path": str(path),
        })

    def workspace(self, profile_id: str) -> str | None:
        """返回 Profile 的项目目录；尚未设置时为 None。"""
        path = self._store.profile_dir(profile_id) / "workspace.json"
        if not path.is_file():
            return None
        return self._read_json(path)["path"]

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
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)


def _mask_key(api_key: str) -> str:
    """显示最少尾部字符，避免界面和 API 泄露完整密钥。"""
    if len(api_key) <= 6:
        return "••••"
    prefix = api_key[:3] if api_key.startswith("sk-") else ""
    return f"{prefix}••••{api_key[-4:]}"
