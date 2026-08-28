from scene_switch.router import RouteInput, SceneRouter
from scene_switch.settings import settings_from_dict
from scene_switch.state import SessionStore


def _router(**overrides) -> SceneRouter:
    base = {
        "require_consent": False,
        "honor_existing_selection": False,
        "chat": {"provider_id": "chat-fast", "aliases": "闲聊", "keywords": "陪我聊聊\n晚安"},
        "code": {"provider_id": "code-strong", "aliases": "代码", "keywords": "代码\n报错\n重构"},
        "search": {"provider_id": "search-web", "aliases": "搜索", "keywords": "搜一下\n热点"},
        "vision": {"provider_id": "vision-mm", "aliases": "看图", "keywords": "这张图"},
        "translate": {"provider_id": "translate-mt", "aliases": "翻译", "keywords": "翻译成\n译成"},
        "write": {"provider_id": "write-prose", "aliases": "写作\n润色", "keywords": "润色\n文案"},
        "model_aliases": "deepseek=code\ngpt=chat\n翻译=translate",
        "announce_switch": "force_only",
        "sticky_rounds": 3,
        "sticky_ttl_seconds": 600,
    }
    base.update(overrides)
    return SceneRouter(settings_from_dict(base), SessionStore())


def _inp(text: str, **kwargs) -> RouteInput:
    payload = {
        "text": text,
        "umo": "webchat:FriendMessage:u1",
        "sender_id": "u1",
        "is_group": False,
        "available_providers": (
            "chat-fast",
            "code-strong",
            "search-web",
            "vision-mm",
            "translate-mt",
            "write-prose",
        ),
    }
    payload.update(kwargs)
    return RouteInput(**payload)


def test_user_named_model_routes_to_code():
    decision = _router().decide(_inp("用 deepseek 帮我看这段报错"))
    assert decision.applied
    assert decision.scene_id == "code"
    assert decision.provider_id == "code-strong"
    assert decision.source == "force"
    assert decision.reasoning_effort is None
    assert decision.cleaned_prompt and "报错" in decision.cleaned_prompt
    assert not decision.stop_for_switch_only


def test_named_model_carries_scene_effort_when_override_on():
    decision = _router(
        override_reasoning_effort=True,
        code={
            "provider_id": "code-strong",
            "aliases": "代码",
            "keywords": "代码\n报错\n重构",
            "reasoning_effort": "high",
        },
    ).decide(_inp("用 deepseek 帮我看这段报错"))
    assert decision.applied
    assert decision.scene_id == "code"
    assert decision.reasoning_effort == "high"


def test_switch_only_stops_llm():
    decision = _router().decide(_inp("切到闲聊模型"))
    assert decision.applied
    assert decision.scene_id == "chat"
    assert decision.stop_for_switch_only


def test_code_error_uses_code_scene():
    decision = _router().decide(_inp("帮我看看这段 TypeError 怎么修"))
    assert decision.applied
    assert decision.scene_id == "code"
    assert decision.source == "rules"


def test_chat_keyword():
    decision = _router().decide(_inp("晚安呀，陪我聊聊"))
    assert decision.applied
    assert decision.scene_id == "chat"


def test_media_goes_to_vision():
    decision = _router().decide(_inp("这是什么", has_media=True))
    assert decision.applied
    assert decision.scene_id == "vision"


def test_uncertain_keeps_default():
    decision = _router().decide(_inp("今天天气怎么样，顺便帮我定个闹钟"))
    assert not decision.applied
    assert decision.source == "keep"


def test_honor_existing_selection():
    decision = _router(honor_existing_selection=True).decide(
        _inp("用 deepseek 看报错", selected_provider="already-set")
    )
    assert not decision.applied
    assert decision.source == "honor"


def test_command_like_skipped():
    decision = _router().decide(_inp("/provider 2"))
    assert not decision.applied


def test_sticky_then_release_on_opposite():
    router = _router()
    first = router.decide(_inp("用 deepseek"))
    assert first.applied and first.scene_id == "code"
    sticky = router.decide(_inp("那再帮我解释一下返回值"))
    assert sticky.applied
    assert sticky.source == "sticky"
    assert sticky.provider_id == "code-strong"
    released = router.decide(_inp("晚安呀，陪我聊聊"))
    assert released.applied
    assert released.scene_id == "chat"
    assert released.source == "rules"


