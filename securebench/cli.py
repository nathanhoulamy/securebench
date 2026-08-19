"""Command line interface for SecureBench."""

from __future__ import annotations

import argparse
import sys

from securebench.errors import ConfigError
from securebench.audit import audit_config, audit_self
from securebench.audit.report import render_text_summary, write_json_report
from securebench.env import load_env_file
from securebench.progress import NullProgressReporter, StreamProgressReporter
from securebench.harnesses.codex_oauth import (
    CodexOAuthError,
    ensure_valid_codex_oauth_credentials,
    run_codex_login,
    run_codex_logout,
)
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
        "--workers",
        type=int,
        help="Run up to this many benchmark rows concurrently",
    )
    run_parser.add_argument(
        "--max-cached-images",
        type=int,
        help="Remove each batch of this many benchmark images after their tasks finish",
    )
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

    audit_parser = subparsers.add_parser("audit", help="Audit a tester YAML benchmark-pack config")
    audit_parser.add_argument("--config", required=True, help="Path to tester YAML config")
    audit_parser.add_argument("--output-dir", required=True, help="Directory for audit report artifacts")
    audit_parser.add_argument("--limit", type=int, help="Limit benchmark rows")

    audit_self_parser = subparsers.add_parser("audit-self", help="Run built-in SecureBench robustness audits")
    audit_self_parser.add_argument("--output-dir", required=True, help="Directory for audit report artifacts")

    auth_parser = subparsers.add_parser("auth", help="Manage harness subscription logins")
    auth_providers = auth_parser.add_subparsers(dest="auth_provider", required=True)
    codex_auth_parser = auth_providers.add_parser(
        "codex",
        help="Manage the isolated Codex subscription login",
    )
    codex_auth_actions = codex_auth_parser.add_subparsers(dest="auth_action", required=True)
    codex_login_parser = codex_auth_actions.add_parser("login", help="Log in with ChatGPT")
    codex_login_parser.add_argument(
        "--device-auth",
        action="store_true",
        help="Use the Codex device-code login flow",
    )
    codex_auth_actions.add_parser("status", help="Check the SecureBench Codex login")
    codex_auth_actions.add_parser("logout", help="Remove the SecureBench Codex login")

    args = parser.parse_args(argv)

    if args.command == "run":
        return _run(args)
    if args.command == "audit":
        return _audit(args)
    if args.command == "audit-self":
        return _audit_self(args)
    if args.command == "auth":
        return _auth(args)
    parser.error(f"Unknown command {args.command!r}")
    return 2


def _run(args: argparse.Namespace) -> int:
    try:
        load_env_file(args.env_file)
        config = load_tester_config(args.config)
        config = with_tester_overrides(
            config,
            output_dir=args.output_dir,
            max_workers=args.workers,
            max_cached_images=args.max_cached_images,
        )
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
        f"images_pruned={summary.images_pruned} "
        f"image_prune_failures={summary.image_prune_failures} "
        f"output={summary.output_path}"
    )
    return 0


def _audit(args: argparse.Namespace) -> int:
    try:
        config = load_tester_config(args.config)
        report = audit_config(config, output_dir=args.output_dir, limit=args.limit)
        output_path = write_json_report(report, args.output_dir)
    except (ConfigError, ImportError, OSError, ValueError) as exc:
        print(f"securebench: error: {exc}")
        return 1

    print(render_text_summary(report, output_path))
    return 1 if report.failed else 0


def _audit_self(args: argparse.Namespace) -> int:
    try:
        report = audit_self(
            output_dir=args.output_dir,
        )
        output_path = write_json_report(report, args.output_dir)
    except (ConfigError, ImportError, OSError, ValueError) as exc:
        print(f"securebench: error: {exc}")
        return 1

    print(render_text_summary(report, output_path))
    return 1 if report.failed else 0


def _auth(args: argparse.Namespace) -> int:
    if args.auth_provider != "codex":
        print(f"securebench: error: unsupported auth provider {args.auth_provider!r}")
        return 1
    try:
        if args.auth_action == "login":
            path = run_codex_login(device_auth=args.device_auth)
            credentials = ensure_valid_codex_oauth_credentials(path)
            plan = credentials.plan_type or "unknown"
            print(f"securebench: Codex subscription login saved ({plan} plan)")
            return 0
        if args.auth_action == "status":
            credentials = ensure_valid_codex_oauth_credentials()
            plan = credentials.plan_type or "unknown"
            print(f"securebench: Codex subscription login is ready ({plan} plan)")
            return 0
        if args.auth_action == "logout":
            run_codex_logout()
            print("securebench: Codex subscription login removed")
            return 0
    except (CodexOAuthError, OSError, ValueError) as exc:
        print(f"securebench: error: {exc}")
        return 1
    print(f"securebench: error: unsupported Codex auth action {args.auth_action!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
