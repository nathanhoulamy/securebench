"""Registry for benchmark family contracts and row schema validators."""

from __future__ import annotations

from typing import Any

from securebench.errors import ConfigError
from securebench.families.base import FamilyContract, FamilyValidator
from securebench.families.code_completion import validate as validate_code_completion
from securebench.families.free_response import validate as validate_free_response
from securebench.families.multiple_choice import validate as validate_multiple_choice
from securebench.families.repo_patch import validate as validate_repo_patch
from securebench.families.short_answer import validate as validate_short_answer
from securebench.families.terminal_task import validate as validate_terminal_task


FAMILY_CONTRACTS: dict[str, FamilyContract] = {
    "multiple_choice": FamilyContract("multiple_choice", "text"),
    "short_answer": FamilyContract("short_answer", "text"),
    "free_response": FamilyContract("free_response", "text"),
    "code_completion": FamilyContract("code_completion", "code"),
    "repo_patch": FamilyContract("repo_patch", "patch", requires_workspace=True),
    "terminal_task": FamilyContract("terminal_task", "workspace", requires_workspace=True),
}


FAMILY_VALIDATORS: dict[str, FamilyValidator] = {
    "multiple_choice": validate_multiple_choice,
    "short_answer": validate_short_answer,
    "free_response": validate_free_response,
    "code_completion": validate_code_completion,
    "repo_patch": validate_repo_patch,
    "terminal_task": validate_terminal_task,
}


def family_contract_for(family: str) -> FamilyContract:
    """Return the candidate-output contract for a known benchmark family."""
    contract = FAMILY_CONTRACTS.get(family)
    if contract is None:
        raise ConfigError(f"Unknown benchmark family contract: {family!r}")
    return contract


def known_family_contracts() -> tuple[FamilyContract, ...]:
    """Return all currently executable family contracts."""
    return tuple(FAMILY_CONTRACTS.values())


def validate_benchmark_row_family(row: Any, *, context: str | None = None) -> None:
    """Validate active family-specific row fields.

    Unknown and deferred families intentionally remain permissive here so pack
    loading and compilation can keep accepting benchmark families whose
    verifiers are not implemented yet.
    """
    validator = FAMILY_VALIDATORS.get(row.family)
    if validator is None:
        return
    validator(row, context or f"task {row.id!r} ({row.family})")
