"""Harness registry for tester YAML runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from securebench.candidates import CandidateProducer
from securebench.errors import ConfigError
from securebench.harnesses.claude_code import (
    ClaudeCodeHarnessProducer,
    claude_code_config,
    claude_code_env_names,
)
from securebench.harnesses.codex import CodexHarnessProducer, codex_config, codex_env_names
from securebench.harnesses.command import CommandHarnessProducer, command_config
from securebench.tester_config import TesterHarnessSection


def build_harness_producer(
    harness: TesterHarnessSection,
    *,
    workspace_root: str | Path | None = None,
) -> CandidateProducer:
    """Build a candidate producer for one parsed tester harness section."""
    config = normalized_harness_config(harness)
    env_names = effective_harness_env_names(harness)
    if harness.type == "command":
        return CommandHarnessProducer(
            env_names=env_names,
            workspace_root=workspace_root,
            **config,
        )
    if harness.type == "codex":
        return CodexHarnessProducer(
            env_names=env_names,
            workspace_root=workspace_root,
            **config,
        )
    if harness.type == "claude_code":
        return ClaudeCodeHarnessProducer(
            env_names=env_names,
            workspace_root=workspace_root,
            **config,
        )
    raise ConfigError(
        f"Harness type {harness.type!r} is parsed but not implemented yet; "
        "use harness.type 'command' for this refactoring step"
    )


def normalized_harness_config(harness: TesterHarnessSection) -> dict[str, Any]:
    """Return the semantic harness config with all defaults made explicit."""
    if harness.type == "command":
        return command_config(harness.config)
    if harness.type == "codex":
        return codex_config(harness.config)
    if harness.type == "claude_code":
        return claude_code_config(harness.config)
    raise ConfigError(f"Unsupported harness type: {harness.type!r}")


def effective_harness_env_names(harness: TesterHarnessSection) -> tuple[str, ...]:
    """Return only environment names that the selected harness passes to the Agent."""
    if harness.type == "command":
        return harness.env
    if harness.type == "codex":
        return codex_env_names(harness.env)
    if harness.type == "claude_code":
        return claude_code_env_names(harness.env)
    raise ConfigError(f"Unsupported harness type: {harness.type!r}")
