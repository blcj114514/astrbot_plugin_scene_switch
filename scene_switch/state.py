"""Lock / sticky / last-scene state, optionally persisted to JSON."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class StickySlot:
    scene_id: str
    provider_id: str
    rounds_left: int
    expires_at: float
    source: str = "force"


@dataclass
class ConsentPending:
    scene_id: str
    provider_id: str
    original_text: str
    reason: str
    persona_id: str = ""
    persona_label: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0


class SessionStore:
    def __init__(self, persist_path: Path | None = None) -> None:
        self.persist_path = persist_path
        self._lock = threading.Lock()
        self._locks: dict[str, tuple[str, str]] = {}
        self._sticky: dict[str, StickySlot] = {}
        self._last_scene: dict[str, str] = {}
        self._think: dict[str, tuple[str, float]] = {}
        self._pending: dict[str, ConsentPending] = {}
        self._cooldown_until: dict[str, float] = {}
        self._last_prompt_at: dict[str, float] = {}
        if persist_path is not None:
            self.load()

    @staticmethod
    def make_key(umo: str, sender_id: str) -> str:
        return f"{umo}::{sender_id or '-'}"

    def get_lock(self, key: str) -> tuple[str, str] | None:
        with self._lock:
            return self._locks.get(key)

    def set_lock(self, key: str, scene_id: str, provider_id: str) -> None:
        with self._lock:
            self._locks[key] = (scene_id, provider_id)
            self._sticky.pop(key, None)
            self._save_unlocked()

    def clear_lock(self, key: str) -> None:
        with self._lock:
            self._locks.pop(key, None)
            self._save_unlocked()

    def get_sticky(self, key: str, now: float | None = None) -> StickySlot | None:
        with self._lock:
            slot = self._sticky.get(key)
            if slot is None:
                return None
            current = time.time() if now is None else now
            if slot.expires_at <= current or slot.rounds_left <= 0:
                self._sticky.pop(key, None)
                self._save_unlocked()
                return None
            return slot

    def set_sticky(
        self,
        key: str,
        scene_id: str,
        provider_id: str,
        rounds: int,
        ttl_seconds: int,
        source: str = "force",
        now: float | None = None,
    ) -> None:
        current = time.time() if now is None else now
        with self._lock:
            self._sticky[key] = StickySlot(
                scene_id=scene_id,
                provider_id=provider_id,
                rounds_left=max(1, rounds),
                expires_at=current + max(1, ttl_seconds),
                source=source,
            )
            self._save_unlocked()

    def consume_sticky(self, key: str) -> None:
        with self._lock:
            slot = self._sticky.get(key)
            if slot is None:
                return
            slot.rounds_left -= 1
            if slot.rounds_left <= 0:
                self._sticky.pop(key, None)
            self._save_unlocked()

    def clear_sticky(self, key: str) -> None:
        with self._lock:
            self._sticky.pop(key, None)
            self._save_unlocked()

    def remember_scene(self, key: str, scene_id: str) -> None:
        with self._lock:
            self._last_scene[key] = scene_id
            self._save_unlocked()

    def last_scene(self, key: str) -> str | None:
        with self._lock:
            return self._last_scene.get(key)

    def set_think(
        self,
        key: str,
        effort: str,
        ttl_seconds: int = 3600,
        now: float | None = None,
    ) -> None:
        current = time.time() if now is None else now
        with self._lock:
            self._think[key] = (effort, current + max(1, ttl_seconds))
            self._save_unlocked()

    def get_think(self, key: str, now: float | None = None) -> str | None:
        with self._lock:
            slot = self._think.get(key)
            if slot is None:
                return None
            effort, expires_at = slot
            current = time.time() if now is None else now
            if expires_at <= current or not effort:
                self._think.pop(key, None)
                self._save_unlocked()
                return None
            return effort

    def clear_think(self, key: str) -> None:
        with self._lock:
            self._think.pop(key, None)
            self._save_unlocked()

    def get_pending(self, key: str, now: float | None = None) -> ConsentPending | None:
        current = time.time() if now is None else now
        with self._lock:
            pending = self._pending.get(key)
            if pending is None:
                return None
            if pending.expires_at <= current:
                self._pending.pop(key, None)
                self._save_unlocked()
                return None
            return pending

    def set_pending(
        self,
        key: str,
        pending: ConsentPending,
    ) -> None:
        with self._lock:
            self._pending[key] = pending
            self._save_unlocked()

    def clear_pending(self, key: str) -> None:
        with self._lock:
            self._pending.pop(key, None)
            self._save_unlocked()

    def in_cooldown(self, key: str, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        with self._lock:
            until = self._cooldown_until.get(key)
            if until is None:
                return False
            if until <= current:
                self._cooldown_until.pop(key, None)
                self._save_unlocked()
                return False
            return True

    def set_cooldown(self, key: str, seconds: int, now: float | None = None) -> None:
        if seconds <= 0:
            return
        current = time.time() if now is None else now
        with self._lock:
            self._cooldown_until[key] = current + seconds
            self._save_unlocked()

    def last_prompt_recent(self, key: str, seconds: int, now: float | None = None) -> bool:
        if seconds <= 0:
            return False
        current = time.time() if now is None else now
        with self._lock:
            last = self._last_prompt_at.get(key)
            return bool(last and current - last < seconds)

    def mark_prompt(self, key: str, now: float | None = None) -> None:
        current = time.time() if now is None else now
        with self._lock:
            self._last_prompt_at[key] = current
            self._save_unlocked()

    def load(self) -> bool:
        path = self.persist_path
        if path is None or not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return False
        if not isinstance(data, dict):
            return False

        locks: dict[str, tuple[str, str]] = {}
        for key, value in (data.get("locks") or {}).items():
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                locks[str(key)] = (str(value[0]), str(value[1]))

        sticky: dict[str, StickySlot] = {}
        now = time.time()
        for key, value in (data.get("sticky") or {}).items():
            if not isinstance(value, dict):
                continue
            slot = StickySlot(
                scene_id=str(value.get("scene_id") or ""),
                provider_id=str(value.get("provider_id") or ""),
                rounds_left=int(value.get("rounds_left") or 0),
                expires_at=float(value.get("expires_at") or 0),
                source=str(value.get("source") or "force"),
            )
            if slot.scene_id and slot.provider_id and slot.rounds_left > 0 and slot.expires_at > now:
                sticky[str(key)] = slot

        last_scene = {
            str(key): str(value)
            for key, value in (data.get("last_scene") or {}).items()
            if key and value
        }
        think: dict[str, tuple[str, float]] = {}
        now = time.time()
        for key, value in (data.get("think") or {}).items():
            if isinstance(value, dict):
                effort = str(value.get("effort") or "")
                expires_at = float(value.get("expires_at") or 0)
            elif isinstance(value, (list, tuple)) and len(value) >= 2:
                effort = str(value[0])
                expires_at = float(value[1])
            else:
                continue
            if effort and expires_at > now:
                think[str(key)] = (effort, expires_at)

        pending: dict[str, ConsentPending] = {}
        for key, value in (data.get("pending") or {}).items():
            if not isinstance(value, dict):
                continue
            item = ConsentPending(
                scene_id=str(value.get("scene_id") or ""),
                provider_id=str(value.get("provider_id") or ""),
                original_text=str(value.get("original_text") or ""),
                reason=str(value.get("reason") or ""),
                persona_id=str(value.get("persona_id") or ""),
                persona_label=str(value.get("persona_label") or ""),
                created_at=float(value.get("created_at") or 0),
                expires_at=float(value.get("expires_at") or 0),
            )
            if item.scene_id and item.provider_id and item.expires_at > now:
                pending[str(key)] = item

        cooldown = {
            str(key): float(value)
            for key, value in (data.get("cooldown_until") or {}).items()
            if float(value or 0) > now
        }
        last_prompt = {
            str(key): float(value)
            for key, value in (data.get("last_prompt_at") or {}).items()
            if float(value or 0) > now - 86400
        }
        with self._lock:
            self._locks = locks
            self._sticky = sticky
            self._last_scene = last_scene
            self._think = think
            self._pending = pending
            self._cooldown_until = cooldown
            self._last_prompt_at = last_prompt
        return True

    def save(self) -> None:
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        path = self.persist_path
        if path is None:
            return
        now = time.time()
        payload = {
            "locks": {key: list(value) for key, value in self._locks.items()},
            "sticky": {
                key: asdict(slot)
                for key, slot in self._sticky.items()
                if slot.rounds_left > 0 and slot.expires_at > now
            },
            "last_scene": dict(self._last_scene),
            "think": {
                key: {"effort": effort, "expires_at": expires_at}
                for key, (effort, expires_at) in self._think.items()
                if effort and expires_at > now
            },
            "pending": {
                key: asdict(item)
                for key, item in self._pending.items()
                if item.expires_at > now
            },
            "cooldown_until": {
                key: until
                for key, until in self._cooldown_until.items()
                if until > now
            },
            "last_prompt_at": dict(self._last_prompt_at),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
