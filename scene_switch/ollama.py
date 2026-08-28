"""Ollama Cloud OpenAI-compatible client (stdlib only)."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_BASE = "https://ollama.com/v1"
CATALOG_PATH = Path(__file__).with_name("ollama_catalog.json")

_OPENAI_EFFORT = {
    False: "none",
    True: "high",
    "false": "none",
    "true": "high",
    "off": "none",
    "none": "none",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "max": "max",
}

_NATIVE_THINK: dict[Any, Any] = {
    False: False,
    True: True,
    "false": False,
    "true": True,
    "off": False,
    "none": False,
    "low": "low",
    "medium": "medium",
    "high": "high",
    "max": "max",
}


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatResult:
    content: str
    reasoning: str = ""
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def openai_effort(value: Any) -> str:
    if value is None or value == "":
        return "none"
    if isinstance(value, str):
        key: Any = value.strip().lower()
    else:
        key = value
    if key not in _OPENAI_EFFORT:
        raise OllamaError(f"unsupported reasoning_effort: {value!r}")
    return _OPENAI_EFFORT[key]


def native_think(value: Any) -> Any:
    if value is None or value == "":
        return False
    if isinstance(value, str):
        key: Any = value.strip().lower()
    else:
        key = value
    if key not in _NATIVE_THINK:
        raise OllamaError(f"unsupported think: {value!r}")
    return _NATIVE_THINK[key]


def load_dotenv(*paths: Path) -> None:
    for path in paths:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    target = path or CATALOG_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def settings_dict_from_catalog(catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    from .heuristic import PHRASES
    data = catalog or load_catalog()
    scenes = data.get("scenes") or {}
    aliases = data.get("aliases") or {}
    alias_lines = "\n".join(f"{key}={value}" for key, value in aliases.items())
    extra = "\n".join(
        [
            "gpt=chat",
            "chatgpt=chat",
            "闲聊=chat",
            "代码=code",
            "编程=code",
            "搜索=search",
            "看图=vision",
            "翻译=translate",
            "写作=write",
            "润色=write",
        ]
    )
    judge = data.get("judge") or {}
    out: dict[str, Any] = {
        "classifier_mode": "llm_for_language",
        "classifier_provider_id": str(judge.get("model") or ""),
        "classifier_reasoning_effort": str(judge.get("reasoning_effort") or "none"),
        "announce_switch": "always",
        "model_aliases": f"{alias_lines}\n{extra}",
    }
    for scene_id, spec in scenes.items():
        if not isinstance(spec, dict):
            continue
        out[scene_id] = {
            "provider_id": str(spec.get("model") or ""),
            "aliases": str(spec.get("label") or scene_id),
            "keywords": "\n".join(PHRASES.get(scene_id, ())),
            "reasoning_effort": str(spec.get("reasoning_effort") or ""),
        }
    return out


def catalog_provider_ids(catalog: dict[str, Any] | None = None) -> tuple[str, ...]:
    data = catalog or load_catalog()
    models = [str(item) for item in (data.get("models") or []) if item]
    scenes = data.get("scenes") or {}
    for spec in scenes.values():
        if isinstance(spec, dict) and spec.get("model"):
            mid = str(spec["model"])
            if mid not in models:
                models.append(mid)
        if isinstance(spec, dict) and spec.get("alt"):
            alt = str(spec["alt"])
            if alt not in models:
                models.append(alt)
    judge = data.get("judge") or {}
    if judge.get("model") and str(judge["model"]) not in models:
        models.append(str(judge["model"]))
    return tuple(models)


def resolve_credentials() -> tuple[str, str]:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(Path.cwd() / ".env", root / ".env")
    key = (os.environ.get("OLLAMA_API_KEY") or os.environ.get("OLLAMA_KEY") or "").strip()
    base = (os.environ.get("OLLAMA_BASE_URL") or DEFAULT_BASE).strip().rstrip("/")
    return key, base


def extract_message_text(message: dict[str, Any] | None) -> tuple[str, str]:
    msg = message or {}
    content = msg.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        content = "".join(parts)
    content_s = str(content or "")
    reasoning = (
        msg.get("reasoning")
        or msg.get("reasoning_content")
        or msg.get("thinking")
        or ""
    )
    return content_s, str(reasoning or "")


class OllamaClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE, timeout: int = 90) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._ssl = ssl.create_default_context()

    def __repr__(self) -> str:
        return f"OllamaClient(base_url={self.base_url!r}, api_key='***')"

    @classmethod
    def from_env(cls) -> "OllamaClient":
        key, base = resolve_credentials()
        if not key:
            raise OllamaError(
                "缺少 OLLAMA_API_KEY。可在环境变量或仓库根目录 .env 里设置（不要提交密钥）。"
            )
        return cls(key, base)

    @property
    def openai_compatible(self) -> bool:
        return self.base_url.endswith("/v1")

    def list_models(self) -> list[str]:
        if self.openai_compatible:
            payload = self._request("GET", "/models")
            items = payload.get("data") or payload.get("models") or []
            ids: list[str] = []
            for item in items:
                if isinstance(item, dict):
                    mid = item.get("id") or item.get("name")
                    if mid:
                        ids.append(str(mid))
                elif item:
                    ids.append(str(item))
            return ids
        payload = self._request("GET", "/api/tags")
        names = []
        for item in payload.get("models") or []:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
        return names

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        reasoning_effort: Any = "none",
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> ChatResult:
        if self.openai_compatible:
            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "reasoning_effort": openai_effort(reasoning_effort),
            }
            payload = self._request("POST", "/chat/completions", body)
            choice = (payload.get("choices") or [{}])[0]
            content, reasoning = extract_message_text(choice.get("message") if isinstance(choice, dict) else None)
            return ChatResult(
                content=content,
                reasoning=reasoning,
                model=str(payload.get("model") or model),
                usage=dict(payload.get("usage") or {}),
                raw=payload,
            )

        think = native_think(reasoning_effort)
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": think,
            "options": {"think": think, "temperature": temperature, "num_predict": max_tokens},
        }
        payload = self._request("POST", "/api/chat", body)
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        content, reasoning = extract_message_text(message)
        if not reasoning:
            reasoning = str(message.get("thinking") or "")
        return ChatResult(
            content=content,
            reasoning=reasoning,
            model=str(payload.get("model") or model),
            usage=dict(payload.get("usage") or {}),
            raw=payload,
        )

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=self._ssl, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = _redact_secret(exc.read().decode("utf-8", errors="replace")[:800], self.api_key)
            raise OllamaError(f"Ollama HTTP {exc.code} {path}: {body}") from exc
        except urllib.error.URLError as exc:
            raise OllamaError(f"Ollama 连接失败: {exc.reason}") from exc


def _redact_secret(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")
