"""Parse thinking-strength phrases. AstrBot injection is OpenAI-shaped only.

Ollama native `/api/chat` uses `think` (true/false or low/medium/high/max).
Ollama OpenAI `/v1` uses `reasoning_effort` (none/low/medium/high/max).
Official DeepSeek Chat Completions uses `thinking.type` plus `reasoning_effort`
(low/high/max; disable with type=disabled, not none).
Those fields are not interchangeable. AstrBot providers should carry their own
extra_body. This module only optionally sets `reasoning_effort` on a request
when the plugin overlay is enabled — it never writes native `think`.
"""

from __future__ import annotations

import re
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


def inject_reasoning_effort(req: Any, effort: str | None) -> bool:
    """Set AstrBot `reasoning_effort` only.

    Do not write Ollama native `think`, DeepSeek `thinking.type`, HTTP headers,
    or extra_body. Those belong on the Provider the user configured.
    """
    mapped = normalize_effort(effort)
    if not mapped:
        return False
    try:
        value = openai_effort(mapped)
    except Exception:
        value = mapped
    try:
        setattr(req, "reasoning_effort", value)
        return True
    except Exception:
        return False
