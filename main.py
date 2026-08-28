"""AstrBot plugin: switch LLM provider by scene or user request."""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parent
_plugin_dir = str(_PLUGIN_DIR)
if sys.path[:1] != [_plugin_dir]:
    if _plugin_dir in sys.path:
        sys.path.remove(_plugin_dir)
    sys.path.insert(0, _plugin_dir)
for _mod in list(sys.modules):
    if _mod == "scene_switch" or _mod.startswith("scene_switch."):
        sys.modules.pop(_mod, None)

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.provider import ProviderRequest
import astrbot.api.message_components as Comp

from scene_switch.astrbot_persona import (
    bind_request_conversation_persona,
    persona_exists,
    plan_official_persona,
    should_write_official_slots,
    sync_official_persona,
)
from scene_switch.display import compact_label, confirm_switch, reply_prefix
from scene_switch.matcher import (
    find_named_scene_ids,
    has_explicit_switch_intent,
    is_capability_request,
    is_help_intent,
    match_force,
    mentions_blocked_persona,
)
from scene_switch.flood import (
    CUTOFF_LOCKED_TEXT,
    CUTOFF_TEXT,
    build_deepseek_verdict_messages,
    build_qwen_grab_messages,
    looks_like_flood_complaint,
    matched_flood_phrases,
    parse_deepseek_verdict,
    parse_qwen_grab,
    pin_flood_provider,
    pin_verifier_provider,
    should_local_escalate,
)
from scene_switch.flood_state import FloodStore, LONG_MUTE_SECONDS, flood_path_from_plugin_data
from scene_switch.helptext import build_feature_intro
from scene_switch.judge import (
    INTERNAL_MARK,
    JudgeVerdict,
    build_judge_messages,
    fallback_from_heuristic,
    parse_judge_reply,
)
from scene_switch.persona import apply_persona, default_persona_prompt, persona_from_astrbot
from scene_switch.router import RouteDecision, RouteInput, SceneRouter
from scene_switch.settings import PluginSettings, settings_from_dict
from scene_switch.silence import (
    ACK_SLAP,
    DEFAULT_SECONDS,
    SilenceStore,
    is_slap_command,
    is_speak_command,
    silence_path_from_plugin_data,
)
from scene_switch.caption import should_caption
from scene_switch.queue import WAIT_TEXT, MentionQueue
from scene_switch.sanitize import chain_has_at, strip_model_mentions
from scene_switch.state import SessionStore
from scene_switch.think import inject_reasoning_effort, normalize_effort


