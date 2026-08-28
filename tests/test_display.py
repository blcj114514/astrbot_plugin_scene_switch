from scene_switch.display import compact_label, confirm_switch, reply_prefix
from scene_switch.router import RouteDecision
from scene_switch.settings import settings_from_dict


def _settings():
    return settings_from_dict(
        {
            "chat": {"provider_id": "chat-fast"},
            "code": {"provider_id": "code-strong"},
        }
    )


def test_compact_label_hides_provider_by_default():
    settings = _settings()
    text = compact_label(settings, "code", persona_label="编程助手", provider_id="code-strong")
    assert text == "『代码 · 编程助手』"
    assert "code-strong" not in text
    verbose = compact_label(
        settings,
        "code",
        persona_label="编程助手",
        provider_id="code-strong",
        effort="high",
        verbose=True,
    )
    assert "code-strong" in verbose
    assert "high" in verbose


def test_reply_prefix_and_confirm_copy():
    settings = _settings()
    assert reply_prefix("编程助手", "code", settings) == "〔编程助手〕 "
    decision = RouteDecision(
        applied=True,
        scene_id="chat",
        provider_id="chat-fast",
        source="force",
        reason="switch",
        stop_for_switch_only=True,
        persona_label="闲聊伙伴",
    )
    note = confirm_switch(settings, decision)
    assert "闲聊" in note
    assert "闲聊伙伴" in note
    assert "下一句" in note
