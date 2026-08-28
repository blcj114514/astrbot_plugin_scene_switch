# 场景模型切换 / Scene Switch

AstrBot 插件：按**对话场景**或用户点名，在**本轮**切换 LLM Provider 和人设。不改会话默认模型，不在插件里保存 API Key。

An AstrBot plugin that routes each incoming LLM request to a scene-specific provider and persona. It never writes API keys, and it never calls `set_provider` to change the session default.

当前版本 **v1.15.0** · 目标 AstrBot **≥ 4.10.4** · 许可证 **AGPL-3.0-only** · 作者 **le**

---

## 中文介绍

AstrBot 自带的 `/provider`、`/model` 只改当前会话的默认模型。这个插件挂在「即将进入 LLM」的请求上，改写本轮的 `selected_provider` 和人设：看报错走代码模型，陪聊走闲聊模型，点名自定义场景走你绑好的那条 Provider。会话默认模型保持不动，其它插件自己的模型配置也不会被改掉。

密钥和模型 id 都在 AstrBot 官方 Provider 页配置。插件配置里只用下拉框选出：闲聊 / 代码 / 搜索 / 看图 / 翻译 / 写作（以及你自己加的额外场景），再选一个便宜的**审判模型**（只判断场景，不回答用户）。DeepSeek、GPT、Ollama 及其它兼容接口都能接。

群聊默认要先 **@ 机器人**（或回复机器人的消息），再说「切换到某某」「帮我写代码」这类明确意图，才会弹出「是否同意切换」。同意之后才换模型和人设。

开源默认：**插件启用、切换前征求同意、刷屏自检关闭**。场景模型从 AstrBot 下拉框选（官方或你自己添加的 Provider）。思考强度默认 `provider`（不改各家请求头）。群里 `@` 后可发「开启思考 max」。唤醒词可设为包含 / 整句 / 正则，配置里有一套可删的中文样例。

### 功能清单

1. **自然语言审判**  
   「我需要你帮我写代码」「把这段翻译成英文」交给审判模型选场景。可超时（默认 12 秒）回退本地启发式；按会话隔离，A 在审判时不挡住 B。

2. **直接点名**  
   「用 deepseek 看这段报错」「切到闲聊模型」「切换到代码助手」。点名后会从用户原文清掉控制词再交给真正的聊天模型；整句只有「切到 xxx」时只确认切换，不再把空句子送给 LLM。

3. **征求同意**  
   开启后默认一直用默认场景（通常是闲聊）。只有点名或能力请求才会让审核 AI 判断，并发「是否同意」。支持同意等待超时、重复申请冷却、切换冷却。可限制为仅管理员能切。

4. **场景人设**  
   切模型的同时换人设。私聊可写入 AstrBot 官方会话人设；群聊默认只改本轮提示词，避免 A 切场景把整群官方人设也换掉。内联人设会登记为 `scene_switch_<场景>`。某个场景填 `off` 则不换人设。不改其它插件的模型。

5. **短时黏性**  
   点名或自动切到某场景后，接下来几轮（默认 3 轮 / 10 分钟）继续用它。群聊按「会话 + 发送者」隔离。遇到明确反方向话题会放开。

6. **会话锁定**  
   `/scene lock 代码` 之后不再自动跳；`/scene auto` 恢复自动。锁定记在插件自己的状态文件里，不是 AstrBot 会话默认模型。

7. **短句跟进**  
   「继续」「详细点」沿用上一场景。

8. **硬规则**  
   图片 / 文件 / 视频可默认走看图；代码块和报错栈走代码；带链接可倾向搜索（默认关）。问功能、问能切换哪些模型时直接介绍，不进聊天模型。

9. **额外场景**  
   六个内置场景之外可再加场景（见 `examples/custom_scenes.example.json`）。冲突 id 以额外场景为准。

10. **思考强度**  
    默认**不覆盖**，沿用各 Provider 在 AstrBot 里的配置。各家协议字段不同，乱注入会 400 或把思考写进正文。打开「覆盖思考强度」后，才按场景档位、自然语言「认真想想」、`/scene think` 注入 OpenAI 形的 `reasoning_effort`，且不写 Ollama 原生 `think`。

11. **掌嘴 / 张嘴**  
    整句明确说「闭嘴」「别回了」等（不是引用气泡、不是长句里碰巧出现这两个字）后确认一句，默认 10 分钟内不再回复。只有明确「张嘴」才解除。`@` 不会提前解禁。其它插件可通过共享的 `silence.json` 读取同一份静音状态。

