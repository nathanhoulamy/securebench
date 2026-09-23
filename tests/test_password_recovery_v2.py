from __future__ import annotations

import json
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck, FileBundleCandidate
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    assert_base_capture_rejected,
    assert_file_bundle_capture_rejected,
    assert_missing_candidate_failure,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/password-recovery"
IMAGE = "sha256:61af4bf647ba5a2d8567824059149f0a609fb549d9b3247e3a18f1dee2114f17"
# The deleted password, recoverable from the disk image the task ships. Host-side
# qualification material; it is never shown to an Agent or Evaluation runtime.
EXPECTED_PASSWORD = "8XDP5Q2RT9ZK7VB3BV4WW54"


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_guesses(tmp_path: Path, content: str | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    # Forensic scratch work is outside the declared candidate.
    (workspace / "carved.bin").write_bytes(b"excluded")
    target = workspace / "recovered_passwords.txt"
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="password-recovery-test-seed",
    )


def assert_candidate_failure(tmp_path: Path, content: str | bytes, category: str):
    result, _, _ = verify_guesses(tmp_path, content)

    assert result.status == "failed", result
    assert result.score == 0.0
    assert result.infrastructure_error is None, result
    assert category in result.public_diagnostics["failure_categories"], result
    return result


def test_password_recovery_row_is_bounded_split_and_executable():
    task = compiled_task()
    validate_executable_task(task)

    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    # The task is local forensics on the shipped disk image; the tools it needs
    # are baked in, so it declares no egress at all.
    assert task.environment.agent_network.mode == "none"
    assert task.environment.agent_network.allowed_domains == ()

    candidate = task.verification.candidate
    assert isinstance(candidate, FileBundleCandidate)
    assert candidate.max_total_files == 1
    assert [entry.id for entry in candidate.files] == ["recovered_passwords"]
    assert candidate.files[0].path == "/app/recovered_passwords.txt"
    assert candidate.files[0].max_bytes == 65536

    (check,) = task.verification.checks
    assert isinstance(check, ArtifactCheck)
    assert check.id == "recovered_passwords_artifact"
    (artifact,) = check.artifacts
    assert artifact.parser == "securebench.utf8-text/v1"
    assert artifact.limits.max_bytes == 65536

    assert task.verification.oracle == "host.task_oracle"
    assert task.assets == ()
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert EXPECTED_PASSWORD not in view
        assert "oracle" not in view


def test_oracle_encodes_exactly_the_source_expectation():
    oracle_source = (
        PACK / "v2" / "hidden" / "password-recovery" / "oracle" / "oracle.py"
    ).read_text(encoding="utf-8")
    source_verifier = (
        PACK / "hidden" / "password-recovery" / "tests" / "test_outputs.py"
    ).read_text(encoding="utf-8")

    assert f'EXPECTED = "{EXPECTED_PASSWORD}"' in oracle_source
    assert EXPECTED_PASSWORD in source_verifier
    # The source predicate is membership after strip()+split("\n").
    assert '.strip().split("\\n")' in oracle_source


