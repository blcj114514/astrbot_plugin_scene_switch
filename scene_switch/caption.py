"""When a group image should be captioned: @ plus look-at phrases or sticky vision."""

from __future__ import annotations

LOOK_AT_PHRASES = (
    "看这张",
    "这张图",
    "识图",
    "看图",
)
CAPTION_SCENE_IDS = frozenset({"vision"})


def text_wants_caption(text: str) -> bool:
    stripped = text or ""
    if not stripped:
        return False
    return any(phrase in stripped for phrase in LOOK_AT_PHRASES)


def should_caption(
    *,
    mentioned: bool,
    text: str,
    sticky_scene_id: str | None = None,
    named_scene_ids: tuple[str, ...] = (),
) -> bool:
    if not mentioned:
        return False
    if sticky_scene_id in CAPTION_SCENE_IDS:
        return True
    if any(item in CAPTION_SCENE_IDS for item in named_scene_ids):
        return True
    return text_wants_caption(text)
