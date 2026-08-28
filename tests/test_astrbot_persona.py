import asyncio
from types import SimpleNamespace

from scene_switch.astrbot_persona import (
    apply_persona_to_session_config,
    bind_request_conversation_persona,
    managed_persona_id,
    plan_official_persona,
    should_write_official_slots,
    sync_official_persona,
)
from scene_switch.persona import apply_persona, strip_injected_personas


class FakePersona:
    def __init__(self, persona_id: str, system_prompt: str):
        self.persona_id = persona_id
        self.name = persona_id
        self.system_prompt = system_prompt


class FakePersonaManager:
    def __init__(self, personas: list[FakePersona] | None = None):
        self.personas = list(personas or [])
        self.created: list[tuple[str, str]] = []
        self.updated: list[tuple[str, str]] = []
        self.refreshed = 0

    def get_persona_v3_by_id(self, persona_id: str):
        for item in self.personas:
            if item.name == persona_id or item.persona_id == persona_id:
                return item
        return None

    async def create_persona(self, persona_id: str, system_prompt: str):
        self.created.append((persona_id, system_prompt))
        self.personas.append(FakePersona(persona_id, system_prompt))

    async def update_persona(self, persona_id: str, system_prompt: str):
        self.updated.append((persona_id, system_prompt))
        for item in self.personas:
            if item.persona_id == persona_id:
                item.system_prompt = system_prompt
                return

    async def get_v3_persona_data(self):
        self.refreshed += 1


class FakeConversationManager:
    def __init__(self, persona_id: str | None = "old-persona"):
        self.persona_id = persona_id
        self.updates: list[dict] = []

    async def get_curr_conversation_id(self, umo: str):
        return f"conv-{umo}"

    async def get_conversation(self, unified_msg_origin: str, conversation_id: str):
        return SimpleNamespace(persona_id=self.persona_id, id=conversation_id)

    async def update_conversation(self, unified_msg_origin: str, persona_id: str | None = None, **kwargs):
        self.updates.append(
            {"umo": unified_msg_origin, "persona_id": persona_id, **kwargs}
        )
        self.persona_id = persona_id


class FakePrefs:
    def __init__(self, persona_id: str | None = "old-persona"):
        self.store = {"session_service_config": {"persona_id": persona_id, "llm": "keep-me"}}
        self.puts: list[tuple] = []

    async def get_async(self, scope, scope_id, key, default=None):
        return self.store.get(key, default)

    async def put_async(self, scope, scope_id, key, value):
        self.puts.append((scope, scope_id, key, value))
        self.store[key] = value


def test_managed_persona_id_is_stable_and_safe():
    assert managed_persona_id("code") == "scene_switch_code"
    assert managed_persona_id("my-scene") == "scene_switch_my_scene"
    assert managed_persona_id("2cool") == "scene_switch_s_2cool"


def test_plan_uses_existing_astrbot_persona():
    plan = plan_official_persona(
        scene_id="code",
        persona_id="persona-1",
        persona_prompt="你是人设1。",
        persona_label="人设 1",
        persona_exists=True,
    )
    assert plan.skip is False
    assert plan.official_id == "persona-1"
    assert plan.ensure_managed is False
    assert plan.reason == "existing_astrbot_persona"


def test_plan_falls_back_to_managed_when_id_missing():
    plan = plan_official_persona(
        scene_id="code",
        persona_id="missing-id",
        persona_prompt="你现在是编程助手。",
        persona_exists=False,
    )
    assert plan.official_id == "scene_switch_code"
    assert plan.ensure_managed is True
    assert "编程助手" in plan.prompt


def test_plan_skips_when_persona_off_or_sync_disabled():
    off = plan_official_persona(scene_id="code", persona_id="", persona_prompt="")
    assert off.skip and off.reason == "persona_off"
    disabled = plan_official_persona(
        scene_id="code",
        persona_prompt="x",
        sync_official=False,
    )
    assert disabled.skip and disabled.reason == "sync_official_off"


def test_session_config_overwrites_old_persona_and_keeps_other_keys():
    cfg, changed = apply_persona_to_session_config(
        {"persona_id": "old-persona", "llm": "other-plugin-model"},
        "persona-1",
    )
    assert changed is True
    assert cfg["persona_id"] == "persona-1"
    assert cfg["llm"] == "other-plugin-model"
    same, changed_again = apply_persona_to_session_config(cfg, "persona-1")
    assert changed_again is False
    assert same["persona_id"] == "persona-1"


def test_session_config_does_not_create_force_when_missing_or_empty():
    empty, changed = apply_persona_to_session_config({}, "scene_switch_chat")
    assert changed is False
    assert "persona_id" not in empty
    blank, changed_blank = apply_persona_to_session_config(
        {"persona_id": "", "llm": "keep-me"},
        "scene_switch_chat",
    )
    assert changed_blank is False
    assert blank["persona_id"] == ""
    assert blank["llm"] == "keep-me"
    none_cfg, changed_none = apply_persona_to_session_config(
        {"persona_id": None},
        "scene_switch_chat",
    )
    assert changed_none is False
    assert not none_cfg.get("persona_id")


def test_bind_request_overwrites_loaded_conversation_persona():
    req = SimpleNamespace(conversation=SimpleNamespace(persona_id="old-persona"))
    assert bind_request_conversation_persona(req, "persona-1") is True
    assert req.conversation.persona_id == "persona-1"