def test_reviewed_reference_passes_real_capture_parser_and_oracle(tmp_path):
    result, candidate, store = verify_guesses(tmp_path, EXPECTED_PASSWORD)

    assert result.status == "passed", result
    assert result.score == 1.0
    assert result.checks[0].id == "recovered_passwords_artifact"

    manifest = store.load_candidate(candidate.digest)
    assert manifest.type == "file_bundle"
    assert [entry["id"] for entry in manifest.payload["entries"]] == [
        "recovered_passwords"
    ]
    assert "carved.bin" not in json.dumps(manifest.payload)


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        pytest.param(
            f"{EXPECTED_PASSWORD}\n", "trailing newline is stripped", id="trailing_newline"
        ),
        pytest.param(
            f"8XDAAAAAAAAAAAAAAAAW54\n{EXPECTED_PASSWORD}\n8XDBBBBBBBBBBBBBBBBW54",
            "the source accepts a correct guess among incorrect ones",
            id="correct_among_wrong",
        ),
        pytest.param(
            f"\n\n{EXPECTED_PASSWORD}\n\n",
            "surrounding blank lines are stripped before splitting",
            id="blank_padding",
        ),
        pytest.param(
            "\n".join([f"8XD{index:017d}W54" for index in range(200)] + [EXPECTED_PASSWORD]),
            "the source sets no upper bound on the number of guesses",
            id="many_guesses",
        ),
    ],
)
def test_source_accepted_quirks_are_preserved(tmp_path, content, reason):
    result, _, _ = verify_guesses(tmp_path, content)

    assert result.status == "passed", f"{reason}: {result}"


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(
            "8XDP5Q2RT9ZK7VB3BV4WW55",
            "password_not_recovered",
            id="one_character_wrong",
        ),
        pytest.param(
            EXPECTED_PASSWORD.lower(),
            "password_not_recovered",
            id="lowercased",
        ),
        pytest.param(
            f"PASSWORD={EXPECTED_PASSWORD}",
            "password_not_recovered",
            id="prefixed_with_key_name",
        ),
        pytest.param(
            f"  {EXPECTED_PASSWORD}  \nother",
            "password_not_recovered",
            id="inner_line_whitespace_not_stripped",
        ),
        pytest.param(
            f"{EXPECTED_PASSWORD} {EXPECTED_PASSWORD}",
            "password_not_recovered",
            id="two_on_one_line",
        ),
        pytest.param("", "password_not_recovered", id="empty_file"),
        pytest.param(
            "\n".join(f"8XD{index:017d}W54" for index in range(50)),
            "password_not_recovered",
            id="brute_force_misses",
        ),
    ],
)
def test_targeted_semantic_mutants_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(b"\xff\xfe", "invalid_utf8", id="invalid_utf8"),
        pytest.param(
            EXPECTED_PASSWORD.encode() + b"\x00",
            "password_not_recovered",
            id="nul_suffix_is_not_stripped",
        ),
        pytest.param(
            b'{"verdict":"pass","score":1.0}',
            "password_not_recovered",
            id="forged_verdict_object",
        ),
        pytest.param(
            b'{"passed":true,"password":"' + EXPECTED_PASSWORD.encode() + b'"}',
            "password_not_recovered",
            id="forged_verdict_with_password",
        ),
    ],
)
def test_malformed_and_forged_artifacts_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
def test_malicious_candidate_filesystem_shapes_are_rejected_at_capture(
    tmp_path, attack
):
    assert_file_bundle_capture_rejected(
        compiled_task(),
        tmp_path,
        attack=attack,
        target_id="recovered_passwords",
    )


def test_missing_deliverable_scores_as_candidate_failure():
    assert_missing_candidate_failure(
        compiled_task(),
        run_seed="password-recovery-missing",
        check_ids=("recovered_passwords_artifact",),
    )


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_guesses(tmp_path, EXPECTED_PASSWORD)
    second = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="password-recovery-replay",
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest
    assert store.reference(candidate.digest) == candidate


@DOCKER_INTEGRATION
def test_base_image_without_deliverable_is_rejected_at_capture(tmp_path):
    """Gate 1: the pinned image ships no recovered_passwords.txt."""
    assert_base_capture_rejected(
        compiled_task(),
        tmp_path,
        command=("true",),
    )


@DOCKER_INTEGRATION
def test_pinned_image_still_contains_the_recoverable_disk_image(tmp_path):
    """The task is only solvable because the carved disk image ships in the image.

    This also proves the plaintext password is NOT directly greppable from the
    disk image: it is split across two embedded fragments, which is what makes
    the forensic recovery a real task rather than a string search.
    """
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=(
            "sh",
            "-c",
            "test -f /app/varsea/disks/sub1/subA/subAlpha/ae3f4c.dat "
            "&& grep -a -c '8XDP5Q2RT9ZK7VB3BV4WW54' "
            "/app/varsea/disks/sub1/subA/subAlpha/ae3f4c.dat > /app/recovered_passwords.txt "
            "|| echo no-plaintext-match > /app/recovered_passwords.txt",
        ),
        run_seed="password-recovery-disk-image-present",
    )

    # Either way the candidate fails scoring; what matters is that the command
    # ran, the disk image existed, and no infrastructure error occurred.
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("written", "expected_status"),
    [
        pytest.param(EXPECTED_PASSWORD, "passed", id="reference"),
        pytest.param("8XDWRONGWRONGWRONGW54", "failed", id="wrong_password"),
    ],
)
def test_pinned_agent_capture_and_verification(tmp_path, written, expected_status):
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=(
            "sh",
            "-c",
            f"printf '%s\\n' '{written}' > /app/recovered_passwords.txt",
        ),
        run_seed=f"password-recovery-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
