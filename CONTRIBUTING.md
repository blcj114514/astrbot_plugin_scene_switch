# Contributing

中文 / English below.

## 中文

感谢你愿意改这个插件。提 PR 前请：

1. 不要提交 API Key、`.env`、QQ 号、本机 Provider id。
2. 默认值保持可移植：征求同意默认开，刷屏默认关，思考强度默认 `provider`。
3. 在仓库根目录运行 `python -m pytest`。
4. 新行为请补单测，并更新 `CHANGELOG.md`。

议题请说明 AstrBot 版本、适配器（如 aiocqhttp）、以及是否开启了征求同意。

## English

Please do not commit secrets, QQ numbers, or machine-specific Provider ids.

Keep portable defaults: consent on, flood audit off, thinking effort `provider`.

Run `python -m pytest` at the repo root before opening a pull request. Add tests and a changelog line for new behavior.
