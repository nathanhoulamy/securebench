"""CLI entry point for the minimal workspace agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from securebench.agent.core import WorkspaceAgent
from securebench.agent.models import (
    OpenAICompatibleToolConfig,
    OpenAICompatibleToolModel,
    ReplayToolModel,
    load_replay_actions,
)
from securebench.candidates.openai_compatible import OpenAICompatibleError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m securebench.agent.run")
    parser.add_argument("--repo-root", default=".", help="Repository root where tools execute")
    parser.add_argument("--task-file", default="SECUREBENCH_TASK.md", help="Public task file inside the repository")
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--max-tool-output", type=int, default=12_000)
    parser.add_argument("--command-timeout", type=float, default=60.0)
    parser.add_argument("--allow-command", action="append", help="Allowed executable name for run_command")
    parser.add_argument("--deny-command", action="append", help="Denied executable name for run_command")
    parser.add_argument("--replay-file", help="JSON replay action file for deterministic runs")
    parser.add_argument("--model", help="OpenAI-compatible model name")
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--timeout", type=float, default=60.0, help="OpenAI-compatible request timeout")
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args(argv)

    try:
        if args.replay_file:
            model = ReplayToolModel(load_replay_actions(args.replay_file))
        elif args.model:
            model = OpenAICompatibleToolModel(
                OpenAICompatibleToolConfig(
                    model=args.model,
                    base_url=args.base_url,
                    api_key_env=args.api_key_env,
                    timeout=args.timeout,
                    temperature=args.temperature,
                )
            )
        else:
            raise ValueError("Either --replay-file or --model is required")

        agent = WorkspaceAgent(
            repo_root=Path(args.repo_root),
            task_file=args.task_file,
            model=model,
            max_steps=args.max_steps,
            max_tool_output=args.max_tool_output,
            command_timeout=args.command_timeout,
            command_allow=None if args.allow_command is None else set(args.allow_command),
            command_deny=None if args.deny_command is None else set(args.deny_command),
        )
        result = agent.run()
    except (OSError, ValueError, OpenAICompatibleError) as exc:
        print(f"securebench-agent: error: {exc}")
        return 1

    print(
        json.dumps(
            {
                "finished": result.finished,
                "steps": result.steps,
                "summary": result.summary,
            },
            sort_keys=True,
        )
    )
    return 0 if result.finished else 1


if __name__ == "__main__":
    raise SystemExit(main())
