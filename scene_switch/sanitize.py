"""Strip model-emitted quote tags and extra @nickname text."""

from __future__ import annotations

import re
from typing import Any

QUOTE_RE = re.compile(r"<quote\s+id=\"[^\"]+\"\s*/>", re.IGNORECASE)
AT_NICK_RE = re.compile(r"(?:^|(?<=\s))@[^\s@]{1,32}")
CQ_AT_RE = re.compile(r"\[CQ:at,[^\]]+\]", re.IGNORECASE)


def strip_model_mentions(text: str, *, has_at_component: bool = False) -> str:
    cleaned = QUOTE_RE.sub("", text or "")
    cleaned = CQ_AT_RE.sub("", cleaned)
    if has_at_component:
        cleaned = AT_NICK_RE.sub("", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def chain_has_at(chain: Any) -> bool:
    for item in chain or []:
        name = type(item).__name__
        if name in {"At", "AtAll"}:
            return True
        if getattr(item, "type", "") in {"at", "At"}:
            return True
    return False
