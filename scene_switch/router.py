"""Decide which provider to use for the current message."""

from __future__ import annotations

from dataclasses import dataclass, replace
import time

from . import matcher
from .heuristic import guess_scene
from .persona import fields_for_scene
from .settings import PluginSettings
from .display import format_consent_prompt
from .state import ConsentPending, SessionStore
from .think import match_think, match_think_command, normalize_effort


@dataclass(frozen=True)
class RouteInput:
    text: str
    umo: str
    sender_id: str
    is_group: bool
    has_media: bool = False
    selected_provider: str | None = None
    available_providers: tuple[str, ...] = ()
    prompt_override: str | None = None
    mentioned: bool = False
    is_admin: bool = False
    reply_committed: bool = False


@dataclass(frozen=True)
class RouteDecision:
    applied: bool
    scene_id: str | None
    provider_id: str | None
    source: str
    reason: str
    cleaned_prompt: str | None = None
    needs_judge: bool = False
    announce: bool = False
    stop_for_switch_only: bool = False
    help_requested: bool = False
    reasoning_effort: str | None = None
    persona_id: str | None = None
    persona_prompt: str | None = None
    persona_label: str | None = None
    scene_changed: bool = False
    previous_scene_id: str | None = None
    needs_consent: bool = False
    consent_prompt: str | None = None

    def to_dict(self, *, include_prompt: bool = False) -> dict:
        payload = {
            "applied": self.applied,
            "scene": self.scene_id,
            "scene_id": self.scene_id,
            "provider": self.provider_id,
            "provider_id": self.provider_id,
            "source": self.source,
            "reason": self.reason,
            "cleaned_prompt": self.cleaned_prompt,
            "needs_judge": self.needs_judge,
            "announce": self.announce,
            "stop_for_switch_only": self.stop_for_switch_only,
            "help": self.help_requested,
            "help_requested": self.help_requested,
            "reasoning_effort": self.reasoning_effort,
            "persona_id": self.persona_id,
            "persona_label": self.persona_label,
            "scene_changed": self.scene_changed,
            "previous_scene_id": self.previous_scene_id,
            "needs_consent": self.needs_consent,
            "consent_prompt": self.consent_prompt,
        }
        if include_prompt:
            payload["persona_prompt"] = self.persona_prompt
        return payload

    @staticmethod
    def keep(reason: str, source: str = "keep") -> RouteDecision:
        return RouteDecision(
            applied=False,
            scene_id=None,
            provider_id=None,
            source=source,
            reason=reason,
        )


