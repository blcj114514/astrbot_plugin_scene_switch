<div align="center">

<img src="logo.png" width="160" alt="Scene Switch logo" />

# 多模型对话交互切换与管理 / Scene Switch

**按对话场景或点名，在「本轮」切换 LLM 与人设的 AstrBot 插件**

[![Version](https://img.shields.io/badge/版本-1.15.2-blue)](CHANGELOG.md)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.10.4-green)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/许可证-AGPL--3.0--only-orange)](LICENSE)
[![Tests](https://img.shields.io/badge/测试-pytest%20170%E2%9C%93-brightgreen)](#开发与测试)

</div>

AstrBot 插件：按**对话场景**或用户点名，在**本轮**切换 LLM Provider 和人设。不改会话默认模型，不在插件里保存 API Key。

An AstrBot plugin that routes each incoming LLM request to a scene-specific provider and persona. It never writes API keys, and never calls `set_provider` to change the session default.

---

## 它解决什么问题 / Why

AstrBot 自带的 `/provider`、`/model` 只改**当前会话的默认模型**。这个插件挂在「即将进入 LLM」的请求上，改写**本轮**的 `selected_provider` 和人设：看报错走代码模型，陪聊走闲聊模型，点名自定义场景走你绑好的那条 Provider。会话默认模型不动，其它插件自己的模型配置也不受影响。

密钥和模型 id 都留在 AstrBot 官方 Provider 页。插件配置里只用下拉框选出：闲聊 / 代码 / 搜索 / 看图 / 翻译 / 写作（以及你自定义的额外场景），再选一个便宜的**审判模型**（只判断场景，不回答用户）。DeepSeek、OpenAI、Ollama 及其它兼容接口都能接，**本地模型（LM Studio / Ollama 等）也一样即插即用**。

群聊默认要先 **@ 机器人**（或回复它），再说「切换到某某」「帮我写代码」这类明确意图，才会弹出「是否同意切换」；同意之后才换模型和人设。

开源默认：**插件启用、切换前征求同意、刷屏自检关闭**。思考强度默认 `provider`（不改各家请求头）。唤醒词匹配支持包含 / 整句 / 正则，配置里带一套可删的中文样例。

## 功能亮点 / Highlights

| 分类 | 能力 |
| --- | --- |
| **智能路由** | 自然语言审判（超时回退本地启发式，按会话隔离）、直接点名、短时黏性、会话锁定、短句跟进、硬规则（媒体→看图 / 报错→代码）、六个内置场景 + 无限自定义场景 |
| **群聊体验** | @ 门槛与征求同意、掌嘴/张嘴静音、两级刷屏自检、多人 @ 排队、看图配文门槛、回复清洗（去 `<quote>` / 多余 @）、发送者黑名单 |
| **人设与思考** | 切模型同时换人设（群聊只改本轮，不整群换脸）；思考档位打进本轮 OpenAI 兼容 `extra_body.reasoning_effort`，不写各家私有字段 |
| **运维与安全** | 决策日志与使用统计（`/scene stats`、`/scene log`）、Playground 本地试玩、全程不保存 API Key、单测扫描防密钥入库 |

### 功能明细 / Features

1. **自然语言审判** — 「我需要你帮我写代码」交给审判模型选场景。可超时（默认 12 秒）回退本地启发式；按会话隔离，A 在审判时不挡住 B。
2. **直接点名** — 「用 deepseek 看这段报错」「切到闲聊模型」。点名后控制词会从原文清掉再交给聊天模型；整句只有「切到 xxx」时只确认切换，不发空句子。
3. **征求同意** — 开启后默认一直用默认场景，点名或能力请求才弹「是否同意」。支持同意超时、重复申请冷却、切换冷却，可限制仅管理员能切。
4. **场景人设** — 切模型同时换人设。私聊可写入 AstrBot 官方会话人设；群聊默认只改本轮提示词，避免一个人把整群官方人设换掉。内联人设登记为 `scene_switch_<场景>`，填 `off` 则不换。
5. **短时黏性** — 点名或自动切到某场景后，接下来几轮（默认 3 轮 / 10 分钟）继续用它；群聊按「会话 + 发送者」隔离，明确反方向话题会放开。
6. **会话锁定** — `/scene lock 代码` 之后不再自动跳；`/scene auto` 恢复。锁定记在插件自己的状态文件里，不是会话默认模型。
7. **短句跟进** — 「继续」「详细点」沿用上一场景。
8. **硬规则** — 图片/文件/视频可默认走看图；代码块和报错栈走代码；带链接可倾向搜索（默认关）。问功能、问能切哪些模型时直接介绍，不进聊天模型。
9. **额外场景** — 六个内置场景之外可再加（见 `examples/custom_scenes.example.json`），id 冲突以额外场景为准。
10. **思考强度** — 默认**不覆盖**，沿用各 Provider 自己的配置。群里 @ 后「开启思考 max」或 `/scene think` **不依赖**「覆盖思考强度」。AstrBot 官方 `ProviderRequest` 没有 `reasoning_effort` 字段、agent runner 也不会把 `setattr` 的属性带进 `text_chat`——插件包一层当前 OpenAI 兼容 Provider，把本轮 HTTP `extra_body.reasoning_effort` 设为该档位（能盖过 Provider 的 `custom_extra_body`）。仍不写 Ollama 原生 `think`、DeepSeek `thinking.type`、HTTP 请求头。
11. **掌嘴 / 张嘴** — 整句明确说「闭嘴」「别回了」（不是引用气泡、不是长句里碰巧出现）后确认一句，默认 10 分钟不再回复；只有「张嘴」解除，`@` 不能提前解禁。其它插件可读共享的 `silence.json`。
12. **群聊刷屏自检** — 本地命中刷屏词后，第一级模型粗判，必须再交第二级总审核才禁言；弱语气词必须点名机器人；窗口内机器人没发言不禁；首犯短禁（默认 3 分钟），再犯长禁，只有配置的管理员说「张嘴」能解。**二级禁止回落到聊天模型**。
13. **群聊点名排队** — 多人同时 @ 时，后到的人先收到一次「正在回复中，请稍后」，当前回复结束后继续原消息。
14. **看图配文门槛** — 群图不会因为「随便 @ + 一张图」就转文字；只有点名看图、黏性已在看图，或说了「看这张 / 识图 / 看图」才配文。
15. **回复清洗** — 去掉模型自己写的 `<quote>` 和正文里多余的 `@昵称`。
16. **用户黑名单** — 指定发送者 ID 直接丢弃，不进审判、不回复；也可禁止调用某些人设名。
17. **尊重已指定 Provider** — 其它插件已设 `selected_provider` 时默认不覆盖（征求同意模式建议关掉这项，否则抢跑后切不动）。
18. **命令前缀跳过** — `/` `.` `!` 开头的消息不参与自动路由，`/scene` 仍可用。
19. **不保存密钥** — 插件配置没有 API Key 字段；日志和报错打码；单测扫描已跟踪文件防止密钥入库。
20. **决策日志（v1.15.2 新增）** — 开启后按天写 JSONL 决策日志：每条消息判成哪个场景、判定来源（点名/审判/关键词/黏性/命令…）、审判耗时、拦截事件（静音/黑名单/刷屏/排队）、思考档位。管理员可用 `/scene stats` 看使用统计、`/scene log` 看最近决策，排错不用再翻控制台。**默认不记消息原文**，预览字数默认 0，日志文件请勿提交进 git。

## 指令 / Commands

| 指令 | 作用 |
| --- | --- |
| `/scene` | 当前锁定、黏性、最近场景 |
| `/scene help` | 功能介绍，以及可切换哪些模型 |
| `/scene list` | 场景、别名、已加载 Provider |
| `/scene use 代码` | 点名切换并短时黏住 |
| `/scene lock 闲聊` | 本会话锁死在该场景 |
| `/scene auto` | 解除锁定，恢复自动 |
| `/scene think max` | 本会话思考强度（none/low/medium/high/max/auto） |
| `/scene stats` | 决策统计：场景使用、判定来源、审判耗时、拦截（管理员，需开决策日志） |
| `/scene log 10` | 最近 10 条决策日志（管理员，默认 10 条，上限 50） |

自然语言示例：`我需要你帮我写代码` · `把这段翻译成英文` · `帮我润色一下文案` · `用 deepseek 看这段报错` · `切换到代码助手`（需先 @，再回复同意）· `有哪些模型可以切换` · `闭嘴` / `张嘴`

## 安装 / Install

**方式一：插件市场**（推荐）— AstrBot WebUI 插件市场搜索 `astrbot_plugin_scene_switch`，或到 [cloud.astrbot.app](https://cloud.astrbot.app) 搜索安装。

**方式二：从仓库地址安装** — AstrBot WebUI → 插件页 → 从仓库安装，填：

```
https://github.com/blcj114514/astrbot_plugin_scene_switch
```

**方式三：git clone**

```bash
cd /path/to/AstrBot/data/plugins
git clone https://github.com/blcj114514/astrbot_plugin_scene_switch.git astrbot_plugin_scene_switch
```

装好后（或复制文件夹到 `data/plugins/astrbot_plugin_scene_switch` 后）：

1. 在 WebUI 插件页重载或重启 AstrBot。
2. 打开插件配置，为闲聊 / 代码 / 搜索 / 看图 / 翻译 / 写作各选一个已配好的 Provider。
3. 选一个便宜的**审判模型**（不选则主要靠关键词和点名）。
4. 按需打开「切换前征求同意」、刷屏自检、人设同步；想要决策日志就打开「记录路由决策日志」。
5. 发几句自测：`我需要你帮我写代码`、`有哪些模型可以切换`，再 `/scene stats` 看统计。

## 决策日志与隐私 / Decision log & privacy

- 日志写在插件数据目录 `decision_log/decisions-YYYYMMDD.jsonl`，按天滚动，`decision_log_days`（默认 7 天）自动清理。
- 记录的是**决策元数据**（场景、来源、耗时、会话与发送者 id、拦截事件），**默认不记消息原文**；`decision_log_preview_chars` 默认 0，设为 30–50 才会记截断预览。
- `/scene stats`、`/scene log` 仅管理员（AstrBot 管理员或刷屏管理员名单）可用。
- 日志含 QQ 号，**不要提交进 git、不要贴到公开场合**。

## 不会做的事 / Non-goals

- 不在插件配置里保存 API Key，也不要求手填模型 id
- 不修改 AstrBot 源码（可为了本轮 `reasoning_effort` 包一层当前 Provider 实例）
- 不调用 `set_provider` 去改会话默认模型
- 不改其它插件自己的模型配置和人设下拉框
- 不在未配置 Provider 时请求外部 API
- 审判模型只判断场景，真正回答仍由各场景绑定的聊天模型完成

## 思考强度字段（各家不一样） / Reasoning fields

AstrBot 4.x 主聊天路径不会读取 `ProviderRequest.reasoning_effort`：官方请求对象没有该字段，agent runner 组 `text_chat` 时只拷贝固定键。插件因此包一层当前 Provider：在 `_apply_provider_specific_request_overrides` 之后把本轮 `extra_body.reasoning_effort` 写上（能盖过 Provider 配置里的 `custom_extra_body` 和「关闭思考」）。仍然**不写** Ollama 原生 `think`、DeepSeek `thinking.type`、HTTP 请求头。

| Path | 关思考 | 开 / 调档 | 思考内容落点 |
| --- | --- | --- | --- |
| 任意 AstrBot Provider | 在该 Provider 里配 | 会话思考 / 覆盖写本轮 `extra_body.reasoning_effort`（OpenAI 兼容适配器） | 插件不写原生 `think` |
| Ollama 原生 `/api/chat` | `think: false` | `think: true` 或 `low`/`medium`/`high`/`max` | `message.thinking` |
| Ollama OpenAI `/v1` | `reasoning_effort: "none"` | `low`/`medium`/`high`/`max` | `message.reasoning` |
| DeepSeek 官方 Chat Completions | `extra_body.thinking.type = disabled` | `type = enabled` + 顶层 `reasoning_effort`：`low`/`high`/`max` | `reasoning_content` |
| OpenAI 推理模型 | Provider 里配 `reasoning_effort` | `low`/`medium`/`high` | 官方推理字段 |

注意：Ollama `/v1` **不能**发原生 `think`（布尔会 400）；原生 `/api/chat` **不能**用 `think: "none"`；DeepSeek 官方**不能用** `"none"` 关思考（那是 Ollama `/v1` 的写法，要用 `thinking.type=disabled`）；GPT-OSS on Ollama 只认 `low`/`medium`/`high`。

## 判定顺序 / Routing order

已指定 Provider（若开启尊重）→ 掌嘴/黑名单 → 会话锁定 → 点名 → 短时黏性 → 短句跟进 → 帮助/介绍 → 硬规则（图/代码/链接）→ 审判模型 → 本地启发式 → 仍不确定则保持默认场景。

## 配置要点 / Config highlights

- **审判模式**：`llm_for_language`（推荐）、`rules_then_llm`、`rules_only`。
- **征求同意**：热闹群建议开启，配合 @ / 回复机器人门槛。
- **刷屏自检**：一级绑便宜 Provider，二级绑更强的总审核；填机器人显示名和管理员 id 用于长禁解禁。留空即关闭。
- **模型别名**：`deepseek=code` 表示说「用 deepseek」会路由到代码场景绑定的 Provider。
- **官方人设同步**：私聊默认开，群聊默认关。

## 可选试玩页 / Playground（不是安装路径）

不装 AstrBot 也能点路由规则的本地试玩页。服务器只绑 **127.0.0.1**、无登录；若 `.env` 里有 `OLLAMA_API_KEY`，会拒绝绑定局域网地址。

```bash
cp .env.example .env   # 本地密钥，永不提交
python playground/server.py   # 打开 http://127.0.0.1:43187
```

## 开发与测试 / Development

```bash
python -m pytest
```

改动后请至少跑 `tests/test_secrets.py`（实例标识与密钥扫描）和 `tests/test_think.py`（思考注入）。

## 反馈 / Support

插件问题或 bug 请用 QQ **1844372102** 联系。请只为这个插件的问题来找，不要闲聊加好友。

GitHub issues 也欢迎：不要贴 API Key、token 或无关账号 id。

## 许可 / License

GNU Affero General Public License v3.0 only（AGPL-3.0-only）。AstrBot 本身也是 AGPL-3.0。