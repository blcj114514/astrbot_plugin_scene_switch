import time
from pathlib import Path

from scene_switch.silence import (
    SilenceStore,
    is_slap_command,
    is_speak_command,
)


def test_slap_and_speak_words():
    assert is_slap_command("闭嘴")
    assert is_slap_command("你给我闭嘴")
    assert is_slap_command("别回了")
    assert is_speak_command("张嘴")
    assert is_speak_command("可以说话了")
    assert not is_slap_command("张嘴继续说")
    assert not is_slap_command("今天天气真好")
    assert not is_slap_command("走开")
    assert not is_slap_command("不想聊")
    assert not is_slap_command("我在他的昵称里面设置有错误请对他闭嘴")
    assert not is_slap_command(
        "[引用消息(机器人（bot）【有错误请对她说闭嘴】: @九九 人均20)] 麦当劳😋😋😋"
    )
    assert is_slap_command(
        "[引用消息(机器人（bot）【有错误请对她说闭嘴】: 人均20)] 闭嘴"
    )


def test_silence_store_roundtrip(tmp_path: Path):
    store = SilenceStore(tmp_path / "silence.json", default_seconds=30)
    now = 1_700_000_000.0
    umo = "aiocqhttp:GroupMessage:1"
    assert not store.is_silenced(umo, now=now)
    store.slap(umo, seconds=60, now=now)
    assert store.is_silenced(umo, now=now + 10)
    reloaded = SilenceStore(tmp_path / "silence.json")
    assert reloaded.is_silenced(umo, now=now + 10)
    reloaded.unmute(umo)
    assert not reloaded.is_silenced(umo, now=now + 11)


def test_expired_silence_clears(tmp_path: Path):
    store = SilenceStore(tmp_path / "silence.json")
    now = time.time()
    store.slap("u", seconds=1, now=now - 5)
    assert not store.is_silenced("u", now=now)