12. **群聊刷屏自检**  
    本地命中明确刷屏词后：第一级模型只做粗判，必须再交给第二级总审核才禁言。弱语气词（「好烦」）必须点名或提到这只机器人。第一级失败且未点名则不禁。窗口内机器人没发过言不禁。第一次验实短禁（默认 3 分钟）；同一窗口再次验实则长禁，只有配置的管理员说「张嘴」才能解。

13. **群聊点名排队**  
    多人同时 `@` 时，后到的人先收到一次「正在回复中，请稍后」，等当前回复结束再继续原消息。

14. **看图配文门槛**  
    群图不会因为「随便 `@` + 一张图」就转文字。只有点名看图，或黏性已在看图场景，或用户说了「看这张 / 识图 / 看图」才配文。

15. **回复清洗**  
    去掉模型自己写的 `<quote>` 和正文里多余的 `@昵称`，减少引用错人和双 `@`。

16. **用户黑名单**  
    指定发送者 ID 的消息直接丢弃，不进审判、不回复。也可禁止调用某些人设名。

17. **尊重已指定 Provider**  
    若 WebUI、API 或其他插件已经设置 `selected_provider`，默认不覆盖。征求同意模式建议关掉这一项，否则其它插件抢先指定后无法切换。

18. **命令前缀跳过**  
    以 `/` `.` `!` 开头的消息不参与自动路由，避免干扰 AstrBot 指令。`/scene` 本身仍可用。

19. **不保存密钥**  
    插件配置里没有 API Key 字段。日志和报错会打码。单测会扫描已跟踪文件，避免把 Key 提交进仓库。

### 指令

| 指令 | 作用 |
| --- | --- |
| `/scene` | 当前锁定、黏性、最近场景 |
| `/scene help` | 功能介绍，以及可以切换哪些模型 |
| `/scene list` | 场景、别名、已加载 Provider |
| `/scene use 代码` | 点名切换并短时黏住 |
| `/scene lock 闲聊` | 本会话锁死在该场景 |
| `/scene auto` | 解除锁定，恢复自动 |
| `/scene think max` | 本会话思考强度（none/low/medium/high/max/auto） |

自然语言示例：

- `我需要你帮我写代码`
- `把这段翻译成英文`
- `帮我润色一下文案`
- `用 deepseek 看这段报错`
- `切换到代码助手`（需先 @，再回复同意）
- `有哪些模型可以切换`
- `闭嘴` / `张嘴`

### 安装

```bash
cd /path/to/AstrBot
mkdir -p data/plugins
cd data/plugins
git clone https://github.com/blcj114514/astrbot_plugin_scene_switch.git astrbot_plugin_scene_switch
```

也可以把本仓库文件夹复制到 `data/plugins/astrbot_plugin_scene_switch`。额外场景示例见 `examples/custom_scenes.example.json`。把仓库地址填进 `metadata.yaml` 的 `repo` 后，才能在插件市场里点到源码。

1. 重启 AstrBot，或在 WebUI 插件页重载该插件。
2. 打开插件配置，为闲聊 / 代码 / 搜索 / 看图 / 翻译 / 写作各选一个已经在 WebUI 里配好的 Provider。
3. 再选一个便宜的审判模型。不选则主要靠关键词和点名。
4. 按需打开「切换前征求同意」、刷屏自检、人设同步。
5. 发几句自测：`我需要你帮我写代码`、`有哪些模型可以切换`。

### 不会做的事

- 不在插件配置里保存 API Key，也不要求手填模型 id
- 不修改 AstrBot 本体
- 不调用 `set_provider` 去改会话默认模型
- 不改其它插件自己的模型配置，也不改它们插件配置里的人设下拉框
- 不在未配置 Provider 时请求外部 API
- 审判模型只判断场景，真正回答仍由各场景绑定的聊天模型完成

---

## English introduction

AstrBot’s built-in `/provider` and `/model` only change the **session default** model. This plugin rewrites `selected_provider` (and the persona) on **each LLM request**: debugging goes to a code model, small talk stays on a chat model, and naming an extra scene uses whatever provider you bound. The session default is left alone. Other plugins keep their own model settings.

