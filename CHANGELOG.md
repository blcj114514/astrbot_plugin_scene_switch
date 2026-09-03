# Changelog

## v1.15.2

- New persistent decision log ("debug log"): when `decision_log_enabled` is on, the plugin appends one JSON line per routing decision, judge call (with latency), blocked event (blocklist / silence / slap / flood mute / queue wait), `/scene` command and session-think change to `plugin_data/.../decision_log/decisions-YYYYMMDD.jsonl`, with daily rotation and automatic retention sweep (`decision_log_days`, default 7).
- Message text is never recorded by default; `decision_log_preview_chars` (default 0) optionally stores a truncated preview for debugging.
- New admin-only commands: `/scene stats` (per-scene usage today/total, decision-source breakdown, judge count/latency, blocked counts) and `/scene log [n]` (last n decisions, default 10, max 50). Visible to AstrBot admins or `flood_admin_ids`.
- Safe open-source defaults: logging off, preview off; log files are gitignored because they contain QQ ids.
- Marketplace identity: version 1.15.2, plugin logo (`logo.png`) added to the repo root.

## v1.15.1

- Main-chat thinking actually takes effect on OpenAI-compatible providers: AstrBot's `ProviderRequest` has no `reasoning_effort`, and the agent runner never copies a setattr on that request into `text_chat`. The plugin now wraps the current Provider so this turn's HTTP `extra_body.reasoning_effort` is set (still no native `think` / headers).
- Docs and schema no longer imply that writing `req.reasoning_effort` is enough. Tests now simulate the official runner drop and the extra_body merge order.
- Marketplace listing contact: QQ 1844372102 for plugin bugs only
- Marketplace Chinese display name: 多模型对话交互切换与管理

## v1.15.0

- Open-source defaults: plugin on, consent before switch, no instance Provider / admin / bot-name pins
- Public names only: builtin scenes (chat / code / search / vision / translate / write) and generic extra-scene samples such as 长文助手
- Full GNU AGPL v3 LICENSE text (GitHub license detection)
- Playground binds 127.0.0.1; LAN bind is refused when an API key is loaded
- Consent replies are explicit (同意 / 切换吧); 好 / 嗯 / ok no longer switch models
- Flood stage-2 never falls back to the chat Provider
- AstrBot hook tests for silence, flood L2 unbound, consent, blocklist, silenced LLM
- Wakeup words are configurable (contains / exact / regex), with deletable Chinese samples
- Group `@` + `开启思考 max|high|medium|low|none` sets session `reasoning_effort` only; no extra_body / HTTP headers / native `think`
- Scene Provider dropdowns list AstrBot official and custom providers; thinking dropdown defaults to `provider`
- Repo files: CONTRIBUTING, SECURITY, example extra scenes, GitHub issue template, CI pytest

## v1.14.1

- 本地刷屏语气词加厚，并补上变体正则；第一级审核只做抓取和粗判，提示词带示例，并把近几条群聊交给它看
- 第一级漏判或没吐出 JSON 时，点名/叫到这只号仍会上报
- 禁言改由上游 DeepSeek 总审核拍板；10 分钟内机器人没发过言仍不禁

## v1.14.0

- 群聊刷屏自检：本地语气词命中后，由配置的第一级模型确认是在说本机器人
- 确认之后再查 10 分钟内机器人有没有发过言；发过才自行截断
- 第一次验实禁言 3 分钟；30 分钟内第二次起长禁，只有管理员说「张嘴」才能解开

## v1.13.1

- 多人 `@` 时后到的人先收到一次「正在回复中，请稍后」，并等到当前回复结束才继续原消息
- 配文不再跟任意 `@`+图走：只有点名看图，或黏性已在看图场景，或用户说了看图口令才转文字

## v1.13.0

- 群里必须先 `@`（或回复机器人），并且明确说要切换/找某个场景/写代码，才会弹出同意；只喊场景名不会切
- 多人同时 `@` 时，排队的人各收到一次「正在回复中，请稍后」
- 去掉模型自己写的 `<quote>` 和正文里的 `@昵称`，避免引用错人和双 `@`

## v1.12.2

- 点名完整场景名（唤醒词 / 显示名）不再经过审判模型，避免被判成 keep 后看起来像切换失败
- 群里直接喊「某某助手出来 / 切到 xxx」也会弹出同意；短别名仍要 `@` 或回复机器人
- 回复机器人的消息视为点名；同意/不同意不再依赖群聊增强先发起 LLM

## v1.12.1

- 人机 QQ 号写入黑名单后直接丢弃，不进审判、不回复
- 群聊审判模型只在明确 `@`、点名默认场景，或群聊增强已经决定回复之后才调用

## v1.12.0

- 掌嘴词（闭嘴 / 别说话 / 别回了 等）改成跨插件硬拦截：确认一句后 10 分钟内不再回复，只有「张嘴」才解除；`@` 不会提前解禁
- 群聊未 `@` 且未点名默认场景时，不再因其它场景名或写代码意图弹出切换确认
- 失效的本机模型计划配置从运行配置里清掉

## v1.10.0

