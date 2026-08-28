"""Sync scene personas onto AstrBot's official conversation slot.

Other plugins and `/persona` read `conversation.persona_id`. Session custom
rules (`session_service_config.persona_id`) are only overwritten when a force
persona already exists; this module never creates a new force rule.
It never touches provider / model selection.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any

from .persona import default_persona_prompt, persona_from_astrbot

MANAGED_PREFIX = "scene_switch_"


@dataclass(frozen=True)
class PersonaSyncPlan:
    official_id: str
    prompt: str
    label: str
    ensure_managed: bool
    skip: bool = False
    reason: str = ""


@dataclass(frozen=True)
class PersonaSyncResult:
    official_id: str
    ensured: bool = False
    conversation_updated: bool = False
    session_updated: bool = False
    skipped: bool = False
    reason: str = ""


def managed_persona_id(scene_id: str | None) -> str:
    raw = str(scene_id or "").strip()
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_") or "scene"
    if safe[0].isdigit():
        safe = f"s_{safe}"
    return f"{MANAGED_PREFIX}{safe}"


def is_managed_persona_id(persona_id: str | None) -> bool:
    return str(persona_id or "").startswith(MANAGED_PREFIX)


def item_persona_id(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, dict):
        return str(item.get("name") or item.get("persona_id") or item.get("id") or "").strip()
    return str(
        getattr(item, "name", None)
        or getattr(item, "persona_id", None)
        or getattr(item, "id", None)
        or ""
    ).strip()


def plan_official_persona(
    *,
    scene_id: str | None,
    persona_id: str | None = None,
    persona_prompt: str | None = None,
    persona_label: str | None = None,
    persona_exists: bool = False,
    switch_persona: bool = True,
    sync_official: bool = True,
) -> PersonaSyncPlan:
    """Decide which official AstrBot persona id this scene should own."""
    if not switch_persona:
        return PersonaSyncPlan("", "", "", False, skip=True, reason="switch_persona_off")
    if not sync_official:
        return PersonaSyncPlan("", "", "", False, skip=True, reason="sync_official_off")
    if not scene_id or scene_id == "named":
        return PersonaSyncPlan("", "", "", False, skip=True, reason="no_scene")

    ident = str(persona_id or "").strip()
    prompt = str(persona_prompt or "").strip()
    label = str(persona_label or "").strip() or scene_id
    if not ident and not prompt:
        return PersonaSyncPlan("", "", "", False, skip=True, reason="persona_off")

    if ident and persona_exists:
        return PersonaSyncPlan(
            official_id=ident,
            prompt=prompt,
            label=label,
            ensure_managed=False,
            reason="existing_astrbot_persona",
        )

    if not prompt:
        prompt = default_persona_prompt(scene_id)
    if not prompt and not ident:
        return PersonaSyncPlan("", "", "", False, skip=True, reason="empty_prompt")

    return PersonaSyncPlan(
        official_id=managed_persona_id(scene_id),
        prompt=prompt or default_persona_prompt(scene_id),
        label=label,
        ensure_managed=True,
        reason="managed_scene_persona",
    )


def existing_forced_persona_id(cfg: Any) -> str:
    if not isinstance(cfg, dict):
        return ""
    return str(cfg.get("persona_id") or "").strip()


def apply_persona_to_session_config(cfg: Any, persona_id: str) -> tuple[dict, bool]:
    """Overwrite an existing session-forced persona; never create a new force rule."""
    data = dict(cfg) if isinstance(cfg, dict) else {}
    current = existing_forced_persona_id(data)
    if not current:
        return data, False
    if current == persona_id:
        return data, False
    data["persona_id"] = persona_id
    return data, True


def should_write_official_slots(*, is_group: bool, sync_in_groups: bool) -> bool:
    if not is_group:
        return True
    return bool(sync_in_groups)


def bind_request_conversation_persona(req: Any, persona_id: str) -> bool:
    """Point this turn's ProviderRequest at the new official persona id."""
    if not persona_id or req is None:
        return False
    changed = False
    conv = getattr(req, "conversation", None)
    if conv is not None and getattr(conv, "persona_id", None) != persona_id:
        try:
            conv.persona_id = persona_id
            changed = True
        except Exception:
            pass
    if hasattr(req, "persona_id") and getattr(req, "persona_id", None) != persona_id:
        try:
            req.persona_id = persona_id
            changed = True
        except Exception:
            pass
    return changed


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def import_shared_prefs() -> Any:
    try:
        from astrbot.api import sp  # type: ignore

        return sp
    except Exception:
        try:
            from astrbot.core import sp  # type: ignore

            return sp
        except Exception:
            return None


