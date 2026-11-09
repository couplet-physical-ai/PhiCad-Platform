#!/usr/bin/env python3
"""Run a dependency-free high-confidence secret scan before packaging.

This is a release guard, not a replacement for GitHub's secret scanning.  It errs on
blocking suspicious credentials and deliberately reports only paths and line numbers,
never the matched value.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
EXCLUDED_PATH_PARTS = {"dist", "build", ".tox", ".mypy_cache"}
FORBIDDEN_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
FORBIDDEN_SUFFIXES = (".pem", ".p12", ".pfx", ".key", ".keystore", ".secret")
PLACEHOLDER_VALUES = {
    "changeme",
    "change-me",
    "example",
    "example-token",
    "placeholder",
    "replace-me",
    "replace_me",
    "your-token",
    "your_token",
    "your-api-key",
    "your_api_key",
    "todo",
}

PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("generic-api-token", re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{20,}\b")),
    (
        "credential-url",
        re.compile(r"https?://[^\s/:]+:[^\s/@]+@", re.IGNORECASE),
    ),
    (
        "credential-assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|access[_-]?key|client[_-]?secret|password|secret|token)"
            r"\s*[:=]\s*['\"]?([A-Za-z0-9+/=_.:-]{20,})"
        ),
    ),
)

Finding = Tuple[str, int, str]


def _excluded(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    parts = set(relative.parts)
    if parts & EXCLUDED_DIRS or parts & EXCLUDED_PATH_PARTS:
        return True
    if any(part.startswith(".env") for part in relative.parts):
        return True
    return False


def iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or _excluded(path, root):
            continue
        yield path


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip("'\"` \t\r\n").lower()
    return normalized in PLACEHOLDER_VALUES or normalized.startswith(("your-", "your_", "<"))


def scan_file(path: Path, root: Path) -> List[Finding]:
    name = path.name.lower()
    if name in FORBIDDEN_NAMES or name.endswith(FORBIDDEN_SUFFIXES):
        return [(str(path.relative_to(root)), 1, "credential-file-name")]
    try:
        raw = path.read_bytes()
    except OSError:
        return [(str(path.relative_to(root)), 1, "unreadable-file")]
    if b"\x00" in raw[:8192]:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []

    findings: List[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            if label == "credential-assignment" and _looks_like_placeholder(match.group(1)):
                continue
            findings.append((str(path.relative_to(root)), line_number, label))
    return findings


def scan_paths(root: Path, paths: Sequence[Path] | None = None) -> List[Finding]:
    root = root.resolve()
    files = paths if paths is not None else list(iter_files(root))
    findings: List[Finding] = []
    for path in files:
        candidate = path if path.is_absolute() else root / path
        if candidate.is_file() and not _excluded(candidate, root):
            findings.extend(scan_file(candidate, root))
    return findings


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.root.resolve()
    findings = scan_paths(root)
    if findings:
        print("Secret scan failed; suspicious material was found:", file=sys.stderr)
        for relative, line, label in findings:
            print("  %s:%d (%s)" % (relative, line, label), file=sys.stderr)
        return 1
    print("Secret scan passed (%s)" % root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
