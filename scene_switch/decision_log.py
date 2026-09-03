"""Persistent routing decision log (JSONL, daily files) + in-memory aggregates.

Records routing metadata only (scene, source, latency, session/sender ids).
Message text is never written unless the operator opts in via the preview
setting in main.py. Log files contain QQ ids and must never be committed.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROUTE = "route"
JUDGE = "judge"
BLOCKED = "blocked"
COMMAND = "command"
THINK = "think"


def _date_key(stamp: datetime) -> str:
    return stamp.strftime("%Y%m%d")


class DecisionLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dir: Path | None = None
        self._enabled = False
        self._days = 7
        self._date_key = ""
        self._scene_today: dict[str, int] = {}
        self._scene_total: dict[str, int] = {}
        self._source_total: dict[str, int] = {}
        self._blocked_total: dict[str, int] = {}
        self._judge_count = 0
        self._judge_ms_total = 0
        self._judge_ms_max = 0
        self._last_sweep = 0.0

    def configure(
        self,
        directory: Path | None,
        *,
        enabled: bool,
        days: int = 7,
    ) -> None:
        with self._lock:
            self._dir = Path(directory) if directory is not None else None
            self._enabled = bool(enabled) and self._dir is not None
            try:
                self._days = max(1, int(days or 7))
            except (TypeError, ValueError):
                self._days = 7

    @property
    def enabled(self) -> bool:
        return self._enabled

    def append(self, kind: str, **fields) -> None:
        if not self._enabled or self._dir is None:
            return
        stamp = datetime.now()
        payload: dict = {"ts": stamp.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind}
        for key, value in fields.items():
            if value is None or value == "":
                continue
            if isinstance(value, (bool, int, float, str)):
                payload[key] = value
        with self._lock:
            self._record_unlocked(kind, payload, stamp)

    def _record_unlocked(self, kind: str, payload: dict, stamp: datetime) -> None:
        date_key = _date_key(stamp)
        if date_key != self._date_key:
            self._date_key = date_key
            self._scene_today = {}
        scene = payload.get("scene")
        source = payload.get("source")
        if kind in (ROUTE, COMMAND):
            if payload.get("applied") and scene:
                name = str(scene)
                self._scene_total[name] = self._scene_total.get(name, 0) + 1
                self._scene_today[name] = self._scene_today.get(name, 0) + 1
            if source:
                name = str(source)
                self._source_total[name] = self._source_total.get(name, 0) + 1
        elif kind == JUDGE:
            latency = payload.get("latency_ms")
            self._judge_count += 1
            if isinstance(latency, (int, float)) and latency >= 0:
                ms = int(latency)
                self._judge_ms_total += ms
                self._judge_ms_max = max(self._judge_ms_max, ms)
        elif kind == BLOCKED and payload.get("blocked"):
            name = str(payload["blocked"])
            self._blocked_total[name] = self._blocked_total.get(name, 0) + 1
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / f"decisions-{date_key}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            return
        self._sweep_unlocked(time.time())

    def sweep(self, now: float | None = None) -> None:
        if not self._enabled or self._dir is None:
            return
        current = time.time() if now is None else now
        with self._lock:
            self._sweep_unlocked(current)

    def _sweep_unlocked(self, now: float) -> None:
        if now - self._last_sweep < 3600:
            return
        self._last_sweep = now
        try:
            cutoff = (
                datetime.now() - timedelta(days=max(1, self._days))
            ).strftime("%Y%m%d")
            for path in self._dir.glob("decisions-*.jsonl"):
                stem = path.stem.removeprefix("decisions-")
                if stem.isdigit() and stem < cutoff:
                    path.unlink(missing_ok=True)
        except OSError:
            return

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "enabled": self._enabled,
                "date": self._date_key,
                "scene_today": dict(self._scene_today),
                "scene_total": dict(self._scene_total),
                "source_total": dict(self._source_total),
                "blocked_total": dict(self._blocked_total),
                "judge_count": self._judge_count,
                "judge_avg_ms": (
                    self._judge_ms_total // self._judge_count
                    if self._judge_count
                    else 0
                ),
                "judge_max_ms": self._judge_ms_max,
            }

    def tail(self, n: int, *, max_files: int = 3) -> list[dict]:
        if not self._enabled or self._dir is None or n <= 0:
            return []
        with self._lock:
            dates: list[str] = []
            try:
                for path in self._dir.glob("decisions-*.jsonl"):
                    stem = path.stem.removeprefix("decisions-")
                    if stem.isdigit():
                        dates.append(stem)
            except OSError:
                return []
            dates.sort(reverse=True)
            entries: list[dict] = []
            for date in dates[:max(1, max_files)]:
                try:
                    lines = (
                        self._dir / f"decisions-{date}.jsonl"
                    ).read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for raw in reversed(lines):
                    if not raw.strip():
                        continue
                    try:
                        entries.append(json.loads(raw))
                    except json.JSONDecodeError:
                        continue
                    if len(entries) >= n:
                        return entries[:n]
            return entries


def format_stats(snapshot: dict) -> str:
    if not snapshot.get("enabled"):
        return "决策日志未开启。请在插件配置里打开「记录路由决策日志」。"
    lines = ["决策日志统计（本次运行累计）"]
    scene_total = snapshot.get("scene_total") or {}
    if scene_total:
        scene_today = snapshot.get("scene_today") or {}
        pairs = "，".join(
            f"{name} {scene_today.get(name, 0)}/{count}"
            for name, count in sorted(
                scene_total.items(), key=lambda item: (-item[1], item[0])
            )
        )
        lines.append(f"场景（今日/累计）：{pairs}")
    else:
        lines.append("场景：暂无记录")
    source_total = snapshot.get("source_total") or {}
    if source_total:
        pairs = "，".join(
            f"{name}={count}"
            for name, count in sorted(
                source_total.items(), key=lambda item: (-item[1], item[0])
            )
        )
        lines.append(f"判定来源：{pairs}")
    judge_count = int(snapshot.get("judge_count") or 0)
    if judge_count:
        avg = int(snapshot.get("judge_avg_ms") or 0) / 1000
        longest = int(snapshot.get("judge_max_ms") or 0) / 1000
        lines.append(f"审判：{judge_count} 次，平均 {avg:.1f}s，最长 {longest:.1f}s")
    blocked_total = snapshot.get("blocked_total") or {}
    if blocked_total:
        pairs = "，".join(f"{name}={count}" for name, count in sorted(blocked_total.items()))
        lines.append(f"拦截：{pairs}")
    return "\n".join(lines)


def format_entry(entry: dict) -> str:
    ts = str(entry.get("ts") or "")
    stamp = ts[5:19].replace("T", " ") if len(ts) >= 19 else ts or "-"
    kind = str(entry.get("kind") or "")
    if kind == ROUTE:
        line = (
            f"{stamp} 路由 scene={entry.get('scene') or '-'}"
            f" src={entry.get('source') or '-'}"
        )
        if entry.get("provider"):
            line += f" 模型={entry['provider']}"
        if entry.get("effort"):
            line += f" 思考={entry['effort']}"
        if entry.get("applied") is False:
            line += "（未生效）"
        if entry.get("preview"):
            line += f" 原文={entry['preview']}"
        return line
    if kind == JUDGE:
        latency = entry.get("latency_ms")
        tail = f" {int(latency)}ms" if isinstance(latency, (int, float)) else ""
        if entry.get("timed_out"):
            tail += " 超时"
        elif entry.get("action") == "error":
            tail += " 失败"
        scene = f" scene={entry['scene']}" if entry.get("scene") else ""
        return f"{stamp} 审判 action={entry.get('action') or '-'}{scene}{tail}"
    if kind == BLOCKED:
        return f"{stamp} 拦截 {entry.get('blocked') or '-'}"
    if kind == COMMAND:
        return f"{stamp} 命令 {entry.get('source') or '-'} scene={entry.get('scene') or '-'}"
    if kind == THINK:
        effort = entry.get("effort") or "恢复默认"
        return f"{stamp} 思考 {effort}"
    return f"{stamp} {kind or '-'}"


def format_recent(entries: list[dict]) -> str:
    if not entries:
        return "决策日志暂无记录。"
    return "\n".join(format_entry(entry) for entry in entries)