@register(
    "astrbot_plugin_scene_switch",
    "le",
    "按对话场景或用户点名，审核同意后切换本轮 LLM Provider 和人设",
    "1.15.0",
)
class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self._raw_config = config if config is not None else {}
        self.store = SessionStore()
        self.silence = SilenceStore(_PLUGIN_DIR / ".data" / "silence.json")
        self.router = SceneRouter(settings_from_dict(dict(self._raw_config)), self.store)
        self.mentions = MentionQueue()
        self.flood = FloodStore(_PLUGIN_DIR / ".data" / "flood.json")
        self._classifying_umos: set[str] = set()
        self._ensured_personas: dict[str, str] = {}

    def _resolve_state_path(self) -> Path:
        try:
            from astrbot.api.star import StarTools

            getter = getattr(StarTools, "get_data_dir", None)
            if getter:
                try:
                    data_dir = Path(getter())
                except TypeError:
                    data_dir = Path(getter("astrbot_plugin_scene_switch"))
                data_dir.mkdir(parents=True, exist_ok=True)
                return data_dir / "session_state.json"
        except Exception:
            logger.debug("StarTools.get_data_dir unavailable, fallback to plugin .data", exc_info=True)
        fallback = _PLUGIN_DIR / ".data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback / "session_state.json"

    async def initialize(self) -> None:
        self._reload_settings()
        path = self._resolve_state_path()
        self.store.persist_path = path
        self.silence = SilenceStore(silence_path_from_plugin_data(path.parent))
        self.flood = FloodStore(flood_path_from_plugin_data(path.parent))
        loaded = self.store.load()
        logger.info(
            "场景模型切换插件已加载，scenes=%s state=%s restored=%s",
            list(self.router.settings.scenes),
            path,
            loaded,
        )

    def _reload_settings(self) -> PluginSettings:
        settings = settings_from_dict(dict(self._raw_config))
        self.router.reload(settings)
        return settings

    @property
    def settings(self) -> PluginSettings:
        return self.router.settings

    def _provider_ids(self) -> tuple[str, ...]:
        try:
            providers = self.context.get_all_providers()
        except Exception:
            logger.exception("failed to list providers")
            return ()
        ids: list[str] = []
        for provider in providers or []:
            try:
                ids.append(provider.meta().id)
            except Exception:
                continue
        return tuple(ids)

    def _sender_id(self, event: AstrMessageEvent) -> str:
        if hasattr(event, "get_sender_id"):
            try:
                value = event.get_sender_id()
                if value:
                    return str(value)
            except Exception:
                pass
        sender = getattr(event.message_obj, "sender", None)
        for attr in ("user_id", "id", "nickname"):
            value = getattr(sender, attr, None)
            if value:
                return str(value)
        return "-"

    def _is_group(self, event: AstrMessageEvent) -> bool:
        return bool(getattr(event.message_obj, "group_id", ""))

    def _has_media(self, event: AstrMessageEvent) -> bool:
        chain = getattr(event.message_obj, "message", None) or []
        return any(isinstance(item, (Comp.Image, Comp.File, Comp.Video, Comp.Record)) for item in chain)

    def _is_at_self(self, event: AstrMessageEvent) -> bool:
        try:
            self_id = str(event.get_self_id() or "").strip()
        except Exception:
            self_id = ""
        if not self_id:
            return False
        chain = getattr(event.message_obj, "message", None) or []
        for item in chain:
            if not isinstance(item, Comp.At):
                continue
            qq = str(getattr(item, "qq", "") or getattr(item, "target", "") or "").strip()
            if qq and qq == self_id:
                return True
        text = event.message_str or ""
        return f"[CQ:at,qq={self_id}]" in text

    def _is_reply_to_self(self, event: AstrMessageEvent) -> bool:
        try:
            self_id = str(event.get_self_id() or "").strip()
        except Exception:
            self_id = ""
        if not self_id:
            return False
        chain = getattr(event.message_obj, "message", None) or []
        for item in chain:
            if not isinstance(item, Comp.Reply):
                continue
            sender_id = str(
                getattr(item, "sender_id", "") or getattr(item, "qq", "") or ""
            ).strip()
            if sender_id and sender_id == self_id:
                return True
        return False

    def _is_mentioned(self, event: AstrMessageEvent) -> bool:
        if not self._is_group(event):
            return True
        return self._is_at_self(event) or self._is_reply_to_self(event)

    def _want_caption(self, event: AstrMessageEvent) -> bool:
        text = event.message_str or ""
        key = SessionStore.make_key(event.unified_msg_origin, self._sender_id(event))
        sticky = self.store.get_sticky(key)
        named = find_named_scene_ids(text, self.settings)
        return should_caption(
            mentioned=self._is_mentioned(event),
            text=text,
            sticky_scene_id=sticky.scene_id if sticky else None,
            named_scene_ids=named,
        )

    def _is_blocked_sender(self, event: AstrMessageEvent) -> bool:
        return self.settings.is_blocked_sender(self._sender_id(event))

    def _reply_committed(self, event: AstrMessageEvent) -> bool:
        return bool(
            event.get_extra("_group_chat_plus_request")
            or event.get_extra("scene_switch_allow_judge")
        )

    def _allow_switch_command(self, event: AstrMessageEvent) -> bool:
        if not self.settings.switch_require_admin:
            return True
        try:
            return bool(event.is_admin())
        except Exception:
            return False

    def _build_input(self, event: AstrMessageEvent) -> RouteInput:
        selected = event.get_extra("selected_provider")
        if selected is not None:
            selected = str(selected)
        return RouteInput(
            text=event.message_str or "",
            umo=event.unified_msg_origin,
            sender_id=self._sender_id(event),
            is_group=self._is_group(event),
            has_media=self._has_media(event),
            selected_provider=selected,
            available_providers=self._provider_ids(),
            mentioned=self._is_mentioned(event),
            is_admin=self._allow_switch_command(event) if self.settings.switch_require_admin else True,
            reply_committed=self._reply_committed(event),
        )

    def _log_decision(self, decision: RouteDecision) -> None:
        if not self.settings.log_decisions:
            return
        logger.info(
            "scene_switch applied=%s scene=%s provider=%s source=%s reason=%s changed=%s persona=%s",
            decision.applied,
            decision.scene_id,
            decision.provider_id,
            decision.source,
            decision.reason,
            decision.scene_changed,
            decision.persona_label,
        )

    def _store_decision(self, event: AstrMessageEvent, decision: RouteDecision) -> None:
        event.set_extra(
            "scene_switch_decision",
            {
                "applied": decision.applied,
                "scene_id": decision.scene_id,
                "provider_id": decision.provider_id,
                "source": decision.source,
                "reason": decision.reason,
                "announce": decision.announce,
                "cleaned_prompt": decision.cleaned_prompt,
                "reasoning_effort": decision.reasoning_effort,
                "persona_id": decision.persona_id,
                "persona_prompt": decision.persona_prompt,
                "persona_label": decision.persona_label,
                "scene_changed": decision.scene_changed,
                "previous_scene_id": decision.previous_scene_id,
                "official_persona_id": None,
            },
        )
        if decision.applied and decision.provider_id:
            event.set_extra("selected_provider", decision.provider_id)
        if decision.cleaned_prompt is not None:
            event.set_extra("scene_switch_cleaned_prompt", decision.cleaned_prompt)

    def _label(
        self,
        scene_id: str | None,
        provider_id: str | None,
        effort: str | None = None,
        persona_label: str | None = None,
        *,
        verbose: bool = False,
    ) -> str:
        scene = self.settings.scene(scene_id) if scene_id else None
        if persona_label is None and scene and self.settings.switch_persona:
            if scene.persona_prompt or scene.persona_id:
                persona_label = scene.persona_label or None
        return compact_label(
            self.settings,
            scene_id,
            persona_label=persona_label,
            provider_id=provider_id,
            effort=effort,
            verbose=verbose,
        )

    async def _persona_from_astrbot(self, persona_id: str) -> str:
        mgr = getattr(self.context, "persona_manager", None)
        if mgr is None or not persona_id:
            return ""
        for name in ("get_persona_v3_by_id", "get_v3_persona", "get_persona"):
            fn = getattr(mgr, name, None)
            if not callable(fn):
                continue
            try:
                obj = fn(persona_id)
                if inspect.isawaitable(obj):
                    obj = await obj
                text = persona_from_astrbot(obj)
                if text:
                    return text
            except Exception:
                logger.debug("scene_switch persona lookup %s failed", name, exc_info=True)
        try:
            personas = getattr(mgr, "personas_v3", None) or getattr(mgr, "personas", None)
            if callable(personas):
                personas = personas()
                if inspect.isawaitable(personas):
                    personas = await personas
            if isinstance(personas, dict):
                text = persona_from_astrbot(personas.get(persona_id))
                if text:
                    return text
            if isinstance(personas, list):
                for item in personas:
                    ident = (
                        getattr(item, "name", None)
                        or getattr(item, "persona_id", None)
                        or getattr(item, "id", None)
                    )
                    if ident is None and isinstance(item, dict):
                        ident = item.get("name") or item.get("id") or item.get("persona_id")
                    if str(ident or "") == persona_id:
                        return persona_from_astrbot(item)
        except Exception:
            logger.debug("scene_switch persona list lookup failed", exc_info=True)
        return ""

    async def _sync_official_persona(
        self,
        umo: str,
        *,
        scene_id: str | None,
        persona_id: str | None,
        persona_prompt: str | None,
        persona_label: str | None,
        req: ProviderRequest | None = None,
        is_group: bool = False,
    ) -> str | None:
        if not self.settings.switch_persona or not self.settings.sync_official_persona:
            return None
        ident = str(persona_id or "").strip()
        prompt = str(persona_prompt or "").strip()
        manager = getattr(self.context, "persona_manager", None)
        exists = False
        if ident:
            looked = await self._persona_from_astrbot(ident)
            if looked and not prompt:
                prompt = looked
            exists = bool(looked) or await persona_exists(manager, ident)
        plan = plan_official_persona(
            scene_id=scene_id,
            persona_id=ident or None,
            persona_prompt=prompt or None,
            persona_label=persona_label,
            persona_exists=exists,
            switch_persona=self.settings.switch_persona,
            sync_official=self.settings.sync_official_persona,
        )
        if plan.skip:
            return None
        write_slots = should_write_official_slots(
            is_group=is_group,
            sync_in_groups=self.settings.sync_official_persona_in_groups,
        )
        try:
            result = await sync_official_persona(
                umo=umo,
                plan=plan,
                persona_manager=manager,
                conversation_manager=getattr(self.context, "conversation_manager", None),
                req=req,
                ensured_cache=self._ensured_personas,
                write_slots=write_slots,
            )
        except Exception:
            logger.exception("scene_switch failed to sync official persona")
            if write_slots and req is not None and plan.official_id:
                bind_request_conversation_persona(req, plan.official_id)
            if not write_slots:
                return None
            return plan.official_id or None
        if result.skipped or not result.official_id:
            return None
        if self.settings.log_decisions:
            logger.info(
                "scene_switch official persona id=%s ensured=%s conversation=%s session=%s reason=%s",
                result.official_id,
                result.ensured,
                result.conversation_updated,
                result.session_updated,
                result.reason,
            )
        return result.official_id

    async def _sync_decision_persona(
        self,
        event: AstrMessageEvent,
        decision: RouteDecision,
        req: ProviderRequest | None = None,
    ) -> str | None:
        if not decision.applied:
            return None
        official_id = await self._sync_official_persona(
            event.unified_msg_origin,
            scene_id=decision.scene_id,
            persona_id=decision.persona_id,
            persona_prompt=decision.persona_prompt,
            persona_label=decision.persona_label,
            req=req,
            is_group=self._is_group(event),
        )
        payload = event.get_extra("scene_switch_decision")
        if official_id and isinstance(payload, dict):
            payload["official_persona_id"] = official_id
        return official_id

    async def _inject_persona(self, req: ProviderRequest, payload: dict) -> None:
        if not self.settings.switch_persona:
            return
        prompt = str(payload.get("persona_prompt") or "").strip()
        persona_id = str(payload.get("persona_id") or "").strip()
        scene_id = payload.get("scene_id")
        if not prompt and persona_id:
            prompt = await self._persona_from_astrbot(persona_id)
            if not prompt:
                prompt = default_persona_prompt(scene_id)
        if not prompt:
            return
        try:
            req.system_prompt = apply_persona(
                getattr(req, "system_prompt", None),
                prompt,
                scene_id=scene_id,
                label=payload.get("persona_label"),
                mode=self.settings.persona_mode,
                switched_from=payload.get("previous_scene_id")
                if payload.get("scene_changed")
                else None,
            )
        except Exception:
            logger.debug("scene_switch failed to inject persona", exc_info=True)

    def _classifying_token(self, umo: str | None) -> str:
        return str(umo or "").strip() or "-"

    def _is_classifying(self, event: AstrMessageEvent) -> bool:
        return self._classifying_token(event.unified_msg_origin) in self._classifying_umos

    async def _judge(self, text: str, last_scene: str | None, umo: str) -> JudgeVerdict:
        provider_id = self.settings.classifier_provider_id
        scene_ids = {scene.id for scene in self.settings.enabled_scenes()}
        if not provider_id or not scene_ids:
            return JudgeVerdict("keep", None, "judge not configured")
        named_ids = find_named_scene_ids(text, self.settings)
        named = next((item for item in named_ids if not self.settings.is_default_scene(item)), None)
        system, prompt = build_judge_messages(
            self.settings,
            text,
            last_scene,
            named_scene=named,
        )
        token = self._classifying_token(umo)
        timeout = max(1, int(self.settings.classifier_timeout_seconds or 12))
        self._classifying_umos.add(token)
        try:
            try:
                raw = await asyncio.wait_for(
                    self._llm_text(
                        provider_id,
                        prompt,
                        system,
                        reasoning_effort=self.settings.classifier_reasoning_effort or None,
                    ),
                    timeout=timeout,
                )
                verdict = parse_judge_reply(raw, scene_ids)
            except TimeoutError:
                logger.warning(
                    "scene_switch judge timed out after %ss, falling back to heuristic",
                    timeout,
                )
                return fallback_from_heuristic(text, scene_ids, "judge timeout")
            except Exception:
                logger.exception("scene_switch judge failed")
                return fallback_from_heuristic(text, scene_ids, "judge call failed")
            if self.settings.log_decisions:
                logger.info(
                    "scene_switch judge action=%s scene=%s reason=%s raw=%s",
                    verdict.action,
                    verdict.scene_id,
                    verdict.reason,
                    (verdict.raw or "")[:200],
                )
            return verdict
        finally:
            self._classifying_umos.discard(token)

    async def _llm_text(
        self,
        provider_id: str,
        prompt: str,
        system: str,
        reasoning_effort: str | None = None,
        max_tokens: int = 80,
    ) -> str:
        extra: dict = {}
        effort = normalize_effort(reasoning_effort)
        if effort:
            extra["reasoning_effort"] = effort
            extra["max_tokens"] = max_tokens
            extra["temperature"] = 0
        try:
            resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=system,
                **extra,
            )
        except TypeError:
            try:
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=system,
                )
            except TypeError:
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=f"{system}\n\n{prompt}",
                )
        return (getattr(resp, "completion_text", None) or "").strip()

    def _is_self_message(self, event: AstrMessageEvent) -> bool:
        try:
            return str(event.get_sender_id()) == str(event.get_self_id())
        except Exception:
            return False

    def _is_flood_admin(self, event: AstrMessageEvent) -> bool:
        return self._sender_id(event) in set(self.settings.flood_admin_ids)

    def _apply_silence_gate(self, event: AstrMessageEvent) -> str | None:
        """Return 'stop', 'ack', or None. 'ack' means send ACK_SLAP then stop."""
        if self._is_self_message(event):
            return None
        if self._is_blocked_sender(event):
            logger.info("scene_switch drop blocked sender id=%s", self._sender_id(event))
            self._block_default_llm(event)
            return "stop"
        umo = event.unified_msg_origin
        text = event.message_str or ""
        if is_speak_command(text):
            if self.flood.is_locked(umo) and not self._is_flood_admin(event):
                logger.info(
                    "scene_switch locked, ignore unmute sender=%s umo=%s",
                    self._sender_id(event),
                    umo,
                )
                self._block_default_llm(event)
                return "stop"
            self.silence.unmute(umo)
            self.flood.unlock(umo)
            logger.info("scene_switch unmute umo=%s", umo)
            return None
        if self.silence.is_silenced(umo):
            logger.info("scene_switch silenced, drop umo=%s", umo)
            self._block_default_llm(event)
            return "stop"
        if is_slap_command(text):
            self.silence.slap(umo, seconds=DEFAULT_SECONDS)
            logger.info("scene_switch slap umo=%s", umo)
            self._block_default_llm(event)
            return "ack"
        return None

    def _should_intercept_switch(self, event: AstrMessageEvent, inp: RouteInput) -> bool:
        key = SessionStore.make_key(inp.umo, inp.sender_id)
        if self.store.get_pending(key):
            return True
        text = inp.text or ""
        if mentions_blocked_persona(text, self.settings.blocked_personas):
            return True
        named_ids = find_named_scene_ids(text, self.settings)
        named_other = tuple(
            item for item in named_ids if not self.settings.is_default_scene(item)
        )
        awake = (not inp.is_group) or inp.mentioned
        explicit = has_explicit_switch_intent(text)
        if named_other and awake and explicit:
            return True
        force = match_force(text, self.settings, extra_names=inp.available_providers)
        if (
            awake
            and force
            and force.had_verb
            and force.scene_id
            and not self.settings.is_default_scene(force.scene_id)
        ):
            return True
        if awake and is_help_intent(text):
            return True
        if awake and is_capability_request(text):
            return True
        return False

    async def _route_event(self, event: AstrMessageEvent) -> RouteDecision | None:
        self._reload_settings()
        if not self.settings.enabled:
            return None
        inp = self._build_input(event)
        decision = self.router.decide(inp)
        if decision.needs_judge:
            key = SessionStore.make_key(inp.umo, inp.sender_id)
            verdict = await self._judge(inp.text, self.store.last_scene(key), inp.umo)
            if verdict.action == "help":
                hint = "help"
            elif verdict.action == "route" and verdict.scene_id:
                hint = verdict.scene_id
            else:
                hint = "keep"
            decision = self.router.decide(inp, judge_hint=hint)
        self._log_decision(decision)
        return decision

    async def _apply_routed_decision(
        self, event: AstrMessageEvent, decision: RouteDecision
    ) -> None:
        self._store_decision(event, decision)
        await self._sync_decision_persona(event, decision)

    @staticmethod
    def _block_default_llm(event: AstrMessageEvent) -> None:
        try:
            event.should_call_llm(True)
        except Exception:
            event.call_llm = True

    @filter.event_message_type(
        filter.EventMessageType.ALL,
        priority=sys.maxsize,
    )
    async def silence_gate(self, event: AstrMessageEvent):
        action = self._apply_silence_gate(event)
        if action == "ack":
            yield event.plain_result(ACK_SLAP)
            event.stop_event()
            return
        if action == "stop":
            event.stop_event()

    @filter.event_message_type(
        filter.EventMessageType.ALL,
        priority=sys.maxsize - 1,
    )
    async def flood_audit_gate(self, event: AstrMessageEvent):
        if self._is_classifying(event) or event.get_extra("scene_switch_bypass"):
            return
        if self._is_self_message(event) or self._is_blocked_sender(event):
            return
        if not self._is_group(event):
            return
        self._reload_settings()
        if not self.settings.flood_audit_enabled:
            return
        text = event.message_str or ""
        umo = event.unified_msg_origin
        self.flood.remember_line(
            umo, self._sender_id(event), text, is_bot=False
        )
        if self.silence.is_silenced(umo):
            return
        if is_speak_command(text) or is_slap_command(text):
            return
        mentioned = self._is_mentioned(event)
        names = self.settings.flood_bot_names
        if not looks_like_flood_complaint(
            text,
            mentioned=mentioned,
            bot_names=names,
            strong=self.settings.flood_strong_phrases,
            weak=self.settings.flood_weak_phrases,
        ):
            return
        if self.flood.recently_audited(umo, 45):
            return
        self.flood.mark_audit(umo)
        try:
            bot_id = str(event.get_self_id() or "").strip()
        except Exception:
            bot_id = ""
        captured = self.flood.format_capture(umo, limit=20)
        hits = matched_flood_phrases(
            text,
            strong=self.settings.flood_strong_phrases,
            weak=self.settings.flood_weak_phrases,
        )
        qwen_id = pin_flood_provider(
            self.settings.flood_provider_id or self.settings.classifier_provider_id
        )
        if not qwen_id:
            logger.info("scene_switch flood L1 unbound, skip umo=%s", umo)
            return
        qwen_sys, qwen_prompt = build_qwen_grab_messages(
            text=text,
            bot_id=bot_id,
            bot_names=names,
            mentioned=mentioned,
            captured=captured,
            hits=hits,
        )
        qwen_raw = await self._flood_llm(umo, qwen_id, qwen_prompt, qwen_sys, 280)
        escalate = False
        about = False
        complaint = False
        qwen_reason = ""
        if qwen_raw is None:
            if should_local_escalate(text, names, mentioned):
                escalate = True
                qwen_reason = "l1 unavailable, pending deepseek"
                qwen_raw = (
                    '{"escalate":true,"about_this_bot":true,'
                    '"flood_complaint":true,"reason":"l1 unavailable, pending deepseek"}'
                )
                logger.info(
                    "scene_switch flood L1 qwen failed, still send DeepSeek umo=%s",
                    umo,
                )
            else:
                return
        else:
            escalate, about, complaint, qwen_reason = parse_qwen_grab(qwen_raw)
        logger.info(
            "scene_switch flood L1 escalate=%s about=%s complaint=%s reason=%s provider=%s raw=%s",
            escalate,
            about,
            complaint,
            qwen_reason,
            qwen_id,
            (qwen_raw or "")[:200],
        )
        if not escalate:
            return
        window = self.settings.flood_spoke_window_seconds
        bot_spoke = self.flood.bot_spoke_within(umo, window)
        verifier_id = pin_verifier_provider(self.settings.flood_verifier_provider_id)
        if not verifier_id:
            logger.info(
                "scene_switch flood L2 unbound, refuse mute umo=%s",
                umo,
            )
            return
        ds_sys, ds_prompt = build_deepseek_verdict_messages(
            text=text,
            bot_id=bot_id,
            bot_names=names,
            mentioned=mentioned,
            captured=captured,
            qwen_raw=qwen_raw,
            bot_spoke=bot_spoke,
            spoke_window_seconds=window,
        )
        ds_raw = await self._flood_llm(umo, verifier_id, ds_prompt, ds_sys, 160)
        if ds_raw is None:
            logger.info(
                "scene_switch flood L2 missing, refuse mute provider=%s umo=%s",
                verifier_id,
                umo,
            )
            return
        mute, ds_reason = parse_deepseek_verdict(ds_raw)
        logger.info(
            "scene_switch flood L2 mute=%s reason=%s provider=%s raw=%s",
            mute,
            ds_reason,
            verifier_id,
            (ds_raw or "")[:200],
        )
        if not mute:
            return
        if not bot_spoke:
            logger.info(
                "scene_switch flood L2 mute ignored, bot silent last %ss umo=%s",
                window,
                umo,
            )
            return
        count = self.flood.add_strike(
            umo, window_seconds=self.settings.flood_strike_window_seconds
        )
        locked = count >= self.settings.flood_strikes_for_lock
        if locked:
            self.flood.lock(umo)
            self.silence.slap(umo, seconds=LONG_MUTE_SECONDS)
            notice = CUTOFF_LOCKED_TEXT
        else:
            self.silence.slap(umo, seconds=self.settings.flood_short_seconds)
            notice = CUTOFF_TEXT
        logger.info(
            "scene_switch flood mute count=%s locked=%s umo=%s",
            count,
            locked,
            umo,
        )
        self._block_default_llm(event)
        yield event.plain_result(notice)
        event.stop_event()

    async def _flood_llm(
        self,
        umo: str,
        provider_id: str,
        prompt: str,
        system: str,
        max_tokens: int,
    ) -> str | None:
        token = self._classifying_token(umo)
        timeout = max(18, int(self.settings.classifier_timeout_seconds or 12))
        self._classifying_umos.add(token)
        try:
            return await asyncio.wait_for(
                self._llm_text(
                    provider_id,
                    prompt,
                    system,
                    reasoning_effort="none",
                    max_tokens=max_tokens,
                ),
                timeout=timeout,
            )
        except Exception:
            logger.exception("scene_switch flood llm failed provider=%s", provider_id)
            return None
        finally:
            self._classifying_umos.discard(token)

    @filter.event_message_type(
        filter.EventMessageType.ALL,
        priority=sys.maxsize - 2,
    )
    async def mention_queue_gate(self, event: AstrMessageEvent):
        if self._is_self_message(event) or self._is_blocked_sender(event):
            return
        self._reload_settings()
        event.set_extra("scene_switch_caption", self._want_caption(event))
        if not self._is_group(event) or not self._is_mentioned(event):
            return
        ticket = self.mentions.submit(
            event.unified_msg_origin, self._sender_id(event)
        )
        if ticket.notice:
            try:
                await event.send(event.plain_result(ticket.notice))
            except Exception:
                logger.exception("scene_switch wait notice failed")
        await ticket.wait()

    @filter.event_message_type(
        filter.EventMessageType.ALL,
        priority=sys.maxsize - 3,
    )
    async def switch_intent_gate(self, event: AstrMessageEvent):
        if self._is_classifying(event) or event.get_extra("scene_switch_bypass"):
            return
        action = self._apply_silence_gate(event)
        if action in {"ack", "stop"}:
            return
        if self._is_blocked_sender(event):
            return
        self._reload_settings()
        if not self.settings.enabled:
            return
        inp = self._build_input(event)
        if not self._should_intercept_switch(event, inp):
            return
        decision = await self._route_event(event)
        if decision is None:
            return
        if decision.help_requested:
            event.set_extra("scene_switch_handled", True)
            self._block_default_llm(event)
            yield event.plain_result(self._format_help(event))
            event.stop_event()
            return
        if decision.needs_consent and decision.consent_prompt:
            event.set_extra("scene_switch_handled", True)
            self._block_default_llm(event)
            yield event.plain_result(decision.consent_prompt)
            event.stop_event()
            return
        if (
            decision.source == "think"
            and decision.consent_prompt
            and not decision.reasoning_effort
        ):
            event.set_extra("scene_switch_handled", True)
            self._block_default_llm(event)
            yield event.plain_result(decision.consent_prompt)
            event.stop_event()
            return
        if (
            decision.source in {"blocked", "admin_required", "cooldown"}
            and decision.consent_prompt
        ):
            event.set_extra("scene_switch_handled", True)
            self._block_default_llm(event)
            yield event.plain_result(decision.consent_prompt)
            if decision.stop_for_switch_only:
                event.stop_event()
            return
        if (
            decision.source == "consent_denied"
            and decision.consent_prompt
            and not decision.applied
        ):
            event.set_extra("scene_switch_handled", True)
            self._block_default_llm(event)
            yield event.plain_result(decision.consent_prompt)
            event.stop_event()
            return
        if (
            decision.applied
            and decision.source == "consent"
            and decision.cleaned_prompt
        ):
            await self._apply_routed_decision(event, decision)
            event.set_extra("scene_switch_handled", True)
            self._block_default_llm(event)
            yield event.request_llm(
                prompt=decision.cleaned_prompt,
                session_id=event.session_id,
            )
            event.stop_event()
            return
        if decision.stop_for_switch_only:
            await self._apply_routed_decision(event, decision)
            event.set_extra("scene_switch_handled", True)
            self._block_default_llm(event)
            yield event.plain_result(confirm_switch(self.settings, decision))
            event.stop_event()

    @filter.on_waiting_llm_request()
    async def on_waiting_llm_request(self, event: AstrMessageEvent) -> None:
        if self._is_classifying(event) or event.get_extra("scene_switch_bypass"):
            return
        if event.get_extra("scene_switch_handled"):
            return
        if self._is_blocked_sender(event):
            self._block_default_llm(event)
            event.stop_event()
            return
        action = self._apply_silence_gate(event)
        if action == "ack":
            await event.send(event.plain_result(ACK_SLAP))
            event.stop_event()
            return
        if action == "stop":
            event.stop_event()
            return
        decision = await self._route_event(event)
        if decision is None:
            return
        if decision.help_requested:
            await event.send(event.plain_result(self._format_help(event)))
            event.stop_event()
            return

        if decision.needs_consent and decision.consent_prompt:
            await event.send(event.plain_result(decision.consent_prompt))
            event.stop_event()
            return
        if (
            decision.source == "think"
            and decision.consent_prompt
            and not decision.reasoning_effort
        ):
            await event.send(event.plain_result(decision.consent_prompt))
            event.stop_event()
            return

        if decision.source in {"blocked", "admin_required", "cooldown"} and decision.consent_prompt:
            await event.send(event.plain_result(decision.consent_prompt))
            if decision.stop_for_switch_only:
                event.stop_event()
                return

        if decision.source == "consent_denied" and decision.consent_prompt and not decision.applied:
            await event.send(event.plain_result(decision.consent_prompt))
            event.stop_event()
            return

        await self._apply_routed_decision(event, decision)

        if decision.stop_for_switch_only:
            await event.send(event.plain_result(confirm_switch(self.settings, decision)))
            event.stop_event()

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if self._is_classifying(event):
            return
        if self.silence.is_silenced(event.unified_msg_origin):
            event.stop_event()
            return
        prompt = req.prompt or ""
        if INTERNAL_MARK in prompt:
            return
        cleaned = event.get_extra("scene_switch_cleaned_prompt")
        if cleaned is not None:
            req.prompt = cleaned
        payload = event.get_extra("scene_switch_decision")
        if isinstance(payload, dict):
            session_key = SessionStore.make_key(
                event.unified_msg_origin, self._sender_id(event)
            )
            session_effort = self.store.get_think(session_key)
            if self.settings.override_reasoning_effort:
                inject_reasoning_effort(req, payload.get("reasoning_effort"))
            elif session_effort or payload.get("source") == "think":
                inject_reasoning_effort(
                    req, session_effort or payload.get("reasoning_effort")
                )
            if payload.get("applied"):
                official_id = payload.get("official_persona_id")
                if not official_id:
                    official_id = await self._sync_official_persona(
                        event.unified_msg_origin,
                        scene_id=payload.get("scene_id"),
                        persona_id=payload.get("persona_id"),
                        persona_prompt=payload.get("persona_prompt"),
                        persona_label=payload.get("persona_label"),
                        req=req,
                        is_group=self._is_group(event),
                    )
                    if official_id:
                        payload["official_persona_id"] = official_id
                elif official_id:
                    bind_request_conversation_persona(req, official_id)
                await self._inject_persona(req, payload)

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, _response) -> None:
        if self._is_classifying(event):
            return
        if self._is_group(event) and self._is_mentioned(event):
            self.mentions.finish(event.unified_msg_origin, self._sender_id(event))

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent) -> None:
        result = event.get_result()
        if result is not None and getattr(result, "chain", None):
            if self._is_group(event) and not self._is_classifying(event):
                self.flood.note_bot_speak(event.unified_msg_origin)
                spoken = " ".join(
                    str(getattr(item, "text", "") or "").strip()
                    for item in result.chain
                    if getattr(item, "text", None)
                ).strip()
                if spoken:
                    self.flood.remember_line(
                        event.unified_msg_origin,
                        str(event.get_self_id() or "BOT"),
                        spoken,
                        is_bot=True,
                    )
            has_at = chain_has_at(result.chain)
            for item in result.chain:
                text = getattr(item, "text", None)
                if isinstance(text, str) and text:
                    item.text = strip_model_mentions(text, has_at_component=has_at)
            if (
                self._is_group(event)
                and self._is_mentioned(event)
                and not self._is_classifying(event)
            ):
                texts = [
                    str(getattr(item, "text", "") or "").strip()
                    for item in result.chain
                    if getattr(item, "text", None)
                ]
                if texts != [WAIT_TEXT]:
                    self.mentions.finish(
                        event.unified_msg_origin, self._sender_id(event)
                    )
        payload = event.get_extra("scene_switch_decision")
        if not isinstance(payload, dict) or not payload.get("announce"):
            return
        if not payload.get("applied"):
            return
        if result is None or not getattr(result, "chain", None):
            return
        prefix = reply_prefix(
            payload.get("persona_label"),
            payload.get("scene_id"),
            self.settings,
        )
        first = result.chain[0]
        if isinstance(first, Comp.Plain) and (
            first.text.startswith(prefix) or first.text.startswith("〔")
        ):
            return
        result.chain.insert(0, Comp.Plain(prefix))

    @filter.after_message_sent()
    async def on_after_message_sent(self, event: AstrMessageEvent) -> None:
        if self._is_classifying(event) or not self._is_group(event):
            return
        result = event.get_result()
        if result is None or not getattr(result, "chain", None):
            return
        texts = [
            str(getattr(item, "text", "") or "").strip()
            for item in result.chain
            if getattr(item, "text", None)
        ]
        if texts == [WAIT_TEXT]:
            return
        self.flood.note_bot_speak(event.unified_msg_origin)

    @filter.command("scene", alias={"场景"})
    async def scene_cmd(self, event: AstrMessageEvent) -> None:
        """查看或切换对话场景模型。/scene [help|list|use|lock|auto|think]"""
        self._reload_settings()
        parts = (event.message_str or "").strip().split()
        if parts and parts[0].lstrip("/.!").lower() in {"scene", "场景"}:
            parts = parts[1:]
        action = parts[0].lower() if parts else "status"
        arg = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
        umo = event.unified_msg_origin
        sender = self._sender_id(event)

        if action in {"list", "ls"}:
            yield event.plain_result(self._format_list())
            return
        if action in {"help", "帮助", "功能", "intro"}:
            yield event.plain_result(self._format_help(event))
            return
        if action in {"use", "切", "用"}:
            if not self._allow_switch_command(event):
                yield event.plain_result("切换模型需要管理员权限。")
                return
            if not arg:
                yield event.plain_result("用法：/scene use <场景或别名>")
                return
            decision = self.router.use_now(umo, sender, arg)
            if not decision.applied:
                yield event.plain_result(f"无法解析「{arg}」。用 /scene list 查看可用场景。")
                return
            self._store_decision(event, decision)
            await self._sync_decision_persona(event, decision)
            yield event.plain_result(confirm_switch(self.settings, decision))
            return
        if action in {"lock", "锁定"}:
            if not self._allow_switch_command(event):
                yield event.plain_result("锁定模型需要管理员权限。")
                return
            if not arg:
                yield event.plain_result("用法：/scene lock <场景>")
                return
            scene_id, _ = self.settings.resolve_target(arg)
            decision = self.router.lock(umo, sender, scene_id or arg)
            if not decision.applied:
                yield event.plain_result(f"无法锁定「{arg}」。{decision.reason}")
                return
            self._store_decision(event, decision)
            await self._sync_decision_persona(event, decision)
            yield event.plain_result(
                f"已锁定{self._label(decision.scene_id, decision.provider_id, decision.reasoning_effort, decision.persona_label)}。"
                "本会话不再自动跳场景。发送 /scene auto 恢复。"
            )
            return
        if action in {"auto", "unlock", "解锁"}:
            if not self._allow_switch_command(event):
                yield event.plain_result("解锁需要管理员权限。")
                return
            self.router.unlock(umo, sender)
            yield event.plain_result("已恢复自动场景切换。")
            return
        if action in {"think", "思考"}:
            token = arg.strip().lower() or "status"
            key = SessionStore.make_key(umo, sender)
            if token in {"status", "当前"}:
                current = self.store.get_think(key)
                yield event.plain_result(
                    "当前会话思考强度："
                    + (current or "未设置（沿用各 Provider 自己的配置）")
                    + "。插件只写 reasoning_effort，不改请求头。"
                )
                return
            if token in {"auto", "default", "默认", "provider"}:
                self.store.clear_think(key)
                yield event.plain_result("已恢复各 Provider 自己的思考设置。")
                return
            effort = normalize_effort(token)
            if effort not in {"none", "low", "medium", "high", "max"}:
                yield event.plain_result(
                    "用法：/scene think none|low|medium|high|max|auto"
                    "；群里也可 @ 后发「开启思考 max」。"
                )
                return
            self.store.set_think(key, effort, self.settings.think_ttl_seconds)
            yield event.plain_result(
                f"已将本会话思考强度设为 {effort}。"
                "仅写入 AstrBot 的 reasoning_effort；各家 extra_body / 请求头请在 Provider 里配。"
            )
            return
        if action in {"status", "当前"}:
            yield event.plain_result(self._format_status(event))
            return
        if action and action not in {"help", "帮助", "功能", "intro"}:
            if not self._allow_switch_command(event):
                yield event.plain_result("切换模型需要管理员权限。")
                return
            token = " ".join(parts)
            decision = self.router.use_now(umo, sender, token)
            if decision.applied:
                self._store_decision(event, decision)
                await self._sync_decision_persona(event, decision)
                yield event.plain_result(confirm_switch(self.settings, decision))
                return
        yield event.plain_result(self._format_help(event))

    def _format_list(self) -> str:
        lines = ["可用场景："]
        for scene in self.settings.scenes.values():
            status = scene.provider_id or "（未配置 Provider，已禁用）"
            aliases = "、".join(scene.aliases[:6]) or "-"
            lines.append(f"- {scene.id} / {scene.display_name} → {status}")
            if self.settings.override_reasoning_effort:
                effort = scene.reasoning_effort or "provider"
            else:
                effort = "沿用 Provider"
            if scene.persona_prompt or scene.persona_id:
                persona = scene.persona_label or scene.persona_id or "场景人设"
            else:
                persona = "关闭"
            lines.append(f"  别名：{aliases}；思考：{effort}；人设：{persona}")
        if self.settings.model_aliases:
            pairs = "、".join(f"{k}={v}" for k, v in list(self.settings.model_aliases.items())[:12])
            lines.append(f"模型别名：{pairs}")
        providers = self._provider_ids()
        if providers:
            lines.append("已加载 Provider：" + "、".join(providers))
        else:
            lines.append("当前环境还没有读到 Provider 列表。请先在 WebUI 配置模型。")
        return "\n".join(lines)

    def _format_status(self, event: AstrMessageEvent) -> str:
        key = SessionStore.make_key(event.unified_msg_origin, self._sender_id(event))
        lock = self.store.get_lock(key)
        sticky = self.store.get_sticky(key)
        last = self.store.last_scene(key)
        lines = ["场景模型切换状态："]
        lines.append(f"- 插件：{'开启' if self.settings.enabled else '关闭'}")
        if self.settings.judge_available:
            lines.append(
                f"- 审判模型：已启用（{self.settings.classifier_provider_id} / "
                f"{self.settings.classifier_mode} / think "
                f"{self.settings.classifier_reasoning_effort or '沿用 Provider'} / "
                f"超时 {self.settings.classifier_timeout_seconds}s）"
            )
        else:
            lines.append(
                f"- 审判模型：未配置，当前用规则（模式 {self.settings.classifier_mode}）"
            )
        if lock:
            lines.append(f"- 锁定：{lock[0]} → {lock[1]}")
        else:
            lines.append("- 锁定：无（自动）")
        if sticky:
            lines.append(
                f"- 黏性：{sticky.scene_id} → {sticky.provider_id}（剩余 {sticky.rounds_left} 轮）"
            )
        else:
            lines.append("- 黏性：无")
        if self.settings.override_reasoning_effort:
            think = self.store.get_think(key)
            lines.append(f"- 思考强度：{think or '场景默认'}（插件覆盖已开）")
        else:
            lines.append("- 思考强度：沿用 AstrBot Provider（插件覆盖关闭）")
        if self.settings.switch_persona:
            if not self.settings.sync_official_persona:
                official = "，仅本轮提示词"
            elif self.settings.sync_official_persona_in_groups:
                official = "，同步官方人设（含群聊）"
            else:
                official = "，同步官方人设（仅私聊）"
            lines.append(f"- 场景人设：开启（{self.settings.persona_mode}{official}）")
        else:
            lines.append("- 场景人设：关闭")
        lines.append(f"- 最近场景：{last or '无'}")
        return "\n".join(lines)

    def _format_help(self, event: AstrMessageEvent) -> str:
        intro = build_feature_intro(
            self.settings,
            loaded_providers=self._provider_ids(),
            judge_ready=self.settings.judge_available,
        )
        return f"{intro}\n\n{self._format_status(event)}"
