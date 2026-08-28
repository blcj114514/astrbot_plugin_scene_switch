"""Run scene routing without AstrBot: python -m scene_switch"""

from __future__ import annotations

import argparse
import json
import sys

from .live import decide_live, make_live_router
from .ollama import OllamaClient, OllamaError, load_catalog, resolve_credentials
from .router import RouteInput, SceneRouter
from .settings import settings_from_dict
from .state import SessionStore

DEMO_CONFIG = {
    "chat": {"provider_id": "chat-fast", "aliases": "闲聊\n陪聊", "keywords": "陪我聊聊\n晚安\n哈哈"},
    "code": {
        "provider_id": "code-strong",
        "aliases": "代码\n编程",
        "keywords": "代码\n报错\n重构",
    },
    "search": {"provider_id": "search-web", "aliases": "搜索", "keywords": "搜一下\n热点"},
    "vision": {"provider_id": "vision-mm", "aliases": "看图\n识图", "keywords": "这张图\n截图"},
    "translate": {
        "provider_id": "translate-mt",
        "aliases": "翻译\n译",
        "keywords": "翻译成\n译成",
    },
    "write": {
        "provider_id": "write-prose",
        "aliases": "写作\n润色",
        "keywords": "润色\n文案",
    },
    "model_aliases": "gpt=chat\ndeepseek=code\nds=code\ngrok=search\n翻译=translate\n润色=write",
    "announce_switch": "force_only",
    "require_consent": False,
    "honor_existing_selection": False,
}


def _format(decision) -> str:
    return json.dumps(decision.to_dict(), ensure_ascii=False, indent=2)


def _router() -> SceneRouter:
    return SceneRouter(
        settings_from_dict(DEMO_CONFIG),
        SessionStore(),
    )


def decide_line(
    router: SceneRouter,
    text: str,
    *,
    media: bool,
    group: bool,
    sender: str,
    judge_hint: str | None = None,
):
    inp = RouteInput(
        text=text,
        umo="sim:private:demo" if not group else "sim:group:demo",
        sender_id=sender,
        is_group=group,
        has_media=media,
        available_providers=(
            "chat-fast",
            "code-strong",
            "search-web",
            "vision-mm",
            "translate-mt",
            "write-prose",
        ),
    )
    decision = router.decide(inp)
    if decision.needs_judge:
        decision = router.decide(inp, judge_hint=judge_hint or "keep")
    return decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scene_switch",
        description="不启动 AstrBot，直接试跑场景模型路由。",
    )
    parser.add_argument("text", nargs="*", help="要判定的一句话")
    parser.add_argument("-i", "--interactive", action="store_true", help="进入多轮模拟，黏性和跟进会保留")
    parser.add_argument("--media", action="store_true", help="把这条消息当成带了图片/文件")
    parser.add_argument("--group", action="store_true", help="按群聊会话模拟")
    parser.add_argument("--sender", default="u1", help="发送者 ID，群聊黏性按人隔离")
    parser.add_argument(
        "--judge",
        default="",
        help="模拟审判模型输出，如 code / chat / help。用于试「我需要你帮我写代码」",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="用 Ollama Cloud 真实模型审判（需要 OLLAMA_API_KEY）",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="列出 Ollama 账号里的模型 id",
    )
    parser.add_argument(
        "--answer",
        action="store_true",
        help="路由之后再用对应场景模型答一句（需 --live）",
    )
    parser.add_argument(
        "--effort",
        default="",
        help="覆盖思考强度：none / low / high / max（需 --live）",
    )
    args = parser.parse_args(argv)

    if args.list_models:
        try:
            client = OllamaClient.from_env()
            live_ids = client.list_models()
        except OllamaError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        catalog = load_catalog()
        print(
            json.dumps(
                {
                    "base": client.base_url,
                    "live": live_ids,
                    "catalog": catalog.get("models"),
                    "judge": catalog.get("judge"),
                    "scenes": catalog.get("scenes"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.live:
        try:
            client = OllamaClient.from_env()
        except OllamaError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        router, catalog, providers = make_live_router()

        def run_live(line: str):
            return decide_live(
                router,
                catalog,
                providers,
                line,
                media=args.media,
                group=args.group,
                sender=args.sender,
                client=client,
                answer=args.answer,
                effort_override=args.effort.strip() or None,
            )

        if args.interactive:
            _, base = resolve_credentials()
            print(f"真实 Ollama 审判。base={base} judge={catalog.get('judge', {}).get('model')}")
            print("直接回车退出。")
            while True:
                try:
                    line = input("scene> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return 0
                if not line:
                    return 0
                print(json.dumps(run_live(line), ensure_ascii=False, indent=2))
            return 0

        text = " ".join(args.text).strip()
        if not text:
            parser.print_help()
            return 2
        print(json.dumps(run_live(text), ensure_ascii=False, indent=2))
        return 0

    config = dict(DEMO_CONFIG)
    if args.judge:
        config["classifier_mode"] = "llm_for_language"
        config["classifier_provider_id"] = "judge-lite"

    router = SceneRouter(settings_from_dict(config), SessionStore())
    hint = args.judge.strip() or None

    def run(line: str):
        return decide_line(
            router,
            line,
            media=args.media,
            group=args.group,
            sender=args.sender,
            judge_hint=hint,
        )

    if args.interactive:
        print("多轮模拟。直接回车退出。可试：我需要你帮我写代码 / 有什么功能 / 用 deepseek 看报错")
        while True:
            try:
                line = input("scene> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                return 0
            print(_format(run(line)))
        return 0

    text = " ".join(args.text).strip()
    if not text:
        parser.print_help()
        return 2
    print(_format(run(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
