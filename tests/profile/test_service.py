"""Profile 密钥保护、配置摘要与预算行为测试。"""

import json

from Alincode.profile.service import ProfileService
from Alincode.profile.store import ProfileStore


def test_provider_key_is_protected_and_summary_is_masked(tmp_path):
    store = ProfileStore(tmp_path)
    profile = store.create("Alin", "correct-password")
    service = ProfileService(store)

    service.save_provider(
        profile.id,
        protocol="openai",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key="sk-test-secret-9nF2",
    )

    assert service.provider_summary(profile.id) == {
        "protocol": "openai",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-••••9nF2",
    }
    assert service.provider_key(profile.id) == "sk-test-secret-9nF2"
    assert "sk-test-secret-9nF2" not in "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in tmp_path.rglob("*.json")
    )


def test_usage_reaches_budget_and_blocks_new_turns(tmp_path):
    store = ProfileStore(tmp_path)
    profile = store.create("Alin", "correct-password")
    service = ProfileService(store)

    service.set_budget(profile.id, 100)
    service.record_usage(profile.id, input_tokens=40, output_tokens=60)

    assert service.budget_status(profile.id) == {
        "budget": 100,
        "input_tokens": 40,
        "output_tokens": 60,
        "used_tokens": 100,
        "blocked": True,
    }
