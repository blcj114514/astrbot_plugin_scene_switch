"""User-facing labels after a scene switch."""

from __future__ import annotations

from typing import Any

from .settings import PluginSettings

SOURCE_NAMES = {
    "force": "用户点名",
    "judge": "审判模型",
    "heuristic": "本地启发式审判",
    "rules": "规则 / 关键词",
    "sticky": "沿用刚才的场景",
    "follow_up": "短句跟进",
    "lock": "会话锁定",
    "think": "思考强度",
    "fallback": "兜底场景",
    "consent": "用户同意切换",
    "consent_denied": "用户不同意切换",
}


def scene_title(settings: PluginSettings, scene_id: str | None) -> str:
    scene = settings.scene(scene_id) if scene_id else None
    if scene:
        return scene.display_name
    return scene_id or "模型"


def compact_label(
    settings: PluginSettings,
    scene_id: str | None,
    *,
    persona_label: str | None = None,
    provider_id: str | None = None,
    effort: str | None = None,
    verbose: bool = False,
) -> str:
    bits = [scene_title(settings, scene_id)]
    if verbose and provider_id:
        bits.append(provider_id)
    if verbose and effort:
        bits.append(effort)
    if persona_label and persona_label not in bits:
        bits.append(persona_label)
    return f"『{' · '.join(bits)}』"


def reply_prefix(persona_label: str | None, scene_id: str | None, settings: PluginSettings) -> str:
    tag = persona_label or scene_title(settings, scene_id)
    return f"〔{tag}〕 "


def confirm_switch(settings: PluginSettings, decision: Any) -> str:
    label = compact_label(
        settings,
        getattr(decision, "scene_id", None),
        persona_label=getattr(decision, "persona_label", None),
    )
    source = getattr(decision, "source", "")
    hint = getattr(decision, "consent_prompt", None)
    if source == "think" and hint and not getattr(decision, "reasoning_effort", None):
        return str(hint)
    if source == "think":
        effort = getattr(decision, "reasoning_effort", None) or "auto"
        if getattr(decision, "applied", False):
            return f"思考强度已设为 {effort}。下一句会用{label}。"
        return f"思考强度已设为 {effort}。下一句会按这个强度调用当前模型。"
    if getattr(decision, "stop_for_switch_only", False):
        return f"已切到{label}。下一句开始用这个模型和人设。"
    if source == "consent":
        return f"已切到{label}。接下来用这个模型和人设回答。"
    return f"已切到{label}。接下来几轮会优先用这个模型和人设。"


def format_consent_prompt(settings: PluginSettings, scene_id: str, reason: str = "") -> str:
    scene = settings.scene(scene_id)
    label = (scene.persona_label or scene.display_name) if scene else scene_id
    template = settings.consent_prompt_template or (
        "该对话更适合切换到{label}由它来回答你，你是否同意？回复「同意」或「不同意」。"
    )
    try:
        text = template.format(
            label=label,
            scene=scene.display_name if scene else scene_id,
            persona=label,
            provider=scene.provider_id if scene else "",
            reason=reason or "更适合这个模型",
        )
    except (KeyError, IndexError, ValueError):
        text = f"该对话更适合切换到{label}由它来回答你，你是否同意？回复「同意」或「不同意」。"
    return text.strip()


def describe_route(settings: PluginSettings, payload: Any) -> str:
    if not isinstance(payload, dict):
        help_requested = getattr(payload, "help_requested", False)
        source = getattr(payload, "source", "")
        applied = getattr(payload, "applied", False)
        stop = getattr(payload, "stop_for_switch_only", False)
        effort = getattr(payload, "reasoning_effort", None)
        scene_id = getattr(payload, "scene_id", None)
        provider_id = getattr(payload, "provider_id", None)
        persona_label = getattr(payload, "persona_label", None)
        changed = getattr(payload, "scene_changed", False)
    else:
        help_requested = payload.get("help") or payload.get("help_requested")
        source = payload.get("source") or ""
        applied = payload.get("applied")
        stop = payload.get("stop_for_switch_only")
        effort = payload.get("reasoning_effort")
        scene_id = payload.get("scene") or payload.get("scene_id")
        provider_id = payload.get("provider") or payload.get("provider_id")
        persona_label = payload.get("persona_label")
        changed = payload.get("scene_changed")

    if help_requested:
        return "这是在问功能，直接介绍插件，不切换聊天模型。"
    if source == "think" and stop:
        return f"思考强度 → {effort or 'auto'}"
    if not applied:
        return "没有改写模型，会继续用当前默认。"
    how = SOURCE_NAMES.get(source, source)
    title = scene_title(settings, scene_id)
    extra = f" · think {effort}" if effort else ""
    if persona_label:
        extra += f" · {persona_label}"
    switched = " · 刚切换" if changed else ""
    return f"{how} → {title}（{provider_id}{extra}{switched}）"
