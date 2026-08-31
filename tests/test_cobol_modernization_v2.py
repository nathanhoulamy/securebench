from __future__ import annotations

from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ProtocolCheck
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/cobol-modernization"
IMAGE = (
    "alexgshaw/cobol-modernization@"
    "sha256:593ab9df3d83f771e927888b2d9436b380cdf7ec4d0af2a9f0802d541edebba0"
)
ADAPTER = (
    PACK
    / "v2"
    / "evaluation_inputs"
    / "cobol-modernization"
    / "adapter"
)
ORACLE = (
    PACK
    / "v2"
    / "hidden"
    / "cobol-modernization"
    / "oracle"
    / "oracle.py"
)
REFERENCE = Path("/tmp/securebench-cobol-reference/program.py")
ORIGINAL_ACCOUNTS = (
    "U001John Doe            0000001000"
    "U002Jane Smith          0000002000"
    "U003Bob Wilson          0000001500"
)
ORIGINAL_BOOKS = (
    "B001Python Basics       U001"
    "B002COBOL Guide         U002"
    "B003Java Tutorial       U003"
)
EXPECTED_ACCOUNTS = (
    "U001John Doe            0000001180"
    "U002Jane Smith          0000001800"
    "U003Bob Wilson          0000001520"
)
EXPECTED_BOOKS = (
    "B001Python Basics       U002"
    "B002COBOL Guide         U002"
    "B003Java Tutorial       U002"
)
EXPECTED_TRANSACTIONS = (
    "B0030000000020U003U001"
    "B0030000000050U001U002"
    "B0010000000150U001U002"
)


def compiled_task():
    return load_terminal_task(TASK_ID)


def _successful_evidence(context, index):
    evaluation_id = f"evaluation_{index}"
    challenge_id = f"challenge_{index}"
    artifacts = {
        name: {
            "challenge_id": challenge_id,
            "evaluation_id": evaluation_id,
            "status": "observed",
            "digest": "sha256:" + f"{index + offset:064x}",
            "size": len(value.encode()),
            "parser": "securebench.utf8-text/v1",
            "parsed_value": value,
            "failure": None,
        }
        for offset, (name, value) in enumerate(context["expected"].items())
    }
    return {
        "status": "observed",
        "challenge": {"id": challenge_id},
        "evaluation_id": evaluation_id,
        "observation": {
            "exit_codes": [0] * context["input_count"],
            "timed_out": False,
        },
        "output_artifacts": artifacts,
        "failure": None,
    }


def _capture_and_verify(tmp_path, name, content, *, run_seed):
    task = compiled_task()
    workspace = tmp_path / name
    workspace.mkdir()
    (workspace / "program.py").write_bytes(content)
    result, _, _ = verify_workspace(
        task,
        workspace,
        tmp_path / f"store-{name}",
        run_seed=run_seed,
    )
    return result


