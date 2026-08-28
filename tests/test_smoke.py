"""End-to-end conversation through the router, labels, and persona injection."""

from scene_switch.display import compact_label, confirm_switch, reply_prefix
from scene_switch.persona import apply_persona
from scene_switch.router import RouteInput, SceneRouter
from scene_switch.settings import settings_from_dict
from scene_switch.state import SessionStore


def _router():
    return SceneRouter(
        settings_from_dict(
            {
                "chat": {"provider_id": "chat-fast", "aliases": "闲聊", "keywords": "陪我聊聊\n晚安"},
                "code": {
                    "provider_id": "code-strong",
                    "aliases": "代码",
                    "keywords": "代码\n报错\n重构",
                },
                "search": {"provider_id": "search-web", "aliases": "搜索", "keywords": "搜一下"},
                "vision": {"provider_id": "vision-mm", "aliases": "看图", "keywords": "这张图"},
                "translate": {
                    "provider_id": "translate-mt",
                    "aliases": "翻译",
                    "keywords": "翻译成\n译成",
                },
                "write": {
                    "provider_id": "write-prose",
                    "aliases": "写作",
                    "keywords": "润色\n文案",
                },
                "model_aliases": "deepseek=code",
                "announce_switch": "always",
                "require_consent": False,
                "honor_existing_selection": False,
            }
        ),
        SessionStore(),
    )


def _inp(text: str) -> RouteInput:
    return RouteInput(
        text=text,
        umo="smoke:private:demo",
        sender_id="u1",
        is_group=False,
        available_providers=(
            "chat-fast",
            "code-strong",
            "search-web",
            "vision-mm",
            "translate-mt",
            "write-prose",
        ),
    )


def test_smoke_conversation_switch_and_persona():
    router = _router()
    turns = [
        ("帮我看看这段 TypeError 怎么修", "code", "编程助手", True),
        ("那怎么修", "code", "编程助手", False),
        ("把这段翻译成英文", "translate", "翻译", True),
        ("切到闲聊模型", "chat", "闲聊伙伴", True),
    ]
    previous = None
    for text, scene, persona, changed in turns:
        decision = router.decide(_inp(text))
        assert decision.applied, text
        assert decision.scene_id == scene, text
        assert decision.persona_label == persona, text
        assert decision.scene_changed is changed, text
        if changed and previous:
            assert decision.previous_scene_id == previous
            injected = apply_persona(
                "你是默认机器人。",
                decision.persona_prompt or "",
                scene_id=decision.scene_id,
                label=decision.persona_label,
                switched_from=decision.previous_scene_id,
            )
            assert "不要沿用上一轮" in injected
        label = compact_label(
            router.settings,
            decision.scene_id,
            persona_label=decision.persona_label,
        )
        assert persona in label
        prefix = reply_prefix(decision.persona_label, decision.scene_id, router.settings)
        assert prefix.startswith("〔")
        if decision.stop_for_switch_only:
            assert "已切到" in confirm_switch(router.settings, decision)
        previous = scene


def test_smoke_help_and_keep():
    router = _router()
    help_decision = router.decide(_inp("有哪些模型可以切换"))
    assert help_decision.help_requested
    keep = router.decide(_inp("今天天气怎么样，顺便帮我定个闹钟"))
    assert not keep.applied
