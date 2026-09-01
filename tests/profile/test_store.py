"""Profile 本机存储的隔离与安全行为测试。"""

from pathlib import Path

from Alincode.profile.store import ProfileStore


def test_profiles_use_isolated_storage_and_passwords(tmp_path):
    store = ProfileStore(tmp_path)

    alin = store.create("Alin", "correct-password")
    demo = store.create("Demo", "another-password")

    assert alin.id != demo.id
    assert store.sessions_dir(alin.id) != store.sessions_dir(demo.id)
    assert store.sessions_dir(alin.id).is_dir()
    assert store.sessions_dir(demo.id).is_dir()
    assert store.verify_password(alin.id, "correct-password") is True
    assert store.verify_password(alin.id, "wrong-password") is False


def test_profile_creation_survives_windows_atomic_replace_failure(tmp_path, monkeypatch):
    original_replace = Path.replace

    def fail_for_temporary_file(path: Path, target: Path):
        if path.suffix == ".tmp":
            raise OSError(17, "cross-device move", None, 17)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_for_temporary_file)
    store = ProfileStore(tmp_path)

    profile = store.create("Alin", "correct-password")

    assert store.get(profile.id) == profile
    assert store.verify_password(profile.id, "correct-password") is True
