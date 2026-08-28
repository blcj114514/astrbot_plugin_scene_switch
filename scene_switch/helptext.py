"""User-facing help / capability copy."""

from __future__ import annotations

from .settings import PluginSettings

SCENE_INTRO = {
    "chat": "日常闲聊、陪伴、短回复",
    "code": "写代码、改代码、看报错、重构",
    "search": "搜资料、看热点、查新闻",
    "vision": "看图、截图、识别图片内容",
    "translate": "翻译、英译中、中译英",
    "write": "润色、改写、写文案和作文",
}


def build_feature_intro(
    settings: PluginSettings,
    *,
    loaded_providers: tuple[str, ...] = (),
    judge_ready: bool = False,
) -> str:
    think_cap = (
        "3. 思考强度：群里 @ 后发「开启思考 max」或「关闭思考」；"
        "也可 /scene think max。会把本轮 OpenAI 兼容请求的 extra_body."
        "reasoning_effort 设为该档位，不写 Ollama 原生 think。"
        "打开「覆盖思考强度」才会按场景档位注入。"
    )
    think_cmd = "/scene think max — 本会话思考强度（none/low/medium/high/max/auto）"
    lines = [
        "我是场景模型切换插件。群里要先 @，再说「切换到某某」或「帮我写代码」，同意后才会换模型和人设。可以说「开启思考 max」。群友抱怨刷屏时（若已开启刷屏自检）会自行静音，说「张嘴」继续。",
        "",
        "主要能力：",
        "1. 自然语言审判：像「我需要你帮我写代码」会识别成写代码，切到代码模型。",
        "2. 直接点名：说「用 deepseek 看这段报错」「切到闲聊模型」。",
        think_cap,
        "4. 场景人设：切到代码模型时变成编程助手，切到闲聊时变成闲聊伙伴。私聊会覆盖 AstrBot 官方会话人设；群聊默认只改本轮。不改其它插件的模型。",
        "5. 短时黏性：点名或自动切到某个场景后，接下来几轮继续用它；群聊按人隔离。明确换话题才会放开。",
        "6. 会话锁定：/scene lock 代码 之后不再自动跳。",
        "7. 短句跟进：「继续」「详细点」沿用上一场景。",
        "8. 翻译 / 写作场景：译成英文、润色文案会切到对应模型。",
        "",
        "当前可切换的场景：",
    ]
    enabled = False
    for scene in settings.scenes.values():
        intro = SCENE_INTRO.get(scene.id, "自定义场景")
        aliases = "、".join(scene.aliases[:6])
        if scene.enabled:
            enabled = True
            extra = f"别名 {aliases}；" if aliases else ""
            if settings.override_reasoning_effort:
                think = f"思考 {scene.reasoning_effort or '沿用 Provider'}；"
            else:
                think = "思考沿用 Provider；"
            persona = ""
            if settings.switch_persona and (scene.persona_prompt or scene.persona_id):
                persona = f"人设 {scene.persona_label or scene.persona_id}；"
            lines.append(
                f"- {scene.display_name}（{scene.id}）→ {scene.provider_id}。{extra}{think}{persona}{intro}。"
            )
        else:
            lines.append(f"- {scene.display_name}（{scene.id}）还未配置模型，暂不可切换。")
    if not enabled:
        lines.append("还没有场景绑定 Provider。请先在插件配置里为闲聊 / 代码 / 搜索 / 看图 / 翻译 / 写作各选一个模型。")

    if settings.model_aliases:
        pairs = "、".join(f"{key}→{value}" for key, value in list(settings.model_aliases.items())[:10])
        lines.append("")
        lines.append(f"点名别名：{pairs}")

    lines.append("")
    if judge_ready:
        lines.append(f"审判模型：已启用（{settings.classifier_provider_id}），会分析自然语言再选场景。")
    else:
        lines.append("审判模型：还没选。现在主要靠关键词和点名；请在插件配置里选择一个便宜的「审判模型」。")

    if loaded_providers:
        lines.append("AstrBot 已加载的 Provider：" + "、".join(loaded_providers))

    examples = [
        "- 我需要你帮我写代码",
        "- 把这段翻译成英文",
        "- 帮我润色一下文案",
        "- 用 deepseek 看这段报错",
    ]
    if settings.override_reasoning_effort:
        examples.extend(
            [
                "- 认真想想怎么写这个函数",
                "- 别想了，把这段翻译成英文",
            ]
        )
    examples.extend(
        [
            "- 开启思考 max",
            "- 关闭思考",
            "- 切到闲聊模型",
            "- 有哪些模型可以切换",
        ]
    )
    lines.extend(
        [
            "",
            "常用说法：",
            *examples,
            "",
            "指令：",
            "/scene — 当前状态",
            "/scene list — 场景和模型列表",
            "/scene help — 本段介绍",
            "/scene use 代码 — 点名切换",
            "/scene lock 闲聊 — 锁定",
            "/scene auto — 恢复自动",
            think_cmd,
        ]
    )
    return "\n".join(lines)
