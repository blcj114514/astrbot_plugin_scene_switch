from scene_switch.ollama import (
    OllamaClient,
    extract_message_text,
    load_catalog,
    native_think,
    openai_effort,
    settings_dict_from_catalog,
)


def test_effort_mapping():
    assert openai_effort("none") == "none"
    assert openai_effort(False) == "none"
    assert openai_effort("medium") == "medium"
    assert openai_effort("max") == "max"
    assert native_think("none") is False
    assert native_think("medium") == "medium"
    assert native_think("max") == "max"


def test_ollama_native_think_and_v1_effort_are_disjoint():
    """Native think rejects the string none; /v1 reasoning_effort rejects booleans."""
    assert openai_effort("none") == "none"
    assert native_think(False) is False
    assert native_think(True) is True
    assert openai_effort(False) == "none"


def test_catalog_is_placeholder():
    catalog = load_catalog()
    assert "your-chat-model" in catalog["models"]
    settings = settings_dict_from_catalog(catalog)
    assert settings["classifier_provider_id"] == "your-classifier-model"
    assert settings["code"]["provider_id"] == "your-code-model"
    assert settings["chat"]["provider_id"] == "your-chat-model"


def test_extract_reasoning_field():
    content, reasoning = extract_message_text(
        {"role": "assistant", "content": "2", "reasoning": "1+1"}
    )
    assert content == "2"
    assert reasoning == "1+1"


def test_openai_chat_sends_reasoning_effort(monkeypatch):
    import json

    captured = {}

    class FakeResp:
        def read(self):
            return json.dumps(
                {
                    "model": "your-chat-model",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"scene":"code","reason":"写代码"}',
                            }
                        }
                    ],
                    "usage": {"total_tokens": 12},
                }
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, context=None, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return FakeResp()

    monkeypatch.setattr("scene_switch.ollama.urllib.request.urlopen", fake_urlopen)
    client = OllamaClient("secret", "https://example.invalid/v1")
    result = client.chat(
        "your-chat-model",
        [{"role": "user", "content": "写代码"}],
        reasoning_effort="none",
    )
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["body"]["reasoning_effort"] == "none"
    assert captured["body"]["model"] == "your-chat-model"
    assert "scene" in result.content
    assert "***" in repr(client)
    assert "secret" not in repr(client)


def test_http_error_redacts_api_key(monkeypatch):
    import io
    import urllib.error

    from scene_switch.ollama import OllamaError

    def fake_urlopen(req, context=None, timeout=None):
        err = urllib.error.HTTPError(
            "https://ollama.com/v1/chat/completions",
            401,
            "no",
            hdrs=None,
            fp=io.BytesIO(b"ignored"),
        )
        err.read = lambda: b"upstream echoed secret-value"  # type: ignore[method-assign]
        raise err

    monkeypatch.setattr("scene_switch.ollama.urllib.request.urlopen", fake_urlopen)
    client = OllamaClient("secret-value", "https://ollama.com/v1")
    try:
        client.chat("m", [{"role": "user", "content": "hi"}])
    except OllamaError as exc:
        text = str(exc)
        assert "secret-value" not in text
        assert "***" in text
    else:
        raise AssertionError("expected OllamaError")
