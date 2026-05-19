"""Harness registry for tester YAML runs."""

from __future__ import annotations

from pathlib import Path

from securebench.candidates import CandidateProducer
from securebench.errors import ConfigError
from securebench.harnesses.codex import CodexHarnessProducer, codex_config
from securebench.harnesses.command import CommandHarnessProducer, command_config
from securebench.tester_config import TesterHarnessSection


def build_harness_producer(
    harness: TesterHarnessSection,
    *,
    workspace_root: str | Path | None = None,
) -> CandidateProducer:
    """Build a candidate producer for one parsed tester harness section."""
    if harness.type == "command":
        config = command_config(harness.config)
        return CommandHarnessProducer(
            env_names=harness.env,
            workspace_root=workspace_root,
            **config,
        )
    if harness.type == "codex":
        config = codex_config(harness.config)
        return CodexHarnessProducer(
            env_names=harness.env,
            workspace_root=workspace_root,
            **config,
        )
    raise ConfigError(
        f"Harness type {harness.type!r} is parsed but not implemented yet; "
        "use harness.type 'command' for this refactoring step"
    )
