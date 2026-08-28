"""Parse thinking-strength phrases and inject OpenAI-shaped effort.

Ollama native `/api/chat` uses `think` (true/false or low/medium/high/max).
Ollama OpenAI `/v1` uses `reasoning_effort` (none/low/medium/high/max).
Official DeepSeek Chat Completions uses `thinking.type` plus `reasoning_effort`
(low/high/max; disable with type=disabled, not none).
Those fields are not interchangeable.

AstrBot's official `ProviderRequest` has no `reasoning_effort`. The agent runner
only copies a fixed set of fields into `text_chat` / `text_chat_stream`, so
`setattr(req, "reasoning_effort", ...)` is ignored on the main chat path.
OpenAI-compatible adapters also drop unknown kwargs inside
`_prepare_chat_payload`; they only send `reasoning_effort` when it is already
in the HTTP payload or Provider `custom_extra_body`.

This module therefore:

- still sets `req.reasoning_effort` (intent / future AstrBot versions)
- sets a task-local ContextVar for the current turn
- wraps the current Provider so this turn's OpenAI extra_body carries
  `reasoning_effort` (after Provider config merge, so session overlay wins)

It never writes Ollama native `think`, DeepSeek `thinking.type`, or HTTP headers.
"""

from __future__ import annotations

import inspect
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from .ollama import openai_effort

EFFORT_LEVELS = ("none", "low", "medium", "high", "max")

DEFAULT_SCENE_EFFORT = {
    "chat": "none",
    "code": "high",
    "search": "low",
    "vision": "none",
    "translate": "none",
    "write": "high",
}

# Keys copied by AstrBot ToolLoopAgentRunner._iter_llm_responses into text_chat.
# reasoning_effort is not among them.
ASTRBOT_AGENT_TEXT_CHAT_KEYS = (
    "contexts",
    "func_tool",
    "session_id",
    "extra_user_content_parts",
    "abort_signal",
    "request_max_retries",
    "model",
)

_effort_cv: ContextVar[str | None] = ContextVar(
    "scene_switch_reasoning_effort", default=None
)

_STASH_APPLY = "_scene_switch_orig_apply"
_STASH_PREPARE = "_scene_switch_orig_prepare"
_STASH_TEXT_CHAT = "_scene_switch_orig_text_chat"
_STASH_TEXT_CHAT_STREAM = "_scene_switch_orig_text_chat_stream"

# Longer phrases first. Explicit 开启思考 <档位> is handled by match_think_command.
_THINK_PHRASES: tuple[tuple[str, str], ...] = (
    ("开启思考 max", "max"),
    ("开启思考 high", "high"),
    ("开启思考 medium", "medium"),
    ("开启思考 low", "low"),
    ("开启思考 none", "none"),
    ("思考强度拉满", "max"),
    ("把思考拉满", "max"),
    ("深度思考", "max"),
    ("认真想想", "max"),
    ("仔细想想", "max"),
    ("使劲想", "max"),
    ("think max", "max"),
    ("用 max 思考", "max"),
    ("用max思考", "max"),
    ("好好想想", "high"),
    ("多想想", "high"),
    ("想清楚", "high"),
    ("think high", "high"),
    ("用 high 思考", "high"),
    ("用high思考", "high"),
    ("浅想一下", "low"),
    ("简单想想", "low"),
    ("think low", "low"),
    ("用 low 思考", "low"),
    ("用low思考", "low"),
    ("关闭思考", "none"),
    ("不要思考", "none"),
    ("不用思考", "none"),
    ("别想了", "none"),
    ("直接答", "none"),
    ("think none", "none"),
    ("think off", "none"),
    ("用 none 思考", "none"),
    ("恢复默认思考", "auto"),
    ("自动思考", "auto"),
    ("think auto", "auto"),
)


@dataclass(frozen=True)
class ThinkMatch:
    effort: str
    leftover: str
    token: str


