from types import SimpleNamespace

from scene_switch.persona import (
    PERSONA_BEGIN,
    apply_persona,
    extract_persona_block,
    fields_for_scene,
    persona_from_astrbot,
    resolve_persona_prompt,
)
from scene_switch.settings import settings_from_dict


def test_resolve_prefers_inline_prompt():
    prompt = resolve_persona_prompt(
        "code",
        persona_prompt="你是编程助手，只谈代码。",
        persona_id="coder",
        lookup={"coder": "你是严肃工程师。"},
    )
    assert prompt == "你是编程助手，只谈代码。"


def test_resolve_looks_up_persona_id():
    prompt = resolve_persona_prompt(
        "chat",
        persona_id="buddy",
        lookup={"buddy": "你是老邻居。"},
    )
    assert prompt == "你是老邻居。"


def test_resolve_off_disables_even_with_id():
    assert resolve_persona_prompt("code", persona_prompt="off", persona_id="coder") == ""
    assert resolve_persona_prompt("code", persona_id="关闭") == ""


def test_resolve_pending_id_without_lookup_is_empty():
    assert resolve_persona_prompt("code", persona_id="coder") == ""


def test_apply_persona_overlay_and_replace():
    overlaid = apply_persona(
        "你是默认机器人。",
        "你现在是编程助手。",
        scene_id="code",
        label="编程助手",
        mode="overlay",
    )
    assert "你是默认机器人。" in overlaid
    assert PERSONA_BEGIN in overlaid
    assert "编程助手" in overlaid
    assert "以本轮人设为准" in overlaid
    replaced = apply_persona(
        "你是默认机器人。",
        "你现在是编程助手。",
        scene_id="code",
        mode="replace",
    )
    assert "你是默认机器人。" in replaced
    assert "以本段为准" in replaced


def test_apply_persona_replaces_previous_block():
    first = apply_persona("", "第一套人设", scene_id="chat", label="闲聊伙伴")
    second = apply_persona(first, "第二套人设", scene_id="code", label="编程助手")
    assert "第一套人设" not in second
    assert "第二套人设" in second
    assert extract_persona_block(second).count(PERSONA_BEGIN) == 1


def test_apply_persona_strips_previous_official_block():
    first = apply_persona(
        "系统。\n# Persona Instructions\n\n旧官方人设。",
        "新场景人设",
        scene_id="code",
        label="编程助手",
    )
    assert "旧官方人设" not in first
    assert "新场景人设" in first
    assert "系统。" in first


def test_persona_from_astrbot_dict_and_object():
    assert persona_from_astrbot({"prompt": "来自 v3"}) == "来自 v3"
    assert persona_from_astrbot(SimpleNamespace(system_prompt="来自对象")) == "来自对象"


def test_apply_persona_handover_on_scene_change():
    text = apply_persona(
        "你是默认机器人。",
        "你现在是编程助手。",
        scene_id="code",
        label="编程助手",
        switched_from="chat",
    )
    assert "闲聊伙伴" in text
    assert "编程助手" in text
    assert "不要沿用上一轮" in text


def test_fields_for_scene_respects_enabled_flag():
    scene = settings_from_dict({"code": {"provider_id": "code-strong"}}).scene("code")
    ident, prompt, label = fields_for_scene(scene, enabled=True)
    assert ident is None
    assert prompt and "编程助手" in prompt
    assert label == "编程助手"
    assert fields_for_scene(scene, enabled=False) == (None, None, None)
