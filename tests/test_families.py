from dataclasses import FrozenInstanceError

import pytest

from securebench.benchmark_compiler import compile_benchmark_row
from securebench.benchmark_pack import BenchmarkPackManifest, BenchmarkRow
from securebench.errors import ConfigError
from securebench.families import family_contract_for, known_family_contracts


@pytest.mark.parametrize(
    ("family", "candidate_kind", "requires_workspace"),
    [
        ("multiple_choice", "text", False),
        ("short_answer", "text", False),
        ("free_response", "text", False),
        ("code_generation", "code", False),
        ("repo_patch", "patch", True),
    ],
)
def test_family_contracts_return_candidate_kind(family, candidate_kind, requires_workspace):
    contract = family_contract_for(family)

    assert contract.family == family
    assert contract.candidate_kind == candidate_kind
    assert contract.requires_workspace is requires_workspace


def test_family_contracts_are_immutable():
    contract = family_contract_for("multiple_choice")

    with pytest.raises(FrozenInstanceError):
        contract.candidate_kind = "patch"


def test_known_family_contracts_returns_only_active_families():
    contracts = known_family_contracts()

    assert [contract.family for contract in contracts] == [
        "multiple_choice",
        "short_answer",
        "free_response",
        "code_generation",
        "repo_patch",
    ]


def test_unknown_family_contract_errors_when_execution_contract_is_requested():
    with pytest.raises(ConfigError, match="Unknown benchmark family contract"):
        family_contract_for("terminal_task")


def test_compiled_repo_patch_task_can_lookup_contract_by_task_type():
    task = compile_benchmark_row(
        BenchmarkRow(
            id="repo-1",
            family="repo_patch",
            input={
                "repo": "repo/",
                "base_commit": "abc123",
                "instructions": "Fix the bug",
            },
            eval={"tests": {"path": "tests/test_bug.py"}},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )

    contract = family_contract_for(task.task_type)

    assert contract.family == "repo_patch"
    assert contract.candidate_kind == "patch"
    assert contract.requires_workspace is True
