"""Two-stage flood audit: local phrases → stage-1 grab → stage-2 verdict."""

from __future__ import annotations

import json
import re

JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z]+")

# 开源默认样例，可在插件配置里整段删掉。不绑定任何本机 Provider。
SAMPLE_STRONG_FLOOD_PHRASES = (
    "刷屏了",
    "刷屏了吧",
    "刷屏了啊",
    "又刷屏",
    "又在刷屏",
    "别刷屏",
    "不要刷屏",
    "别再刷了",
    "消息也太多了",
    "消息太多了吧",
    "这些消息怎么这么多",
    "发的消息也太多了",
    "发这么多干嘛",
    "怎么发这么多",
    "话怎么这么多",
    "话也太多了",
    "回这么多干嘛",
    "回得也太多",
    "回太多了",
    "能不能少回点",
    "能不能少说点",
    "能不能少发点",
    "别发这么多",
    "别回这么多",
    "别刷了行不行",
    "占屏了",
    "占满屏了",
    "别占屏",
    "一条接一条发",
    "stop spamming",
    "stop spam",
)

# 弱触发样例：必须点名/提到这只机器人才叫醒审核，避免「好烦啊」这种闲聊。
SAMPLE_WEAK_FLOOD_PHRASES = (
    "怎么这么烦人",
    "你怎么这么烦",
    "你烦不烦",
    "怎么还不闭嘴",
    "这机器人好烦",
    "这机器人刷屏",
    "这机器人话太多",
    "机器人好烦",
    "机器人刷屏",
    "机器人话太多",
    "你们机器人能不能少说",
)

STRONG_FLOOD_PHRASES = SAMPLE_STRONG_FLOOD_PHRASES
WEAK_FLOOD_PHRASES = SAMPLE_WEAK_FLOOD_PHRASES
FLOOD_PHRASES = STRONG_FLOOD_PHRASES + WEAK_FLOOD_PHRASES

SKIP_PHRASES = (
    "总结一下",
    "帮我总结",
    "总结这些",
    "概括一下",
    "归纳一下",
    "梳理一下",
    "整理一下这些",
    "帮我看看这些消息",
    "帮我看看上面",
    "这些消息是什么意思",
    "这些消息帮我",
    "这么多消息帮我",
    "这么多聊天记录",
    "帮我整理这些消息",
    "这些记录帮我看",
    "翻译这些",
    "翻译一下这些",
    "解释这些消息",
    "复述一下",
    "帮我看看这堆消息",
)

CUTOFF_TEXT = "目前消息过多已自行截断。说「张嘴」才会继续发言。"
CUTOFF_LOCKED_TEXT = "目前消息过多已自行截断。这个群要等管理员说「张嘴」才会继续发言。"

FLOOD_PATTERNS = (
    re.compile(r"(刷屏|刷爆|占屏|连环发|一条接一条发)"),
    re.compile(r"(话|消息|回复|输出).{0,6}(太多|这么多|也太多)"),
    re.compile(r"(这么多|太多).{0,6}(话|消息|回复)"),
    re.compile(r"(回得|回的|发得|发的).{0,4}(太多|也太多)"),
    re.compile(r"(能不能|求你).{0,8}(少回|少说|少发|别刷)"),
    re.compile(r"(别|不要).{0,6}(刷屏|发这么多|回这么多)"),
    re.compile(r"(机器人).{0,12}(烦|刷屏|话多|太多|少回|少说)"),
)
WEAK_FLOOD_PATTERNS = (
    re.compile(r"(怎么这么烦|你烦不烦|这机器人好烦)"),
)

EN_WORD_HITS = frozenset({"spamming"})


def pin_flood_provider(provider_id: str | None) -> str:
    """Use the configured Provider id as-is. Empty means flood L1 is unbound."""
    return str(provider_id or "").strip()


def pin_verifier_provider(provider_id: str | None, fallback: str | None = None) -> str:
    """Configured verifier only. Empty means L2 is unbound; never fall back to chat."""
    del fallback
    return str(provider_id or "").strip()


