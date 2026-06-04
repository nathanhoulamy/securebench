"""Verifier registry for benchmark-pack task families."""

from __future__ import annotations

from securebench.verifiers.base import Verifier
from securebench.verifiers.repo_patch import RepoPatchVerifier
from securebench.verifiers.terminal_task import TerminalTaskVerifier


def verifier_for_task_type(task_type: str) -> Verifier | None:
    """Return the implemented verifier for a task family, if any."""
    if task_type == "repo_patch":
        return RepoPatchVerifier()
    if task_type == "terminal_task":
        return TerminalTaskVerifier()
    return None
