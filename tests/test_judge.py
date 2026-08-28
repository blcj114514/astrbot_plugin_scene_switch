from scene_switch.helptext import build_feature_intro
from scene_switch.judge import fallback_from_heuristic, parse_judge_reply
from scene_switch.matcher import is_help_intent
from scene_switch.settings import settings_from_dict


def test_parse_json_verdict():
    verdict = parse_judge_reply(
        '{"scene":"code","reason":"用户要写代码"}',
        {"chat", "code", "search", "vision"},
    )
    assert verdict.action == "route"
    assert verdict.scene_id == "code"


def test_parse_json_after_chain_of_thought():
    raw = (
        "The user wants code.\n"
        '{"scene":"code","reason":"明确要写代码"}'
    )
    verdict = parse_judge_reply(raw, {"chat", "code", "search"})
    assert verdict.action == "route"
    assert verdict.scene_id == "code"


def test_parse_help_and_keep():
    scene_ids = {"chat", "code"}
    assert parse_judge_reply('{"scene":"help"}', scene_ids).action == "help"
    assert parse_judge_reply("keep", scene_ids).action == "keep"
    assert parse_judge_reply("```json\n{\"scene\":\"chat\"}\n```", scene_ids).scene_id == "chat"


def test_fallback_from_heuristic_routes_or_keeps():
    scene_ids = {"chat", "code", "search", "translate"}
    routed = fallback_from_heuristic("我需要你帮我写代码", scene_ids, "judge timeout")
    assert routed.action == "route"
    assert routed.scene_id == "code"
    assert routed.reason == "judge timeout"
    help_v = fallback_from_heuristic("有哪些模型可以切换", scene_ids, "judge call failed")
    assert help_v.action == "help"
    keep = fallback_from_heuristic("今天天气怎么样", scene_ids, "judge timeout")
    assert keep.action == "keep"
    assert keep.scene_id is None


def test_help_intent_phrases():
    assert is_help_intent("你有什么功能")
    assert is_help_intent("有哪些模型可以切换")
    assert not is_help_intent("我需要你帮我写代码")


def test_feature_intro_mentions_judge_and_models():
    settings = settings_from_dict(
        {
            "chat": {"provider_id": "chat-fast", "aliases": "闲聊", "keywords": ""},
            "code": {"provider_id": "code-strong", "aliases": "代码", "keywords": ""},
            "search": {"provider_id": "", "aliases": "", "keywords": ""},
            "vision": {"provider_id": "", "aliases": "", "keywords": ""},
            "classifier_provider_id": "judge-lite",
            "classifier_mode": "llm_for_language",
        }
    )
    text = build_feature_intro(
        settings,
        loaded_providers=("chat-fast", "code-strong"),
        judge_ready=True,
    )
    assert "写代码" in text
    assert "code-strong" in text
    assert "审判模型" in text
    assert "/scene help" in text
    assert "思考" in text
    assert "Provider" in text
    assert "人设" in text
    assert "官方" in text
