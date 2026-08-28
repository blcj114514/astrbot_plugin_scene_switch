"""Persisted flood-audit strikes, admin locks, last bot-speak, and recent lines."""

from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

LONG_MUTE_SECONDS = 10 * 365 * 24 * 3600
RECENT_LIMIT = 24


class FloodStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.last_bot_speak: dict[str, float] = {}
        self.strikes: dict[str, list[float]] = {}
        self.locked: set[str] = set()
        self.last_audit: dict[str, float] = {}
        self._recent: dict[str, deque[dict]] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        self.last_bot_speak = {
            str(key): float(value)
            for key, value in (raw.get("last_bot_speak") or {}).items()
            if _is_number(value)
        }
        strikes: dict[str, list[float]] = {}
        for key, value in (raw.get("strikes") or {}).items():
            if not isinstance(value, list):
                continue
            stamps = [float(item) for item in value if _is_number(item)]
            if stamps:
                strikes[str(key)] = stamps
        self.strikes = strikes
        self.locked = {str(item) for item in (raw.get("locked") or []) if str(item).strip()}
        self.last_audit = {
            str(key): float(value)
            for key, value in (raw.get("last_audit") or {}).items()
            if _is_number(value)
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_bot_speak": dict(self.last_bot_speak),
            "strikes": dict(self.strikes),
            "locked": sorted(self.locked),
            "last_audit": dict(self.last_audit),
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def remember_line(
        self,
        umo: str,
        sender_id: str,
        text: str,
        *,
        is_bot: bool,
        now: float | None = None,
    ) -> None:
        token = (umo or "").strip()
        snippet = (text or "").strip().replace("\n", " ")[:160]
        if not token or not snippet:
            return
        bucket = self._recent.setdefault(token, deque(maxlen=RECENT_LIMIT))
        bucket.append(
            {
                "ts": time.time() if now is None else now,
                "sender": (sender_id or "-")[:24],
                "text": snippet,
                "bot": bool(is_bot),
            }
        )

    def format_capture(self, umo: str, *, limit: int = 16) -> str:
        token = (umo or "").strip()
        lines = list(self._recent.get(token, ()))[-limit:]
        if not lines:
            return ""
        out: list[str] = []
        for item in lines:
            tag = "BOT" if item.get("bot") else f"USER {item.get('sender')}"
            out.append(f"{tag}: {item.get('text')}")
        return "\n".join(out)

    def note_bot_speak(self, umo: str, *, now: float | None = None) -> None:
        token = (umo or "").strip()
        if not token:
            return
        self.last_bot_speak[token] = time.time() if now is None else now
        self.save()

    def bot_spoke_within(self, umo: str, seconds: float, *, now: float | None = None) -> bool:
        token = (umo or "").strip()
        spoken = self.last_bot_speak.get(token, 0.0)
        if spoken <= 0:
            return False
        current = time.time() if now is None else now
        return (current - spoken) <= float(seconds)

    def mark_audit(self, umo: str, *, now: float | None = None) -> None:
        token = (umo or "").strip()
        if not token:
            return
        self.last_audit[token] = time.time() if now is None else now
        self.save()

    def recently_audited(self, umo: str, seconds: float, *, now: float | None = None) -> bool:
        token = (umo or "").strip()
        stamped = self.last_audit.get(token, 0.0)
        if stamped <= 0:
            return False
        current = time.time() if now is None else now
        return (current - stamped) <= float(seconds)

    def add_strike(self, umo: str, *, window_seconds: float, now: float | None = None) -> int:
        token = (umo or "").strip()
        current = time.time() if now is None else now
        kept = [
            stamp
            for stamp in self.strikes.get(token, [])
            if current - stamp <= float(window_seconds)
        ]
        kept.append(current)
        self.strikes[token] = kept
        self.save()
        return len(kept)

    def clear_strikes(self, umo: str) -> None:
        token = (umo or "").strip()
        changed = False
        if token in self.strikes:
            self.strikes.pop(token, None)
            changed = True
        if token in self.locked:
            self.locked.discard(token)
            changed = True
        if changed:
            self.save()

    def lock(self, umo: str) -> None:
        token = (umo or "").strip()
        if not token or token in self.locked:
            return
        self.locked.add(token)
        self.save()

    def is_locked(self, umo: str) -> bool:
        return (umo or "").strip() in self.locked

    def unlock(self, umo: str) -> None:
        self.clear_strikes(umo)


def flood_path_from_plugin_data(plugin_data_dir: Path) -> Path:
    return plugin_data_dir / "flood.json"


def _is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
