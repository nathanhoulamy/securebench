"""Verifier registry for benchmark-pack task families."""

from __future__ import annotations

from securebench.verifiers.base import Verifier
from securebench.verifiers.code_completion import CodeCompletionVerifier
from securebench.verifiers.free_response import FreeResponseVerifier
from securebench.verifiers.multiple_choice import MultipleChoiceVerifier
from securebench.verifiers.repo_patch import RepoPatchVerifier
from securebench.verifiers.short_answer import ShortAnswerVerifier


def verifier_for_task_type(task_type: str) -> Verifier | None:
    """Return the implemented verifier for a task family, if any."""
    if task_type == "multiple_choice":
        return MultipleChoiceVerifier()
    if task_type == "short_answer":
        return ShortAnswerVerifier()
    if task_type == "free_response":
        return FreeResponseVerifier()
    if task_type == "code_completion":
        return CodeCompletionVerifier()
    if task_type == "repo_patch":
        return RepoPatchVerifier()
    return None
