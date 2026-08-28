"""Fail the build if tracked files look like they contain secrets."""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Ollama Cloud keys look like hex.token; never allow that shape in git.
_CLOUD_KEY = re.compile(r"(?i)(?:api[_-]?key|secret|token)\s*[:=]\s*[A-Za-z0-9_\-]{16,}")
_DOT_KEY = re.compile(r"\b[a-f0-9]{32}\.[A-Za-z0-9]{10,}\b")
_BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._\-]{16,}")

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2"}
# Published support QQ may appear in listing/docs only. Other instance ids stay hashed.
_PUBLIC_SUPPORT_QQ = "1844372102"
_SUPPORT_QQ_FILES = {
    "metadata.yaml",
    "README.md",
    "CHANGELOG.md",
    "SECURITY.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    "tests/test_secrets.py",
}
# (char length, sha256) of instance identifiers that must not re-enter the tree.
_FORBIDDEN_HASHES = (
    (10, "abb4d7e417510d22b2bb00103047fa26370d6f3c7c39554e37c5384984973afd"),
    (5, "8ec82e9a63e001110b8c27af605a97ac63101486052a60fe1ba45f03e07d3567"),
    (8, "3af8807b11a0e23c67c03b9cccde6b2595b2a9b3677364061c3e772bad931885"),
    (18, "623624c2be319d30aeb514e8ce5e2eb2e1dea88bf1275063ba8abc05f84cf948"),
    (3, "b9b8ac7e05f7fcbb5c148dda7a5801ef1f54629ed599f73f0013a0d8ab750c6b"),
)


def _contains_forbidden_identifier(text: str, *, rel: str = "") -> bool:
    wanted: dict[int, set[str]] = {}
    for length, digest in _FORBIDDEN_HASHES:
        wanted.setdefault(length, set()).add(digest)
    allowed = rel.replace("\\", "/") in _SUPPORT_QQ_FILES
    for length, digests in wanted.items():
        if length > len(text):
            continue
        for i in range(0, len(text) - length + 1):
            chunk = text[i : i + length]
            if hashlib.sha256(chunk.encode("utf-8")).hexdigest() in digests:
                if allowed and chunk == _PUBLIC_SUPPORT_QQ:
                    continue
                return True
    return False


def _scan_files() -> list[Path]:
    skip_dirs = {".git", ".pytest_cache", ".pytest_tmp", "__pycache__", ".venv", "venv"}
    try:
        raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        names = [item.decode() for item in raw.split(b"\0") if item]
        if names:
            return [ROOT / name for name in names]
    except (OSError, subprocess.CalledProcessError):
        pass
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        files.append(path)
    return files


def test_env_example_has_empty_key():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "OLLAMA_API_KEY=" in text
    for line in text.splitlines():
        if line.startswith("OLLAMA_API_KEY="):
            assert line.strip() == "OLLAMA_API_KEY="


def test_env_is_gitignored():
    listed = subprocess.check_output(["git", "ls-files", ".env"], cwd=ROOT, text=True).strip()
    assert listed == ""
    ignored = subprocess.check_output(
        ["git", "check-ignore", "-v", ".env"],
        cwd=ROOT,
        text=True,
    )
    assert ".env" in ignored


def test_tracked_files_do_not_contain_secrets():
    offenders: list[str] = []
    for path in _scan_files():
        if path.suffix.lower() in SKIP_SUFFIXES or path.name == "test_secrets.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _DOT_KEY.search(text) or _BEARER.search(text):
            offenders.append(str(path.relative_to(ROOT)))
            continue
        if _contains_forbidden_identifier(text, rel=str(path.relative_to(ROOT))):
            offenders.append(str(path.relative_to(ROOT)))
            continue
        for match in _CLOUD_KEY.finditer(text):
            snippet = match.group(0)
            if snippet.rstrip().endswith("=") or snippet.rstrip().endswith("=''"):
                continue
            if "你的密钥" in snippet or "example" in snippet.lower():
                continue
            if re.search(r"[:=]\s*$", snippet):
                continue
            value = re.split(r"[:=]\s*", snippet, maxsplit=1)[-1].strip().strip("'\"")
            if not value or value in {"***", "secret", "changeme"}:
                continue
            offenders.append(str(path.relative_to(ROOT)))
            break
    assert not offenders, f"possible secrets in tracked files: {offenders}"
