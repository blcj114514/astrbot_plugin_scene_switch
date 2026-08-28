"""Serialize group @ replies: waiters get one notice, then the original message continues."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass


WAIT_TEXT = "正在回复中，请稍后"
DEFAULT_TIMEOUT_SECONDS = 180.0


@dataclass
class QueueTicket:
    notice: str | None
    _event: asyncio.Event | None
    _timeout: float
    _queue: "MentionQueue"
    _umo: str
    _sender: str

    @property
    def claimed(self) -> bool:
        return self._event is None

    async def wait(self) -> None:
        if self._event is None:
            return
        try:
            await asyncio.wait_for(self._event.wait(), timeout=self._timeout)
        except TimeoutError:
            self._queue.force_claim(self._umo, self._sender)


class MentionQueue:
    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self._busy: dict[str, str] = {}
        self._waiters: dict[str, deque[tuple[str, asyncio.Event]]] = {}
        self._notified: dict[str, set[str]] = {}
        self._watchdogs: dict[str, asyncio.Task] = {}

    @staticmethod
    def _token(umo: str) -> str:
        return (umo or "").strip() or "-"

    def submit(self, umo: str, sender_id: str) -> QueueTicket:
        token = self._token(umo)
        sender = (sender_id or "").strip()
        if not sender:
            return QueueTicket(None, None, self.timeout_seconds, self, token, sender)
        current = self._busy.get(token)
        if current is None:
            self._busy[token] = sender
            self._arm_watchdog(token, sender)
            return QueueTicket(None, None, self.timeout_seconds, self, token, sender)
        notice = None
        if current != sender:
            notified = self._notified.setdefault(token, set())
            if sender not in notified:
                notified.add(sender)
                notice = WAIT_TEXT
        ready = asyncio.Event()
        self._waiters.setdefault(token, deque()).append((sender, ready))
        return QueueTicket(notice, ready, self.timeout_seconds, self, token, sender)

    def finish(self, umo: str, sender_id: str | None = None) -> None:
        token = self._token(umo)
        sender = (sender_id or "").strip()
        current = self._busy.get(token)
        if current is None:
            return
        if sender and current != sender:
            return
        self._cancel_watchdog(token)
        waiters = self._waiters.get(token)
        if waiters:
            next_sender, ready = waiters.popleft()
            if not waiters:
                self._waiters.pop(token, None)
            self._busy[token] = next_sender
            self._arm_watchdog(token, next_sender)
            ready.set()
            return
        self._busy.pop(token, None)
        self._notified.pop(token, None)
        self._waiters.pop(token, None)

    def force_claim(self, umo: str, sender_id: str) -> None:
        """Waiter timed out: take the slot so the original message can continue."""
        token = self._token(umo)
        sender = (sender_id or "").strip()
        if not sender:
            return
        waiters = self._waiters.get(token)
        if waiters:
            kept: deque[tuple[str, asyncio.Event]] = deque()
            for item_sender, ready in waiters:
                if item_sender == sender and not ready.is_set():
                    ready.set()
                    continue
                kept.append((item_sender, ready))
            if kept:
                self._waiters[token] = kept
            else:
                self._waiters.pop(token, None)
        self._cancel_watchdog(token)
        self._busy[token] = sender
        self._arm_watchdog(token, sender)

    def _arm_watchdog(self, token: str, sender: str) -> None:
        self._cancel_watchdog(token)
        if self.timeout_seconds <= 0:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _kick() -> None:
            try:
                await asyncio.sleep(self.timeout_seconds)
                self.finish(token, sender)
            except asyncio.CancelledError:
                return

        self._watchdogs[token] = loop.create_task(_kick())

    def _cancel_watchdog(self, token: str) -> None:
        task = self._watchdogs.pop(token, None)
        if task is not None:
            task.cancel()
