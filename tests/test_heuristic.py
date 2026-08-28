from scene_switch.heuristic import guess_scene


def test_guess_write_code_intent():
    ids = {"chat", "code", "search", "vision", "translate", "write"}
    assert guess_scene("我需要你帮我写代码", ids) == "code"
    assert guess_scene("帮我实现一个排序算法", ids) == "code"


def test_guess_translate_and_write():
    ids = {"chat", "code", "search", "vision", "translate", "write"}
    assert guess_scene("把这段翻译成英文", ids) == "translate"
    assert guess_scene("帮我润色一下这段文案", ids) == "write"


def test_write_code_is_not_writing_scene():
    ids = {"chat", "code", "translate", "write"}
    assert guess_scene("写代码", ids) == "code"
    assert guess_scene("写一篇小红书", ids) == "write"
