from scene_switch.settings import settings_from_dict


def test_custom_scene_overrides_and_alias():
    settings = settings_from_dict(
        {
            "chat": {"provider_id": "chat-fast", "aliases": "闲聊", "keywords": ""},
            "code": {"provider_id": "code-strong", "aliases": "代码", "keywords": ""},
            "search": {"provider_id": "", "aliases": "", "keywords": ""},
            "vision": {"provider_id": "", "aliases": "", "keywords": ""},
            "model_aliases": "gpt=chat\ntranslator=translate",
            "custom_scenes": [
                {
                    "id": "translate",
                    "display_name": "翻译",
                    "provider_id": "mt-1",
                    "aliases": "翻译\ntranslate",
                    "keywords": "翻译成\n译成",
                }
            ],
        }
    )
    assert settings.scene("translate") is not None
    assert settings.scene("translate").enabled
    scene_id, provider_id = settings.resolve_target("翻译")
    assert scene_id == "translate"
    assert provider_id == "mt-1"
    scene_id, provider_id = settings.resolve_target("translator")
    assert scene_id == "translate"
    assert provider_id == "mt-1"
    scene_id, provider_id = settings.resolve_target("gpt")
    assert scene_id == "chat"
    assert provider_id == "chat-fast"


def test_builtin_scene_effort_defaults():
    settings = settings_from_dict(
        {
            "chat": {"provider_id": "chat-fast"},
            "code": {"provider_id": "code-strong"},
            "translate": {"provider_id": "mt-1"},
            "write": {"provider_id": "write-1"},
        }
    )
    assert settings.scene("chat").reasoning_effort == ""
    assert settings.scene("code").reasoning_effort == ""
    assert settings.scene("translate").reasoning_effort == ""
    assert settings.scene("write").reasoning_effort == ""
    assert settings.classifier_reasoning_effort == ""
    assert settings.classifier_timeout_seconds == 12
    assert settings.override_reasoning_effort is False
    assert settings.require_consent is True
    assert settings.honor_existing_selection is False
    assert settings.wakeup_match_mode == "contains"
    assert settings.session_think_commands is True
    assert settings.flood_audit_enabled is False
    assert settings.flood_admin_ids == ()
    assert settings.flood_bot_names == ()
    assert settings.blocked_personas == ()
    assert settings.switch_persona is True
    assert settings.sync_official_persona is True
    assert settings.sync_official_persona_in_groups is False
    assert settings.persona_mode == "overlay"
    assert settings.scene("chat").persona_label == "闲聊伙伴"
    assert "闲聊伙伴" in settings.scene("chat").persona_prompt
    assert settings.scene("code").persona_label == "编程助手"


def test_persona_can_be_disabled_per_scene_or_globally():
    settings = settings_from_dict(
        {
            "switch_persona": False,
            "chat": {"provider_id": "chat-fast"},
            "code": {"provider_id": "code-strong", "persona_prompt": "off"},
        }
    )
    assert settings.switch_persona is False
    assert settings.scene("code").persona_prompt == ""
    assert settings.scene("code").persona_id == ""


def test_sync_official_persona_can_be_disabled():
    settings = settings_from_dict({"sync_official_persona": False, "chat": {"provider_id": "c"}})
    assert settings.sync_official_persona is False
    groups = settings_from_dict(
        {"sync_official_persona_in_groups": True, "chat": {"provider_id": "c"}}
    )
    assert groups.sync_official_persona_in_groups is True


def test_override_reasoning_effort_and_timeout_can_be_enabled():
    settings = settings_from_dict(
        {
            "override_reasoning_effort": True,
            "classifier_timeout_seconds": 8,
            "chat": {"provider_id": "c"},
        }
    )
    assert settings.override_reasoning_effort is True
    assert settings.classifier_timeout_seconds == 8
    none = settings_from_dict(
        {"classifier_reasoning_effort": "none", "chat": {"provider_id": "c"}}
    )
    assert none.classifier_reasoning_effort == "none"
    zero = settings_from_dict({"classifier_timeout_seconds": 0, "chat": {"provider_id": "c"}})
    assert zero.classifier_timeout_seconds == 1


def test_conf_schema_defaults():
    import json
    from pathlib import Path

    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "_conf_schema.json").read_text(encoding="utf-8")
    )
    assert schema["override_reasoning_effort"]["default"] is False
    assert schema["require_consent"]["default"] is True
    assert schema["honor_existing_selection"]["default"] is False
    assert schema["flood_audit_enabled"]["default"] is False
    assert schema["flood_admin_ids"]["default"] == ""
    assert schema["wakeup_match_mode"]["default"] == "contains"
    assert schema["session_think_commands"]["default"] is True
    assert schema["chat"]["items"]["reasoning_effort"]["default"] == "provider"
    assert schema["chat"]["items"]["provider_id"]["_special"] == "select_provider"
    assert "medium" in schema["chat"]["items"]["reasoning_effort"]["options"]
    assert schema["classifier_timeout_seconds"]["default"] == 12
    assert schema["classifier_timeout_seconds"]["type"] == "int"
    assert schema["classifier_reasoning_effort"]["default"] == "provider"
    assert schema["classifier_provider_id"]["_special"] == "select_provider"
    assert schema["chat"]["items"]["provider_id"]["_special"] == "select_provider"