- 密钥：`.env` 继续 gitignore；报错打码；单测扫描已跟踪文件，避免把 Key 提交进仓库
- 插件只从 AstrBot 已有 Provider 下拉选择（DeepSeek / GPT / Ollama 等），不要求在插件里填模型 id 或 API Key
- 思考默认完全沿用该 Provider：审判 `classifier_reasoning_effort` 默认 `provider`，不再强行注入 Ollama 的 `none`
- 文档写明 Ollama `think` 与 `/v1` `reasoning_effort`、官方 DeepSeek `thinking.type` 不是同一套字段
- 可选覆盖思考时只写 OpenAI 形的 `reasoning_effort`，不再往 AstrBot 请求上挂 Ollama 原生 `think`

## v1.9.0

- 审判改为按会话（UMO）隔离：A 在打审判模型时，B 的消息仍会正常路由
- 审判调用加 12 秒超时（`classifier_timeout_seconds`），超时或失败回退本地启发式
- 会话状态 JSON 写入加锁，并发 `set_sticky` / `remember_scene` 不会丢掉另一个会话的键
- 场景思考覆盖默认关闭（`override_reasoning_effort=false`）：思考以 AstrBot Provider 为准；打开后才按场景档位、「认真想想」、`/scene think` 注入
- 审判模型仍用 `classifier_reasoning_effort=none`，和会话思考不是一条路

## v1.8.1

- 官方人设改为只写当前对话 `conversation.persona_id`（文档签名 `update_conversation`）
- 自定义规则里已经有强制人设时才覆盖 `session_service_config.persona_id`，不再新建强制规则，避免卡住 `/persona`
- 群聊默认不写官方人设（整群一份会串角色）；可打开 `sync_official_persona_in_groups`

## v1.8.0

- 切场景并换人设时，覆盖 AstrBot 官方会话人设（`conversation.persona_id`）
- 同时覆盖会话级强制人设（`session_service_config.persona_id`），避免旧角色挡住新的「人设 1」
- 其它插件读取官方人设栏目时会跟新角色走；其它插件的模型不会被改掉
- 内联 / 内置场景人设会登记为官方人设 `scene_switch_<场景>`，并在本轮清掉旧的 `# Persona Instructions`，防止角色打架
- `/scene use`、`/scene lock` 也会立刻写入官方人设
- 可用 `sync_official_persona` 关掉官方写入，只保留本轮提示词

## v1.7.0

- 自动切到某场景后短时黏住，下一句「那怎么修」仍用代码模型和编程助手
- 人设在换场景时明确接手，不再沿用上一轮语气；回复标签改成短的〔编程助手〕
- 点名切换的确认文案更短；`always` 标注只在场景真正换了时出现
- 试玩页映射卡固定六格，结果先给人看摘要

## v1.6.0

- 切换场景模型时同步换人设：闲聊伙伴 / 编程助手 / 检索 / 看图 / 翻译 / 写作编辑
- 只改本轮 `system_prompt`，不调用 AstrBot 会话人设接口，会话默认人设不会被永久改掉
- 每个场景可选用已有 AstrBot 人设、写内联人设，或填 `off` 关闭；全局可关 `switch_persona`
- 试玩页映射卡和路由结果展示当前人设

## v1.5.0

- 每个场景可配思考强度（闲聊 none、代码 high、写作 high）；审判默认 none
- 自然语言改档：「认真想想」→ max，「别想了直接答」→ none；`/scene think`
- 尽量把 `reasoning_effort` / `think` 写进本轮 LLM 请求，同一模型也能按场景分档
- 试玩页展示场景映射、思考过程；审判失败时回退本地启发式

## v1.4.0

- 接入 Ollama Cloud 真实模型目录（`GET /v1/models` 的实际 id）
- 审判默认关闭思考；代码场景可用更高思考档
- playground / `python -m scene_switch --live` 可直接打 Ollama，确认思考字段 `reasoning` / `thinking`
- playground 首屏写入 Ollama 连接状态，「让真实模型答一句」单独成行，避免旧页或折行漏掉

## v1.3.0

- 内置翻译、写作场景，和写代码分开
- 审判模型拿不准或未配置时，用本地启发式补一刀（例如「实现一个排序算法」）
- 增加 playground 试玩页，不启动 AstrBot 也能看会切到哪个模型

## v1.2.0

- 加入审判模型（审核 AI）：用轻量模型分析自然语言意图后再切场景
- 「我需要你帮我写代码」会先交给审判模型，再切到代码专用模型
- 问「有什么功能 / 有哪些模型可以切换」会直接介绍能力，不再进聊天模型
- `/scene help` 输出功能说明和可切换模型列表
- 未配置审判模型时自动退回关键词规则

## v1.1.0

- 锁定 / 黏性 / 最近场景写入 JSON，AstrBot 重启后仍能恢复
- 「继续」「详细点」等短句沿用上一场景
- 支持「帮我用 deepseek …」这类点名
- 目标 Provider 未加载时不再改写本轮请求
- 增加本地模拟器：`python -m scene_switch "用 deepseek 看报错"`
- 增加 GitHub Actions 跑单测

## v1.0.0

- 按场景 / 用户点名切换本轮 LLM Provider
- `/scene` 指令、WebUI 配置、规则路由与可选分类模型
