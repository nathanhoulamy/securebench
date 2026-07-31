#!/usr/bin/env python3
"""Import every public SWE-bench Pro row into a SecureBench repo-patch pack."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import urlopen


DATASET = "ScaleAI/SWE-bench_Pro"
DATASET_REVISION = "7ab5114912baf22bb098818e604c02fe7ad2c11f"
CONFIG = "default"
SPLIT = "test"
EXPECTED_ROWS = 731
ROWS_URL = "https://datasets-server.huggingface.co/rows"
DATASET_INFO_URL = f"https://huggingface.co/api/datasets/{DATASET}"

EVAL_REPOSITORY = "https://github.com/scaleapi/SWE-bench_Pro-os.git"
EVAL_REVISION = "ca10a60a5fcae51e6948ffe1485d4153d421e6c5"
DOCKER_IMAGE_REPOSITORY = "jefzda/sweap-images"
DEFAULT_OUTPUT = Path("benchmarks/swe-bench-pro/tasks.jsonl")
DEFAULT_PAGE_SIZE = 100
WORKDIR = "/app"
RUNNER_DIR = ".securebench-pro-eval"
RUNNER_PATH = f"{RUNNER_DIR}/run_script.sh"
PARSER_PATH = f"{RUNNER_DIR}/parser.py"

CHECK_RESULTS = """\
import json
import sys

with open(sys.argv[1], encoding="utf-8") as file:
    output = json.load(file)
required = set(json.loads(sys.argv[2])) | set(json.loads(sys.argv[3]))
passed = {
    test["name"]
    for test in output.get("tests", [])
    if test.get("status") == "PASSED" and isinstance(test.get("name"), str)
}
missing = sorted(required - passed)
if missing:
    print(f"{len(missing)} required SWE-bench Pro tests did not pass:", file=sys.stderr)
    for name in missing:
        print(f"- {name}", file=sys.stderr)
    raise SystemExit(1)
print(f"All {len(required)} required SWE-bench Pro tests passed.")
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSONL output path. Defaults to {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Existing SWE-bench_Pro-os checkout at the pinned evaluation revision",
    )
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    args = parser.parse_args()

    verify_dataset_revision()
    rows = list(fetch_rows(page_size=args.page_size))
    if len(rows) != EXPECTED_ROWS:
        raise SystemExit(f"Expected {EXPECTED_ROWS} SWE-bench Pro rows, got {len(rows)}")

    if args.source is not None:
        source = args.source.resolve()
        verify_eval_source(source)
        write_rows(rows, source=source, output=args.output)
    else:
        with tempfile.TemporaryDirectory(prefix="securebench-swe-bench-pro-") as temporary:
            source = Path(temporary) / "source"
            clone_eval_source(source)
            write_rows(rows, source=source, output=args.output)

    print(f"Wrote {len(rows)} SWE-bench Pro rows to {args.output}")
    return 0


def verify_dataset_revision() -> None:
    with urlopen(DATASET_INFO_URL, timeout=60) as response:
        payload = json.load(response)
    revision = payload.get("sha")
    if revision != DATASET_REVISION:
        raise SystemExit(
            f"Expected {DATASET} revision {DATASET_REVISION}, got {revision!r}; "
            "review upstream changes before updating the import"
        )


def fetch_rows(*, page_size: int) -> Iterable[tuple[int, dict[str, Any]]]:
    if page_size <= 0:
        raise SystemExit("--page-size must be positive")

    offset = 0
    total: int | None = None
    while total is None or offset < total:
        query = urlencode(
            {
                "dataset": DATASET,
                "config": CONFIG,
                "split": SPLIT,
                "offset": offset,
                "length": page_size,
            }
        )
        with urlopen(f"{ROWS_URL}?{query}", timeout=120) as response:
            payload = json.load(response)
        if total is None:
            total = int(payload["num_rows_total"])
        page_rows = payload["rows"]
        if not page_rows:
            break
        for item in page_rows:
            yield int(item["row_idx"]), item["row"]
        offset += len(page_rows)


