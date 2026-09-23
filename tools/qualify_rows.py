"""Run the per-row qualification matrix and emit machine-readable records.

Admission tooling is deliberately deferred (see ``current.md``), so this driver
does not decide admission. It runs each row's focused test file plus that row's
cases from the shared file-bundle qualification file, under real Docker, and
records exactly what was executed and what happened.

A row is reported as ``complete`` only when its Docker-gated cases actually ran.
Skips are reported as evidence gaps, never as passes -- an unexecuted gate is the
failure mode this driver exists to make visible.

Usage::

    python -m tools.qualify_rows --pack terminal-bench --out runs/qualification
    python -m tools.qualify_rows --pack terminal-bench --rows cobol-modernization
    python -m tools.qualify_rows --pack terminal-bench --no-docker   # dry gauge

The emitted JSON is the raw material for each dossier's "Implemented v2
conversion" section and for the ``inventory.csv`` status columns. It is not
itself an admission decision.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED_BUNDLE_TESTS = ROOT / "tests" / "test_terminal_file_bundle_qualification.py"

# pytest's short summary line, e.g. "12 passed, 3 skipped in 4.20s".
_COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)")


@dataclass
class RowRecord:
    row: str
    task_id: str
    focused_test: str | None
    docker: bool
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    commands: list[str] = field(default_factory=list)
    skipped_reasons: list[str] = field(default_factory=list)
    status: str = "unknown"
    note: str = ""


def _parse_counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    # Use the last summary line so a re-run inside the output cannot confuse it.
    for number, label in _COUNT.findall(output):
        key = "errors" if label.startswith("error") else label
        if key in counts:
            counts[key] = max(counts[key], int(number))
    return counts


def _skip_reasons(output: str) -> list[str]:
    reasons = []
    for line in output.splitlines():
        if line.startswith("SKIPPED") or " - " in line and line.startswith("SKIPPED"):
            reasons.append(line.strip())
    return reasons


def _run(command: list[str], *, docker: bool) -> tuple[str, int, float]:
    environment = dict(os.environ)
    if docker:
        environment["SECUREBENCH_DOCKER_INTEGRATION"] = "1"
    else:
        environment.pop("SECUREBENCH_DOCKER_INTEGRATION", None)
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    return (
        completed.stdout + completed.stderr,
        completed.returncode,
        time.monotonic() - started,
    )


# Rows whose verification shape is identical share one focused test file, so
# the per-row proof lives there rather than in a file named after the row.
SHARED_FOCUSED_TESTS = {
    "mteb-leaderboard": "test_mteb_exact_answer_v2.py",
    "mteb-retrieve": "test_mteb_exact_answer_v2.py",
}


# DeepSWE rows qualified before the per-row naming convention existed.
DEEPSWE_FOCUSED_TESTS = {
    "cattrs-partial-structuring-recovery": "test_deepswe_first_wave_replay_v2.py",
    "fd-deterministic-multi-key-sorting": "test_deepswe_first_wave_replay_v2.py",
    "updo-policy-alerting": "test_deepswe_first_wave_replay_v2.py",
    "go-critic-doc-link-checker": "test_go_critic_conversion_v2.py",
}


def _focused_test_path(row: str, pack: str = "terminal-bench") -> Path | None:
    if pack == "deep-swe":
        name = DEEPSWE_FOCUSED_TESTS.get(
            row, f"test_deepswe_{row.replace('-', '_')}_v2.py"
        )
        candidate = ROOT / "tests" / name
        return candidate if candidate.is_file() else None
    shared = SHARED_FOCUSED_TESTS.get(row)
    if shared is not None:
        candidate = ROOT / "tests" / shared
        return candidate if candidate.is_file() else None
    candidate = ROOT / "tests" / f"test_{row.replace('-', '_')}_v2.py"
    return candidate if candidate.is_file() else None


def qualify_row(pack: str, row: str, *, docker: bool) -> RowRecord:
    task_id = f"{pack}/{row}"
    focused = _focused_test_path(row, pack)
    record = RowRecord(
        row=row,
        task_id=task_id,
        focused_test=str(focused.relative_to(ROOT)) if focused else None,
        docker=docker,
    )

    if focused is None:
        record.status = "no_focused_test"
        record.note = (
            "No tests/test_<row>_v2.py exists. Row-specific semantic mutants, "
            "malicious candidates, and Oracle decisions are unproven."
        )
        return record

    focused_command = [
        sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
        str(focused.relative_to(ROOT)),
    ]
    shared_file = row in SHARED_FOCUSED_TESTS or (
        pack == "deep-swe" and focused.name == "test_deepswe_first_wave_replay_v2.py"
    )
    if shared_file:
        # Select only this row's parametrised cases out of the shared file.
        focused_command += ["-k", row]

    targets = [focused_command]
    if pack == "terminal-bench":
        # The shared capture suite covers file_bundle rows only; DeepSWE rows are
        # git_patch rows whose capture is exercised by their own focused tests.
        targets.append(
            [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
             str(SHARED_BUNDLE_TESTS.relative_to(ROOT)), "-k", row]
        )

    for command in targets:
        output, _, duration = _run(command, docker=docker)
        counts = _parse_counts(output)
        record.commands.append(" ".join(command))
        record.passed += counts["passed"]
        record.failed += counts["failed"]
        record.skipped += counts["skipped"]
        record.errors += counts["errors"]
        record.duration_seconds += duration
        record.skipped_reasons.extend(_skip_reasons(output))

    if record.failed or record.errors:
        record.status = "failing"
        record.note = "At least one gate failed. Not admissible."
    elif record.skipped:
        record.status = "evidence_gap"
        record.note = (
            f"{record.skipped} case(s) did not execute. A skipped gate is an "
            "evidence gap, not a pass."
        )
    elif record.passed == 0:
        record.status = "no_cases"
        record.note = "No cases selected for this row."
    else:
        record.status = "complete"
        record.note = (
            "All selected gates executed and passed. Admission remains a "
            "separate human decision recorded in the dossier."
        )
    return record


def discover_rows(pack: str) -> list[str]:
    tasks = ROOT / "benchmarks" / pack / "tasks-v2.jsonl"
    rows = []
    for line in tasks.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line)["id"].split("/", 1)[1])
    return rows


def host_identity(docker: bool) -> dict[str, str]:
    identity = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    if docker:
        try:
            identity["docker"] = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            identity["docker"] = "unavailable"
    return identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", default="terminal-bench")
    parser.add_argument("--rows", nargs="*", help="row names; default is every row")
    parser.add_argument("--out", type=Path, help="directory for the JSON record")
    parser.add_argument(
        "--no-docker",
        action="store_true",
        help="run deterministic cases only; every Docker gate reports as a gap",
    )
    arguments = parser.parse_args()

    docker = not arguments.no_docker
    rows = arguments.rows or discover_rows(arguments.pack)

    records = []
    for index, row in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] {row} ...", flush=True)
        record = qualify_row(arguments.pack, row, docker=docker)
        records.append(record)
        print(
            f"    {record.status:16} "
            f"passed={record.passed} failed={record.failed} "
            f"skipped={record.skipped} errors={record.errors} "
            f"({record.duration_seconds:.1f}s)",
            flush=True,
        )

    summary: dict[str, int] = {}
    for record in records:
        summary[record.status] = summary.get(record.status, 0) + 1

    report = {
        "format": "securebench.qualification-report/v1",
        "pack": arguments.pack,
        "docker": docker,
        "host": host_identity(docker),
        "summary": summary,
        "rows": [asdict(record) for record in records],
    }

    print("\n=== summary ===")
    for status, count in sorted(summary.items()):
        print(f"  {count:3}  {status}")

    if arguments.out:
        arguments.out.mkdir(parents=True, exist_ok=True)
        destination = arguments.out / f"{arguments.pack}-qualification.json"
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {destination}")

    return 0 if all(r.status == "complete" for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
