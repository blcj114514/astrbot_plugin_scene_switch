"""Detect explicit model requests, scene keywords, and message features."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .settings import SCENE_PRIORITY, PluginSettings, normalize_token, scene_wakeup_mode

FORCE_VERB_RE = re.compile(
    r"^(?:请|麻烦|帮我|拜托){0,2}"
    r"(?:用|使用|切到|切换到|切换为|切换成|切换|换成|改用|走|调用|改成)"
    r"|^(?:please\s+)?(?:use|switch\s+to|change\s+to)\b",
    re.IGNORECASE,
)
EXPLICIT_SWITCH_RE = re.compile(
    r"(?:切换到|切换为|切换成|切换|切到|换成|改用|改成|调用)|"
    r"(?:我想找|我想要|我要找|我要换|找一下|帮我找)"
)

CODE_FENCE_RE = re.compile(r"```")
STACK_RE = re.compile(
    r"\b(TypeError|ValueError|Traceback|NullPointerException|undefined is not|SyntaxError)\b",
    re.IGNORECASE,
)
LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
TRAILING_NOISE_RE = re.compile(
    r"^(?:模型|这个|来|帮我|请|吧|回答|来回答)[\s，,、]*",
    re.IGNORECASE,
)

DEFAULT_FOLLOW_UPS = (
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

HELP_PHRASES = (
    "有什么功能",
    "有哪些功能",
    "介绍一下功能",
    "功能介绍",
    "怎么切换模型",
    "如何切换模型",
    "有哪些模型",
    "可以切换哪些",
    "能切换哪些",
    "能用哪些模型",
    "切换哪些模型",
    "模型列表",
)

CAPABILITY_PHRASES = (
    "写代码",
    "写段代码",
    "帮我写",
    "实现一个",
    "写个函数",
    "这段代码",
    "这段报错",
    "traceback",
    "翻译成",
    "译成",
    "润色",
    "扩写",
    "缩写",
    "看这张",
    "这张图",
    "识图",
    "切到",
    "切换到",
    "换成",
    "改用",
)

AGREE_EXACT = {
    "同意",
    "我同意",
    "确定切换",
    "确认切换",
    "切吧",
    "切换",
    "切换吧",
    "用它",
    "换成它",
}

DISAGREE_EXACT = {
    "不同意",
    "不同意",
    "不用",
    "算了",
    "不要",
    "不切",
    "取消",
    "还是原来",
    "不用切",
    "no",
    "n",
}


@dataclass(frozen=True)
class ForceMatch:
    token: str
    scene_id: str | None
    provider_id: str | None
    leftover: str
    matched_span: str
    had_verb: bool = False


@dataclass(frozen=True)
class KeywordHit:
    scene_id: str
    keyword: str
    score: int


def looks_like_command(text: str, prefixes: tuple[str, ...]) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    for prefix in prefixes:
        if prefix and stripped.startswith(prefix):
            return True
    return False


def has_code_signal(text: str) -> bool:
    if CODE_FENCE_RE.search(text):
        return True
    if STACK_RE.search(text):
        return True
    return False


def has_link(text: str) -> bool:
    return bool(LINK_RE.search(text))


def is_follow_up(
    text: str,
    keywords: tuple[str, ...] = DEFAULT_FOLLOW_UPS,
    max_chars: int = 20,
) -> bool:
    stripped = (text or "").strip().strip("。.!！?？~～、，,")
    if not stripped or len(stripped) > max_chars:
        return False
    compact = stripped.lower()
    names = {item.strip().lower() for item in keywords if item and item.strip()}
    return compact in names


def is_help_intent(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    compact = stripped.lower()
    if compact in {"help", "/help", "帮助"}:
        return True
    if len(stripped) > 80:
        return False
    return any(phrase in stripped or phrase in compact for phrase in HELP_PHRASES)


def _normalize_reply(text: str) -> str:
    return (text or "").strip().strip("。.!！?？~～、，, ").lower()


def is_consent_agree(text: str) -> bool:
    compact = _normalize_reply(text)
    if not compact or len(compact) > 16:
        return False
    return compact in AGREE_EXACT


def is_consent_disagree(text: str) -> bool:
    compact = _normalize_reply(text)
    if not compact or len(compact) > 16:
        return False
    return compact in DISAGREE_EXACT


def is_capability_request(text: str) -> bool:
    stripped = text or ""
    if not stripped:
        return False
    lowered = stripped.lower()
    return any(phrase in stripped or phrase.lower() in lowered for phrase in CAPABILITY_PHRASES)


def has_explicit_switch_intent(text: str) -> bool:
    """User must say they want to switch/find a model, not just mention a scene name."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    if EXPLICIT_SWITCH_RE.search(stripped):
        return True
    return bool(FORCE_VERB_RE.match(stripped))


def scene_names(scene) -> tuple[str, ...]:
    names = [scene.id, scene.display_name, scene.persona_id, scene.persona_label, *scene.aliases]
    return tuple(item for item in names if item and str(item).strip())


def scene_wakeup_names(scene) -> tuple[str, ...]:
    if scene.wakeup_words:
        return tuple(item for item in scene.wakeup_words if item and str(item).strip())
    return tuple(item for item in scene.aliases if item and str(item).strip())


def wakeup_matches(text: str, pattern: str, mode: str) -> bool:
    stripped = text or ""
    token = str(pattern or "").strip()
    if not stripped or not token:
        return False
    if mode == "exact":
        compact_text = normalize_token(stripped)
        compact_pat = normalize_token(token)
        return bool(compact_pat) and compact_text == compact_pat
    if mode == "regex":
        try:
            return bool(re.search(token, stripped, re.IGNORECASE))
        except re.error:
            return False
    if token in stripped:
        return True
    lowered = stripped.lower()
    return token.lower() in lowered


