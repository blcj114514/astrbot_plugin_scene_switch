from playground.server import playground_bind_error


def test_loopback_always_allowed():
    assert playground_bind_error("127.0.0.1", live_ready=True, allow_lan=False) is None
    assert playground_bind_error("localhost", live_ready=True, allow_lan=False) is None
    assert playground_bind_error("::1", live_ready=False, allow_lan=False) is None


def test_lan_bind_refused_when_api_key_loaded():
    err = playground_bind_error("0.0.0.0", live_ready=True, allow_lan=True)
    assert err is not None
    assert "OLLAMA_API_KEY" in err


def test_lan_bind_needs_explicit_flag_without_key():
    assert playground_bind_error("0.0.0.0", live_ready=False, allow_lan=False) is not None
    assert playground_bind_error("0.0.0.0", live_ready=False, allow_lan=True) is None
