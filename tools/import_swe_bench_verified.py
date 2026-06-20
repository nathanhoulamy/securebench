#!/usr/bin/env python3
"""Import SWE-bench Verified rows into SecureBench benchmark-pack JSONL."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import urlopen


DATASET = "SWE-bench/SWE-bench_Verified"
CONFIG = "default"
SPLIT = "test"
ROWS_URL = "https://datasets-server.huggingface.co/rows"
DEFAULT_OUTPUT = Path("benchmarks/swe-bench-verified/tasks.jsonl")
DEFAULT_PAGE_SIZE = 100
EPOCH_IMAGE_PREFIX = "ghcr.io/epoch-research/swe-bench.eval.x86_64"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSONL output path, relative to cwd by default. Defaults to {DEFAULT_OUTPUT}",
    )
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    args = parser.parse_args()

    rows = list(fetch_rows(page_size=args.page_size))
    if len(rows) != 500:
        raise SystemExit(f"Expected 500 SWE-bench Verified rows, got {len(rows)}")

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as file:
        for source_index, source_row in rows:
            file.write(json.dumps(convert_row(source_index, source_row), sort_keys=True))
            file.write("\n")

    print(f"Wrote {len(rows)} rows to {output}")
    return 0


def fetch_rows(*, page_size: int) -> Iterable[tuple[int, dict[str, Any]]]:
    if page_size <= 0:
        raise SystemExit("--page-size must be positive")

    offset = 0
    total: int | None = None
    while total is None or offset < total:
        payload = fetch_page(offset=offset, length=page_size)
        if total is None:
            total = int(payload["num_rows_total"])
        page_rows = payload["rows"]
        if not page_rows:
            break
        for item in page_rows:
            yield int(item["row_idx"]), item["row"]
        offset += len(page_rows)


def fetch_page(*, offset: int, length: int) -> dict[str, Any]:
    query = urlencode(
        {
            "dataset": DATASET,
            "config": CONFIG,
            "split": SPLIT,
            "offset": offset,
            "length": length,
        }
    )
    with urlopen(f"{ROWS_URL}?{query}", timeout=60) as response:
        return json.load(response)


def convert_row(source_index: int, row: dict[str, Any]) -> dict[str, Any]:
    instance_id = required_str(row, "instance_id")
    fail_to_pass = json_list(row, "FAIL_TO_PASS")
    pass_to_pass = json_list(row, "PASS_TO_PASS")
    test_files = test_files_from_patch(required_str(row, "test_patch"))

    converted: dict[str, Any] = {
        "id": instance_id,
        "environment": {
            "image": f"{EPOCH_IMAGE_PREFIX}.{instance_id}:latest",
            "workdir": "/testbed",
        },
        "eval": {
            "gold_patch": required_str(row, "patch"),
            "tests": {
                "command": [
                    "bash",
                    "-lc",
                    "source /opt/miniconda3/bin/activate testbed && "
                    + shlex.join(["pytest", "-rA", *test_files]),
                ],
                "source": "command",
                "test_patch": {
                    "patch": required_str(row, "test_patch"),
                    "source": "inline",
                },
                "timeout_seconds": 900,
                "workdir": "/testbed",
            },
        },
        "input": {
            "base_commit": required_str(row, "base_commit"),
            "instructions": required_str(row, "problem_statement"),
            "repo": required_str(row, "repo"),
        },
        "metadata": {
            "difficulty": required_str(row, "difficulty"),
            "environment_setup_commit": required_str(row, "environment_setup_commit"),
            "fail_to_pass": fail_to_pass,
            "pass_to_pass_count": len(pass_to_pass),
            "source_dataset": DATASET,
            "source_index": source_index,
            "source_instance_id": instance_id,
            "version": required_str(row, "version"),
        },
    }
    hints = row.get("hints_text")
    if isinstance(hints, str) and hints.strip():
        converted["input"]["hints"] = hints.strip()
    return converted


def test_files_from_patch(patch: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        candidate = parts[3]
        if candidate.startswith("b/"):
            candidate = candidate[2:]
        if candidate != "/dev/null" and candidate not in seen:
            seen.add(candidate)
            files.append(candidate)
    if not files:
        raise ValueError("test_patch did not contain any changed test files")
    return files


def json_list(row: dict[str, Any], key: str) -> list[str]:
    value = required_str(row, key)
    loaded = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError(f"{key} must decode to a string list")
    return loaded


def required_str(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
