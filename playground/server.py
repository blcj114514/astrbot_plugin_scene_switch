"""Tiny playground so you can watch scene routing without AstrBot.

Binds to 127.0.0.1 by default. There is no authentication. If a live
API key is loaded, non-loopback binds are refused.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scene_switch.display import describe_route
from scene_switch.helptext import build_feature_intro
from scene_switch.heuristic import guess_scene
from scene_switch.live import decide_live, make_live_router
from scene_switch.ollama import (
    OllamaClient,
    OllamaError,
    load_catalog,
    resolve_credentials,
)
from scene_switch.router import RouteInput, SceneRouter
from scene_switch.settings import settings_from_dict
from scene_switch.state import SessionStore

PORT = 43187
DEFAULT_HOST = "127.0.0.1"

DEMO = {
    "chat": {"provider_id": "闲聊-轻量", "aliases": "闲聊\n陪聊", "keywords": "陪我聊聊\n晚安"},
    "code": {"provider_id": "代码-强模型", "aliases": "代码\n编程", "keywords": "代码\n报错\n重构"},
    "search": {"provider_id": "搜索-联网", "aliases": "搜索", "keywords": "搜一下\n热点"},
    "vision": {"provider_id": "看图-多模态", "aliases": "看图", "keywords": "这张图\n截图"},
    "translate": {"provider_id": "翻译-专用", "aliases": "翻译", "keywords": "翻译成\n译成"},
    "write": {"provider_id": "写作-润色", "aliases": "写作\n润色", "keywords": "润色\n文案"},
    "model_aliases": "gpt=chat\ndeepseek=code\n翻译=translate\n润色=write",
    "classifier_mode": "llm_for_language",
    "classifier_provider_id": "审判-轻量",
    "announce_switch": "always",
    "require_consent": False,
    "honor_existing_selection": False,
}

CATALOG = load_catalog()
_key, BASE_URL = resolve_credentials()
LIVE_READY = bool(_key)
LIVE_CLIENT: OllamaClient | None = OllamaClient(_key, BASE_URL) if LIVE_READY else None

STORE = SessionStore()
if LIVE_READY:
    ROUTER, CATALOG, PROVIDERS = make_live_router(STORE, CATALOG)
else:
    ROUTER = SceneRouter(settings_from_dict(DEMO), STORE)
    PROVIDERS = tuple(
        scene.provider_id for scene in ROUTER.settings.enabled_scenes() if scene.provider_id
    )


def _human(decision_or_result) -> str:
    return describe_route(ROUTER.settings, decision_or_result)


def _offline_decide(payload: dict) -> dict:
    text = str(payload.get("text") or "")
    media = bool(payload.get("media"))
    group = bool(payload.get("group"))
    sender = str(payload.get("sender") or "preview-user")
    judge_mode = str(payload.get("judge") or "auto")
    inp = RouteInput(
        text=text,
        umo="playground:group:demo" if group else "playground:private:demo",
        sender_id=sender,
        is_group=group,
        has_media=media,
        available_providers=PROVIDERS,
    )
    decision = ROUTER.decide(inp)
    if decision.needs_judge:
        if judge_mode in {"auto", ""}:
            guessed = guess_scene(text, {scene.id for scene in ROUTER.settings.enabled_scenes()})
            hint = guessed or "keep"
        else:
            hint = judge_mode
        decision = ROUTER.decide(inp, judge_hint=hint)
    intro = None
    if decision.help_requested:
        intro = build_feature_intro(
            ROUTER.settings,
            loaded_providers=PROVIDERS,
            judge_ready=True,
        )
    payload = decision.to_dict(include_prompt=True)
    payload.update(
        {
            "intro": intro,
            "label": _human(decision),
            "live": False,
        }
    )
    return payload


def _decide(payload: dict) -> dict:
    judge_mode = str(payload.get("judge") or "auto")
    want_live = LIVE_READY and judge_mode in {"auto", "live", ""}
    want_answer = bool(payload.get("answer"))
    if want_live:
        if LIVE_CLIENT is None:
            raise OllamaError("Ollama 客户端未就绪")
        result = decide_live(
            ROUTER,
            CATALOG,
            PROVIDERS,
            str(payload.get("text") or ""),
            media=bool(payload.get("media")),
            group=bool(payload.get("group")),
            sender=str(payload.get("sender") or "preview-user"),
            client=LIVE_CLIENT,
            answer=want_answer,
            umo="playground:group:demo" if payload.get("group") else "playground:private:demo",
            effort_override=str(payload.get("effort") or "").strip() or None,
        )
        result["live"] = True
        result["label"] = _human(result)
        return result
    return _offline_decide(payload)


def _status(*, include_live_models: bool = False) -> dict:
    live_models = None
    live_error = None
    if include_live_models and LIVE_CLIENT is not None:
        try:
            live_models = LIVE_CLIENT.list_models()
        except Exception as exc:
            live_error = str(exc)
    catalog_scenes = CATALOG.get("scenes") if LIVE_READY else {}
    scenes = {}
    for scene in ROUTER.settings.scenes.values():
        spec = dict((catalog_scenes or {}).get(scene.id) or {})
        spec.setdefault("model", scene.provider_id)
        spec.setdefault("reasoning_effort", scene.reasoning_effort or "none")
        spec["persona_label"] = scene.persona_label or "无人设"
        spec["display_name"] = scene.display_name
        scenes[scene.id] = spec
    return {
        "live": LIVE_READY,
        "base": BASE_URL if LIVE_READY else None,
        "judge": (CATALOG.get("judge") or {}).get("model") if LIVE_READY else None,
        "scenes": scenes,
        "catalog_models": CATALOG.get("models"),
        "live_models": live_models,
        "live_error": live_error,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("playground: " + (fmt % args) + "\n")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            html = (ROOT / "index.html").read_text(encoding="utf-8")
            boot = json.dumps(_status(include_live_models=False), ensure_ascii=False)
            html = html.replace(
                '<script id="boot" type="application/json">{}</script>',
                f'<script id="boot" type="application/json">{boot}</script>',
                1,
            )
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/intro":
            text = build_feature_intro(
                ROUTER.settings,
                loaded_providers=PROVIDERS,
                judge_ready=True,
            )
            self._send(200, json.dumps({"intro": text}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return
        if path == "/api/status":
            self._send(
                200,
                json.dumps(_status(include_live_models=True), ensure_ascii=False).encode(),
                "application/json; charset=utf-8",
            )
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if path == "/api/reset":
            global STORE, ROUTER, CATALOG, PROVIDERS
            STORE = SessionStore()
            if LIVE_READY:
                ROUTER, CATALOG, PROVIDERS = make_live_router(STORE, load_catalog())
            else:
                ROUTER = SceneRouter(settings_from_dict(DEMO), STORE)
                PROVIDERS = tuple(
                    scene.provider_id
                    for scene in ROUTER.settings.enabled_scenes()
                    if scene.provider_id
                )
            self._send(200, b'{"ok":true}', "application/json; charset=utf-8")
            return
        if path != "/api/route":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        try:
            payload = json.loads(raw.decode() or "{}")
            result = _decide(payload if isinstance(payload, dict) else {})
        except Exception as exc:
            self._send(
                400,
                json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                "application/json; charset=utf-8",
            )
            return
        self._send(
            200,
            json.dumps(result, ensure_ascii=False).encode(),
            "application/json; charset=utf-8",
        )


def is_loopback_host(host: str) -> bool:
    text = (host or "").strip().lower()
    if text in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host.strip()).is_loopback
    except ValueError:
        return False


def playground_bind_error(host: str, *, live_ready: bool, allow_lan: bool) -> str | None:
    """Refuse LAN binds that would expose an unauthenticated playground."""
    if is_loopback_host(host):
        return None
    if live_ready:
        return (
            f"refusing to bind {host}: OLLAMA_API_KEY is set and this server has no auth. "
            "Keep the default 127.0.0.1, or unset the key."
        )
    if not allow_lan:
        return (
            f"refusing to bind {host}: playground has no auth. "
            "Use 127.0.0.1, or pass --allow-lan for heuristic-only demos."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local scene-switch playground (no auth).")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--allow-lan",
        action="store_true",
        help="Allow a non-loopback bind when no API key is loaded",
    )
    args = parser.parse_args(argv)
    host = (args.host or DEFAULT_HOST).strip() or DEFAULT_HOST
    err = playground_bind_error(host, live_ready=LIVE_READY, allow_lan=args.allow_lan)
    if err:
        print(err, file=sys.stderr)
        return 2
    server = ThreadingHTTPServer((host, args.port), Handler)
    mode = f"live {BASE_URL}" if LIVE_READY else "offline heuristic"
    print(f"scene playground http://{host}:{args.port} ({mode})", flush=True)
    if not is_loopback_host(host):
        print("warning: bound off-loopback with no authentication", file=sys.stderr)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