async def fetch_persona(manager: Any, persona_id: str) -> Any:
    if manager is None or not persona_id:
        return None
    for name in ("get_persona_v3_by_id", "get_v3_persona", "get_persona"):
        fn = getattr(manager, name, None)
        if not callable(fn):
            continue
        try:
            obj = await _maybe_await(fn(persona_id))
        except Exception:
            continue
        if obj is not None:
            return obj
    try:
        listing = getattr(manager, "personas_v3", None) or getattr(manager, "personas", None)
        if callable(listing):
            listing = await _maybe_await(listing())
        if isinstance(listing, dict):
            hit = listing.get(persona_id)
            if hit is not None:
                return hit
        if isinstance(listing, list):
            for item in listing:
                if item_persona_id(item) == persona_id:
                    return item
    except Exception:
        return None
    return None


async def persona_exists(manager: Any, persona_id: str) -> bool:
    return await fetch_persona(manager, persona_id) is not None


async def _refresh_persona_cache(manager: Any) -> None:
    fn = getattr(manager, "get_v3_persona_data", None)
    if callable(fn):
        try:
            await _maybe_await(fn())
        except Exception:
            return


async def create_persona(manager: Any, persona_id: str, prompt: str) -> bool:
    fn = getattr(manager, "create_persona", None)
    if not callable(fn):
        return False
    attempts = (
        lambda: fn(persona_id, prompt),
        lambda: fn(persona_id=persona_id, system_prompt=prompt),
        lambda: fn(persona_id, system_prompt=prompt),
    )
    for attempt in attempts:
        try:
            await _maybe_await(attempt())
            await _refresh_persona_cache(manager)
            return True
        except TypeError:
            continue
        except Exception:
            if await fetch_persona(manager, persona_id) is not None:
                await _refresh_persona_cache(manager)
                return True
            return False
    return False


async def update_persona(manager: Any, persona_id: str, prompt: str) -> bool:
    fn = getattr(manager, "update_persona", None)
    if not callable(fn):
        return False
    attempts = (
        lambda: fn(persona_id, system_prompt=prompt),
        lambda: fn(persona_id=persona_id, system_prompt=prompt),
        lambda: fn(persona_id, prompt),
    )
    for attempt in attempts:
        try:
            await _maybe_await(attempt())
            await _refresh_persona_cache(manager)
            return True
        except TypeError:
            continue
        except Exception:
            return False
    return False


async def ensure_official_persona(
    manager: Any,
    persona_id: str,
    prompt: str,
    cache: dict[str, str] | None = None,
) -> bool:
    if not persona_id or not prompt or manager is None:
        return False
    if cache is not None and cache.get(persona_id) == prompt:
        return True
    existing = await fetch_persona(manager, persona_id)
    if existing is None:
        created = await create_persona(manager, persona_id, prompt)
        if created and cache is not None:
            cache[persona_id] = prompt
        return created
    if persona_from_astrbot(existing) == prompt:
        if cache is not None:
            cache[persona_id] = prompt
        return True
    updated = await update_persona(manager, persona_id, prompt)
    if updated and cache is not None:
        cache[persona_id] = prompt
    return updated


