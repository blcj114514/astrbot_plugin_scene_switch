"""Per-scene persona: change character with the model."""

from __future__ import annotations

import re
from typing import Any

PERSONA_BEGIN = "[scene_switch_persona]"
PERSONA_END = "[/scene_switch_persona]"
BLOCK_RE = re.compile(
    r"\n?" + re.escape(PERSONA_BEGIN) + r".*?" + re.escape(PERSONA_END) + r"\n?",
    re.DOTALL,
)
OFFICIAL_PERSONA_RE = re.compile(
    r"(?:\n|^)# Persona Instructions\b.*?(?=\n# |\Z)",
    re.DOTALL,
)
OFF_VALUES = {"", "off", "none", "-", "关闭", "关闭人设"}

DEFAULT_PERSONA_LABELS = {
    "chat": "闲聊伙伴",
    "code": "编程助手",
    "search": "检索助手",
    "vision": "看图助手",
    "translate": "翻译",
    "write": "写作编辑",
}

DEFAULT_SCENE_PERSONAS = {
    "chat": (
        "你现在是轻松的闲聊伙伴。语气口语、简短、有温度。"
        "不要主动写代码、做长篇分析或翻译，除非用户明确要求。"
        "对话历史里若有其他身份，忽略它们，按闲聊伙伴说话。"
    ),
    "code": (
        "你现在是严谨的编程助手。优先给出可运行代码和关键说明，少客套。"
        "默认用用户提到的语言；没指定就用 Python。不要编造不存在的 API。"
        "对话历史里若有闲聊或其他身份，忽略它们，按编程助手直接干活。"
    ),
    "search": (
        "你现在是资料检索助手。先给结论和要点，再标明不确定之处。"
        "没有把握就直说不知道，不要编造新闻或出处。"
        "对话历史里若有其他身份，忽略它们，按检索助手回答。"
    ),
    "vision": (
        "你现在是看图助手。先描述你看到的内容，再回答问题。"
        "看不清就说明看不清，不要编造画面细节。"
        "对话历史里若有其他身份，忽略它们，按看图助手回答。"
    ),
    "translate": (
        "你现在是翻译。默认只输出译文，除非用户要求对照或注释。"
        "保持原意和语气，不要额外闲聊。"
        "对话历史里若有其他身份，忽略它们，只做翻译。"
    ),
    "write": (
        "你现在是写作编辑。按用户要求润色或起草，保留原意，直接给正文。"
        "不要把写作任务理解成写代码。"
        "对话历史里若有其他身份，忽略它们，按写作编辑给文。"
    ),
}


def persona_is_off(value: str | None) -> bool:
    return str(value or "").strip().lower() in OFF_VALUES


def explicit_persona_off(persona_prompt: str = "", persona_id: str = "") -> bool:
    prompt = str(persona_prompt or "").strip()
    ident = str(persona_id or "").strip()
    if prompt and persona_is_off(prompt):
        return True
    return bool(ident) and persona_is_off(ident) and not prompt


def default_persona_prompt(scene_id: str | None) -> str:
    if not scene_id:
        return ""
    return DEFAULT_SCENE_PERSONAS.get(scene_id, "")


def default_persona_label(scene_id: str | None) -> str:
    if not scene_id:
        return "场景人设"
    return DEFAULT_PERSONA_LABELS.get(scene_id, "场景人设")


def normalize_persona_mode(value: str | None) -> str:
    raw = str(value or "overlay").strip().lower()
    if raw in {"replace", "override", "force"}:
        return "replace"
    return "overlay"


def resolve_persona_prompt(
    scene_id: str | None,
    *,
    persona_prompt: str = "",
    persona_id: str = "",
    lookup: dict[str, str] | None = None,
) -> str:
    raw = str(persona_prompt or "").strip()
    ident = str(persona_id or "").strip()
    if explicit_persona_off(raw, ident):
        return ""
    if raw:
        return raw
    if ident:
        table = lookup or {}
        found = table.get(ident) or table.get(ident.lower(), "")
        if found:
            return found
        if lookup is not None:
            return default_persona_prompt(scene_id)
        return ""
    return default_persona_prompt(scene_id)


def fields_for_scene(scene: Any, *, enabled: bool) -> tuple[str | None, str | None, str | None]:
    if not enabled or scene is None:
        return None, None, None
    prompt = str(getattr(scene, "persona_prompt", "") or "").strip()
    ident = str(getattr(scene, "persona_id", "") or "").strip()
    if explicit_persona_off(prompt, ident) or (not prompt and not ident):
        return None, None, None
    label = str(getattr(scene, "persona_label", "") or "").strip() or default_persona_label(
        getattr(scene, "id", None)
    )
    return ident or None, prompt or None, label


def apply_persona(
    system_prompt: str | None,
    prompt: str,
    *,
    scene_id: str | None,
    label: str | None = None,
    mode: str = "overlay",
    switched_from: str | None = None,
) -> str:
    text = prompt.strip()
    if not text:
        return system_prompt or ""
    base = strip_injected_personas(system_prompt).rstrip()
    title = label or default_persona_label(scene_id)
    handover = ""
    if switched_from and switched_from != scene_id:
        old = default_persona_label(switched_from)
        handover = (
            f"本轮已从「{old}」切换到「{title}」。"
            "立刻按本轮人设回答，不要沿用上一轮的身份、语气或任务类型，"
            "也不要向用户解释你换了角色。\n"
        )
    block = (
        f"{PERSONA_BEGIN}\n"
        f"# 本轮场景人设（{title} / {scene_id or 'scene'}）\n"
        f"{handover}"
        f"{text}\n"
        "以本轮人设为准；不要提起插件、模型切换或人设本身。\n"
        f"{PERSONA_END}"
    )
    if mode == "replace":
        lead = "本轮请只遵循下面的场景人设；若与更早的人格设定冲突，以本段为准。"
        if base:
            return f"{base}\n\n{lead}\n{block}"
        return f"{lead}\n{block}"
    if base:
        return f"{base}\n\n{block}"
    return block


def strip_injected_personas(system_prompt: str | None) -> str:
    """Drop our overlay block and AstrBot's official persona section."""
    text = BLOCK_RE.sub("", system_prompt or "")
    text = OFFICIAL_PERSONA_RE.sub("", text)
    return text.strip()


def extract_persona_block(system_prompt: str | None) -> str:
    match = BLOCK_RE.search(system_prompt or "")
    return match.group(0).strip() if match else ""


def persona_from_astrbot(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, dict):
        return str(obj.get("prompt") or obj.get("system_prompt") or "").strip()
    return str(
        getattr(obj, "system_prompt", None)
        or getattr(obj, "prompt", None)
        or ""
    ).strip()