def test_group_sticky_is_per_sender():
    router = _router()
    router.decide(_inp("用 deepseek", is_group=True, sender_id="alice"))
    other = router.decide(_inp("你好呀", is_group=True, sender_id="bob"))
    assert not other.applied
    same = router.decide(_inp("继续", is_group=True, sender_id="alice"))
    assert same.source == "sticky"
    assert same.provider_id == "code-strong"


def test_lock_blocks_auto_routing():
    router = _router()
    locked = router.lock("webchat:FriendMessage:u1", "u1", "chat")
    assert locked.applied
    decision = router.decide(_inp("这段代码报错了"))
    assert decision.source == "lock"
    assert decision.scene_id == "chat"


def test_disabled_scene_is_ignored():
    router = _router(vision={"provider_id": "", "aliases": "看图", "keywords": "这张图"})
    decision = router.decide(_inp("这张图是什么", has_media=True))
    assert not decision.applied


def test_follow_up_keeps_last_scene():
    router = _router()
    first = router.decide(_inp("帮我看看这段 TypeError 怎么修"))
    assert first.scene_id == "code"
    follow = router.decide(_inp("继续"))
    assert follow.applied
    assert follow.scene_id == "code"
    assert follow.source in {"follow_up", "sticky"}


def test_missing_provider_is_not_applied():
    decision = _router().decide(
        _inp("用 deepseek 看报错", available_providers=("chat-fast",))
    )
    assert not decision.applied
    assert decision.source == "missing_provider"


def test_classifier_pending_when_enabled():
    router = _router(
        classifier_mode="rules_then_llm",
        classifier_provider_id="judge-lite",
    )
    pending = router.decide(_inp("帮我处理一下这个"))
    assert pending.needs_judge
    filled = router.decide(_inp("帮我处理一下这个"), judge_hint="code")
    assert filled.applied
    assert filled.scene_id == "code"
    assert filled.source == "judge"


def test_natural_language_write_code_uses_judge():
    router = _router(
        classifier_mode="llm_for_language",
        classifier_provider_id="judge-lite",
    )
    pending = router.decide(_inp("我需要你帮我写代码"))
    assert pending.needs_judge
    assert not pending.applied
    filled = router.decide(_inp("我需要你帮我写代码"), judge_hint="code")
    assert filled.applied
    assert filled.scene_id == "code"
    assert filled.provider_id == "code-strong"
    assert filled.source == "judge"


def test_write_code_falls_back_to_keywords_without_judge():
    decision = _router(classifier_mode="llm_for_language").decide(_inp("我需要你帮我写代码"))
    assert decision.applied
    assert decision.scene_id == "code"
    assert decision.source == "rules"


def test_help_question_is_intercepted():
    decision = _router().decide(_inp("你有什么功能，有哪些模型可以切换"))
    assert decision.help_requested
    assert decision.source == "help"
    assert not decision.applied


def test_hard_code_signal_skips_judge():
    router = _router(
        classifier_mode="llm_for_language",
        classifier_provider_id="judge-lite",
    )
    decision = router.decide(_inp("帮我看看这段 TypeError 怎么修"))
    assert decision.applied
    assert decision.source == "rules"
    assert not decision.needs_judge


def test_translate_and_write_keywords():
    assert _router().decide(_inp("把这段翻译成英文")).scene_id == "translate"
    assert _router().decide(_inp("帮我润色一下这段文案")).scene_id == "write"


def test_heuristic_sort_algorithm_without_code_keyword():
    decision = _router().decide(_inp("帮我实现一个排序算法"))
    assert decision.applied
    assert decision.scene_id == "code"
    assert decision.source == "heuristic"


def test_think_phrase_sets_max_and_cleans_prompt():
    router = _router(override_reasoning_effort=True)
    decision = router.decide(_inp("认真想想，我需要你帮我写代码"))
    assert decision.applied
    assert decision.scene_id == "code"
    assert decision.reasoning_effort == "max"
    assert decision.cleaned_prompt
    assert "认真想想" not in decision.cleaned_prompt


def test_think_only_remembers_effort():
    router = _router(override_reasoning_effort=True)
    first = router.decide(_inp("认真想想"))
    assert first.source == "think"
    assert first.stop_for_switch_only
    assert first.reasoning_effort == "max"
    follow = router.decide(_inp("帮我看看这段 TypeError"))
    assert follow.scene_id == "code"
    assert follow.reasoning_effort == "max"


