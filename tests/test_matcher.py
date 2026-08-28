from scene_switch.matcher import (
    has_code_signal,
    is_follow_up,
    looks_like_command,
    match_force,
    match_keywords,
)
from scene_switch.settings import settings_from_dict


def _settings(**overrides):
    base = {
        "chat": {"provider_id": "chat-fast", "aliases": "闲聊\n陪聊", "keywords": "陪我聊聊\n晚安\n哈哈"},
        "code": {
            "provider_id": "code-strong",
            "aliases": "代码\n编程",
            "keywords": "代码\n报错\n重构",
        },
        "search": {"provider_id": "search-web", "aliases": "搜索", "keywords": "搜一下\n热点"},
        "vision": {"provider_id": "vision-mm", "aliases": "看图\n识图", "keywords": "这张图\n截图"},
        "model_aliases": "gpt=chat\ndeepseek=code\nds=code\ngrok=search",
    }
    base.update(overrides)
    return settings_from_dict(base)


def test_help_me_use_model():
    hit = match_force("帮我用 deepseek 看这段报错", _settings())
    assert hit is not None
    assert hit.scene_id == "code"
    assert "报错" in hit.leftover


def test_force_with_remaining_prompt():
    hit = match_force("用 deepseek 帮我看这段报错", _settings())
    assert hit is not None
    assert hit.scene_id == "code"
    assert hit.provider_id == "code-strong"
    assert "报错" in hit.leftover
    assert "deepseek" not in hit.leftover


def test_force_switch_only_message():
    hit = match_force("切到闲聊模型", _settings())
    assert hit is not None
    assert hit.scene_id == "chat"
    assert hit.leftover == ""


def test_force_english_use():
    hit = match_force("use gpt to rewrite this paragraph", _settings())
    assert hit is not None
    assert hit.scene_id == "chat"
    assert "rewrite" in hit.leftover


def test_whole_message_alias_without_verb():
    hit = match_force("代码模型", _settings())
    assert hit is not None
    assert hit.scene_id == "code"
    assert hit.leftover == ""


def test_plain_sentence_is_not_force():
    hit = match_force("这段代码为什么报错", _settings())
    assert hit is None


def test_keyword_prefers_code():
    hit = match_keywords("帮我看看这段代码的报错", _settings())
    assert hit is not None
    assert hit.scene_id == "code"


def test_code_fence_signal():
    assert has_code_signal("```python\nprint(1)\n```")
    assert has_code_signal("TypeError: 'NoneType' object")
    assert not has_code_signal("今晚吃什么")


def test_follow_up_short_phrases():
    assert is_follow_up("继续")
    assert is_follow_up("详细点！")
    assert not is_follow_up("继续把这段代码重构一下")


def test_command_like_detection():
    assert looks_like_command("/help", ("/", ".", "!"))
    assert looks_like_command(".provider", ("/", ".", "!"))
    assert not looks_like_command("用 deepseek 看看", ("/", ".", "!"))
