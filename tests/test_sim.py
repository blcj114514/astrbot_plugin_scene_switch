from scene_switch.sim import decide_line, main, _router


def test_sim_named_switch():
    router = _router()
    decision = decide_line(router, "用 deepseek 看这段报错", media=False, group=False, sender="u1")
    assert decision.applied
    assert decision.scene_id == "code"


def test_sim_cli_json(capsys):
    assert main(["用 deepseek 看报错"]) == 0
    out = capsys.readouterr().out
    assert "code-strong" in out
    assert '"applied": true' in out


def test_sim_judge_natural_language(capsys):
    assert main(["--judge", "code", "我需要你帮我写代码"]) == 0
    out = capsys.readouterr().out
    assert "code-strong" in out
    assert '"source": "judge"' in out