class SceneRouter:
    def __init__(self, settings: PluginSettings, store: SessionStore | None = None) -> None:
        self.settings = settings
        self.store = store or SessionStore()

    def reload(self, settings: PluginSettings) -> None:
        self.settings = settings

    def decide(
        self,
        inp: RouteInput,
        *,
        classifier_hint: str | None = None,
        now: float | None = None,
        judge_hint: str | None = None,
    ) -> RouteDecision:
        settings = self.settings
        if not settings.enabled:
            return RouteDecision.keep("plugin disabled")

        if inp.is_group and not settings.allow_group:
            return RouteDecision.keep("group routing disabled")
        if not inp.is_group and not settings.allow_private:
            return RouteDecision.keep("private routing disabled")
        if settings.is_blocked_sender(inp.sender_id):
            return RouteDecision.keep("blocked sender")

        text = inp.text or ""
        if settings.skip_command_like_messages and matcher.looks_like_command(
            text, settings.command_like_prefixes
        ):
            return RouteDecision.keep("command-like message skipped")

        if settings.session_think_commands:
            cmd = match_think_command(text)
            if cmd and ((not inp.is_group) or inp.mentioned):
                handled = self._apply_session_think(inp, cmd, now=now)
                if handled is not None:
                    return handled
                if cmd.leftover:
                    text = cmd.leftover
                    inp = replace(inp, text=text, prompt_override=cmd.leftover)

        if settings.honor_existing_selection and inp.selected_provider:
            return RouteDecision.keep(
                f"honor existing selected_provider={inp.selected_provider}",
                source="honor",
            )

        key = SessionStore.make_key(inp.umo, inp.sender_id)
        available = set(inp.available_providers)
        hint = (judge_hint if judge_hint is not None else classifier_hint) or None

        if settings.require_consent:
            return self._decide_consent(inp, hint=hint, now=now)

        think = match_think(text) if settings.override_reasoning_effort else None
        if think:
            if think.effort == "auto":
                self.store.clear_think(key)
            else:
                self.store.set_think(
                    key,
                    think.effort,
                    settings.think_ttl_seconds,
                    now=now,
                )
            if think.leftover:
                text = think.leftover
                inp = replace(inp, text=text, prompt_override=think.leftover)
            else:
                return self._think_only(inp, think.effort, now=now)

        lock = self.store.get_lock(key)
        if lock:
            scene_id, provider_id = lock
            return self._finish(
                inp,
                scene_id=scene_id,
                provider_id=provider_id,
                source="lock",
                reason=f"session locked to {scene_id}",
                cleaned_prompt=None,
            )

        force = matcher.match_force(text, settings, extra_names=inp.available_providers)
        if force and (force.scene_id or force.provider_id):
            scene_id, provider_id = self._resolve_choice(
                force.scene_id, force.provider_id, available
            )
            if provider_id:
                leftover = force.leftover
                return self._finish(
                    inp,
                    scene_id=scene_id or "named",
                    provider_id=provider_id,
                    source="force",
                    reason=f"user requested {force.token}",
                    cleaned_prompt=leftover,
                    stop_for_switch_only=not leftover.strip(),
                )

        sticky = self.store.get_sticky(key, now=now)
        opposite = None
        if sticky and settings.sticky_release_on_opposite:
            opposite = self._detect_scene(inp) or self._guess_opposite(inp, sticky.scene_id)
            if opposite and opposite != sticky.scene_id:
                self.store.clear_sticky(key)
                sticky = None

        if sticky:
            self.store.consume_sticky(key)
            return self._finish(
                inp,
                scene_id=sticky.scene_id,
                provider_id=sticky.provider_id,
                source="sticky",
                reason=f"sticky {sticky.scene_id}",
                cleaned_prompt=None,
            )

        if settings.follow_up_enabled and matcher.is_follow_up(
            text, settings.follow_up_keywords, settings.follow_up_max_chars
        ):
            last = self.store.last_scene(key)
            scene = settings.scene(last) if last else None
            if scene and scene.enabled:
                return self._finish(
                    inp,
                    scene_id=scene.id,
                    provider_id=scene.provider_id,
                    source="follow_up",
                    reason=f"follow-up keeps {scene.id}",
                    cleaned_prompt=None,
                )

        if matcher.is_help_intent(text):
            return self._help("user asked what this plugin can do")

        if opposite:
            scene = settings.scene(opposite)
            if scene and scene.enabled:
                return self._finish(
                    inp,
                    scene_id=scene.id,
                    provider_id=scene.provider_id,
                    source="rules",
                    reason=f"scene {scene.id}",
                    cleaned_prompt=None,
                )

        hard = self._detect_hard_scene(inp)
        if hard:
            scene = settings.scene(hard)
            if scene and scene.enabled:
                return self._finish(
                    inp,
                    scene_id=scene.id,
                    provider_id=scene.provider_id,
                    source="rules",
                    reason=f"hard signal {scene.id}",
                    cleaned_prompt=None,
                )

        hint_token = (hint or "").strip()
        if hint_token:
            routed = self._apply_judge_hint(inp, hint_token)
            if routed is not None:
                return routed

        if settings.judge_available and not hint_token:
            if settings.judge_before_keywords:
                return self._need_judge("natural language needs judge")
            keyword_scene = self._detect_keyword_scene(inp)
            if keyword_scene:
                scene = settings.scene(keyword_scene)
                if scene and scene.enabled:
                    return self._finish(
                        inp,
                        scene_id=scene.id,
                        provider_id=scene.provider_id,
                        source="rules",
                        reason=f"scene {scene.id}",
                        cleaned_prompt=None,
                    )
            return self._need_judge("rules uncertain, need judge")

        keyword_scene = self._detect_keyword_scene(inp)
        if keyword_scene:
            scene = settings.scene(keyword_scene)
            if scene and scene.enabled:
                return self._finish(
                    inp,
                    scene_id=scene.id,
                    provider_id=scene.provider_id,
                    source="rules",
                    reason=f"scene {scene.id}",
                    cleaned_prompt=None,
                )

        guessed = guess_scene(text, {scene.id for scene in settings.enabled_scenes()})
        if guessed == "help":
            return self._help("heuristic detected a help question")
        if guessed:
            scene = settings.scene(guessed)
            if scene and scene.enabled:
                return self._finish(
                    inp,
                    scene_id=scene.id,
                    provider_id=scene.provider_id,
                    source="heuristic",
                    reason=f"heuristic chose {scene.id}",
                    cleaned_prompt=None,
                )

        fallback = settings.uncertain_route
        if fallback and fallback != "keep_default":
            scene = settings.scene(fallback)
            if scene and scene.enabled:
                return self._finish(
                    inp,
                    scene_id=scene.id,
                    provider_id=scene.provider_id,
                    source="fallback",
                    reason=f"uncertain, fallback to {scene.id}",
                    cleaned_prompt=None,
                )

        return RouteDecision.keep("uncertain, keep default")

    def _decide_consent(
        self,
        inp: RouteInput,
        *,
        hint: str | None,
        now: float | None,
    ) -> RouteDecision:
        settings = self.settings
        text = inp.text or ""
        key = SessionStore.make_key(inp.umo, inp.sender_id)
        default = settings.default_scene()
        pending = self.store.get_pending(key, now=now)

        if pending:
            if matcher.is_consent_agree(text):
                self.store.clear_pending(key)
                self.store.set_cooldown(key, settings.switch_cooldown_seconds, now=now)
                return self._finish(
                    inp,
                    scene_id=pending.scene_id,
                    provider_id=pending.provider_id,
                    source="consent",
                    reason=pending.reason or "user agreed to switch",
                    cleaned_prompt=pending.original_text or None,
                )
            if matcher.is_consent_disagree(text):
                original = pending.original_text
                self.store.clear_pending(key)
                if default and default.enabled:
                    return self._finish(
                        inp,
                        scene_id=default.id,
                        provider_id=default.provider_id,
                        source="consent_denied",
                        reason="user declined switch",
                        cleaned_prompt=original or None,
                    )
                return RouteDecision(
                    applied=False,
                    scene_id=None,
                    provider_id=None,
                    source="consent_denied",
                    reason="user declined switch",
                    cleaned_prompt=original or None,
                    consent_prompt="好，还是用当前默认模型和人设。",
                )
            # Any other reply cancels the yes/no wait and continues.
            self.store.clear_pending(key)

        lock = self.store.get_lock(key)
        if lock:
            scene_id, provider_id = lock
            return self._finish(
                inp,
                scene_id=scene_id,
                provider_id=provider_id,
                source="lock",
                reason=f"session locked to {scene_id}",
                cleaned_prompt=None,
            )

        if matcher.mentions_blocked_persona(text, settings.blocked_personas):
            return RouteDecision(
                applied=False,
                scene_id=None,
                provider_id=None,
                source="blocked",
                reason="blocked persona",
                consent_prompt="这个人设不在可调用列表里。",
                stop_for_switch_only=True,
            )

        named_ids = matcher.find_named_scene_ids(text, settings)
        named_other = tuple(item for item in named_ids if not settings.is_default_scene(item))
        force = matcher.match_force(text, settings, extra_names=inp.available_providers)
        force_other = bool(
            force
            and force.had_verb
            and force.scene_id
            and not settings.is_default_scene(force.scene_id)
        )
        capability = matcher.is_capability_request(text)
        explicit = matcher.has_explicit_switch_intent(text) or force_other
        group_awake = (not inp.is_group) or inp.mentioned
        named_switch = bool(group_awake and named_other and explicit)
        capability_switch = bool(group_awake and capability and not named_switch)
        switch_intent = bool(named_switch or capability_switch)

        if switch_intent and settings.switch_require_admin and not inp.is_admin:
            return RouteDecision(
                applied=False,
                scene_id=None,
                provider_id=None,
                source="admin_required",
                reason="switch requires admin",
                consent_prompt="切换模型需要管理员权限。当前仍用默认场景。",
                stop_for_switch_only=True,
            )
        if switch_intent and self.store.in_cooldown(key, now=now):
            return self._stay_current(
                inp,
                now=now,
                reason="switch cooldown",
                source="cooldown",
                stop=not (text.strip() and len(text.strip()) > 8),
                prompt="刚刚切换过，先冷却一下。继续的话还是当前模型和人设。",
            )

        if hint:
            routed = self._apply_consent_hint(inp, hint, now=now)
            if routed is not None:
                return routed

        if switch_intent:
            target_id = (named_other[0] if named_other else None) or (
                force.scene_id if force else None
            )
            if named_switch and target_id:
                return self._propose_or_keep(inp, target_id, "named request", now=now)
            if settings.judge_available and not hint:
                return self._need_judge("consent mode needs judge")
            if target_id:
                return self._propose_or_keep(inp, target_id, "named request", now=now)
            guessed = matcher.match_keywords(text, settings)
            if guessed:
                return self._propose_or_keep(inp, guessed.scene_id, "capability request", now=now)
            return self._stay_current(inp, now=now, reason="switch intent but no target")

        if matcher.is_help_intent(text) and (not inp.is_group or inp.mentioned):
            return self._help("user asked which models can switch")

        return self._stay_current(inp, now=now, reason="consent default")

    def _stay_current(
        self,
        inp: RouteInput,
        *,
        now: float | None,
        reason: str,
        source: str = "fallback",
        stop: bool = False,
        prompt: str | None = None,
    ) -> RouteDecision:
        key = SessionStore.make_key(inp.umo, inp.sender_id)
        sticky = self.store.get_sticky(key, now=now)
        if sticky:
            self.store.consume_sticky(key)
            decision = self._finish(
                inp,
                scene_id=sticky.scene_id,
                provider_id=sticky.provider_id,
                source="sticky",
                reason=reason,
                cleaned_prompt=None,
            )
            if stop:
                return replace(
                    decision,
                    stop_for_switch_only=True,
                    consent_prompt=prompt,
                )
            return decision
        default = self.settings.default_scene()
        named_ids = matcher.find_named_scene_ids(inp.text or "", self.settings)
        named_default = any(self.settings.is_default_scene(item) for item in named_ids)
        wake = (not inp.is_group) or inp.mentioned or named_default
        if default and default.enabled and wake:
            decision = self._finish(
                inp,
                scene_id=default.id,
                provider_id=default.provider_id,
                source=source,
                reason=reason,
                cleaned_prompt=None,
            )
            if stop:
                return replace(
                    decision,
                    stop_for_switch_only=True,
                    consent_prompt=prompt,
                    applied=False if source in {"cooldown", "admin_required"} else decision.applied,
                )
            return decision
        return RouteDecision(
            applied=False,
            scene_id=None,
            provider_id=None,
            source=source,
            reason=reason,
            stop_for_switch_only=stop,
            consent_prompt=prompt,
        )

    def _apply_consent_hint(self, inp: RouteInput, hint: str, now: float | None) -> RouteDecision | None:
        token = hint.strip().lower()
        if token in {"help", "meta", "intro"}:
            return self._help("judge requested help")
        if token in {"keep", "keep_default", "default"}:
            return self._stay_current(inp, now=now, reason="judge keep")
        scene = self.settings.scene(hint.strip()) or self.settings.scene(token)
        if scene is None or not scene.enabled:
            return None
        if self.settings.is_default_scene(scene.id):
            return self._stay_current(inp, now=now, reason="judge chose default")
        return self._propose_or_keep(inp, scene.id, f"judge chose {scene.id}", now=now)

    def _propose_or_keep(
        self,
        inp: RouteInput,
        scene_id: str,
        reason: str,
        now: float | None,
    ) -> RouteDecision:
        settings = self.settings
        scene = settings.scene(scene_id)
        if scene is None or not scene.enabled:
            return self._stay_current(inp, now=now, reason=f"unknown target {scene_id}")
        key = SessionStore.make_key(inp.umo, inp.sender_id)
        sticky = self.store.get_sticky(key, now=now)
        if sticky and sticky.scene_id == scene.id:
            return self._stay_current(inp, now=now, reason="already on target")
        if settings.is_default_scene(scene.id):
            return self._stay_current(inp, now=now, reason="target is default")
        if self.store.last_prompt_recent(key, settings.prompt_cooldown_seconds, now=now):
            pending = self.store.get_pending(key, now=now)
            if pending:
                return RouteDecision(
                    applied=False,
                    scene_id=pending.scene_id,
                    provider_id=pending.provider_id,
                    source="consent",
                    reason="prompt cooldown",
                    needs_consent=True,
                    consent_prompt=None,
                    stop_for_switch_only=True,
                )
        current = time.time() if now is None else now
        pending = ConsentPending(
            scene_id=scene.id,
            provider_id=scene.provider_id,
            original_text=inp.text or "",
            reason=reason,
            persona_id=scene.persona_id,
            persona_label=scene.persona_label or scene.display_name,
            created_at=current,
            expires_at=current + settings.consent_ttl_seconds,
        )
        self.store.set_pending(key, pending)
        self.store.mark_prompt(key, now=now)
        return RouteDecision(
            applied=False,
            scene_id=scene.id,
            provider_id=scene.provider_id,
            source="consent",
            reason=reason,
            needs_consent=True,
            consent_prompt=format_consent_prompt(settings, scene.id, reason),
            stop_for_switch_only=True,
            persona_id=scene.persona_id or None,
            persona_label=scene.persona_label or scene.display_name,
        )

    def _apply_session_think(
        self,
        inp: RouteInput,
        cmd,
        now: float | None,
    ) -> RouteDecision | None:
        key = SessionStore.make_key(inp.umo, inp.sender_id)
        if cmd.effort == "":
            return RouteDecision(
                applied=False,
                scene_id=None,
                provider_id=None,
                source="think",
                reason="think command missing level",
                stop_for_switch_only=True,
                consent_prompt=(
                    "用法：开启思考 none|low|medium|high|max，例如「开启思考 max」。"
                    "关闭请说「关闭思考」。插件只写入 AstrBot 的 reasoning_effort，"
                    "不会改各家请求头或 extra_body。"
                ),
            )
        if cmd.effort == "auto":
            self.store.clear_think(key)
        else:
            self.store.set_think(
                key,
                cmd.effort,
                self.settings.think_ttl_seconds,
                now=now,
            )
        if cmd.leftover:
            return None
        return self._think_only(inp, cmd.effort, now=now)

    def _think_only(self, inp: RouteInput, effort: str, now: float | None = None) -> RouteDecision:
        key = SessionStore.make_key(inp.umo, inp.sender_id)
        last = self.store.last_scene(key)
        scene = self.settings.scene(last) if last else None
        if scene and scene.enabled:
            return self._finish(
                inp,
                scene_id=scene.id,
                provider_id=scene.provider_id,
                source="think",
                reason=f"think set to {effort or 'auto'}",
                cleaned_prompt=None,
                stop_for_switch_only=True,
                reasoning_effort=None if effort in {"", "auto"} else effort,
            )
        return RouteDecision(
            applied=False,
            scene_id=None,
            provider_id=None,
            source="think",
            reason=f"think set to {effort}",
            stop_for_switch_only=True,
            reasoning_effort=None if effort == "auto" else effort,
        )

    def _resolve_effort(self, key: str, scene_id: str | None, now: float | None = None) -> str | None:
        session_effort = self.store.get_think(key, now=now)
        if session_effort:
            return session_effort
        if not self.settings.override_reasoning_effort:
            return None
        scene = self.settings.scene(scene_id) if scene_id else None
        effort = normalize_effort(scene.reasoning_effort if scene else "")
        return effort or None

    def _help(self, reason: str) -> RouteDecision:
        return RouteDecision(
            applied=False,
            scene_id=None,
            provider_id=None,
            source="help",
            reason=reason,
            help_requested=True,
        )

    def _need_judge(self, reason: str) -> RouteDecision:
        return RouteDecision(
            applied=False,
            scene_id=None,
            provider_id=None,
            source="pending_judge",
            reason=reason,
            needs_judge=True,
        )

    def _apply_judge_hint(self, inp: RouteInput, hint: str) -> RouteDecision | None:
        token = hint.strip().lower()
        if token in {"help", "meta", "intro"}:
            return self._help("judge requested help")
        if token in {"keep", "keep_default", "default"}:
            return None
        scene = self.settings.scene(hint.strip()) or self.settings.scene(token)
        if scene and scene.enabled:
            return self._finish(
                inp,
                scene_id=scene.id,
                provider_id=scene.provider_id,
                source="judge",
                reason=f"judge chose {scene.id}",
                cleaned_prompt=None,
            )
        return None

    def _detect_hard_scene(self, inp: RouteInput) -> str | None:
        settings = self.settings
        text = inp.text or ""
        if inp.has_media and settings.route_media_to_vision:
            vision = settings.scene("vision")
            if vision and vision.enabled:
                return "vision"
        if matcher.has_code_signal(text):
            code = settings.scene("code")
            if code and code.enabled:
                return "code"
        if settings.route_links_to_search and matcher.has_link(text):
            search = settings.scene("search")
            if search and search.enabled:
                return "search"
        return None

    def _detect_keyword_scene(self, inp: RouteInput) -> str | None:
        hit = matcher.match_keywords(inp.text or "", self.settings)
        return hit.scene_id if hit else None

    def _detect_scene(self, inp: RouteInput) -> str | None:
        return self._detect_hard_scene(inp) or self._detect_keyword_scene(inp)

    def _guess_opposite(self, inp: RouteInput, current: str | None) -> str | None:
        guessed = guess_scene(
            inp.text or "",
            {scene.id for scene in self.settings.enabled_scenes()},
        )
        if guessed in {None, "help", current}:
            return None
        return guessed

    def _resolve_choice(
        self,
        scene_id: str | None,
        provider_id: str | None,
        available: set[str],
    ) -> tuple[str | None, str | None]:
        if scene_id:
            scene = self.settings.scene(scene_id)
            if scene and scene.enabled:
                provider_id = scene.provider_id
        if provider_id and available and provider_id not in available:
            # Still allow it: AstrBot will log if missing; caller may have stale IDs.
            pass
        return scene_id, provider_id

    def _finish(
        self,
        inp: RouteInput,
        *,
        scene_id: str,
        provider_id: str,
        source: str,
        reason: str,
        cleaned_prompt: str | None,
        stop_for_switch_only: bool = False,
        reasoning_effort: str | None = None,
    ) -> RouteDecision:
        if not provider_id:
            return RouteDecision.keep(f"{reason}, but provider_id empty")
        available = set(inp.available_providers)
        if available and provider_id not in available:
            return RouteDecision.keep(
                f"{reason}, but provider {provider_id} is not loaded",
                source="missing_provider",
            )
        settings = self.settings
        key = SessionStore.make_key(inp.umo, inp.sender_id)
        previous = self.store.last_scene(key)
        scene_changed = previous != scene_id
        self.store.remember_scene(key, scene_id)
        if (
            settings.sticky_enabled
            and source in {"force", "rules", "judge", "heuristic", "fallback", "consent"}
            and scene_id
            and scene_id != "named"
        ):
            self.store.set_sticky(
                key,
                scene_id,
                provider_id,
                settings.sticky_rounds,
                settings.sticky_ttl_seconds,
                source=source,
            )
        effort = reasoning_effort or self._resolve_effort(key, scene_id)
        if cleaned_prompt is None and inp.prompt_override is not None:
            cleaned_prompt = inp.prompt_override
        persona_id, persona_prompt, persona_label = self._persona_fields(scene_id)
        mode = settings.announce_switch
        if source == "lock":
            announce = False
        elif source in {"force", "think"}:
            announce = mode in {"force_only", "always"}
        else:
            announce = mode == "always" and scene_changed
        return RouteDecision(
            applied=True,
            scene_id=scene_id,
            provider_id=provider_id,
            source=source,
            reason=reason,
            cleaned_prompt=cleaned_prompt,
            announce=announce,
            stop_for_switch_only=stop_for_switch_only,
            reasoning_effort=effort,
            persona_id=persona_id,
            persona_prompt=persona_prompt,
            persona_label=persona_label,
            scene_changed=scene_changed,
            previous_scene_id=previous,
        )

    def _persona_fields(self, scene_id: str | None) -> tuple[str | None, str | None, str | None]:
        scene = self.settings.scene(scene_id) if scene_id else None
        return fields_for_scene(scene, enabled=self.settings.switch_persona)

    def lock(self, umo: str, sender_id: str, scene_id: str) -> RouteDecision:
        scene = self.settings.scene(scene_id)
        if scene is None:
            return RouteDecision.keep(f"unknown scene {scene_id}")
        if not scene.enabled:
            return RouteDecision.keep(f"scene {scene_id} has no provider")
        key = SessionStore.make_key(umo, sender_id)
        previous = self.store.last_scene(key)
        self.store.set_lock(key, scene.id, scene.provider_id)
        self.store.remember_scene(key, scene.id)
        persona_id, persona_prompt, persona_label = self._persona_fields(scene.id)
        return RouteDecision(
            applied=True,
            scene_id=scene.id,
            provider_id=scene.provider_id,
            source="lock",
            reason=f"locked to {scene.id}",
            persona_id=persona_id,
            persona_prompt=persona_prompt,
            persona_label=persona_label,
            reasoning_effort=self._resolve_effort(key, scene.id),
            scene_changed=previous != scene.id,
            previous_scene_id=previous,
        )

    def unlock(self, umo: str, sender_id: str) -> None:
        key = SessionStore.make_key(umo, sender_id)
        self.store.clear_lock(key)
        self.store.clear_sticky(key)

    def use_now(self, umo: str, sender_id: str, token: str) -> RouteDecision:
        scene_id, provider_id = self.settings.resolve_target(token)
        if scene_id:
            scene = self.settings.scene(scene_id)
            if scene and scene.enabled:
                provider_id = scene.provider_id
                scene_id = scene.id
        if not provider_id:
            return RouteDecision.keep(f"cannot resolve {token}")
        key = SessionStore.make_key(umo, sender_id)
        previous = self.store.last_scene(key)
        if self.settings.sticky_enabled:
            self.store.set_sticky(
                key,
                scene_id or "named",
                provider_id,
                self.settings.sticky_rounds,
                self.settings.sticky_ttl_seconds,
                source="force",
            )
        resolved_scene = scene_id or "named"
        self.store.remember_scene(key, resolved_scene)
        persona_id, persona_prompt, persona_label = self._persona_fields(
            scene_id if scene_id else None
        )
        return RouteDecision(
            applied=True,
            scene_id=resolved_scene,
            provider_id=provider_id,
            source="force",
            reason=f"command use {token}",
            announce=self.settings.announce_switch in {"force_only", "always"},
            persona_id=persona_id,
            persona_prompt=persona_prompt,
            persona_label=persona_label,
            reasoning_effort=self._resolve_effort(key, resolved_scene),
            scene_changed=previous != resolved_scene,
            previous_scene_id=previous,
        )
