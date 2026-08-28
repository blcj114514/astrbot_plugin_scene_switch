import json
import threading
import time
from pathlib import Path

from scene_switch.state import SessionStore


def test_state_roundtrip(tmp_path: Path):
    path = tmp_path / "session_state.json"
    store = SessionStore(persist_path=path)
    store.set_lock("umo::u1", "code", "code-strong")
    store.remember_scene("umo::u1", "code")
    store.set_sticky("umo::u2", "chat", "chat-fast", rounds=4, ttl_seconds=600)

    restored = SessionStore(persist_path=path)
    assert restored.get_lock("umo::u1") == ("code", "code-strong")
    assert restored.last_scene("umo::u1") == "code"
    sticky = restored.get_sticky("umo::u2")
    assert sticky is not None
    assert sticky.scene_id == "chat"
    assert sticky.rounds_left == 4

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "locks" in data
    assert "umo::u1" in data["locks"]
    assert restored.get_sticky("umo::u2", now=time.time() + 10_000) is None


def test_think_override_roundtrip(tmp_path: Path):
    path = tmp_path / "session_state.json"
    store = SessionStore(persist_path=path)
    store.set_think("umo::u1", "max", ttl_seconds=600)
    restored = SessionStore(persist_path=path)
    assert restored.get_think("umo::u1") == "max"
    restored.clear_think("umo::u1")
    assert restored.get_think("umo::u1") is None


def test_concurrent_writes_keep_both_keys(tmp_path: Path):
    path = tmp_path / "session_state.json"
    store = SessionStore(persist_path=path)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def writer(key: str, scene_id: str) -> None:
        try:
            barrier.wait()
            store.set_sticky(key, scene_id, f"{scene_id}-p", rounds=3, ttl_seconds=600)
            store.remember_scene(key, scene_id)
        except BaseException as exc:  # pragma: no cover - surface in assertions
            errors.append(exc)

    first = threading.Thread(target=writer, args=("umo::a", "chat"))
    second = threading.Thread(target=writer, args=("umo::b", "code"))
    first.start()
    second.start()
    first.join()
    second.join()
    assert not errors

    restored = SessionStore(persist_path=path)
    sticky_a = restored.get_sticky("umo::a")
    sticky_b = restored.get_sticky("umo::b")
    assert sticky_a is not None and sticky_a.scene_id == "chat"
    assert sticky_b is not None and sticky_b.scene_id == "code"
    assert restored.last_scene("umo::a") == "chat"
    assert restored.last_scene("umo::b") == "code"
