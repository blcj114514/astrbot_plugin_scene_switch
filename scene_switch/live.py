"""Route a message with a live Ollama Cloud judge / answer model."""

from __future__ import annotations

from typing import Any

from .display import describe_route
from .heuristic import guess_scene
from .helptext import build_feature_intro
from .judge import build_judge_messages, parse_judge_reply
from .ollama import (
    ChatResult,
    OllamaClient,
    catalog_provider_ids,
    load_catalog,
    settings_dict_from_catalog,
)
from .persona import apply_persona
from .router import RouteInput, RouteDecision, SceneRouter
from .settings import settings_from_dict
from .state import SessionStore


def live_settings_dict(catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    return settings_dict_from_catalog(catalog)


def make_live_router(
    store: SessionStore | None = None,
    catalog: dict[str, Any] | None = None,
) -> tuple[SceneRouter, dict[str, Any], tuple[str, ...]]:
    data = catalog or load_catalog()
    settings = settings_from_dict(live_settings_dict(data))
    providers = catalog_provider_ids(data)
    return SceneRouter(settings, store or SessionStore()), data, providers


def _hint_from_verdict(verdict) -> str:
    if verdict.action == "help":
        return "help"
    if verdict.action == "route" and verdict.scene_id:
        return verdict.scene_id
    return "keep"


def live_judge(
    client: OllamaClient,
    router: SceneRouter,
    catalog: dict[str, Any],
    text: str,
    last_scene: str | None = None,
) -> tuple[str, ChatResult]:
    judge = catalog.get("judge") or {}
    model = str(judge.get("model") or "")
    if not model:
        raise RuntimeError("catalog 里没有审判模型")
    system, user = build_judge_messages(router.settings, text, last_scene)
    result = client.chat(
        model,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        reasoning_effort=judge.get("reasoning_effort", "none"),
        max_tokens=int(judge.get("max_tokens") or 80),
        temperature=0,
    )
    scene_ids = {scene.id for scene in router.settings.enabled_scenes()}
    verdict = parse_judge_reply(result.content, scene_ids)
    return _hint_from_verdict(verdict), result


def scene_effort(catalog: dict[str, Any], scene_id: str | None) -> str:
    scenes = catalog.get("scenes") or {}
    spec = scenes.get(scene_id or "") or {}
    return str(spec.get("reasoning_effort") or "none")


def live_answer(
    client: OllamaClient,
    catalog: dict[str, Any],
    decision: RouteDecision,
    text: str,
    *,
    max_tokens: int = 256,
    effort_override: str | None = None,
    persona_mode: str = "overlay",
) -> ChatResult | None:
    if decision.help_requested or not decision.provider_id:
        return None
    prompt = decision.cleaned_prompt if decision.cleaned_prompt is not None else text
    if not str(prompt).strip():
        return None
    effort = effort_override or decision.reasoning_effort or scene_effort(catalog, decision.scene_id)
    messages: list[dict[str, str]] = []
    if decision.persona_prompt:
        messages.append(
            {
                "role": "system",
                "content": apply_persona(
                    "",
                    decision.persona_prompt,
                    scene_id=decision.scene_id,
                    label=decision.persona_label,
                    mode=persona_mode,
                    switched_from=decision.previous_scene_id
                    if decision.scene_changed
                    else None,
                ),
            }
        )
    messages.append({"role": "user", "content": prompt})
    return client.chat(
        decision.provider_id,
        messages,
        reasoning_effort=effort,
        max_tokens=max_tokens,
        temperature=0.2,
    )


def decide_live(
    router: SceneRouter,
    catalog: dict[str, Any],
    providers: tuple[str, ...],
    text: str,
    *,
    media: bool = False,
    group: bool = False,
    sender: str = "live-user",
    client: OllamaClient | None = None,
    answer: bool = False,
    umo: str | None = None,
    effort_override: str | None = None,
) -> dict[str, Any]:
    inp = RouteInput(
        text=text,
        umo=umo or ("live:group:demo" if group else "live:private:demo"),
        sender_id=sender,
        is_group=group,
        has_media=media,
        available_providers=providers,
    )
    if effort_override:
        key = SessionStore.make_key(inp.umo, inp.sender_id)
        if effort_override in {"auto", "provider", ""}:
            router.store.clear_think(key)
        else:
            router.store.set_think(key, effort_override, router.settings.think_ttl_seconds)
    decision = router.decide(inp)
    judge_payload: dict[str, Any] | None = None
    if decision.needs_judge:
        if client is None:
            client = OllamaClient.from_env()
        key = SessionStore.make_key(inp.umo, inp.sender_id)
        try:
            hint, judged = live_judge(client, router, catalog, text, router.store.last_scene(key))
            judge_payload = {
                "model": judged.model,
                "content": judged.content,
                "reasoning": judged.reasoning,
                "usage": judged.usage,
                "hint": hint,
            }
        except Exception as exc:
            guessed = guess_scene(text, {scene.id for scene in router.settings.enabled_scenes()})
            hint = guessed or "keep"
            judge_payload = {
                "error": str(exc),
                "fallback": "heuristic",
                "hint": hint,
            }
        decision = router.decide(inp, judge_hint=hint)

    intro = None
    if decision.help_requested:
        intro = build_feature_intro(
            router.settings,
            loaded_providers=providers,
            judge_ready=True,
        )

    answer_payload: dict[str, Any] | None = None
    if answer:
        if client is None:
            client = OllamaClient.from_env()
        replied = live_answer(
            client,
            catalog,
            decision,
            text,
            effort_override=effort_override,
            persona_mode=router.settings.persona_mode,
        )
        if replied is not None:
            used_effort = (
                effort_override or decision.reasoning_effort or scene_effort(catalog, decision.scene_id)
            )
            answer_payload = {
                "model": replied.model,
                "content": replied.content,
                "reasoning": replied.reasoning,
                "reasoning_chars": len(replied.reasoning or ""),
                "usage": replied.usage,
                "reasoning_effort": used_effort,
            }

    payload = decision.to_dict(include_prompt=True)
    payload.update(
        {
            "intro": intro,
            "judge": judge_payload,
            "answer": answer_payload,
            "reasoning_effort": effort_override
            or decision.reasoning_effort
            or (scene_effort(catalog, decision.scene_id) if decision.scene_id else None),
            "label": describe_route(router.settings, decision),
        }
    )
    return payload