def test_apply_persona_strips_official_instructions_to_avoid_role_conflict():
    old = (
        "你是默认机器人。\n"
        "# Persona Instructions\n\n"
        "你是旧角色，每句加喵。\n"
        "# Skills\n\n"
        "keep-this"
    )
    out = apply_persona(old, "你现在是编程助手。", scene_id="code", label="编程助手")
    assert "旧角色" not in out
    assert "keep-this" in out
    assert "编程助手" in out
    assert "你是默认机器人。" in out
    stripped = strip_injected_personas(out)
    assert "scene_switch_persona" not in stripped


def test_sync_overwrites_official_and_session_persona_not_model():
    async def _run():
        personas = FakePersonaManager([FakePersona("persona-1", "你是人设1。")])
        conversations = FakeConversationManager("old-persona")
        prefs = FakePrefs("old-persona")
        req = SimpleNamespace(conversation=SimpleNamespace(persona_id="old-persona"))
        plan = plan_official_persona(
            scene_id="code",
            persona_id="persona-1",
            persona_prompt="你是人设1。",
            persona_exists=True,
        )
        result = await sync_official_persona(
            umo="qq:private:1001",
            plan=plan,
            persona_manager=personas,
            conversation_manager=conversations,
            sp=prefs,
            req=req,
        )
        assert result.official_id == "persona-1"
        assert result.conversation_updated is True
        assert result.session_updated is True
        assert conversations.persona_id == "persona-1"
        assert prefs.store["session_service_config"]["persona_id"] == "persona-1"
        assert prefs.store["session_service_config"]["llm"] == "keep-me"
        assert req.conversation.persona_id == "persona-1"
        assert personas.created == []
        assert personas.updated == []

    asyncio.run(_run())


def test_sync_creates_managed_official_persona_for_inline_prompt():
    async def _run():
        personas = FakePersonaManager()
        conversations = FakeConversationManager(None)
        prefs = FakePrefs(None)
        plan = plan_official_persona(
            scene_id="code",
            persona_prompt="你现在是编程助手。",
            persona_label="编程助手",
            persona_exists=False,
        )
        cache: dict[str, str] = {}
        result = await sync_official_persona(
            umo="qq:private:1001",
            plan=plan,
            persona_manager=personas,
            conversation_manager=conversations,
            sp=prefs,
            ensured_cache=cache,
        )
        assert result.official_id == "scene_switch_code"
        assert result.ensured is True
        assert result.session_updated is False
        assert personas.created == [("scene_switch_code", "你现在是编程助手。")]
        assert cache["scene_switch_code"] == "你现在是编程助手。"
        again = await sync_official_persona(
            umo="qq:private:1001",
            plan=plan,
            persona_manager=personas,
            conversation_manager=conversations,
            sp=prefs,
            ensured_cache=cache,
        )
        assert again.conversation_updated is False
        assert again.session_updated is False
        assert len(personas.created) == 1

    asyncio.run(_run())


def test_sync_updates_managed_persona_when_prompt_changes():
    async def _run():
        personas = FakePersonaManager([FakePersona("scene_switch_chat", "旧闲聊")])
        conversations = FakeConversationManager("scene_switch_chat")
        prefs = FakePrefs("scene_switch_chat")
        plan = plan_official_persona(
            scene_id="chat",
            persona_prompt="新的闲聊伙伴。",
            persona_exists=False,
        )
        result = await sync_official_persona(
            umo="qq:private:1001",
            plan=plan,
            persona_manager=personas,
            conversation_manager=conversations,
            sp=prefs,
        )
        assert result.ensured is True
        assert personas.updated == [("scene_switch_chat", "新的闲聊伙伴。")]
        assert personas.created == []

    asyncio.run(_run())


def test_should_write_official_slots_private_vs_group():
    assert should_write_official_slots(is_group=False, sync_in_groups=False) is True
    assert should_write_official_slots(is_group=True, sync_in_groups=False) is False
    assert should_write_official_slots(is_group=True, sync_in_groups=True) is True


def test_sync_skips_official_slots_for_groups_by_default():
    async def _run():
        personas = FakePersonaManager([FakePersona("persona-1", "你是人设1。")])
        conversations = FakeConversationManager("old-persona")
        prefs = FakePrefs("old-persona")
        plan = plan_official_persona(
            scene_id="code",
            persona_id="persona-1",
            persona_prompt="你是人设1。",
            persona_exists=True,
        )
        result = await sync_official_persona(
            umo="qq:group:2002",
            plan=plan,
            persona_manager=personas,
            conversation_manager=conversations,
            sp=prefs,
            write_slots=False,
        )
        assert result.skipped is True
        assert result.reason == "group_skip_official"
        assert result.conversation_updated is False
        assert result.session_updated is False
        assert conversations.persona_id == "old-persona"
        assert prefs.store["session_service_config"]["persona_id"] == "old-persona"
        assert personas.created == []
        assert conversations.updates == []

    asyncio.run(_run())


def test_sync_private_updates_conversation_persona():
    async def _run():
        conversations = FakeConversationManager("old-persona")
        prefs = FakePrefs()
        prefs.store = {"session_service_config": {"llm": "keep-me"}}
        plan = plan_official_persona(
            scene_id="code",
            persona_id="persona-1",
            persona_prompt="你是人设1。",
            persona_exists=True,
        )
        result = await sync_official_persona(
            umo="qq:private:1001",
            plan=plan,
            persona_manager=FakePersonaManager([FakePersona("persona-1", "你是人设1。")]),
            conversation_manager=conversations,
            sp=prefs,
        )
        assert result.conversation_updated is True
        assert result.session_updated is False
        assert conversations.persona_id == "persona-1"
        assert "persona_id" not in prefs.store["session_service_config"]
        assert prefs.store["session_service_config"]["llm"] == "keep-me"

    asyncio.run(_run())
