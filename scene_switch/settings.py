"""Parse AstrBot plugin config into plain dataclasses (no AstrBot import)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .flood import SAMPLE_STRONG_FLOOD_PHRASES, SAMPLE_WEAK_FLOOD_PHRASES
from .think import normalize_effort
from .persona import (
    DEFAULT_PERSONA_LABELS,
    default_persona_prompt,
    explicit_persona_off,
    normalize_persona_mode,
)


DEFAULT_CONSENT_TEMPLATE = (
    "该对话更适合切换到{label}由它来回答你，你是否同意？"
    "回复「同意」或「不同意」。"
)
DEFAULT_BLOCKED_PERSONAS: tuple[str, ...] = ()
WAKEUP_MODES = ("contains", "exact", "regex")
DEFAULT_WAKEUP_WORDS = {
    "chat": ("闲聊", "陪聊", "闲聊助手"),
    "code": ("代码助手", "编程助手"),
    "search": ("搜索助手", "检索助手"),
    "vision": ("看图助手", "识图助手"),
    "translate": ("翻译助手",),
    "write": ("写作助手", "润色助手"),
}
DEFAULT_MODEL_ALIASES = (
    "闲聊=chat\n"
    "代码=code\n"
    "编程=code\n"
    "搜索=search\n"
    "看图=vision\n"
    "识图=vision\n"
    "翻译=translate\n"
    "写作=write\n"
    "润色=write\n"
    "gpt=chat\n"
    "deepseek=code"
)

BUILTIN_SCENES = {
    "chat": "闲聊",
    "code": "代码",
    "search": "搜索",
    "vision": "看图",
    "translate": "翻译",
    "write": "写作",
}
BUILTIN_SCENE_IDS = tuple(BUILTIN_SCENES)
SCENE_PRIORITY = ("vision", "code", "translate", "write", "search", "chat")


def split_lines(text: str | None) -> list[str]:
    if not text:
        return []
    items: list[str] = []
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return items


def parse_alias_table(text: str | None) -> dict[str, str]:
    """Parse `alias=scene_or_provider` lines. Keys are stored in original form."""
    table: dict[str, str] = {}
    for line in split_lines(text):
        if "=" in line:
            left, right = line.split("=", 1)
        elif ":" in line:
            left, right = line.split(":", 1)
        else:
            continue
        key = left.strip()
        value = right.strip()
        if key and value:
            table[key] = value
    return table


@dataclass(frozen=True)
class SceneSpec:
    id: str
    display_name: str
    provider_id: str
    aliases: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    wakeup_words: tuple[str, ...] = ()
    wakeup_match: str = "inherit"
    reasoning_effort: str = ""
    persona_id: str = ""
    persona_prompt: str = ""
    persona_label: str = ""
    capabilities: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.provider_id.strip())


@dataclass
class PluginSettings:
    enabled: bool = True
    allow_private: bool = True
    allow_group: bool = True
    skip_command_like_messages: bool = True
    command_like_prefixes: tuple[str, ...] = ("/", ".", "!")
    honor_existing_selection: bool = False
    uncertain_route: str = "keep_default"
    announce_switch: str = "force_only"
    log_decisions: bool = True
    decision_log_enabled: bool = False
    decision_log_days: int = 7
    decision_log_preview_chars: int = 0
    sticky_enabled: bool = True
    sticky_rounds: int = 3
    sticky_ttl_seconds: int = 600
    sticky_release_on_opposite: bool = True
    classifier_mode: str = "llm_for_language"
    classifier_provider_id: str = ""
    classifier_reasoning_effort: str = ""
    classifier_timeout_seconds: int = 12
    override_reasoning_effort: bool = False
    session_think_commands: bool = True
    think_ttl_seconds: int = 3600
    wakeup_match_mode: str = "contains"
    switch_persona: bool = True
    sync_official_persona: bool = True
    sync_official_persona_in_groups: bool = False
    persona_mode: str = "overlay"
    model_aliases: dict[str, str] = field(default_factory=dict)
    scenes: dict[str, SceneSpec] = field(default_factory=dict)
    route_media_to_vision: bool = True
    route_links_to_search: bool = False
    follow_up_enabled: bool = True
    follow_up_max_chars: int = 20
    follow_up_keywords: tuple[str, ...] = (
        "继续",
        "展开",
        "详细点",
        "再说说",
        "然后呢",
        "还有呢",
        "接着说",
        "continue",
        "more",
        "go on",
    )
    require_consent: bool = True
    consent_prompt_template: str = DEFAULT_CONSENT_TEMPLATE
    switch_require_admin: bool = False
    switch_cooldown_seconds: int = 60
    consent_ttl_seconds: int = 120
    prompt_cooldown_seconds: int = 30
    default_scene_id: str = "chat"
    blocked_personas: tuple[str, ...] = DEFAULT_BLOCKED_PERSONAS
    blocked_sender_ids: tuple[str, ...] = ()
    flood_audit_enabled: bool = False
    flood_provider_id: str = ""
    flood_bot_names: tuple[str, ...] = ()
    flood_admin_ids: tuple[str, ...] = ()
    flood_short_seconds: int = 180
    flood_spoke_window_seconds: int = 600
    flood_strike_window_seconds: int = 1800
    flood_strikes_for_lock: int = 2
    flood_verifier_provider_id: str = ""
    flood_strong_phrases: tuple[str, ...] = SAMPLE_STRONG_FLOOD_PHRASES
    flood_weak_phrases: tuple[str, ...] = SAMPLE_WEAK_FLOOD_PHRASES

    def scene(self, scene_id: str) -> SceneSpec | None:
        return self.scenes.get(scene_id)

    def enabled_scenes(self) -> list[SceneSpec]:
        return [s for s in self.scenes.values() if s.enabled]

    def default_scene(self) -> SceneSpec | None:
        ident = (self.default_scene_id or "chat").strip() or "chat"
        scene = self.scenes.get(ident)
        if scene and scene.enabled:
            return scene
        chat = self.scenes.get("chat")
        if chat and chat.enabled:
            return chat
        enabled = self.enabled_scenes()
        return enabled[0] if enabled else None

    def is_blocked_sender(self, sender_id: str | None) -> bool:
        sid = str(sender_id or "").strip()
        if not sid:
            return False
        return sid in set(self.blocked_sender_ids)

    def is_default_scene(self, scene_id: str | None) -> bool:
        default = self.default_scene()
        return bool(default and scene_id == default.id)

    @property
    def judge_available(self) -> bool:
        if self.classifier_mode in {"rules_only", "off", ""}:
            return False
        return bool(self.classifier_provider_id)

    @property
    def judge_before_keywords(self) -> bool:
        return self.classifier_mode == "llm_for_language" and self.judge_available

    def resolve_target(self, token: str) -> tuple[str | None, str | None]:
        """Resolve a user token to (scene_id, provider_id)."""
        raw = token.strip()
        if not raw:
            return None, None
        lowered = raw.lower()

        for scene in self.scenes.values():
            if scene.id == lowered or scene.id == raw:
                return scene.id, scene.provider_id or None
            if scene.display_name == raw:
                return scene.id, scene.provider_id or None
            for alias in (*scene.aliases, *scene.wakeup_words):
                if alias == raw or alias.lower() == lowered:
                    return scene.id, scene.provider_id or None

        alias_value = self._lookup_alias(raw)
        if alias_value:
            if alias_value in self.scenes:
                scene = self.scenes[alias_value]
                return scene.id, scene.provider_id or None
            for scene in self.scenes.values():
                if scene.provider_id == alias_value:
                    return scene.id, alias_value
            return None, alias_value

        for scene in self.scenes.values():
            if scene.provider_id and (
                scene.provider_id == raw or scene.provider_id.lower() == lowered
            ):
                return scene.id, scene.provider_id
        return None, None

    def _lookup_alias(self, token: str) -> str | None:
        if token in self.model_aliases:
            return self.model_aliases[token]
        lowered = token.lower()
        for key, value in self.model_aliases.items():
            if key.lower() == lowered:
                return value
        compact = normalize_token(token)
        for key, value in self.model_aliases.items():
            if normalize_token(key) == compact:
                return value
        return None


def normalize_token(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def normalize_wakeup_mode(value, default: str = "contains") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"", "inherit", "default", "auto"}:
        return "inherit" if default == "inherit" else default
    if raw in {"contains", "contain", "substring", "包含"}:
        return "contains"
    if raw in {"exact", "whole", "full", "整句"}:
        return "exact"
    if raw in {"regex", "re", "regexp", "正则"}:
        return "regex"
    return default if default != "inherit" else "contains"


def scene_wakeup_mode(scene: SceneSpec, global_mode: str) -> str:
    local = normalize_wakeup_mode(scene.wakeup_match, "inherit")
    if local in WAKEUP_MODES:
        return local
    resolved = normalize_wakeup_mode(global_mode, "contains")
    return resolved if resolved in WAKEUP_MODES else "contains"


def _optional_lines(data: dict, key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if key not in data:
        return tuple(fallback)
    return tuple(split_lines(data.get(key)))


def _nonneg_int(value, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _positive_int(value, default: int) -> int:
    return max(1, _nonneg_int(value, default))


def _classifier_effort(raw) -> str:
    text = str(raw if raw is not None else "provider").strip().lower()
    if text in {"", "provider", "auto", "default"}:
        return ""
    return normalize_effort(text, "none") or "none"


def _scene_from_block(
    scene_id: str,
    block: dict | None,
    display_name: str,
) -> SceneSpec:
    data = block or {}
    aliases = tuple(split_lines(data.get("aliases", "")))
    keywords = tuple(split_lines(data.get("keywords", "")))
    wakeup_words = tuple(split_lines(data.get("wakeup_words", "")))
    wakeup_match = str(data.get("wakeup_match") or "inherit").strip().lower() or "inherit"
    raw_effort = data.get("reasoning_effort")
    if str(raw_effort or "").strip().lower() in {"", "provider"}:
        effort = ""
    else:
        effort = normalize_effort(raw_effort, "")
    persona_id = str(data.get("persona_id") or "").strip()
    persona_prompt = str(data.get("persona_prompt") or "").strip()
    persona_label = str(data.get("persona_label") or "").strip() or DEFAULT_PERSONA_LABELS.get(
        scene_id, ""
    )
    if explicit_persona_off(persona_prompt, persona_id):
        persona_id = ""
        persona_prompt = ""
    elif not persona_prompt and not persona_id:
        persona_prompt = default_persona_prompt(scene_id)
    return SceneSpec(
        id=scene_id,
        display_name=str(data.get("display_name") or display_name),
        provider_id=str(data.get("provider_id") or "").strip(),
        aliases=aliases,
        keywords=keywords,
        wakeup_words=wakeup_words,
        wakeup_match=wakeup_match,
        reasoning_effort=effort,
        persona_id=persona_id,
        persona_prompt=persona_prompt,
        persona_label=persona_label,
        capabilities=str(data.get("capabilities") or "").strip(),
    )


def settings_from_dict(raw: dict | None) -> PluginSettings:
    data = dict(raw or {})
    scenes: dict[str, SceneSpec] = {}
    for scene_id, display in BUILTIN_SCENES.items():
        scenes[scene_id] = _scene_from_block(scene_id, data.get(scene_id), display)

    for item in data.get("custom_scenes") or []:
        if not isinstance(item, dict):
            continue
        scene_id = str(item.get("id") or "").strip()
        if not scene_id:
            continue
        scenes[scene_id] = _scene_from_block(
            scene_id,
            item,
            str(item.get("display_name") or scene_id),
        )

    prefixes = tuple(split_lines(data.get("command_like_prefixes", "/\n.\n!")) or ["/", ".", "!"])
    return PluginSettings(
        enabled=bool(data.get("enabled", True)),
        allow_private=bool(data.get("allow_private", True)),
        allow_group=bool(data.get("allow_group", True)),
        skip_command_like_messages=bool(data.get("skip_command_like_messages", True)),
        command_like_prefixes=prefixes,
        honor_existing_selection=bool(data.get("honor_existing_selection", False)),
        uncertain_route=str(data.get("uncertain_route") or "keep_default"),
        announce_switch=str(data.get("announce_switch") or "force_only"),
        log_decisions=bool(data.get("log_decisions", True)),
        decision_log_enabled=bool(data.get("decision_log_enabled", False)),
        decision_log_days=_positive_int(data.get("decision_log_days"), 7),
        decision_log_preview_chars=_nonneg_int(
            data.get("decision_log_preview_chars"), 0
        ),
        sticky_enabled=bool(data.get("sticky_enabled", True)),
        sticky_rounds=int(data.get("sticky_rounds") or 3),
        sticky_ttl_seconds=int(data.get("sticky_ttl_seconds") or 600),
        sticky_release_on_opposite=bool(data.get("sticky_release_on_opposite", True)),
        classifier_mode=str(data.get("classifier_mode") or "llm_for_language"),
        classifier_provider_id=str(data.get("classifier_provider_id") or "").strip(),
        classifier_reasoning_effort=_classifier_effort(data.get("classifier_reasoning_effort")),
        classifier_timeout_seconds=_positive_int(data.get("classifier_timeout_seconds"), 12),
        override_reasoning_effort=bool(data.get("override_reasoning_effort", False)),
        session_think_commands=bool(data.get("session_think_commands", True)),
        think_ttl_seconds=int(data.get("think_ttl_seconds") or 3600),
        wakeup_match_mode=normalize_wakeup_mode(data.get("wakeup_match_mode"), "contains"),
        switch_persona=bool(data.get("switch_persona", True)),
        sync_official_persona=bool(data.get("sync_official_persona", True)),
        sync_official_persona_in_groups=bool(
            data.get("sync_official_persona_in_groups", False)
        ),
        persona_mode=normalize_persona_mode(data.get("persona_mode")),
        model_aliases=parse_alias_table(data.get("model_aliases")),
        scenes=scenes,
        route_media_to_vision=bool(data.get("route_media_to_vision", True)),
        route_links_to_search=bool(data.get("route_links_to_search", False)),
        follow_up_enabled=bool(data.get("follow_up_enabled", True)),
        follow_up_max_chars=int(data.get("follow_up_max_chars") or 20),
        follow_up_keywords=tuple(
            split_lines(data.get("follow_up_keywords"))
            or [
                "继续",
                "展开",
                "详细点",
                "再说说",
                "然后呢",
                "还有呢",
                "接着说",
                "continue",
                "more",
                "go on",
            ]
        ),
        require_consent=bool(data.get("require_consent", True)),
        consent_prompt_template=str(
            data.get("consent_prompt_template") or DEFAULT_CONSENT_TEMPLATE
        ).strip()
        or DEFAULT_CONSENT_TEMPLATE,
        switch_require_admin=bool(data.get("switch_require_admin", False)),
        switch_cooldown_seconds=_nonneg_int(data.get("switch_cooldown_seconds"), 60),
        consent_ttl_seconds=_positive_int(data.get("consent_ttl_seconds"), 120),
        prompt_cooldown_seconds=_nonneg_int(data.get("prompt_cooldown_seconds"), 30),
        default_scene_id=str(data.get("default_scene_id") or "chat").strip() or "chat",
        blocked_personas=tuple(split_lines(data.get("blocked_personas"))),
        blocked_sender_ids=tuple(
            str(item).strip()
            for item in split_lines(data.get("blocked_sender_ids"))
            if str(item).strip()
        ),
        flood_audit_enabled=bool(data.get("flood_audit_enabled", False)),
        flood_provider_id=str(data.get("flood_provider_id") or "").strip(),
        flood_bot_names=tuple(split_lines(data.get("flood_bot_names"))),
        flood_admin_ids=tuple(
            str(item).strip()
            for item in split_lines(data.get("flood_admin_ids"))
            if str(item).strip()
        ),
        flood_short_seconds=_positive_int(data.get("flood_short_seconds"), 180),
        flood_spoke_window_seconds=_positive_int(
            data.get("flood_spoke_window_seconds"), 600
        ),
        flood_strike_window_seconds=_positive_int(
            data.get("flood_strike_window_seconds"), 1800
        ),
        flood_strikes_for_lock=_positive_int(data.get("flood_strikes_for_lock"), 2),
        flood_verifier_provider_id=str(
            data.get("flood_verifier_provider_id") or ""
        ).strip(),
        flood_strong_phrases=_optional_lines(
            data, "flood_strong_phrases", SAMPLE_STRONG_FLOOD_PHRASES
        ),
        flood_weak_phrases=_optional_lines(
            data, "flood_weak_phrases", SAMPLE_WEAK_FLOOD_PHRASES
        ),
    )
