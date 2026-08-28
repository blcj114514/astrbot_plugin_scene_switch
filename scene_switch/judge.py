"""审判模型：用轻量 LLM 理解自然语言该走哪个场景。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .heuristic import guess_scene
from .settings import PluginSettings

INTERNAL_MARK = "[scene_switch_classify]"

SCENE_HINTS = {
    "chat": "闲聊、陪伴、情绪、寒暄、日常对话、讲故事、默认回答",
    "code": "写代码、改代码、实现功能、报错、重构、算法、编程、脚本",
    "search": "查资料、新闻、热点、需要联网或最新事实",
    "vision": "看图、截图、图片内容、OCR、描述画面",
    "translate": "翻译、英译中、中译英、译成某种语言",
    "write": "润色、改写、写文案、作文、小红书、扩写缩写",
}

JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


@dataclass(frozen=True)
class JudgeVerdict:
    action: str  # route | help | keep
    scene_id: str | None
    reason: str
    raw: str = ""


def build_judge_messages(
    settings: PluginSettings,
    text: str,
    last_scene: str | None = None,
    named_scene: str | None = None,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt)."""
    lines = []
    for scene in settings.enabled_scenes():
        hint = (
            scene.capabilities
            or SCENE_HINTS.get(scene.id, "、".join(scene.aliases[:6]) or scene.display_name)
        )
        persona = scene.persona_label or scene.persona_id or scene.display_name
        lines.append(f"- {scene.id} ({persona}): {hint}")
    scene_block = "\n".join(lines) or "- keep"
    last = last_scene or "无"
    named_line = f"用户点名了：{named_scene}\n" if named_scene else ""
    default = settings.default_scene()
    default_id = default.id if default else "chat"
    system = (
        "你是模型调度审核 AI，只负责判断这句话该不该换模型、换成哪一个。"
        "不要回答用户的问题。只输出一个 JSON 对象。"
        "只能选择上面列出的 scene，不要选未列出的模型。"
    )
    user = (
        f"{INTERNAL_MARK}\n"
        "根据用户的自然语言意图，选择最合适的 scene。\n"
        "可选 scene：\n"
        f"{scene_block}\n"
        "- help: 用户在问能切换哪些模型\n"
        f"- keep: 继续用默认 {default_id}，不必切换\n\n"
        "规则：\n"
        f"1. 只是打招呼、闲聊、@机器人、喊默认名字 → keep 或 {default_id}\n"
        "2. 用户明确说要切换/换成/切到某个模型，或说「我想找/我想要某某助手」→ 选对应 scene\n"
        "3. 明确要写代码、实现功能、看报错 → 选最擅长代码的可用 scene\n"
        "4. 明确要看图、截图、照片 → 选多模态 scene\n"
        "5. 只是句子里碰巧出现模型名、没有说要切换或要点名 → keep\n"
        "6. 只能选上面列出的 scene / keep / help\n\n"
        f"上一场景：{last}\n"
        f"{named_line}"
        "只输出 JSON，格式："
        '{"scene":"keep|help|scene_id","reason":"简短原因"}\n\n'
        f"用户消息：\n{text[:1500]}"
    )
    return system, user


def parse_judge_reply(text: str, scene_ids: set[str]) -> JudgeVerdict:
    raw = (text or "").strip()
    if not raw:
        return JudgeVerdict("keep", None, "empty judge reply", "")

    cleaned = raw
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    payload: dict | None = None
    try:
        loaded = json.loads(cleaned)
        if isinstance(loaded, dict):
            payload = loaded
    except json.JSONDecodeError:
        payload = None
    if payload is None:
        for match in reversed(list(JSON_RE.finditer(cleaned))):
            try:
                loaded = json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict) and (
                loaded.get("scene") or loaded.get("intent") or loaded.get("route")
            ):
                payload = loaded
                break
            if payload is None and isinstance(loaded, dict):
                payload = loaded

    token = ""
    reason = ""
    if payload:
        token = str(payload.get("scene") or payload.get("intent") or payload.get("route") or "")
        reason = str(payload.get("reason") or "")
    if not token:
        token = cleaned.split()[0]
        token = token.strip("`.,。:：\"'")

    token = token.strip().lower()
    aliases = {
        "help": "help",
        "meta": "help",
        "intro": "help",
        "功能": "help",
        "keep": "keep",
        "keep_default": "keep",
        "default": "keep",
        "unknown": "keep",
        "闲聊": "chat",
        "代码": "code",
        "编程": "code",
        "搜索": "search",
        "翻译": "translate",
        "写作": "write",
        "润色": "write",
        "看图": "vision",
        "识图": "vision",
        "chat": "chat",
        "code": "code",
        "search": "search",
        "vision": "vision",
        "translate": "translate",
        "write": "write",
        "gpt": "chat",
        "deepseek": "code",
    }
    mapped = aliases.get(token, token)
    if mapped == "help":
        return JudgeVerdict("help", None, reason or "judge requested help", raw)
    if mapped == "keep":
        return JudgeVerdict("keep", None, reason or "judge keep", raw)
    if mapped in scene_ids:
        return JudgeVerdict("route", mapped, reason or f"judge chose {mapped}", raw)
    for scene_id in sorted(scene_ids, key=len, reverse=True):
        if scene_id and scene_id in cleaned.lower():
            return JudgeVerdict("route", scene_id, reason or f"found {scene_id} in reply", raw)
    return JudgeVerdict("keep", None, f"unrecognized judge output: {token}", raw)


def fallback_from_heuristic(text: str, scene_ids: set[str], reason: str) -> JudgeVerdict:
    """When the judge times out or errors, use local heuristics instead of blocking."""
    guessed = guess_scene(text, scene_ids)
    if guessed == "help":
        return JudgeVerdict("help", None, reason)
    if guessed and guessed in scene_ids:
        return JudgeVerdict("route", guessed, reason)
    return JudgeVerdict("keep", None, reason)
