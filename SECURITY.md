# Security

Do not put API keys, tokens, or account ids in plugin config, issues, screenshots, or `ollama_catalog.json`.

- Keys belong in AstrBot Provider config, or a local gitignored `.env` for the playground.
- The playground listens on 127.0.0.1 and has no login. Do not bind it on a LAN when a key is set.
- This plugin never stores provider secrets in `_conf_schema.json`.
- If you find a secret in a commit, rotate it and open an issue without pasting the secret.

报告漏洞时请不要附带有效密钥。
