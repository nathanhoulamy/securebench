"""Command line interface for SecureBench."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from securebench.candidates import OpenAICompatibleError
from securebench.config import ConfigError, RunSection, load_run_config
from securebench.env import load_env_file
from securebench.run import run_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="securebench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a benchmark config")
    run_parser.add_argument("--config", required=True, help="Path to YAML run config")
    run_parser.add_argument("--env-file", default=".env", help="Path to dotenv file to load before running")
    run_parser.add_argument("--limit", type=int, help="Override run.limit")
    run_parser.add_argument("--output", help="Override run.output_path")

    args = parser.parse_args(argv)

    if args.command == "run":
        return _run(args)
    parser.error(f"Unknown command {args.command!r}")
    return 2


def _run(args: argparse.Namespace) -> int:
    try:
        load_env_file(args.env_file)
        config = load_run_config(args.config)
        if args.limit is not None or args.output is not None:
            config = replace(
                config,
                run=RunSection(
                    id=config.run.id,
                    limit=args.limit if args.limit is not None else config.run.limit,
                    output_path=config.run.output_path if args.output is None else Path(args.output),
                ),
            )
        summary = run_config(config)
    except (ConfigError, ImportError, OSError, OpenAICompatibleError, ValueError) as exc:
        print(f"securebench: error: {exc}")
        return 1

    print(
        "securebench: "
        f"run_id={summary.run_id} total={summary.total} passed={summary.passed} "
        f"accuracy={summary.accuracy:.4f} average_score={summary.average_score:.4f} "
        f"output={summary.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