def normalize_effort(value: Any, default: str = "") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"", "auto", "default", "provider"}:
        return default
    if raw in {"off", "false", "0", "关", "关闭"}:
        return "none"
    if raw in {"true", "on"}:
        return "high"
    if raw in EFFORT_LEVELS:
        return raw
    return default


_AT_RE = re.compile(r"\[CQ:at[^\]]*\]|@\S+")
_COMMAND_LEVEL = re.compile(
    r"(?:开启思考|打开思考|启用思考|把思考开到|思考开到|"
    r"思考强度(?:设为|改成|切换到|切换为)?|"
    r"(?:please\s+)?(?:enable|set)\s+think(?:ing)?)"
    r"\s*[：:=\s]*"
    r"(none|off|low|medium|high|max|关|关闭)",
    re.IGNORECASE,
)
_BARE_ENABLE = re.compile(r"^(?:开启思考|打开思考|启用思考)[。.!！]?$", re.IGNORECASE)
_BARE_DISABLE = re.compile(r"^(?:关闭思考|关掉思考|停止思考)[。.!！]?$", re.IGNORECASE)


def _strip_at(text: str) -> str:
    return _AT_RE.sub(" ", text or "").strip()


def match_think_command(text: str) -> ThinkMatch | None:
    """Group-friendly command: @bot 开启思考 max / 关闭思考.

    Returns leftover="" when the whole message is the command. effort="" means
    the user said 开启思考 without a level and should get a usage hint.
    """
    compact = re.sub(r"\s+", " ", _strip_at(text)).strip()
    if not compact:
        return None
    if _BARE_DISABLE.fullmatch(compact):
        return ThinkMatch(effort="none", leftover="", token="关闭思考")
    if _BARE_ENABLE.fullmatch(compact):
        return ThinkMatch(effort="", leftover="", token="开启思考")
    match = _COMMAND_LEVEL.search(compact)
    if not match:
        return None
    raw = match.group(1).lower()
    effort = normalize_effort(raw)
    leftover = (compact[: match.start()] + " " + compact[match.end() :]).strip()
    leftover = leftover.strip(" ，,、。.!！")
    return ThinkMatch(effort=effort, leftover=leftover, token=match.group(0))


def scene_default_effort(scene_id: str | None) -> str:
    if not scene_id:
        return ""
    return DEFAULT_SCENE_EFFORT.get(scene_id, "")


def match_think(text: str) -> ThinkMatch | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    for phrase, effort in _THINK_PHRASES:
        needle = phrase.lower()
        idx = lowered.find(needle)
        if idx < 0:
            continue
        leftover = (stripped[:idx] + " " + stripped[idx + len(phrase) :]).strip()
        leftover = re.sub(r"\s+", " ", leftover)
        leftover = leftover.strip(" ，,、。.!！?？~～")
        leftover = re.sub(r"^(?:请|麻烦|帮我|拜托){1,2}\s*", "", leftover)
        leftover = leftover.strip(" ，,、")
        return ThinkMatch(effort=effort, leftover=leftover, token=phrase)
    return None


def _mapped_effort(effort: str | None) -> str:
    mapped = normalize_effort(effort)
    if not mapped:
        return ""
    try:
        return openai_effort(mapped)
    except Exception:
        return mapped


def current_request_effort() -> str | None:
    return _effort_cv.get()


def set_request_effort(effort: str | None) -> Token:
    mapped = _mapped_effort(effort)
    return _effort_cv.set(mapped or None)


def reset_request_effort(token: Token | None) -> None:
    if token is None:
        return
    try:
        _effort_cv.reset(token)
    except Exception:
        _effort_cv.set(None)


def clear_request_effort() -> None:
    _effort_cv.set(None)


def agent_text_chat_payload(req: Any) -> dict[str, Any]:
    """Reproduce the official agent runner's text_chat kwargs.

    Used by tests to prove `req.reasoning_effort` never reaches the provider.
    """
    payload: dict[str, Any] = {}
    for key in ASTRBOT_AGENT_TEXT_CHAT_KEYS:
        if hasattr(req, key):
            payload[key] = getattr(req, key)
    return payload


