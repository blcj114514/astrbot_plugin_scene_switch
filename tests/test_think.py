from types import SimpleNamespace

from scene_switch.think import (
    agent_text_chat_payload,
    clear_request_effort,
    current_request_effort,
    ensure_provider_effort_passthrough,
    inject_reasoning_effort,
    match_think,
    match_think_command,
    normalize_effort,
    reset_request_effort,
    set_request_effort,
)


def test_normalize_effort():
    assert normalize_effort("medium") == "medium"
    assert normalize_effort("off") == "none"
    assert normalize_effort("max") == "max"
    assert normalize_effort("provider") == ""
    assert normalize_effort("", "high") == "high"


def test_match_think_strips_phrase():
    hit = match_think("认真想想怎么写一个排序")
    assert hit is not None
    assert hit.effort == "max"
    assert "认真" not in hit.leftover
    assert "排序" in hit.leftover


def test_match_think_none_and_auto():
    assert match_think("别想了，把这段翻译成英文").effort == "none"
    assert match_think("恢复默认思考").effort == "auto"
    assert match_think("今晚吃什么") is None


def test_inject_sets_reasoning_effort_only():
    req = SimpleNamespace()
    assert inject_reasoning_effort(req, "high")
    assert req.reasoning_effort == "high"
    assert not hasattr(req, "extra_body")
    assert not hasattr(req, "think")


def test_agent_runner_drops_request_reasoning_effort():
    req = SimpleNamespace(
        reasoning_effort="max",
        session_id="s",
        model="m",
        contexts=[],
        func_tool=None,
        extra_user_content_parts=[],
    )
    inject_reasoning_effort(req, "max")
    payload = agent_text_chat_payload(req)
    assert payload["session_id"] == "s"
    assert payload["model"] == "m"
    assert "reasoning_effort" not in payload


def _simulate_openai_non_stream(provider, payloads, custom_extra_body):
    extra_body = {}
    default_params = {"messages", "model", "tools", "tool_choice", "stream"}
    payloads = dict(payloads)
    to_del = [key for key in payloads if key not in default_params]
    for key in to_del:
        extra_body[key] = payloads.pop(key)
    extra_body.update(custom_extra_body)
    provider._apply_provider_specific_request_overrides(payloads, extra_body)
    return extra_body


class _FakeOpenAIProvider:
    def __init__(self) -> None:
        self.chat_kwargs = None
        self.stream_kwargs = None

    def _apply_provider_specific_request_overrides(self, payloads, extra_body):
        extra_body.pop("think", None)
        extra_body["reasoning_effort"] = "none"

    async def _prepare_chat_payload(self, *args, **kwargs):
        return {"messages": [], "model": "x"}, []

    async def text_chat(self, **kwargs):
        self.chat_kwargs = dict(kwargs)
        return SimpleNamespace(completion_text="ok")

    async def text_chat_stream(self, **kwargs):
        self.stream_kwargs = dict(kwargs)
        yield SimpleNamespace(completion_text="chunk")


def test_passthrough_wins_over_provider_extra_body_and_disable_thinking():
    provider = _FakeOpenAIProvider()
    ensure_provider_effort_passthrough(provider)
    effort_cv = set_request_effort("max")
    try:
        extra = _simulate_openai_non_stream(
            provider,
            {"messages": [], "model": "x", "reasoning_effort": "high"},
            {"reasoning_effort": "low", "think": False},
        )
        assert extra["reasoning_effort"] == "max"
        assert "think" not in extra
    finally:
        reset_request_effort(effort_cv)
        clear_request_effort()


def test_prepare_and_text_chat_receive_effort():
    import asyncio

    provider = _FakeOpenAIProvider()
    ensure_provider_effort_passthrough(provider)

    async def _run():
        effort_cv = set_request_effort("high")
        try:
            payloads, _ = await provider._prepare_chat_payload()
            assert payloads["reasoning_effort"] == "high"
            await provider.text_chat(session_id="s")
            assert provider.chat_kwargs["reasoning_effort"] == "high"
            chunks = [item async for item in provider.text_chat_stream()]
            assert chunks
            assert provider.stream_kwargs["reasoning_effort"] == "high"
        finally:
            reset_request_effort(effort_cv)
            clear_request_effort()

        payloads, _ = await provider._prepare_chat_payload(reasoning_effort="low")
        assert payloads["reasoning_effort"] == "low"
        assert current_request_effort() is None

    asyncio.run(_run())


def test_match_think_command_enable_and_close():
    hit = match_think_command("@机器人 开启思考 max")
    assert hit is not None
    assert hit.effort == "max"
    assert hit.leftover == ""
    assert match_think_command("开启思考 high").effort == "high"
    assert match_think_command("开启思考：medium").effort == "medium"
    assert match_think_command("关闭思考").effort == "none"
    missing = match_think_command("开启思考")
    assert missing is not None
    assert missing.effort == ""