def test_scene_default_effort_without_phrase():
    decision = _router().decide(_inp("把这段翻译成英文"))
    assert decision.scene_id == "translate"
    assert decision.reasoning_effort is None
    with_override = _router(
        override_reasoning_effort=True,
        translate={
            "provider_id": "translate-mt",
            "aliases": "翻译",
            "keywords": "翻译成\n译成",
            "reasoning_effort": "none",
        },
    ).decide(_inp("把这段翻译成英文"))
    assert with_override.scene_id == "translate"
    assert with_override.reasoning_effort == "none"


def test_think_phrase_ignored_when_override_off():
    decision = _router().decide(_inp("认真想想怎么写一个排序算法"))
    assert decision.reasoning_effort is None
    assert decision.source != "think"
    assert decision.scene_id == "code"
    assert decision.cleaned_prompt is None or "认真想想" in (decision.cleaned_prompt or "")


def test_think_only_phrase_is_plain_text_when_override_off():
    decision = _router().decide(_inp("认真想想"))
    assert decision.source != "think"
    assert not decision.stop_for_switch_only
    assert decision.reasoning_effort is None


def test_group_enable_think_max_without_override():
    router = _router(require_consent=True, session_think_commands=True)
    decision = router.decide(_inp("开启思考 max", is_group=True, mentioned=True, umo="g:1"))
    assert decision.source == "think"
    assert decision.reasoning_effort == "max"
    assert decision.stop_for_switch_only
    follow = router.decide(_inp("帮我看看这段 TypeError", is_group=True, mentioned=True, umo="g:1"))
    assert follow.reasoning_effort == "max"


def test_group_enable_think_requires_mention():
    router = _router(require_consent=True)
    decision = router.decide(_inp("开启思考 max", is_group=True, mentioned=False, umo="g:1"))
    assert decision.source != "think"
    assert decision.reasoning_effort is None


def test_enable_think_without_level_shows_usage():
    router = _router(require_consent=True)
    decision = router.decide(_inp("开启思考", is_group=True, mentioned=True, umo="g:1"))
    assert decision.source == "think"
    assert not decision.reasoning_effort
    assert decision.consent_prompt and "开启思考" in decision.consent_prompt


def test_code_scene_carries_builtin_persona():
    decision = _router().decide(_inp("帮我看看这段 TypeError 怎么修"))
    assert decision.applied
    assert decision.persona_label == "编程助手"
    assert decision.persona_prompt and "编程助手" in decision.persona_prompt


def test_switch_persona_off_skips_persona():
    decision = _router(switch_persona=False).decide(_inp("帮我看看这段 TypeError 怎么修"))
    assert decision.applied
    assert decision.scene_id == "code"
    assert decision.persona_prompt is None
    assert decision.persona_label is None


def test_auto_sticky_after_scene_switch():
    router = _router()
    first = router.decide(_inp("帮我看看这段 TypeError 怎么修"))
    assert first.applied
    assert first.scene_id == "code"
    assert first.scene_changed
    assert first.persona_label == "编程助手"
    follow = router.decide(_inp("那怎么修"))
    assert follow.applied
    assert follow.scene_id == "code"
    assert follow.source == "sticky"
    assert not follow.scene_changed
    switched = router.decide(_inp("把这段翻译成英文"))
    assert switched.scene_id == "translate"
    assert switched.scene_changed
    assert switched.previous_scene_id == "code"
    assert switched.persona_label == "翻译"


def test_announce_always_only_when_scene_changes():
    router = _router(announce_switch="always")
    first = router.decide(_inp("帮我看看这段 TypeError 怎么修"))
    assert first.announce
    stay = router.decide(_inp("那怎么修"))
    assert stay.source == "sticky"
    assert not stay.announce


def test_sticky_releases_to_translate_even_without_keywords():
    router = _router(
        translate={"provider_id": "translate-mt", "aliases": "翻译", "keywords": ""},
    )
    router.decide(_inp("帮我看看这段 TypeError 怎么修"))
    switched = router.decide(_inp("把这段翻译成英文"))
    assert switched.applied
    assert switched.scene_id == "translate"
    assert switched.scene_changed


def test_missing_provider_does_not_leave_sticky():
    router = _router()
    miss = router.decide(_inp("用 deepseek 看报错", available_providers=("chat-fast",)))
    assert not miss.applied
    later = router.decide(
        _inp("那怎么修", available_providers=("chat-fast", "code-strong"))
    )
    assert later.source != "sticky"