def inject_reasoning_effort(req: Any, effort: str | None) -> bool:
    """Record OpenAI-shaped effort on the request object.

    AstrBot ignores this attribute on the main agent path. Call
    `set_request_effort` plus `ensure_provider_effort_passthrough` so the
    Provider actually sends it. Do not write native `think` or extra_body onto
    the request object.
    """
    mapped = _mapped_effort(effort)
    if not mapped:
        return False
    try:
        setattr(req, "reasoning_effort", mapped)
        return True
    except Exception:
        return False


def _apply_request_effort(payloads: Any, extra_body: Any) -> None:
    effort = current_request_effort()
    if not effort:
        return
    if isinstance(extra_body, dict):
        extra_body["reasoning_effort"] = effort
        extra_body.pop("think", None)
    if isinstance(payloads, dict):
        payloads["reasoning_effort"] = effort


def _stash_orig(provider: Any, attr: str, stash: str) -> Any:
    if not hasattr(provider, stash):
        setattr(provider, stash, getattr(provider, attr, None))
    return getattr(provider, stash)


def _wrap_prepare(orig: Any):
    async def wrapped(*args: Any, **kwargs: Any):
        result = orig(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        if not (isinstance(result, tuple) and result):
            return result
        payloads = result[0]
        effort = kwargs.get("reasoning_effort") or current_request_effort()
        mapped = _mapped_effort(effort) if effort else ""
        if mapped and isinstance(payloads, dict):
            payloads["reasoning_effort"] = mapped
        return result

    return wrapped


def _wrap_apply(orig: Any):
    def wrapped(payloads: Any, extra_body: Any, *args: Any, **kwargs: Any) -> Any:
        if orig is not None:
            orig(payloads, extra_body, *args, **kwargs)
        _apply_request_effort(payloads, extra_body)
        return None

    return wrapped


def _wrap_text_chat(orig: Any):
    async def wrapped(*args: Any, **kwargs: Any):
        effort = current_request_effort()
        if effort:
            kwargs.setdefault("reasoning_effort", effort)
        result = orig(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    return wrapped


def _wrap_text_chat_stream(orig: Any):
    async def wrapped(*args: Any, **kwargs: Any):
        effort = current_request_effort()
        if effort:
            kwargs.setdefault("reasoning_effort", effort)
        stream = orig(*args, **kwargs)
        if inspect.isasyncgen(stream):
            async for item in stream:
                yield item
            return
        if inspect.isawaitable(stream):
            stream = await stream
        if inspect.isasyncgen(stream):
            async for item in stream:
                yield item
            return
        yield stream

    return wrapped


def ensure_provider_effort_passthrough(provider: Any) -> bool:
    """Wrap an AstrBot Provider so this turn's reasoning_effort is actually sent.

    Re-entrant: original methods are stashed once and wrappers are rebuilt from
    those originals so plugin reloads do not stack wraps.
    """
    if provider is None:
        return False
    orig_apply = _stash_orig(
        provider, "_apply_provider_specific_request_overrides", _STASH_APPLY
    )
    provider._apply_provider_specific_request_overrides = _wrap_apply(orig_apply)

    orig_prepare = _stash_orig(provider, "_prepare_chat_payload", _STASH_PREPARE)
    if orig_prepare is not None:
        provider._prepare_chat_payload = _wrap_prepare(orig_prepare)

    orig_chat = _stash_orig(provider, "text_chat", _STASH_TEXT_CHAT)
    if orig_chat is not None:
        provider.text_chat = _wrap_text_chat(orig_chat)

    orig_stream = _stash_orig(provider, "text_chat_stream", _STASH_TEXT_CHAT_STREAM)
    if orig_stream is not None:
        provider.text_chat_stream = _wrap_text_chat_stream(orig_stream)
    return True