def find_named_scene_ids(text: str, settings: PluginSettings) -> tuple[str, ...]:
    stripped = text or ""
    if not stripped:
        return ()
    hits: list[str] = []
    for scene in settings.enabled_scenes():
        mode = scene_wakeup_mode(scene, settings.wakeup_match_mode)
        names = scene_wakeup_names(scene)
        if not names:
            names = scene_names(scene)
        matched = False
        for name in names:
            if wakeup_matches(stripped, name, mode):
                hits.append(scene.id)
                matched = True
                break
        if matched:
            continue
        if mode == "contains":
            for name in scene_names(scene):
                if name and name in stripped:
                    hits.append(scene.id)
                    break
                token = normalize_token(name)
                if token and len(token) >= 2 and token in normalize_token(stripped):
                    hits.append(scene.id)
                    break
    return tuple(dict.fromkeys(hits))


def strong_named_scene_ids(
    text: str,
    settings: PluginSettings,
    named_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Full scene title or wakeup word, not a short alias."""
    stripped = text or ""
    ids = named_ids or find_named_scene_ids(stripped, settings)
    hits: list[str] = []
    for scene_id in ids:
        if settings.is_default_scene(scene_id):
            continue
        scene = settings.scene(scene_id)
        if scene is None:
            continue
        strong_names = [
            scene.display_name,
            scene.persona_label,
            *scene.wakeup_words,
        ]
        for name in strong_names:
            token = str(name or "").strip()
            if token and len(token) >= 2 and token in stripped:
                hits.append(scene_id)
                break
    return tuple(dict.fromkeys(hits))


def mentions_blocked_persona(text: str, blocked: tuple[str, ...]) -> bool:
    compact = normalize_token(text or "")
    if not compact:
        return False
    for item in blocked:
        token = normalize_token(item)
        if token and token in compact:
            return True
    return False


def _catalog_names(settings: PluginSettings, extra_names: tuple[str, ...] = ()) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            return
        key = normalize_token(cleaned)
        if not key or key in seen:
            return
        seen.add(key)
        names.append(cleaned)

    for alias in settings.model_aliases:
        add(alias)
    for scene in settings.scenes.values():
        add(scene.id)
        add(scene.display_name)
        for alias in scene.aliases:
            add(alias)
        if scene.provider_id:
            add(scene.provider_id)
    for name in extra_names:
        add(name)
    names.sort(key=lambda item: len(normalize_token(item)), reverse=True)
    return names


def _starts_with_name(text: str, name: str) -> str | None:
    """If `text` starts with `name` (ignoring case/separators), return the consumed prefix."""
    if not text or not name:
        return None
    if text.startswith(name):
        return name
    if text.lower().startswith(name.lower()):
        return text[: len(name)]

    name_norm = normalize_token(name)
    if not name_norm:
        return None
    consumed = 0
    matched = 0
    for ch in text:
        if ch.isspace() or ch in "-_":
            if matched:
                consumed += 1
            else:
                break
            continue
        compact = normalize_token(ch)
        if not compact:
            if matched:
                consumed += 1
                continue
            break
        if matched < len(name_norm) and compact == name_norm[matched]:
            matched += 1
            consumed += 1
            if matched == len(name_norm):
                return text[:consumed]
            continue
        break
    return None


def match_force(
    text: str,
    settings: PluginSettings,
    extra_names: tuple[str, ...] = (),
) -> ForceMatch | None:
    stripped = text.strip()
    if not stripped:
        return None

    verb = FORCE_VERB_RE.match(stripped)
    rest = stripped[verb.end() :].lstrip(" \t「『\"':：") if verb else stripped
    names = _catalog_names(settings, extra_names)

    for name in names:
        consumed = _starts_with_name(rest, name)
        if not consumed:
            continue
        leftover = rest[len(consumed) :].lstrip()
        leftover = TRAILING_NOISE_RE.sub("", leftover).lstrip(" \t，,、")
        scene_id, provider_id = settings.resolve_target(name)
        if extra_names and not provider_id:
            extra_map = {normalize_token(item): item for item in extra_names}
            provider_id = extra_map.get(normalize_token(name), provider_id)
        if not scene_id and not provider_id:
            continue
        if verb is None:
            # Without a switch verb, only accept a whole-message alias such as「代码模型」.
            remainder = leftover
            remainder = re.sub(r"^(?:模型|这个)\s*$", "", remainder, flags=re.IGNORECASE).strip()
            if remainder:
                continue
            leftover = ""
        return ForceMatch(
            token=name,
            scene_id=scene_id,
            provider_id=provider_id,
            leftover=leftover,
            matched_span=stripped[: len(stripped) - len(rest) + len(consumed)] if verb else consumed,
            had_verb=bool(verb),
        )
    return None


def match_keywords(text: str, settings: PluginSettings) -> KeywordHit | None:
    best: KeywordHit | None = None
    lowered = text.lower()
    for scene in settings.enabled_scenes():
        for keyword in scene.keywords:
            if not keyword:
                continue
            found = keyword in text or keyword.lower() in lowered
            if not found:
                continue
            score = len(keyword)
            if best is None or score > best.score:
                best = KeywordHit(scene_id=scene.id, keyword=keyword, score=score)
            elif best and score == best.score and scene.id != best.scene_id:
                order = {sid: idx for idx, sid in enumerate(SCENE_PRIORITY)}
                if order.get(scene.id, 99) < order.get(best.scene_id, 99):
                    best = KeywordHit(scene_id=scene.id, keyword=keyword, score=score)
    return best
