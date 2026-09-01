"""本机 Profile 元数据存储。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

from Alincode.profile.models import Profile


class ProfileStore:
    """按 Profile 隔离元数据与会话目录的文件存储。"""

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            local_app_data = os.environ.get("LOCALAPPDATA")
            root = Path(local_app_data or Path.home()) / "AlinCode" / "profiles"
        self._root = Path(root)

    def create(self, name: str, password: str) -> Profile:
        """创建一个 Profile，并建立独立的会话目录。"""
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Profile 名称不能为空")
        if not password:
            raise ValueError("Profile 密码不能为空")

        profile_id = secrets.token_hex(8)
        profile_dir = self._root / profile_id
        profile_dir.mkdir(parents=True, exist_ok=False)
        (profile_dir / "sessions").mkdir()
        self._write_json(profile_dir / "profile.json", {
            "id": profile_id,
            "name": cleaned_name,
            "password": self._password_record(password),
        })
        return Profile(id=profile_id, name=cleaned_name)

    def sessions_dir(self, profile_id: str) -> Path:
        """返回 Profile 专属的会话目录。"""
        return self._profile_dir(profile_id) / "sessions"

    def list_profiles(self) -> list[Profile]:
        """返回本机已创建的 Profile，不包含密码校验数据。"""
        if not self._root.is_dir():
            return []
        profiles = []
        for path in self._root.iterdir():
            profile_path = path / "profile.json"
            if profile_path.is_file():
                data = self._read_json(profile_path)
                profiles.append(Profile(id=data["id"], name=data["name"]))
        return sorted(profiles, key=lambda profile: profile.name.casefold())

    def get(self, profile_id: str) -> Profile:
        """读取一个 Profile 的可展示信息。"""
        data = self._read_json(self.profile_path(profile_id))
        return Profile(id=data["id"], name=data["name"])

    def profile_path(self, profile_id: str) -> Path:
        """返回 Profile 元数据文件路径。"""
        return self._profile_dir(profile_id) / "profile.json"

    def profile_dir(self, profile_id: str) -> Path:
        """返回 Profile 专属数据目录。"""
        return self._profile_dir(profile_id)

    def verify_password(self, profile_id: str, password: str) -> bool:
        """校验 Profile 密码，不暴露原始密码。"""
        record = self._read_json(self.profile_path(profile_id))["password"]
        salt = base64.b64decode(record["salt"])
        expected = base64.b64decode(record["digest"])
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
        return secrets.compare_digest(actual, expected)

    def _profile_dir(self, profile_id: str) -> Path:
        profile_dir = self._root / profile_id
        if not (profile_dir / "profile.json").is_file():
            raise KeyError(f"Profile 不存在: {profile_id}")
        return profile_dir

    @staticmethod
    def _password_record(password: str) -> dict[str, str]:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
        return {
            "salt": base64.b64encode(salt).decode(),
            "digest": base64.b64encode(digest).decode(),
        }

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        temp_path = path.with_suffix(".tmp")
        content = json.dumps(data, ensure_ascii=False)
        temp_path.write_text(content, encoding="utf-8")
        try:
            temp_path.replace(path)
        except OSError as error:
            if error.winerror != 17:
                raise
            # EFS 加密目录可能拒绝同目录的原子替换，回退为直接写入目标文件。
            path.write_text(content, encoding="utf-8")
