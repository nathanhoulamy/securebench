"""Command line interface for SecureBench."""

from __future__ import annotations

import argparse
import sys

from securebench.errors import ConfigError
from securebench.env import load_env_file
from securebench.progress import NullProgressReporter, StreamProgressReporter
from securebench.tester_config import load_tester_config
from securebench.tester_run import run_tester_config, with_tester_overrides


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="securebench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a tester YAML benchmark-pack harness")
    run_parser.add_argument("--config", required=True, help="Path to tester YAML config")
    run_parser.add_argument("--env-file", default=".env", help="Path to dotenv file to load before running")
    run_parser.add_argument("--limit", type=int, help="Limit benchmark rows")
    run_parser.add_argument("--output-dir", help="Override run.output_dir")
    run_parser.add_argument(
        "--resume",
        action="store_true",
        help="Keep valid existing output records and skip completed task ids",
    )
    run_parser.add_argument("--quiet", action="store_true", help="Disable interactive progress logs")
    run_parser.add_argument(
        "--show-command-output",
        action="store_true",
        help="Include sandbox stdout/stderr snippets in progress logs",
    )
    run_parser.add_argument(
        "--show-agent-output",
        action="store_true",
        help="Stream readable Codex agent messages and command actions while the agent runs",
    )

    args = parser.parse_args(argv)

    if args.command == "run":
        return _run(args)
    parser.error(f"Unknown command {args.command!r}")
    return 2


def _run(args: argparse.Namespace) -> int:
    try:
        load_env_file(args.env_file)
        config = load_tester_config(args.config)
        config = with_tester_overrides(config, output_dir=args.output_dir)
        progress = (
            NullProgressReporter()
            if args.quiet
            else StreamProgressReporter(
                stream=sys.stderr,
                show_command_output=args.show_command_output,
                show_agent_output=args.show_agent_output,
            )
        )
        summary = run_tester_config(
            config,
            limit=args.limit,
            progress=progress,
            resume=args.resume,
        )
    except (ConfigError, ImportError, OSError, ValueError) as exc:
        print(f"securebench: error: {exc}")
        return 1

    print(
        "securebench: "
        f"run_id={summary.run_id} total={summary.total} "
        f"verification={summary.verification_status} "
        f"verified={summary.verified} passed={summary.passed} "
        f"output={summary.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
