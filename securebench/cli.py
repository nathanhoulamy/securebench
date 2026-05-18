"""Command line interface for SecureBench."""

from __future__ import annotations

import argparse

from securebench.candidates import OpenAICompatibleError
from securebench.errors import ConfigError
from securebench.env import load_env_file
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
        summary = run_tester_config(config, limit=args.limit)
    except (ConfigError, ImportError, OSError, OpenAICompatibleError, ValueError) as exc:
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
