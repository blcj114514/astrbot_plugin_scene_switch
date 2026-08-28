"""Shared slap/silence store so 闭嘴 actually stops every plugin."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

SLAP_WORDS = (
    "闭嘴",
    "闭麦",
    "闭上嘴",
    "你给我闭嘴",
    "给我闭嘴",
    "别说话",
    "不要说话",
    "不要再说话",
    "别再说话",
    "别回了",
    "别回我",
    "不要回了",
    "别插嘴",
    "不要插嘴",
)
SPEAK_WORDS = (
    "张嘴",
    "可以说话了",
    "继续说话",
    "解除闭嘴",
    "开麦",
    "你可以说话了",
)
ACK_SLAP = "好，那我先不说话了。"
DEFAULT_SECONDS = 600
_AT_RE = re.compile(r"\[CQ:at[^\]]*\]|@\S+")
_QUOTE_RE = re.compile(r"\[引用消息[\s\S]*?\]|\[Quote[^\]]*\]", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[\s，。！？、,.!?【】\[\]（）()“”\"'：:；;~～…]+")
_COMMAND_PREFIXES = ("", "你", "给我", "你给我", "求你", "请")


def _normalize(text: str) -> str:
    cleaned = _QUOTE_RE.sub(" ", text or "")
    return _AT_RE.sub("", cleaned).strip()


def _compact_command(text: str) -> str:
    return _PUNCT_RE.sub("", _normalize(text))


def _matches_explicit_command(compact: str, words: tuple[str, ...], *, max_len: int) -> bool:
    if not compact or len(compact) > max_len:
        return False
    for word in words:
        token = str(word or "").strip()
        if not token:
            continue
        if compact == token:
            return True
        if compact.endswith(token):
            prefix = compact[: -len(token)]
            if prefix in _COMMAND_PREFIXES and len(compact) <= max_len:
                return True
    return False


def is_speak_command(text: str, extra_words: tuple[str, ...] = ()) -> bool:
    words = tuple(dict.fromkeys((*SPEAK_WORDS, *extra_words)))
    return _matches_explicit_command(_compact_command(text), words, max_len=16)


def is_slap_command(text: str, extra_words: tuple[str, ...] = ()) -> bool:
    compact = _compact_command(text)
    if not compact or is_speak_command(compact):
        return False
    words = tuple(dict.fromkeys((*SLAP_WORDS, *extra_words)))
    return _matches_explicit_command(compact, words, max_len=12)


def silence_path_from_plugin_data(plugin_data_dir: Path) -> Path:
    return plugin_data_dir / "silence.json"


def discover_data_root(start: Path | None = None) -> Path | None:
    here = (start or Path(__file__).resolve()).resolve()
    for parent in [here, *here.parents]:
        if (parent / "plugin_data").is_dir() and (parent / "plugins").is_dir():
            return parent
    return None


def shared_silence_path(start: Path | None = None) -> Path | None:
    root = discover_data_root(start)
    if root is None:
        return None
    return root / "plugin_data" / "astrbot_plugin_scene_switch" / "silence.json"


def is_umo_silenced(umo: str, *, start: Path | None = None, now: float | None = None) -> bool:
    path = shared_silence_path(start)
    if path is None:
        return False
    return SilenceStore(path).is_silenced(umo, now=now)


class SilenceStore:
    def __init__(self, path: Path, *, default_seconds: int = DEFAULT_SECONDS) -> None:
        self.path = path
        self.default_seconds = default_seconds
        self._until: dict[str, float] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._until = {}
            return
        if not isinstance(raw, dict):
            self._until = {}
            return
        now = time.time()
        out: dict[str, float] = {}
        for key, value in raw.items():
            try:
                until = float(value)
            except (TypeError, ValueError):
                continue
            out[str(key)] = until
        self._until = out

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(self._until)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_silenced(self, umo: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        until = self._until.get(umo, 0.0)
        if until <= current:
            if umo in self._until:
                self._until.pop(umo, None)
                self.save()
            return False
        return True

    def slap(self, umo: str, *, seconds: int | None = None, now: float | None = None) -> float:
        current = time.time() if now is None else now
        until = current + float(seconds if seconds is not None else self.default_seconds)
        self._until[umo] = until
        self.save()
        return until

    def unmute(self, umo: str) -> None:
        if umo in self._until:
            self._until.pop(umo, None)
            self.save()
