"""Verifier registry for benchmark-pack task families."""

from __future__ import annotations

from securebench.verifiers.base import Verifier
from securebench.verifiers.code_completion import CodeCompletionVerifier
from securebench.verifiers.multiple_choice import MultipleChoiceVerifier


def verifier_for_task_type(task_type: str) -> Verifier | None:
    """Return the implemented verifier for a task family, if any."""
    if task_type == "multiple_choice":
        return MultipleChoiceVerifier()
    if task_type == "code_completion":
        return CodeCompletionVerifier()
    return None