API keys and model ids live in AstrBot’s official Provider page. In this plugin you only pick providers from dropdowns: chat / code / search / vision / translate / write, plus optional extra scenes, plus a cheap **classifier** that chooses a scene and never answers the user. Official DeepSeek, OpenAI, Ollama, and other compatible endpoints all work.

In groups, users must **@ the bot** (or reply to it) and clearly ask to switch or to use a capability before a consent prompt appears. The default persona stays until they agree.

Open-source defaults: plugin **on**, **consent required**, flood audit **off**. Bind AstrBot providers (official or custom) from dropdowns. Thinking effort defaults to `provider` (no extra_body / HTTP headers). After `@`, users can send `开启思考 max`. Wakeup matching is contains / exact / regex, with deletable Chinese sample words.

### Features

1. **Natural-language classification** — “help me write this function” is routed to the code scene. Per-session isolation, 12s timeout, heuristic fallback.
2. **Explicit naming** — “use deepseek on this traceback”, “switch to the chat model”. Control words are stripped before the chat model sees the prompt. A message that is only a switch request is acknowledged and not sent to the LLM.
3. **Consent gate** — **on by default**. Default scene until the user says yes. TTL, prompt cooldown, switch cooldown, optional admin-only switching.
4. **Scene personas** — switching a model can switch the persona. Private chats can write AstrBot’s official `persona_id`; groups default to this-turn prompt only so one user cannot retarget the whole group. Inline personas register as `scene_switch_<scene>`.
5. **Short sticky routing** — a few turns / minutes after a switch, keep that scene. Isolated per sender in groups. Opposite-topic phrases release it.
6. **Session lock** — `/scene lock code` stops auto-routing. Stored in the plugin’s own state file, not via `set_provider`.
7. **Follow-ups** — short phrases like “continue” reuse the last scene.
8. **Hard rules** — media can go to vision; code fences / stack traces to code; links optionally to search. “What can you do?” is answered from help text, not the chat model.
9. **Custom scenes** — extra scenes beyond the six builtins (id collision: extra scene wins).
10. **Reasoning effort** — scene dropdown defaults to `provider` (no extra_body / headers). After `@`, `开启思考 max` sets session `reasoning_effort` only. Optional global overlay still exists.
11. **Silence commands** — whole-message “shut up” (not quote bubbles, not accidental substrings) mutes replies for 10 minutes. Only an explicit “speak again” command lifts it. `@` does not unmute. Other plugins can read the same `silence.json`.
12. **Group flood self-check** — local phrase hit → stage-1 coarse judge → stage-2 must confirm before mute. Weak complaints require addressing this bot. No mute if stage-1 fails without a mention, or if the bot has not spoken in the window. First hit: short mute; repeat in the window: long lock until an admin speak-command.
13. **Mention queue** — concurrent `@` in one group: waiters get one “please wait” notice, then their original message continues.
14. **Caption gate** — group images are captioned only when the user `@`s and asks to look / names a vision scene, or sticky is already on vision.
15. **Reply sanitizing** — strips model-emitted `<quote>` tags and extra `@nickname` text.
16. **Sender blocklist** — dropped before classify/reply. Optional blocked persona names.
17. **Honor existing selection** — if another plugin already set `selected_provider`, do not overwrite (turn this off when using consent mode).
18. **Skip command-like messages** — `/` `.` `!` prefixes skip auto-routing; `/scene` still works.
19. **No secrets in the plugin** — keys stay in AstrBot providers or a gitignored `.env` for the optional playground. Logs are redacted; tests scan tracked files.

### Commands

| Command | Effect |
| --- | --- |
| `/scene` | Lock, sticky, last scene |
| `/scene help` | Feature intro and switchable models |
| `/scene list` | Scenes, aliases, loaded providers |
| `/scene use code` | Named switch + sticky |
| `/scene lock chat` | Lock this session to a scene |
| `/scene auto` | Unlock, resume auto routing |
| `/scene think max` | Session thinking level (`none` / `low` / `medium` / `high` / `max` / `auto`) |

### Install

```bash
cd /path/to/AstrBot
mkdir -p data/plugins
cd data/plugins
git clone https://github.com/blcj114514/astrbot_plugin_scene_switch.git astrbot_plugin_scene_switch
```

Keep the folder name `astrbot_plugin_scene_switch`. Reload the plugin in WebUI, bind one Provider per builtin scene, pick a cheap classifier, then try “help me write some code” and “which models can I switch to”.

### Non-goals