def test_cobol_row_is_bounded_split_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.verification.candidate.max_total_files == 1
    assert task.verification.candidate.max_total_bytes == 256 * 1024
    assert task.verification.candidate.files[0].path == "/app/program.py"
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ProtocolCheck)
    assert check.protocol == "securebench.fixed-record-transactions/v1"
    assert check.challenge.max_cases == 4
    assert not check.trusted_helpers
    assert [artifact.name for artifact in check.output_artifacts] == [
        "accounts",
        "books",
        "transactions",
    ]

    adapter_files = {
        path.relative_to(ADAPTER).as_posix()
        for path in ADAPTER.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert adapter_files == {"adapter.py", "adapter.yaml"}
    public_adapter = (ADAPTER / "adapter.py").read_text()
    for hidden_term in (
        "U001",
        "B001",
        "EXPECTED",
        "expected",
        "balance",
        "owner",
        "verdict",
        "score",
    ):
        assert hidden_term not in public_adapter


def test_adapter_regular_file_replacement_rejects_symlinks(tmp_path):
    adapter = load_module(ADAPTER / "adapter.py", "cobol_adapter_paths")
    target = tmp_path / "INPUT.DAT"
    adapter._replace_regular_file(target, "first")
    assert target.read_text() == "first"
    target.unlink()
    outside = tmp_path / "outside"
    outside.write_text("unchanged")
    target.symlink_to(outside)

    with pytest.raises(OSError):
        adapter._replace_regular_file(target, "attack")

    assert outside.read_text() == "unchanged"


def test_oracle_preserves_original_sequence_and_expected_bytes():
    oracle_module = load_module(ORACLE, "cobol_oracle_original")
    challenge, context = oracle_module.original_case()

    assert challenge == {
        "initial_accounts": ORIGINAL_ACCOUNTS,
        "initial_books": ORIGINAL_BOOKS,
        "initial_transactions": "",
        "inputs": list(oracle_module.ORIGINAL_INPUTS),
    }
    assert context["expected"] == {
        "accounts": EXPECTED_ACCOUNTS,
        "books": EXPECTED_BOOKS,
        "transactions": EXPECTED_TRANSACTIONS,
    }


def test_seeded_cases_are_deterministic_private_and_well_formed():
    oracle_module = load_module(ORACLE, "cobol_oracle_seeded")
    first = oracle_module.CobolModernizationOracle()
    repeated = oracle_module.CobolModernizationOracle()
    second = oracle_module.CobolModernizationOracle()
    first.initialize("first-seed")
    repeated.initialize("first-seed")
    second.initialize("second-seed")

    assert len(first.cases) == 4
    assert first.cases == repeated.cases
    assert first.cases[1:] != second.cases[1:]
    for challenge, context in first.cases:
        assert 1 <= len(challenge["inputs"]) <= 4
        assert all(len(item) == 22 and item[12:].isdigit() for item in challenge["inputs"])
        assert len(challenge["initial_accounts"]) == 3 * 34
        assert len(challenge["initial_books"]) == 3 * 28
        assert set(context["expected"]) == {"accounts", "books", "transactions"}


def test_oracle_accepts_independent_correct_evidence():
    oracle_module = load_module(ORACLE, "cobol_oracle_pass")
    oracle = oracle_module.CobolModernizationOracle()
    oracle.initialize("qualification-seed")
    index = 0
    while (case := oracle.next_case())["type"] == "case":
        oracle.evaluate_case(
            case["case_context"],
            _successful_evidence(case["case_context"], index),
        )
        index += 1

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is True
    assert verdict["check_outcomes"] == {"transaction_behavior": True}


@pytest.mark.parametrize(
    "attack",
    [
        "accounts_mutant",
        "fixed_original_outputs",
        "forged_claim",
        "reused_evaluation",
        "missing_artifact",
        "nonzero_exit",
    ],
)
def test_oracle_rejects_mutants_and_candidate_claims(attack):
    oracle_module = load_module(ORACLE, f"cobol_oracle_{attack}")
    oracle = oracle_module.CobolModernizationOracle()
    oracle.initialize("mutant-seed")
    original_expected = oracle.cases[0][1]["expected"]
    index = 0
    while (case := oracle.next_case())["type"] == "case":
        context = case["case_context"]
        evidence = _successful_evidence(context, index)
        if attack == "accounts_mutant" and index == 0:
            evidence["output_artifacts"]["accounts"]["parsed_value"] += "0"
        elif attack == "fixed_original_outputs" and index > 0:
            for name, value in original_expected.items():
                evidence["output_artifacts"][name]["parsed_value"] = value
        elif attack == "forged_claim" and index == 0:
            evidence["observation"]["claimed_verdict"] = {
                "passed": True,
                "score": 1,
            }
            evidence["output_artifacts"]["transactions"]["parsed_value"] = ""
        elif attack == "reused_evaluation":
            evidence["evaluation_id"] = "evaluation_0"
            for artifact in evidence["output_artifacts"].values():
                artifact["evaluation_id"] = "evaluation_0"
        elif attack == "missing_artifact" and index == 0:
            del evidence["output_artifacts"]["books"]
        elif attack == "nonzero_exit" and index == 0:
            evidence["observation"]["exit_codes"][0] = 1
        oracle.evaluate_case(context, evidence)
        index += 1

    assert oracle.verdict()["verdict"]["passed"] is False


@DOCKER_INTEGRATION
def test_official_reference_passes_real_pinned_evaluations(tmp_path):
    if not REFERENCE.is_file():
        pytest.skip("extract the pinned official reference under /tmp for qualification")
    result = _capture_and_verify(
        tmp_path,
        "reference",
        REFERENCE.read_bytes(),
        run_seed="cobol-modernization-reference",
    )

    assert result.status == "passed", result
    behavior = result.checks[0]
    assert behavior.cases == 4
    assert len(set(behavior.evidence_digests)) == 4


@DOCKER_INTEGRATION
def test_noop_fixed_output_and_forged_claim_mutants_fail_real_evaluations(tmp_path):
    fixed = f'''from pathlib import Path
Path("/app/data/ACCOUNTS.DAT").write_text({EXPECTED_ACCOUNTS!r})
Path("/app/data/BOOKS.DAT").write_text({EXPECTED_BOOKS!r})
Path("/app/data/TRANSACTIONS.DAT").write_text({EXPECTED_TRANSACTIONS!r})
'''.encode()
    mutants = {
        "noop": b"pass\n",
        "fixed": fixed,
        "forged": b'print(\'{"verdict":{"passed":true,"score":1}}\')\n',
    }
    for name, content in mutants.items():
        result = _capture_and_verify(
            tmp_path,
            name,
            content,
            run_seed=f"cobol-modernization-{name}-mutant",
        )
        assert result.status == "failed", result
        assert result.infrastructure_error is None, result


@DOCKER_INTEGRATION
def test_output_symlink_is_candidate_failure_in_real_evaluation(tmp_path):
    attack = b'''from pathlib import Path
target = Path("/app/data/ACCOUNTS.DAT")
target.unlink(missing_ok=True)
target.symlink_to("/etc/passwd")
'''
    result = _capture_and_verify(
        tmp_path,
        "output-symlink",
        attack,
        run_seed="cobol-modernization-output-symlink",
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert "output_artifact_rejected" in result.public_diagnostics[
        "failure_categories"
    ]
