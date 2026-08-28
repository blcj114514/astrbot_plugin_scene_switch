from types import SimpleNamespace

from scene_switch.think import (
    inject_reasoning_effort,
    match_think,
    match_think_command,
    normalize_effort,
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
