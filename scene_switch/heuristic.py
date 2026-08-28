"""Cheap local stand-in when the judge LLM is not configured or returns keep."""

from __future__ import annotations

from .matcher import is_help_intent

PHRASES: dict[str, tuple[str, ...]] = {
    "code": (
        "写代码",
        "写个程序",
        "实现一个",
        "实现一下",
        "这段函数",
        "这个函数",
        "排序算法",
        "算法",
        "重构",
        "报错",
        "编程",
        "脚本",
        "接口",
        "api",
        "python",
        "typescript",
        "代码",
    ),
    "translate": (
        "翻译成",
        "翻译为",
        "请翻译",
        "帮我翻译",
        "译成",
        "英译中",
        "中译英",
        "翻译成英文",
        "翻译成中文",
        "日文",
        "韩文",
        "英文版",
        "translate",
    ),
    "write": (
        "润色",
        "改写成",
        "扩写",
        "缩写",
        "写一篇",
        "写个文案",
        "小红书",
        "朋友圈",
        "作文",
        "文案",
        "通顺一点",
        "更正式",
        "polish",
    ),
    "search": (
        "搜一下",
        "查一下",
        "最近发生",
        "今天新闻",
        "热点",
        "联网",
        "最新",
    ),
    "vision": (
        "这张图",
        "看看这张",
        "截图",
        "图片里",
        "识别图",
        "ocr",
    ),
    "chat": (
        "陪我聊聊",
        "陪陪我",
        "安慰我",
        "晚安",
        "想你了",
    ),
}

PRIORITY = ("vision", "code", "translate", "write", "search", "chat")


def guess_scene(text: str, scene_ids: set[str]) -> str | None:
    """Return a scene id, 'help', or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    if is_help_intent(raw):
        return "help"

    lowered = raw.lower()
    best_id = None
    best_score = 0
    for scene_id in PRIORITY:
        if scene_id not in scene_ids:
            continue
        score = 0
        for phrase in PHRASES.get(scene_id, ()):
            if phrase in raw or phrase.lower() in lowered:
                score += max(len(phrase), 2)
        if score > best_score:
            best_score = score
            best_id = scene_id
        elif score == best_score and score > 0 and best_id:
            if PRIORITY.index(scene_id) < PRIORITY.index(best_id):
                best_id = scene_id
    return best_id