- No API keys or raw model ids in plugin config
- No patches to AstrBot core
- No `set_provider` on the session default
- No edits to other plugins’ model or persona dropdowns
- No outbound API calls when providers are unbound
- The classifier only chooses a scene; the bound chat model answers

---

## 思考强度字段（各家不一样） / Reasoning fields

插件默认不覆盖思考强度。需要按场景改档时，打开配置里的「覆盖思考强度」，并且仍建议优先在 AstrBot Provider 里配好各家字段。

| Path | Disable thinking | Enable / scale | Where thoughts land |
| --- | --- | --- | --- |
| Any AstrBot Provider | Configure on that Provider | Configure on that Provider | Plugin does not touch it |
| Ollama native `/api/chat` | `think: false` | `think: true` or `low` / `medium` / `high` / `max` | `message.thinking` |
| Ollama OpenAI `/v1` | `reasoning_effort: "none"` | `low` / `medium` / `high` / `max` | `message.reasoning` |
| Official DeepSeek Chat Completions | `extra_body.thinking.type = disabled` | `type = enabled`, plus top-level `reasoning_effort`: `low` / `high` / `max` | `reasoning_content` |
| OpenAI reasoning models | Provider `reasoning_effort` | `low` / `medium` / `high` | Official reasoning field |

Notes:

- Ollama `/v1` **must not** send native `think` (boolean → 400). Native `/api/chat` **must not** send `think: "none"` (use `false`).
- Official DeepSeek **must not** use `"none"` to disable thinking; that is the Ollama `/v1` spelling. Use `thinking.type=disabled`.
- GPT-OSS on Ollama only accepts `low` / `medium` / `high`.
- AstrBot’s official `ProviderRequest` has no `extra_body`. Even with override on, the plugin only writes OpenAI-style `reasoning_effort`. It will **not** attach Ollama native `think`.

The classifier defaults to `classifier_reasoning_effort=provider` as well.

---

## 判定顺序 / Routing order

1. User names a scene or provider  
2. `/scene lock`  
3. Short sticky after a switch (per sender in groups)  
4. Short follow-up phrases  
5. Help / “which models” → intro text, no chat model  
6. Hard rules: media → vision, code/tracebacks → code  
7. Classifier LLM (if configured)  
8. Keyword fallback  
9. Keep current default if still unsure  

---

## 配置要点 / Config highlights

- **Classifier mode**: `llm_for_language` (recommended), `rules_then_llm`, or `rules_only`.
- **Consent**: recommended for busy groups. Combine with `@` / reply-to-bot.
- **Flood audit**: bind a cheap stage-1 provider and a stronger stage-2 verifier. Fill bot display names and admin ids for long-lock unmute. Leave empty to disable.
- **Model aliases**: `deepseek=code` means “use deepseek” routes to the code scene’s provider.
- **Official persona sync**: on for private chats by default; off for groups by default.

Do not put API keys in plugin config, chat, screenshots, issues, or `ollama_catalog.json`. `.env` is gitignored; the repo only ships `.env.example`.

---

## 可选试玩页 / Optional playground (not the install path)

Local routing demo without AstrBot. Other users should **not** use this as the setup path.
The server binds **127.0.0.1** only. It has **no login**. If `.env` contains `OLLAMA_API_KEY`,
a LAN bind is refused so the key cannot be used from other machines.

```bash
cp .env.example .env   # local secrets only, never commit
python playground/server.py
```

Open http://127.0.0.1:43187 . Without a key, routing is heuristic-only. Do not pass `--host 0.0.0.0` when a key is present.

```bash
python -m pytest
```

---

## 密钥 / Secrets

- Keys belong in AstrBot Provider config, or a local gitignored `.env` for the playground.
- Do not paste keys into chat, screenshots, issues, plugin config, or catalogs.
- Logs and errors are redacted. Tests scan tracked files so keys do not land in git.

## 发布 / Publishing

1. Create a public GitHub (or other) repository named `astrbot_plugin_scene_switch`.
2. Put the clone URL in `metadata.yaml` → `repo`.
3. `git push -u origin main`.
4. Submit the plugin to the AstrBot market if you want it listed.

This working copy is a complete git repo with history starting at v1.15.0. Cursor Origin hosting is not available on native Windows; use GitHub or another host.

## 许可 / License

GNU Affero General Public License v3.0 only. AstrBot itself is AGPL-3.0.
