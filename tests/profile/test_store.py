"""Profile 本机存储的隔离与安全行为测试。"""

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
