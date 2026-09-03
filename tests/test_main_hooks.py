"""Exercise Main's AstrBot hooks with a local stub of astrbot.api."""

from __future__ import annotations

import asyncio
import shutil
import sys
import types
from pathlib import Path
from types import SimpleNamespace

TMP = Path(__file__).resolve().parent / "_tmp_main_hooks"
TMP.mkdir(exist_ok=True)


def _install_astrbot_stub() -> None:
    if "astrbot.api" in sys.modules:
        return

    def _pkg(name: str) -> types.ModuleType:
        mod = types.ModuleType(name)
        mod.__path__ = []  # type: ignore[attr-defined]
        sys.modules[name] = mod
        return mod

    astrbot = _pkg("astrbot")
    api = _pkg("astrbot.api")
    event_mod = _pkg("astrbot.api.event")
    star_mod = _pkg("astrbot.api.star")
    provider_mod = _pkg("astrbot.api.provider")
    comp_mod = _pkg("astrbot.api.message_components")
    astrbot.api = api

    class _Logger:
        def info(self, *args, **kwargs) -> None:
            return None

        def debug(self, *args, **kwargs) -> None:
            return None

        def exception(self, *args, **kwargs) -> None:
            return None

        def warning(self, *args, **kwargs) -> None:
            return None

    class _Filter:
        class EventMessageType:
            ALL = "ALL"

        def event_message_type(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

        def on_waiting_llm_request(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

        def on_llm_request(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

        def on_llm_response(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

        def on_decorating_result(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

        def after_message_sent(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

        def command(self, *args, **kwargs):
            def deco(fn):
                return fn

            return deco

    class Star:
        def __init__(self, context) -> None:
            self.context = context

    def register(*args, **kwargs):
        def deco(cls):
            return cls

        return deco

    class ProviderRequest:
        def __init__(self) -> None:
            self.prompt = ""
            self.system_prompt = ""
            self.conversation = None
            self.extra_body = None

    class At:
        def __init__(self, qq: str = "") -> None:
            self.qq = qq
            self.target = qq

    class Image:
        pass

    class File:
        pass

    class Video:
        pass

    class Record:
        pass

    api.AstrBotConfig = dict
    api.logger = _Logger()
    event_mod.AstrMessageEvent = object
    event_mod.filter = _Filter()
    star_mod.Context = object
    star_mod.Star = Star
    star_mod.register = register
    provider_mod.ProviderRequest = ProviderRequest
    comp_mod.At = At
    comp_mod.Image = Image
    comp_mod.File = File
    comp_mod.Video = Video
    comp_mod.Record = Record
    api.event = event_mod
    api.star = star_mod
    api.provider = provider_mod
    api.message_components = comp_mod


_install_astrbot_stub()

from astrbot.api import message_components as Comp  # noqa: E402
from astrbot.api.provider import ProviderRequest  # noqa: E402

import main as plugin_main  # noqa: E402
from scene_switch.decision_log import format_entry  # noqa: E402


class FakeContext:
    def __init__(self) -> None:
        self.providers: list = []

    def get_all_providers(self):
        return self.providers

    def get_provider_by_id(self, provider_id: str):
        return None

    def get_using_provider(self, umo: str | None = None):
        return self.providers[0] if self.providers else None


class FakeEvent:
    def __init__(
        self,
        text: str,
        *,
        group: bool = True,
        mentioned: bool = True,
        sender: str = "u1",
        self_id: str = "bot1",
        umo: str | None = None,
        is_admin: bool = True,
    ) -> None:
        self.message_str = text
        self.unified_msg_origin = umo or ("g:demo" if group else "p:demo")
        self.session_id = self.unified_msg_origin
        self._extras: dict = {}
        self.stopped = False
        self.sent: list = []
        self.yielded: list = []
        self.call_llm = False
        self._sender = sender
        self._self_id = self_id
        self._admin = is_admin
        chain = []
        if mentioned:
            chain.append(Comp.At(qq=self_id))
        self.message_obj = SimpleNamespace(
            group_id="100" if group else "",
            sender=SimpleNamespace(user_id=sender, id=sender, nickname="n"),
            message=chain,
        )

    def get_sender_id(self):
        return self._sender

    def get_self_id(self):
        return self._self_id

    def is_admin(self):
        return self._admin

    def get_extra(self, key):
        return self._extras.get(key)

    def set_extra(self, key, value):
        self._extras[key] = value

    def stop_event(self):
        self.stopped = True

    def should_call_llm(self, value):
        self.call_llm = value

    def plain_result(self, text):
        return text

    async def send(self, result):
        self.sent.append(result)

    def request_llm(self, **kwargs):
        return ("llm", kwargs)

    def get_result(self):
        return None


def _plugin(slot: str, **config_extra) -> plugin_main.Main:
    folder = TMP / slot
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    config = {
        "enabled": True,
        "require_consent": True,
        "honor_existing_selection": False,
        "classifier_mode": "rules_only",
        "flood_audit_enabled": True,
        "flood_provider_id": "flood-l1",
        "flood_verifier_provider_id": "",
        "chat": {
            "provider_id": "chat-p",
            "aliases": "闲聊助手",
            "persona_prompt": "off",
        },
        "code": {
            "provider_id": "code-p",
            "aliases": "代码助手",
            "keywords": "代码\n报错",
            "persona_prompt": "off",
        },
    }
    config.update(config_extra)
    plugin = plugin_main.Main(FakeContext(), config)
    plugin.silence = plugin_main.SilenceStore(folder / "silence.json")
    plugin.flood = plugin_main.FloodStore(folder / "flood.json")
    plugin.store.persist_path = folder / "session_state.json"
    plugin._dlog_dir = folder / "decision_log"
    plugin._configure_dlog()
    return plugin


async def _drain(agen) -> list:
    items = []
    async for item in agen:
        items.append(item)
    return items


def test_silence_gate_acks_slap_and_stops():
    plugin = _plugin("silence")
    event = FakeEvent("闭嘴", umo="g:silence")

    async def _run():
        items = await _drain(plugin.silence_gate(event))
        assert items
        assert event.stopped
        assert plugin.silence.is_silenced(event.unified_msg_origin)

    asyncio.run(_run())


def test_flood_gate_does_not_mute_when_l2_unbound():
    plugin = _plugin("flood-l2")
    event = FakeEvent("刷屏了", mentioned=True, umo="g:flood")
    plugin.flood.note_bot_speak(event.unified_msg_origin)

    async def _fake_llm(*args, **kwargs):
        return (
            '{"escalate":true,"about_this_bot":true,'
            '"flood_complaint":true,"reason":"test"}'
        )

    plugin._flood_llm = _fake_llm  # type: ignore[method-assign]

    async def _run():
        items = await _drain(plugin.flood_audit_gate(event))
        assert items == []
        assert not event.stopped
        assert not plugin.silence.is_silenced(event.unified_msg_origin)

    asyncio.run(_run())


def test_switch_intent_gate_asks_consent():
    plugin = _plugin("consent")
    event = FakeEvent("帮我写一段代码", umo="g:consent")

    async def _run():
        items = await _drain(plugin.switch_intent_gate(event))
        assert items
        assert "同意" in str(items[0])
        assert event.stopped

    asyncio.run(_run())


def test_waiting_llm_hook_drops_blocked_sender():
    plugin = _plugin("block")
    plugin.router.reload(
        plugin_main.settings_from_dict(
            {
                **dict(plugin._raw_config),
                "blocked_sender_ids": "blocked-user-1",
            }
        )
    )
    event = FakeEvent("你好", sender="blocked-user-1", umo="g:block")

    async def _run():
        await plugin.on_waiting_llm_request(event)
        assert event.stopped

    asyncio.run(_run())


def test_llm_request_hook_stops_when_silenced():
    plugin = _plugin("silenced-llm")
    event = FakeEvent("继续聊", umo="g:llm")
    plugin.silence.slap(event.unified_msg_origin, seconds=600)
    req = ProviderRequest()
    req.prompt = "hi"

    async def _run():
        await plugin.on_llm_request(event, req)
        assert event.stopped

    asyncio.run(_run())


def test_llm_request_hook_applies_session_think_to_provider_extra_body():
    plugin = _plugin("think-pass")
    provider = SimpleNamespace()

    def _orig_apply(payloads, extra_body):
        extra_body["reasoning_effort"] = "none"

    provider._apply_provider_specific_request_overrides = _orig_apply
    plugin.context.providers.append(provider)

    event = FakeEvent("继续", umo="g:think")
    key = plugin_main.SessionStore.make_key(
        event.unified_msg_origin, event.get_sender_id()
    )
    plugin.store.set_think(key, "max", 3600)
    event.set_extra(
        "scene_switch_decision",
        {
            "applied": False,
            "source": "think",
            "reasoning_effort": "max",
            "provider_id": "chat-p",
        },
    )
    req = ProviderRequest()
    req.prompt = "hi"

    async def _run():
        await plugin.on_llm_request(event, req)
        assert getattr(req, "reasoning_effort", None) == "max"
        extra = {"reasoning_effort": "low"}
        provider._apply_provider_specific_request_overrides({}, extra)
        assert extra["reasoning_effort"] == "max"
        await plugin.on_llm_response(event, None)
        extra_after = {"reasoning_effort": "low"}
        provider._apply_provider_specific_request_overrides({}, extra_after)
        assert extra_after["reasoning_effort"] == "none"

    asyncio.run(_run())


def test_decision_log_disabled_writes_nothing():
    plugin = _plugin("dlog-off")
    event = FakeEvent("闭嘴", umo="g:dlog-off")

    async def _run():
        await _drain(plugin.silence_gate(event))

    asyncio.run(_run())
    folder = TMP / "dlog-off"
    assert not (folder / "decision_log").exists()
    assert plugin.dlog.snapshot()["enabled"] is False


def test_decision_log_records_slap():
    plugin = _plugin("dlog-slap", decision_log_enabled=True)
    slap = FakeEvent("闭嘴", umo="g:dlog-slap")

    async def _run():
        await _drain(plugin.silence_gate(slap))

    asyncio.run(_run())
    snap = plugin.dlog.snapshot()
    assert snap["enabled"] is True
    assert snap["blocked_total"].get("slap") == 1
    entries = plugin.dlog.tail(5)
    assert entries and entries[0]["kind"] == "blocked"
    assert entries[0]["blocked"] == "slap"
    assert "原文" not in format_entry(entries[0])

    # the same event must not be logged twice by the second gate
    plugin._log_blocked(slap, "slap")
    assert plugin.dlog.snapshot()["blocked_total"].get("slap") == 1


def test_decision_log_preview_opt_in():
    plugin = _plugin(
        "dlog-preview",
        decision_log_enabled=True,
        decision_log_preview_chars=50,
    )
    event = FakeEvent("帮我写一段代码", umo="g:dlog-preview")

    async def _run():
        items = await _drain(plugin.switch_intent_gate(event))
        assert items and "同意" in str(items[0])

    asyncio.run(_run())
    entries = [e for e in plugin.dlog.tail(5) if e["kind"] == "route"]
    assert entries
    assert entries[0]["preview"].startswith("帮我写一段代码")


def test_decision_log_default_no_preview():
    plugin = _plugin("dlog-nopreview", decision_log_enabled=True)
    event = FakeEvent("帮我写一段代码", umo="g:dlog-nopreview")

    async def _run():
        items = await _drain(plugin.switch_intent_gate(event))
        assert items and "同意" in str(items[0])

    asyncio.run(_run())
    entries = [e for e in plugin.dlog.tail(5) if e["kind"] == "route"]
    assert entries
    assert "preview" not in entries[0]


def test_scene_stats_and_log_commands_admin_gated():
    plugin = _plugin("dlog-stats", decision_log_enabled=True)

    async def _run():
        denied = FakeEvent("/scene stats", umo="g:dlog-stats", is_admin=False)
        items = await _drain(plugin.scene_cmd(denied))
        assert items and "管理员" in str(items[0])
        allowed = FakeEvent("/scene stats", umo="g:dlog-stats", is_admin=True)
        items = await _drain(plugin.scene_cmd(allowed))
        assert items and "决策日志统计" in str(items[0])
        log_view = FakeEvent("/scene log 5", umo="g:dlog-stats", is_admin=True)
        items = await _drain(plugin.scene_cmd(log_view))
        assert items and "决策日志暂无记录" in str(items[0])

    asyncio.run(_run())
