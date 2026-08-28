from scene_switch.matcher import find_named_scene_ids, wakeup_matches
from scene_switch.settings import settings_from_dict


def _settings(**overrides):
    base = {
        "require_consent": True,
        "chat": {
            "provider_id": "chat-fast",
            "aliases": "闲聊",
            "wakeup_words": "闲聊助手",
            "wakeup_match": "inherit",
        },
        "code": {
            "provider_id": "code-strong",
            "aliases": "代码",
            "wakeup_words": "^代码助手$",
            "wakeup_match": "regex",
        },
        "custom_scenes": [
            {
                "id": "docs",
                "display_name": "长文",
                "provider_id": "docs-p",
                "wakeup_words": "长文助手",
                "wakeup_match": "exact",
            }
        ],
    }
    base.update(overrides)
    return settings_from_dict(base)


def test_wakeup_contains_and_exact_and_regex():
    assert wakeup_matches("请来闲聊助手帮忙", "闲聊助手", "contains")
    assert not wakeup_matches("请来闲聊助手帮忙", "闲聊助手", "exact")
    assert wakeup_matches("闲聊助手", "闲聊助手", "exact")
    assert wakeup_matches("代码助手", "^代码助手$", "regex")
    assert not wakeup_matches("请代码助手出来", "^代码助手$", "regex")


def test_find_named_respects_scene_match_mode():
    settings = _settings()
    assert "chat" in find_named_scene_ids("闲聊助手在吗", settings)
    assert "docs" in find_named_scene_ids("长文助手", settings)
    assert "docs" not in find_named_scene_ids("我想找长文助手出来玩", settings)
    assert "code" in find_named_scene_ids("代码助手", settings)
    assert "code" not in find_named_scene_ids("请来代码助手", settings)