def clone_eval_source(target: Path) -> None:
    subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout", EVAL_REPOSITORY, str(target)],
        check=True,
    )
    subprocess.run(["git", "checkout", "--detach", EVAL_REVISION], cwd=target, check=True)
    verify_eval_source(target)


def verify_eval_source(source: Path) -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    )
    revision = completed.stdout.strip()
    if revision != EVAL_REVISION:
        raise SystemExit(f"Expected evaluation source revision {EVAL_REVISION}, got {revision}")
    if not (source / "run_scripts").is_dir():
        raise SystemExit(f"Evaluation source has no run_scripts directory: {source}")


def write_rows(
    rows: list[tuple[int, dict[str, Any]]],
    *,
    source: Path,
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    seen_ids: set[str] = set()
    with output.open("w", encoding="utf-8") as file:
        for source_index, source_row in rows:
            converted = convert_row(source_index, source_row, source=source)
            task_id = converted["id"]
            if task_id in seen_ids:
                raise ValueError(f"Duplicate SWE-bench Pro instance_id: {task_id}")
            seen_ids.add(task_id)
            file.write(json.dumps(converted, sort_keys=True, ensure_ascii=False))
            file.write("\n")


def convert_row(source_index: int, row: dict[str, Any], *, source: Path) -> dict[str, Any]:
    instance_id = required_str(row, "instance_id")
    run_script = required_file(source / "run_scripts" / instance_id / "run_script.sh")
    parser_script = required_file(source / "run_scripts" / instance_id / "parser.py")
    fail_to_pass = string_list(row, "fail_to_pass")
    pass_to_pass = string_list(row, "pass_to_pass")
    selected_tests = string_list(row, "selected_test_files_to_run")
    issue_categories = string_list(row, "issue_categories")
    patch = required_str(row, "patch")
    test_patch = required_str(row, "test_patch")
    before_command = validated_before_command(required_str(row, "before_repo_set_cmd"))
    dockerhub_tag = required_str(row, "dockerhub_tag")

    test_command = evaluation_command(
        before_command=before_command,
        selected_tests=selected_tests,
        fail_to_pass=fail_to_pass,
        pass_to_pass=pass_to_pass,
    )
    runner_patch = new_file_patch(RUNNER_PATH, run_script, mode="100755") + new_file_patch(
        PARSER_PATH,
        parser_script,
        mode="100644",
    )

    return {
        "id": instance_id,
        "environment": {
            "image": f"{DOCKER_IMAGE_REPOSITORY}:{dockerhub_tag}",
            "workdir": WORKDIR,
        },
        "eval": {
            "candidate_policy": {
                "allow_sensitive_paths": list(changed_paths_from_patch(patch)),
            },
            "gold_patch": patch,
            "tests": {
                "command": ["bash", "-lc", test_command],
                "source": "command",
                "test_patch": {
                    "patch": runner_patch,
                    "source": "inline",
                },
                "timeout_seconds": 3600,
                "workdir": WORKDIR,
            },
        },
        "input": {
            "base_commit": required_str(row, "base_commit"),
            "instructions": formatted_instructions(row),
            "repo": required_str(row, "repo"),
        },
        "metadata": {
            "dockerhub_tag": dockerhub_tag,
            "fail_to_pass": fail_to_pass,
            "interface": required_str(row, "interface"),
            "issue_categories": issue_categories,
            "issue_specificity": required_str(row, "issue_specificity"),
            "pass_to_pass_count": len(pass_to_pass),
            "repo_language": required_str(row, "repo_language"),
            "requirements": required_str(row, "requirements"),
            "selected_test_count": len(selected_tests),
            "source_dataset": DATASET,
            "source_dataset_revision": DATASET_REVISION,
            "source_eval_repository": EVAL_REPOSITORY,
            "source_eval_revision": EVAL_REVISION,
            "source_index": source_index,
            "source_instance_id": instance_id,
            "source_test_patch_sha256": hashlib.sha256(test_patch.encode()).hexdigest(),
        },
    }


def formatted_instructions(row: dict[str, Any]) -> str:
    return (
        f"{required_str(row, 'problem_statement')}\n\n"
        f"Requirements:\n{required_str(row, 'requirements')}\n\n"
        f"New interfaces introduced:\n{required_str(row, 'interface')}"
    )


def evaluation_command(
    *,
    before_command: list[str],
    selected_tests: list[str],
    fail_to_pass: list[str],
    pass_to_pass: list[str],
) -> str:
    stdout_path = "/tmp/securebench-pro-stdout.log"
    stderr_path = "/tmp/securebench-pro-stderr.log"
    output_path = "/tmp/securebench-pro-output.json"
    selected_arg = ",".join(selected_tests)
    run = shlex.join(["bash", RUNNER_PATH, selected_arg])
    parse = shlex.join(["python", PARSER_PATH, stdout_path, stderr_path, output_path])
    check = shlex.join(
        [
            "python",
            "-c",
            CHECK_RESULTS,
            output_path,
            json.dumps(fail_to_pass, ensure_ascii=False),
            json.dumps(pass_to_pass, ensure_ascii=False),
        ]
    )
    return "\n".join(
        [
            "set -u",
            shlex.join(before_command),
            shlex.join(["rm", "-f", stdout_path, stderr_path, output_path]),
            f"{run} > {shlex.quote(stdout_path)} 2> {shlex.quote(stderr_path)} || true",
            parse,
            check,
        ]
    )


def validated_before_command(value: str) -> list[str]:
    lines = value.strip().splitlines()
    if not lines:
        raise ValueError("before_repo_set_cmd must contain a command")
    command = shlex.split(lines[-1])
    if (
        len(command) < 5
        or command[:2] != ["git", "checkout"]
        or re.fullmatch(r"[0-9a-f]{40}", command[2]) is None
        or command[3] != "--"
        or any(path.startswith("-") or path.startswith("/") or ".." in Path(path).parts for path in command[4:])
    ):
        raise ValueError(f"Unsupported before_repo_set_cmd: {lines[-1]!r}")
    return command


def new_file_patch(path: str, content: str, *, mode: str) -> str:
    lines = content.splitlines()
    patch = (
        f"diff --git a/{path} b/{path}\n"
        f"new file mode {mode}\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
    )
    patch += "".join(f"+{line}\n" for line in lines)
    if content and not content.endswith("\n"):
        patch += "\\ No newline at end of file\n"
    return patch


def changed_paths_from_patch(patch: str) -> tuple[str, ...]:
    paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            value = line.removeprefix("diff --git ")
            same_path = identical_unquoted_git_path(value)
            if same_path is not None:
                if same_path not in paths:
                    paths.append(same_path)
                continue
            try:
                parts = shlex.split(line)
            except ValueError:
                continue
            if len(parts) == 4:
                for candidate in parts[2:]:
                    path = candidate[2:] if candidate[:2] in {"a/", "b/"} else candidate
                    if path != "/dev/null" and path not in paths:
                        paths.append(path)
        elif line.startswith("rename from ") or line.startswith("rename to "):
            path = line.split(" ", 2)[2]
            if path not in paths:
                paths.append(path)
    if not paths:
        raise ValueError("patch did not contain any changed paths")
    return tuple(paths)


def identical_unquoted_git_path(value: str) -> str | None:
    if not value.startswith("a/"):
        return None
    matches: list[str] = []
    start = 0
    while True:
        separator = value.find(" b/", start)
        if separator == -1:
            break
        left = value[:separator]
        right = value[separator + 1 :]
        if left[2:] == right[2:]:
            matches.append(left[2:])
        start = separator + 1
    return matches[0] if len(matches) == 1 else None


def string_list(row: dict[str, Any], key: str) -> list[str]:
    value = required_str(row, key)
    try:
        loaded = ast.literal_eval(value)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"{key} must contain a Python string-list literal") from exc
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError(f"{key} must decode to a string list")
    return loaded


def required_file(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"Required evaluation file does not exist: {path}")
    return path.read_text(encoding="utf-8")


def required_str(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
