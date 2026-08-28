from scene_switch.matcher import (
    find_named_scene_ids,
    has_explicit_switch_intent,
    is_consent_agree,
    is_consent_disagree,
    is_help_intent,
    mentions_blocked_persona,
)
from scene_switch.router import RouteInput, SceneRouter
from scene_switch.settings import settings_from_dict
from scene_switch.state import SessionStore


def _router(**overrides) -> SceneRouter:
    base = {
        "require_consent": True,
        "honor_existing_selection": False,
        "classifier_mode": "llm_for_language",
        "classifier_provider_id": "judge-lite",
        "default_scene_id": "chat",
        "chat": {
            "provider_id": "chat-p",
            "aliases": "闲聊助手\n闲聊",
            "keywords": "",
            "persona_id": "chat-persona",
            "persona_label": "闲聊助手",
            "persona_prompt": "off",
        },
        "code": {"provider_id": "", "aliases": "", "keywords": ""},
        "search": {"provider_id": "", "aliases": "", "keywords": ""},
        "vision": {"provider_id": "", "aliases": "", "keywords": ""},
        "translate": {"provider_id": "", "aliases": "", "keywords": ""},
        "write": {"provider_id": "", "aliases": "", "keywords": ""},
        "custom_scenes": [
            {
                "id": "docs",
                "display_name": "长文助手",
                "provider_id": "docs-p",
                "aliases": "长文助手\n长文",
                "keywords": "",
                "persona_id": "docs-persona",
                "persona_label": "长文助手",
                "persona_prompt": "off",
            },
            {
                "id": "visionx",
                "display_name": "看图助手",
                "provider_id": "vision-p",
                "aliases": "看图助手\n看图",
                "keywords": "",
                "persona_id": "vision-persona",
                "persona_label": "看图助手",
                "persona_prompt": "off",
            },
        ],
        "blocked_personas": "禁用角色\nbanned",
    }
    base.update(overrides)
    return SceneRouter(settings_from_dict(base), SessionStore())


def _inp(text: str, **kwargs) -> RouteInput:
    payload = {
        "text": text,
        "umo": "aiocqhttp:GroupMessage:g1",
        "sender_id": "u1",
        "is_group": True,
        "mentioned": True,
        "is_admin": True,
        "available_providers": ("chat-p", "docs-p", "vision-p"),
    }
    payload.update(kwargs)
    return RouteInput(**payload)


def test_group_at_without_switch_stays_on_default():
    decision = _router().decide(_inp("闲聊助手 在吗"))
    assert decision.applied
    assert decision.scene_id == "chat"
    assert decision.provider_id == "chat-p"
    assert not decision.needs_consent
    assert not decision.needs_judge


def test_group_without_at_does_not_reply_or_switch():
    decision = _router().decide(_inp("帮我写一段代码", mentioned=False))
    assert not decision.applied
    assert not decision.needs_judge
    assert not decision.needs_consent


def test_blocked_sender_never_reaches_judge():
    router = _router(blocked_sender_ids="blocked-user-1")
    decision = router.decide(_inp("帮我写一段代码", sender_id="blocked-user-1"))
    assert not decision.applied
    assert not decision.needs_judge
    assert decision.source == "keep"


def test_reply_committed_without_at_does_not_judge():
    pending = _router().decide(_inp("帮我写一段代码", mentioned=False, reply_committed=True))
    assert not pending.applied
    assert not pending.needs_judge
    assert not pending.needs_consent


def test_named_other_without_at_does_not_switch():
    decision = _router().decide(_inp("长文助手出来帮我看看", mentioned=False))
    assert not decision.applied
    assert not decision.needs_judge
    assert not decision.needs_consent


def test_short_alias_without_at_does_not_switch():
    decision = _router().decide(_inp("长文也不行啊", mentioned=False))
    assert not decision.applied
    assert not decision.needs_judge
    assert not decision.needs_consent


def test_default_name_without_at_stays_on_default():
    decision = _router().decide(_inp("闲聊助手 在吗", mentioned=False))
    assert decision.applied
    assert decision.scene_id == "chat"
    assert not decision.needs_consent


