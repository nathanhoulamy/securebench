"""Container-side live adversarial agent entrypoint."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from live_openai import run_live_agent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("live_openai",))
    parser.add_argument("--profile", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--trace-file", required=True)
    parser.add_argument("--max-steps", type=int, default=int(os.environ.get("BERKELEY_MAX_STEPS", "4")))
    args = parser.parse_args(argv)

    task = _load_json(Path(args.task_file))
    trace = run_live_agent(
        task=task,
        profile=args.profile,
        task_type=os.environ.get("BERKELEY_TASK_TYPE", ""),
        workspace=Path(os.environ.get("SECUREBENCH_WORKSPACE", ".")),
        workdir=Path(os.environ.get("SECUREBENCH_WORKDIR", ".")),
        max_steps=max(1, args.max_steps),
    )
    trace["requested_profile"] = args.profile
    Path(args.trace_file).write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n")
    return 0


def _load_json(path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())

