"""Find (and optionally redact) the campaign credential anywhere under the campaign root.

The credential is the profile's (``profile.py``): the OpenAI API key for Luna,
the Claude subscription OAuth token for Sonnet 5.

    python -m tools.native_baseline.key_scan [--redact]

The key is read from .env and never printed; only matching paths are listed.
Binary files (tars, images) are scanned as bytes; redaction rewrites text
files only and reports binary hits for manual handling.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.native_baseline.profile import PROFILE

ROOT = Path(__file__).resolve().parents[2]
TARGET = PROFILE.root
NAME = PROFILE.credential_env
SKIP = {"native-venv", "upstream"}


def load_key() -> bytes:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(f"{NAME}="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            if len(value) < 20:
                raise SystemExit(f"{NAME} in .env looks empty")
            return value.encode()
    raise SystemExit(f"{NAME} not found in .env")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redact", action="store_true")
    args = parser.parse_args()
    key = load_key()
    hits = []
    for path in TARGET.rglob("*"):
        if not path.is_file() or path.is_symlink() or SKIP & set(path.relative_to(TARGET).parts):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if key in data:
            hits.append(path)
            if args.redact:
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    print(f"BINARY HIT (not rewritten): {path.relative_to(ROOT)}")
                    continue
                path.write_bytes(data.replace(key, f"[REDACTED-{NAME}]".encode()))
    for path in hits:
        print(f"{'redacted' if args.redact else 'HIT'}: {path.relative_to(ROOT)}")
    print(f"{len(hits)} file(s) contained the key")
    return 1 if hits and not args.redact else 0


if __name__ == "__main__":
    raise SystemExit(main())