def test_write_code_when_mentioned_asks_judge():
    pending = _router().decide(_inp("帮我写一段代码"))
    assert pending.needs_judge
    assert not pending.applied
    asked = _router().decide(_inp("帮我写一段代码"), judge_hint="docs")
    assert asked.needs_consent
    assert asked.scene_id == "docs"
    assert "同意" in (asked.consent_prompt or "")


def test_bare_scene_name_with_at_does_not_switch():
    decision = _router().decide(_inp("长文助手"))
    assert not decision.needs_consent
    assert not decision.needs_judge
    assert decision.scene_id == "chat"


def test_named_summon_skips_judge_and_confirms():
    router = _router()
    pending = router.decide(_inp("我想找长文助手"))
    assert not pending.needs_judge
    assert pending.needs_consent
    assert pending.scene_id == "docs"
    assert pending.stop_for_switch_only


def test_switch_verb_asks_consent():
    pending = _router().decide(_inp("切换为长文助手"))
    assert pending.needs_consent
    assert pending.scene_id == "docs"
    assert not pending.needs_judge


def test_agree_switches_model_and_keeps_original_prompt():
    router = _router()
    router.decide(_inp("帮我写一段代码"), judge_hint="docs")
    agreed = router.decide(_inp("同意"))
    assert agreed.applied
    assert agreed.scene_id == "docs"
    assert agreed.provider_id == "docs-p"
    assert agreed.source == "consent"
    assert agreed.cleaned_prompt == "帮我写一段代码"


def test_disagree_stays_on_default_with_original_prompt():
    router = _router()
    router.decide(_inp("帮我写一段代码"), judge_hint="docs")
    denied = router.decide(_inp("不同意"))
    assert denied.applied
    assert denied.scene_id == "chat"
    assert denied.provider_id == "chat-p"
    assert denied.source == "consent_denied"
    assert denied.cleaned_prompt == "帮我写一段代码"


def test_blocked_persona_is_rejected():
    decision = _router().decide(_inp("切到 禁用角色"))
    assert not decision.applied
    assert decision.source == "blocked"


def test_admin_gate_blocks_non_admin_switch():
    router = _router(switch_require_admin=True)
    decision = router.decide(_inp("帮我写一段代码", is_admin=False), judge_hint="docs")
    assert not decision.applied
    assert decision.source == "admin_required"


def test_judge_keep_does_not_prompt():
    decision = _router().decide(_inp("帮我写一段代码"), judge_hint="keep")
    assert decision.applied
    assert decision.scene_id == "chat"
    assert not decision.needs_consent


def test_sticky_after_agree_does_not_reprompt():
    router = _router()
    router.decide(_inp("帮我写一段代码"), judge_hint="docs")
    router.decide(_inp("同意"))
    follow = router.decide(_inp("那这段怎么改"))
    assert follow.applied
    assert follow.scene_id == "docs"
    assert follow.source == "sticky"
    assert not follow.needs_consent


def test_help_does_not_steal_who_are_you():
    assert not is_help_intent("你是谁")
    assert not is_help_intent("怎么用")
    assert is_help_intent("有哪些模型可以切换")


def test_consent_matchers():
    assert is_consent_agree("同意")
    assert is_consent_agree("切换吧")
    assert is_consent_disagree("不用")
    assert not is_consent_agree("我同意这个观点但是太长了吧真的")
    assert not is_consent_agree("好")
    assert not is_consent_agree("好的")
    assert not is_consent_agree("嗯")
    assert not is_consent_agree("可以")
    assert not is_consent_agree("ok")
    assert not is_consent_agree("yes")


def test_named_and_blocked_helpers():
    settings = _router().settings
    assert "docs" in find_named_scene_ids("长文助手出来", settings)
    assert mentions_blocked_persona("把 禁用角色 叫出来", settings.blocked_personas)
    assert has_explicit_switch_intent("我想要代码模型")
    assert has_explicit_switch_intent("切换gpt模型")
    assert not has_explicit_switch_intent("长文助手")
