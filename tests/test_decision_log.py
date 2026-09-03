import json
import threading
from datetime import datetime as real_datetime
from pathlib import Path

import scene_switch.decision_log as dlog_mod
from scene_switch.decision_log import (
    DecisionLog,
    format_entry,
    format_recent,
    format_stats,
)


def test_disabled_zero_write(tmp_path: Path):
    directory = tmp_path / "decision_log"
    log = DecisionLog()
    log.configure(directory, enabled=False, days=7)
    log.append("route", scene="code", applied=True, source="force")
    log.sweep()
    assert not directory.exists()
    assert log.snapshot()["enabled"] is False
    assert log.tail(10) == []


def test_append_tail_and_aggregates(tmp_path: Path):
    directory = tmp_path / "decision_log"
    log = DecisionLog()
    log.configure(directory, enabled=True, days=7)
    log.append(
        "route",
        umo="g:a",
        sender="u1",
        scene="code",
        provider="p1",
        source="judge",
        reason="r",
        effort="high",
        applied=True,
        changed=True,
    )
    log.append(
        "route",
        umo="g:a",
        sender="u2",
        scene="chat",
        provider="p2",
        source="sticky",
        applied=True,
        changed=False,
    )
    log.append(
        "route",
        umo="g:a",
        sender="u3",
        scene="code",
        provider="p1",
        source="consent",
        applied=False,
    )
    log.append("judge", action="route", scene="code", latency_ms=1500, timed_out=False)
    log.append("blocked", blocked="silence")

    files = list(directory.glob("decisions-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5
    entries = [json.loads(line) for line in lines]
    assert entries[0]["kind"] == "route"
    assert "preview" not in entries[0]

    snap = log.snapshot()
    assert snap["scene_total"] == {"code": 1, "chat": 1}
    assert snap["scene_today"] == {"code": 1, "chat": 1}
    assert snap["source_total"] == {"judge": 1, "sticky": 1, "consent": 1}
    assert snap["judge_count"] == 1
    assert snap["judge_avg_ms"] == 1500
    assert snap["judge_max_ms"] == 1500
    assert snap["blocked_total"] == {"silence": 1}

    tail = log.tail(3)
    assert [entry["kind"] for entry in tail] == ["blocked", "judge", "route"]
    assert tail[-1]["scene"] == "code"


def test_daily_rotation(tmp_path: Path, monkeypatch):
    holder = {"now": real_datetime(2026, 9, 2, 23, 59, 0)}

    class FakeDatetime(real_datetime):
        @classmethod
        def now(cls):  # noqa: N802 - mirrors datetime API
            return holder["now"]

    monkeypatch.setattr(dlog_mod, "datetime", FakeDatetime)
    log = DecisionLog()
    log.configure(tmp_path / "decision_log", enabled=True, days=7)
    log.append("route", scene="chat", applied=True, source="force")
    holder["now"] = real_datetime(2026, 9, 3, 0, 0, 30)
    log.append("route", scene="code", applied=True, source="force")

    names = sorted(
        path.name for path in (tmp_path / "decision_log").glob("decisions-*.jsonl")
    )
    assert names == ["decisions-20260902.jsonl", "decisions-20260903.jsonl"]
    snap = log.snapshot()
    assert snap["scene_total"] == {"chat": 1, "code": 1}
    assert snap["scene_today"] == {"code": 1}


def test_sweep_removes_expired_files(tmp_path: Path):
    directory = tmp_path / "decision_log"
    log = DecisionLog()
    log.configure(directory, enabled=True, days=7)
    stale = directory / "decisions-20200101.jsonl"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text(
        '{"ts":"2020-01-01T00:00:00","kind":"route"}\n', encoding="utf-8"
    )
    log.append("route", scene="chat", applied=True, source="force")
    assert not stale.exists()
    files = list(directory.glob("decisions-*.jsonl"))
    assert len(files) == 1
    assert files[0].name != "decisions-20200101.jsonl"


def test_concurrent_appends_keep_all_lines(tmp_path: Path):
    log = DecisionLog()
    log.configure(tmp_path / "decision_log", enabled=True, days=7)
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def writer(index: int) -> None:
        try:
            barrier.wait()
            for step in range(25):
                log.append(
                    "route",
                    scene="chat",
                    applied=True,
                    source=f"s{index}",
                    sender=f"u{step}",
                )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    files = list((tmp_path / "decision_log").glob("decisions-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 200


def test_format_helpers():
    assert "未开启" in format_stats({"enabled": False})
    line = format_entry(
        {
            "ts": "2026-09-03T14:22:31",
            "kind": "route",
            "scene": "code",
            "source": "judge",
            "effort": "high",
            "applied": False,
        }
    )
    assert line.startswith("09-03 14:22:31")
    assert "思考=high" in line
    assert "未生效" in line
    assert format_recent([]) == "决策日志暂无记录。"

    text = format_stats(
        {
            "enabled": True,
            "scene_total": {"code": 3},
            "scene_today": {"code": 1},
            "source_total": {"judge": 2},
            "judge_count": 2,
            "judge_avg_ms": 1200,
            "judge_max_ms": 1500,
            "blocked_total": {"silence": 1},
        }
    )
    assert "场景（今日/累计）：code 1/3" in text
    assert "判定来源：judge=2" in text
    assert "审判：2 次，平均 1.2s，最长 1.5s" in text
    assert "拦截：silence=1" in text