async def current_conversation_persona_id(manager: Any, umo: str) -> str | None:
    if manager is None or not umo:
        return None
    get_cid = getattr(manager, "get_curr_conversation_id", None)
    get_conv = getattr(manager, "get_conversation", None)
    if not callable(get_cid) or not callable(get_conv):
        return None
    try:
        cid = await _maybe_await(get_cid(umo))
    except Exception:
        return None
    if not cid:
        return None
    attempts = (
        lambda: get_conv(umo, cid),
        lambda: get_conv(unified_msg_origin=umo, conversation_id=cid),
        lambda: get_conv(conversation_id=cid),
    )
    for attempt in attempts:
        try:
            conv = await _maybe_await(attempt())
        except TypeError:
            continue
        except Exception:
            return None
        if conv is None:
            return None
        ident = getattr(conv, "persona_id", None)
        if ident is None and isinstance(conv, dict):
            ident = conv.get("persona_id")
        return str(ident) if ident else None
    return None


async def update_conversation_persona(manager: Any, umo: str, persona_id: str) -> bool:
    if manager is None or not umo or not persona_id:
        return False
    current = await current_conversation_persona_id(manager, umo)
    if current == persona_id:
        return False

    fn = getattr(manager, "update_conversation", None)
    if callable(fn):
        try:
            await _maybe_await(fn(unified_msg_origin=umo, persona_id=persona_id))
            return True
        except TypeError:
            pass
        except Exception:
            return False

    fn = getattr(manager, "update_conversation_persona_id", None)
    if callable(fn):
        try:
            await _maybe_await(fn(umo, persona_id))
            return True
        except TypeError:
            try:
                await _maybe_await(fn(unified_msg_origin=umo, persona_id=persona_id))
                return True
            except Exception:
                return False
        except Exception:
            return False
    return False


async def overwrite_session_persona(umo: str, persona_id: str, sp: Any = None) -> bool:
    if not umo or not persona_id:
        return False
    prefs = sp if sp is not None else import_shared_prefs()
    if prefs is None:
        return False
    get_async = getattr(prefs, "get_async", None)
    put_async = getattr(prefs, "put_async", None)
    if not callable(get_async) or not callable(put_async):
        return False
    try:
        try:
            cfg = await _maybe_await(
                get_async("umo", umo, "session_service_config", default={})
            )
        except TypeError:
            cfg = await _maybe_await(get_async("umo", umo, "session_service_config"))
    except Exception:
        cfg = {}
    new_cfg, changed = apply_persona_to_session_config(cfg, persona_id)
    if not changed:
        return False
    await _maybe_await(put_async("umo", umo, "session_service_config", new_cfg))
    return True


async def sync_official_persona(
    *,
    umo: str,
    plan: PersonaSyncPlan,
    persona_manager: Any = None,
    conversation_manager: Any = None,
    sp: Any = None,
    req: Any = None,
    ensured_cache: dict[str, str] | None = None,
    write_slots: bool = True,
) -> PersonaSyncResult:
    if plan.skip or not plan.official_id:
        return PersonaSyncResult("", skipped=True, reason=plan.reason)
    if not write_slots:
        return PersonaSyncResult(
            plan.official_id,
            skipped=True,
            reason="group_skip_official",
        )
    ensured = False
    if plan.ensure_managed:
        ensured = await ensure_official_persona(
            persona_manager,
            plan.official_id,
            plan.prompt,
            cache=ensured_cache,
        )
    conversation_updated = await update_conversation_persona(
        conversation_manager, umo, plan.official_id
    )
    session_updated = await overwrite_session_persona(umo, plan.official_id, sp=sp)
    bind_request_conversation_persona(req, plan.official_id)
    return PersonaSyncResult(
        official_id=plan.official_id,
        ensured=ensured,
        conversation_updated=conversation_updated,
        session_updated=session_updated,
        reason=plan.reason,
    )
