import asyncio

from scene_switch.caption import should_caption, text_wants_caption
from scene_switch.queue import MentionQueue, WAIT_TEXT
from scene_switch.sanitize import strip_model_mentions


def test_fifo_waiters_get_one_notice_then_original_order():
    async def _run():
        q = MentionQueue(timeout_seconds=2.0)
        order: list[str] = []
        notices: dict[str, str | None] = {}

        async def speaker(name: str, delay: float) -> None:
            await asyncio.sleep(delay)
            ticket = q.submit("g1", name)
            notices[name] = ticket.notice
            await ticket.wait()
            order.append(name)
            await asyncio.sleep(0.03)
            q.finish("g1", name)

        await asyncio.gather(
            speaker("a", 0.0),
            speaker("b", 0.01),
            speaker("c", 0.02),
        )
        assert notices["a"] is None
        assert notices["b"] == WAIT_TEXT
        assert notices["c"] == WAIT_TEXT
        assert order == ["a", "b", "c"]

    asyncio.run(_run())


def test_same_sender_is_not_notified():
    async def _run():
        q = MentionQueue(timeout_seconds=2.0)
        first = q.submit("g1", "a")
        second = q.submit("g1", "a")
        assert first.notice is None
        assert first.claimed
        assert second.notice is None
        assert not second.claimed
        q.finish("g1", "a")
        await second.wait()
        q.finish("g1", "a")

    asyncio.run(_run())


def test_waiter_notice_only_once_per_sender():
    q = MentionQueue(timeout_seconds=0)
    q.submit("g1", "a")
    first = q.submit("g1", "b")
    second = q.submit("g1", "b")
    assert first.notice == WAIT_TEXT
    assert second.notice is None


def test_strip_quote_and_at_when_component_present():
    raw = '<quote id="msg1"/><mention id="x"/> @電磁 你好'
    cleaned = strip_model_mentions(raw, has_at_component=True)
    assert "quote" not in cleaned
    assert not cleaned.startswith("@")
    assert "你好" in cleaned


def test_caption_requires_at_and_explicit_look():
    assert not should_caption(mentioned=True, text="看看")
    assert not should_caption(mentioned=True, text="你好")
    assert not should_caption(mentioned=False, text="看这张图")
    assert should_caption(mentioned=True, text="看这张图")
    assert should_caption(mentioned=True, text="识图")
    assert should_caption(mentioned=True, text="随便发一张", sticky_scene_id="vision")
    assert should_caption(
        mentioned=True, text="你好", named_scene_ids=("vision",)
    )
    assert not text_wants_caption("看看")
    assert text_wants_caption("看图")
