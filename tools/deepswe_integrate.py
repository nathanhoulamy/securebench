"""Integrate a qualified, staged DeepSWE row into the registered pack.

A conversion is authored as ``benchmarks/deep-swe/v2/staging/<task>.json`` so
that unfinished work can never break compilation of the registered pack. This
tool performs the move once the row has qualified, and refuses when the
preconditions for admission are not met:

* the staged row compiles, and passes ``validate_executable_task``;
* the reference patch, Oracle and focused test exist;
* the reference, qualification material, and Oracle are absent from the Agent
  and Evaluation views, and the adapter is absent from the Agent view;
* the row id is not already registered.

It does not run the Docker qualification itself — that is recorded evidence the
integrator must have seen pass — and it does not change the inventory. Use
``--dry-run`` to check a row without writing anything.

Usage::

    python -m tools.deepswe_integrate termenv-preserve-ansi-resets
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PACK = ROOT / "benchmarks" / "deep-swe"
STAGING = PACK / "v2" / "staging"
TASKS = PACK / "tasks-v2.jsonl"
HIDDEN = PACK / "v2" / "hidden"


def check(name: str) -> dict:
    from securebench.execution_profiles import validate_executable_task
    from tests.deepswe_qualification import deep_task

    staged = STAGING / f"{name}.json"
    if not staged.is_file():
        raise SystemExit(f"{name}: no staged row at {staged}")
    row = json.loads(staged.read_text(encoding="utf-8"))
    task_id = f"deep-swe/{name}"
    if row.get("id") != task_id:
        raise SystemExit(f"{name}: staged id {row.get('id')!r} != {task_id!r}")

    registered = {
        json.loads(line)["id"]
        for line in TASKS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    if task_id in registered:
        raise SystemExit(f"{name}: already registered")

    for required in (
        HIDDEN / name / "qualification" / "reference.patch",
        HIDDEN / name / "oracle" / "oracle.py",
        ROOT / "tests" / f"test_deepswe_{name.replace('-', '_')}_v2.py",
    ):
        if not required.is_file():
            raise SystemExit(f"{name}: missing {required.relative_to(ROOT)}")

    task = deep_task(name)
    validate_executable_task(task)

    agent_view = str(task.view_for("agent"))
    evaluation_view = str(task.view_for("evaluation_runtime"))
    for view_name, view in (("agent", agent_view), ("evaluation_runtime", evaluation_view)):
        for secret in ("reference.patch", "qualification", "oracle"):
            if secret in view:
                raise SystemExit(f"{name}: {secret!r} visible in the {view_name} view")
    if "adapter" in agent_view:
        raise SystemExit(f"{name}: adapter visible in the agent view")
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", nargs="+")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    for name in arguments.tasks:
        row = check(name)
        if arguments.dry_run:
            print(f"{name}: ready to integrate")
            continue
        text = TASKS.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            text += "\n"
        TASKS.write_text(text + json.dumps(row) + "\n", encoding="utf-8")
        (STAGING / f"{name}.json").unlink()
        print(f"{name}: integrated into {TASKS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
