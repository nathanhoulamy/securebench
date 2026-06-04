"""Registry for benchmark family contracts and row schema validators."""

from __future__ import annotations

from typing import Any

from securebench.errors import ConfigError
from securebench.families.base import FamilyContract, FamilyValidator
from securebench.families.repo_patch import validate as validate_repo_patch
from securebench.families.terminal_task import validate as validate_terminal_task


FAMILY_CONTRACTS: dict[str, FamilyContract] = {
    "repo_patch": FamilyContract("repo_patch", "patch", requires_workspace=True),
    "terminal_task": FamilyContract("terminal_task", "workspace", requires_workspace=True),
}


FAMILY_VALIDATORS: dict[str, FamilyValidator] = {
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
    """Validate family-specific row fields for supported benchmark families."""
    validator = FAMILY_VALIDATORS.get(row.family)
    if validator is None:
        raise ConfigError(f"Unknown benchmark family: {row.family!r}")
    validator(row, context or f"task {row.id!r} ({row.family})")