def matched_flood_phrases(
    text: str,
    *,
    strong: tuple[str, ...] | None = None,
    weak: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    stripped = text or ""
    lowered = stripped.lower()
    hits: list[str] = []
    phrases = tuple(strong or STRONG_FLOOD_PHRASES) + tuple(weak or WEAK_FLOOD_PHRASES)
    for item in phrases:
        if item in stripped or item.lower() in lowered:
            hits.append(item)
    for word in WORD_RE.findall(lowered):
        if word in EN_WORD_HITS:
            hits.append(word)
    for pattern in (*FLOOD_PATTERNS, *WEAK_FLOOD_PATTERNS):
        found = pattern.search(stripped) or pattern.search(lowered)
        if found:
            hits.append(found.group(0))
    return tuple(dict.fromkeys(hits))


def _names_this_bot(text: str, bot_names: tuple[str, ...] = ()) -> bool:
    blob = (text or "").lower()
    if "机器人" in (text or "") or re.search(r"\bbot\b", blob):
        return True
    for name in bot_names:
        token = str(name or "").strip()
        if token and token.lower() in blob:
            return True
    return False


def _has_strong_flood_hit(text: str, strong: tuple[str, ...] | None = None) -> bool:
    stripped = text or ""
    lowered = stripped.lower()
    phrases = strong or STRONG_FLOOD_PHRASES
    if any(item in stripped or item.lower() in lowered for item in phrases):
        return True
    for word in WORD_RE.findall(lowered):
        if word in EN_WORD_HITS:
            return True
    return any(p.search(stripped) or p.search(lowered) for p in FLOOD_PATTERNS)


def _has_weak_flood_hit(text: str, weak: tuple[str, ...] | None = None) -> bool:
    stripped = text or ""
    lowered = stripped.lower()
    phrases = weak or WEAK_FLOOD_PHRASES
    if any(item in stripped or item.lower() in lowered for item in phrases):
        return True
    return any(p.search(stripped) or p.search(lowered) for p in WEAK_FLOOD_PATTERNS)


def looks_like_flood_complaint(
    text: str,
    *,
    mentioned: bool = False,
    bot_names: tuple[str, ...] = (),
    strong: tuple[str, ...] | None = None,
    weak: tuple[str, ...] | None = None,
) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if any(item in stripped or item.lower() in lowered for item in SKIP_PHRASES):
        return False
    if _has_strong_flood_hit(stripped, strong):
        return True
    if mentioned or _names_this_bot(stripped, bot_names):
        return _has_weak_flood_hit(stripped, weak)
    return False


def should_local_escalate(
    text: str,
    bot_names: tuple[str, ...],
    mentioned: bool,
) -> bool:
    """L1 漏判时：点名了这只号，或句子里点了它的名字，就仍交给终审。"""
    if mentioned:
        return True
    blob = (text or "").lower()
    for name in bot_names:
        token = str(name or "").strip()
        if token and token.lower() in blob:
            return True
    if "机器人" in (text or "") or re.search(r"\bbot\b", blob):
        return True
    return False


def build_qwen_grab_messages(
    *,
    text: str,
    bot_id: str,
    bot_names: tuple[str, ...],
    mentioned: bool,
    captured: str,
    hits: tuple[str, ...],
) -> tuple[str, str]:
    names = "、".join(item for item in bot_names if item) or "这只机器人"
    hit_line = "、".join(hits[:16]) or "无"
    system = (
        "你是第一级刷屏预审员。你的模型很小，只能做两件事："
        "1) 把最近群聊里和「这只机器人话多/刷屏/烦人」有关的句子抓出来；"
        "2) 粗判要不要交给上级终审。"
        "不要扮演群友，不要安慰，不要解答问题，不要输出 JSON 以外的字。"
        f"机器人标识是 {bot_id or '未知'}，提示里的名字有：{names}。"
        "BOT 开头的行才是这只机器人自己发的；USER 开头的行是群友。"
        "\n\n判断规则（必须按这个想）：\n"
        "A. 这句话是在抱怨「话多 / 刷屏 / 烦人 / 回太多 / 占屏 / 吵」这类，才可能是刷屏投诉。\n"
        "B. 投诉对象必须是这只机器人：@了它、点名配置里的名字、说「这机器人/你们机器人」，"
        "或对着它刚发的 BOT 气泡骂。骂群友、骂别的机器人、骂作业/广告，都不算。\n"
        "C. 「帮我总结/翻译/解释/整理这些消息」是在请它干活，不是投诉刷屏。\n"
        "D. 吃不准对象、吃不准是不是刷屏投诉时，escalate=false。"
        "只有比较明确是在抱怨这只机器人刷屏/话多时，才交给上级终审。"
        "不要因为本地语气词像「烦」就升级。\n"
        "\n字段：\n"
        "escalate=true 表示要交给上级终审。\n"
        "about_this_bot=true 表示投诉对象是这只号。\n"
        "flood_complaint=true 表示内容是话多/刷屏/烦人，不是总结请求。\n"
        "captured 用一句话摘录依据。reason 用十个字以内。"
        "\n\n示例（照着学，不要照抄当前消息）：\n"
        "1) 「@机器人 怎么这么烦人」→ "
        '{"escalate":true,"about_this_bot":true,"flood_complaint":true,'
        '"captured":"点名抱怨烦人","reason":"点名刷屏投诉"}\n'
        "2) 「这些消息怎么这么多，刷屏了吧」且上面有 BOT 连续发言 → "
        '{"escalate":true,"about_this_bot":true,"flood_complaint":true,'
        '"captured":"对着机器人气泡说刷屏","reason":"抱怨刷屏"}\n'
        "3) 「你能不能少回点」且点名了这只号 → "
        '{"escalate":true,"about_this_bot":true,"flood_complaint":true,'
        '"captured":"点名少回点","reason":"点名话多"}\n'
        "4) 「这机器人好烦啊一直在回」→ "
        '{"escalate":true,"about_this_bot":true,"flood_complaint":true,'
        '"captured":"这机器人好烦","reason":"说机器人烦"}\n'
        "5) 「帮我总结一下这些消息」→ "
        '{"escalate":false,"about_this_bot":true,"flood_complaint":false,'
        '"captured":"请求总结","reason":"在请它干活"}\n'
        "6) 「作业好烦啊」→ "
        '{"escalate":false,"about_this_bot":false,"flood_complaint":false,'
        '"captured":"抱怨作业","reason":"闲聊"}\n'
        "7) 「那个人话太多了」→ "
        '{"escalate":false,"about_this_bot":false,"flood_complaint":true,'
        '"captured":"说那个人","reason":"在说别人"}\n'
        "8) 「今晚吃什么」→ "
        '{"escalate":false,"about_this_bot":false,"flood_complaint":false,'
        '"captured":"闲聊","reason":"无关"}'
    )
    user = (
        f"机器人名字：{names}\n"
        f"是否@或回复了机器人：{'是' if mentioned else '否'}\n"
        f"本地命中的语气词：{hit_line}\n"
        "本地已经认为这句话很像刷屏投诉，你只做抓取和粗判，不要直接禁言。\n\n"
        "最近群聊（BOT=这只机器人，USER=群友）：\n"
        f"{captured or '（无）'}\n\n"
        f"当前消息：{(text or '')[:800]}\n\n"
        "只输出一行 JSON，不要 markdown，不要解释：\n"
        '{"escalate":true或false,"about_this_bot":true或false,'
        '"flood_complaint":true或false,"captured":"一句话摘录","reason":"简短原因"}'
    )
    return system, user


def build_deepseek_verdict_messages(
    *,
    text: str,
    bot_id: str,
    bot_names: tuple[str, ...],
    mentioned: bool,
    captured: str,
    qwen_raw: str,
    bot_spoke: bool,
    spoke_window_seconds: int,
) -> tuple[str, str]:
    names = "、".join(item for item in bot_names if item) or "这只机器人"
    system = (
        "你是上级总审核。第一级模型只负责抓取和粗判，它经常不敢下结论，也经常把闲聊误报上来。"
        "由你决定要不要禁言这只机器人。只输出 JSON，不要回答群友。"
        f"机器人标识是 {bot_id or '未知'}。提示名字：{names}。"
        "BOT 行才是这只机器人自己发的。"
        "\n\n禁言必须同时满足下面全部条件，缺一条就 mute=false：\n"
        "1. 在说这只机器人，不是群友、不是别的机器人、不是作业广告。"
        "依据可以是 @、点名配置里的名字、「这机器人」，或对着它刚发的 BOT 气泡骂。\n"
        "2. 内容是抱怨话多/刷屏/烦人/回太多/占屏，不是请它总结、翻译、解释、整理这些消息。\n"
        f"3. 近 {spoke_window_seconds} 秒内这只机器人发过言。"
        f"当前系统记录：{'是，这一条过了' if bot_spoke else '否，这一条没过，必须 mute=false'}。\n"
        "吃不准就 mute=false。第一级 escalate=true 不等于你必须禁言。"
        "\n\n示例：\n"
        "1) @机器人 怎么这么烦人，且 BOT 刚发过言 → "
        '{"mute":true,"about_this_bot":true,"reason":"点名抱怨刷屏"}\n'
        "2) 帮我总结这些消息 → "
        '{"mute":false,"about_this_bot":true,"reason":"在请它干活"}\n'
        "3) 那个人话太多了 → "
        '{"mute":false,"about_this_bot":false,"reason":"在说别人"}\n'
        "4) 作业好烦啊 → "
        '{"mute":false,"about_this_bot":false,"reason":"闲聊"}\n'
        "5) 机器人最近没发言 → "
        '{"mute":false,"about_this_bot":true,"reason":"窗口内没发言"}'
    )
    user = (
        f"是否@或回复了机器人：{'是' if mentioned else '否'}\n"
        f"近 {spoke_window_seconds} 秒内机器人发过言："
        f"{'是，可以禁' if bot_spoke else '否，不能禁'}\n\n"
        "第一级预审输出（仅供参考，对错由你裁定）：\n"
        f"{(qwen_raw or '')[:800]}\n\n"
        "最近群聊：\n"
        f"{captured or '（无）'}\n\n"
        f"当前消息：{(text or '')[:800]}\n\n"
        "只输出一行 JSON：\n"
        '{"mute":true或false,"about_this_bot":true或false,"reason":"简短原因"}'
    )
    return system, user


def parse_qwen_grab(text: str) -> tuple[bool, bool, bool, str]:
    payload = _parse_json_object(text)
    if payload:
        escalate = _as_bool(payload.get("escalate"))
        about = _as_bool(payload.get("about_this_bot"))
        flood = _as_bool(payload.get("flood_complaint"))
        reason = str(payload.get("reason") or payload.get("captured") or "").strip()
        # Stage-1 must set escalate itself; about+flood no longer auto-escalate.
        return bool(escalate and flood), bool(about), bool(flood), reason
    escalate = _flag_from_text(text, "escalate")
    about = _flag_from_text(text, "about_this_bot")
    flood = _flag_from_text(text, "flood_complaint")
    if escalate is None and about is None and flood is None:
        return False, False, False, "no json"
    escalate_v = bool(escalate)
    about_v = bool(about)
    flood_v = bool(flood)
    return bool(escalate_v and flood_v), about_v, flood_v, "loose parse"


def parse_deepseek_verdict(text: str) -> tuple[bool, str]:
    payload = _parse_json_object(text)
    if not payload:
        mute = _flag_from_text(text, "mute")
        about = _flag_from_text(text, "about_this_bot")
        if mute is None:
            return False, "no json"
        if not mute or about is not True:
            return False, "not about this bot" if mute else "loose parse"
        return True, "loose parse"
    mute = _as_bool(payload.get("mute"))
    about = payload.get("about_this_bot")
    reason = str(payload.get("reason") or "").strip()
    if not mute:
        return False, reason
    if not _as_bool(about):
        return False, reason or "not about this bot"
    return True, reason


def _strip_wrapper(text: str) -> str:
    cleaned = THINK_RE.sub("", text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _parse_json_object(text: str) -> dict | None:
    cleaned = _strip_wrapper(text)
    if not cleaned:
        return None
    try:
        loaded = json.loads(cleaned)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        snippet = cleaned[start : end + 1]
        try:
            loaded = json.loads(snippet)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass
    for match in reversed(list(JSON_RE.finditer(cleaned))):
        try:
            loaded = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            return loaded
    return None


def _flag_from_text(text: str, key: str) -> bool | None:
    cleaned = _strip_wrapper(text)
    if not cleaned:
        return None
    pattern = re.compile(
        rf'(?:["\']?{re.escape(key)}["\']?\s*[=:：]\s*)(true|false|是|否|1|0)',
        re.IGNORECASE,
    )
    match = pattern.search(cleaned)
    if not match:
        return None
    return _as_bool(match.group(1))


def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return True if value else False
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "是"}:
        return True
    if text in {"0", "false", "no", "n", "否"}:
        return False
    return default
