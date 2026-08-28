from pathlib import Path

from scene_switch.flood import (
    looks_like_flood_complaint,
    matched_flood_phrases,
    parse_deepseek_verdict,
    parse_qwen_grab,
    pin_flood_provider,
    pin_verifier_provider,
    should_local_escalate,
)
from scene_switch.flood_state import FloodStore, LONG_MUTE_SECONDS
from scene_switch.settings import settings_from_dict


def test_local_phrases_cover_colloquial_complaints():
    names = ("测试机器人",)
    assert looks_like_flood_complaint("这些消息怎么这么多")
    assert looks_like_flood_complaint("哎呀话怎么这么多")
    assert looks_like_flood_complaint("刷屏了吧")
    assert looks_like_flood_complaint("@测试机器人 发的消息也太多了吧", bot_names=names)
    assert looks_like_flood_complaint("这机器人好烦啊")
    assert looks_like_flood_complaint("能不能少回点")
    assert looks_like_flood_complaint("一条接一条发")
    assert looks_like_flood_complaint("stop spamming")
    assert looks_like_flood_complaint(
        "怎么这么烦人", mentioned=True, bot_names=names
    )
    assert not looks_like_flood_complaint("怎么这么烦人")
    assert not looks_like_flood_complaint("你烦不烦啊")
    assert not looks_like_flood_complaint("今晚吃什么")
    assert not looks_like_flood_complaint("帮我总结一下这些消息")
    assert not looks_like_flood_complaint("这些消息帮我看看是什么意思")
    assert not looks_like_flood_complaint("喝水了吧")
    assert not looks_like_flood_complaint("作业好烦啊")
    assert not looks_like_flood_complaint("this is spam")


def test_pattern_catches_variants_without_exact_phrase():
    hits = matched_flood_phrases("你回的也太多了真看不下去")
    assert hits
    assert looks_like_flood_complaint("这机器人能不能少回点")


def test_flood_providers_are_not_pinned():
    assert pin_flood_provider("") == ""
    assert pin_flood_provider("my-qwen") == "my-qwen"
    assert pin_verifier_provider("审核模型/qwen") == "审核模型/qwen"
    assert pin_verifier_provider("", "chat-fast") == ""
    assert pin_verifier_provider("chat-fast") == "chat-fast"


def test_parse_two_stage_json():
    escalate, about, flood, reason = parse_qwen_grab(
        '{"escalate": true, "about_this_bot": true, "flood_complaint": true, "reason": "点名刷屏"}'
    )
    assert escalate and about and flood
    assert "刷屏" in reason
    escalate, about, flood, _ = parse_qwen_grab(
        '{"escalate": false, "about_this_bot": false, "flood_complaint": true}'
    )
    assert not escalate
    escalate, about, flood, _ = parse_qwen_grab(
        '{"escalate": false, "about_this_bot": true, "flood_complaint": true}'
    )
    assert not escalate
    wrapped = "<think>ok</think>```json\n{\"escalate\": true, \"about_this_bot\": true, \"flood_complaint\": true}\n```"
    escalate, about, flood, _ = parse_qwen_grab(wrapped)
    assert escalate and about and flood
    escalate, about, flood, _ = parse_qwen_grab("escalate: true about_this_bot: 是 flood_complaint: true")
    assert escalate
    mute, why = parse_deepseek_verdict(
        '{"mute": true, "about_this_bot": true, "reason": "确认是本机器人刷屏"}'
    )
    assert mute
    mute, _ = parse_deepseek_verdict(
        '{"mute": true, "about_this_bot": false, "reason": "别人"}'
    )
    assert not mute


def test_local_escalate_when_bot_is_named():
    names = ("测试机器人",)
    assert should_local_escalate("@测试机器人 怎么这么烦人", names, True)
    assert should_local_escalate("测试机器人你烦不烦", names, False)
    assert should_local_escalate("这机器人好烦", names, False)
    assert not should_local_escalate("怎么这么烦人", names, False)
    assert not should_local_escalate("bottom of the bottle 好烦啊", names, False)


def test_capture_and_second_strike_locks():
    path = Path(__file__).resolve().parent / "_tmp_flood.json"
    try:
        store = FloodStore(path)
        now = 1_700_000_000.0
        store.remember_line("g1", "u1", "怎么这么烦人", is_bot=False, now=now)
        store.remember_line("g1", "BOT", "你好呀", is_bot=True, now=now)
        captured = store.format_capture("g1")
        assert "USER u1" in captured
        assert "BOT:" in captured
        store.note_bot_speak("g1", now=now)
        assert store.bot_spoke_within("g1", 600, now=now + 10)
        assert not store.bot_spoke_within("g1", 600, now=now + 601)
        assert store.add_strike("g1", window_seconds=1800, now=now) == 1
        assert store.add_strike("g1", window_seconds=1800, now=now + 60) == 2
        store.lock("g1")
        assert store.is_locked("g1")
        store.unlock("g1")
        assert not store.is_locked("g1")
        assert LONG_MUTE_SECONDS > 3600
    finally:
        path.unlink(missing_ok=True)


def test_settings_flood_defaults_are_unbound():
    settings = settings_from_dict({"chat": {"provider_id": "flash"}})
    assert settings.flood_audit_enabled is False
    assert settings.flood_admin_ids == ()
    assert settings.flood_bot_names == ()
    assert pin_flood_provider(settings.flood_provider_id) == ""
    assert pin_verifier_provider(settings.flood_verifier_provider_id) == ""
    assert "刷屏了" in settings.flood_strong_phrases
