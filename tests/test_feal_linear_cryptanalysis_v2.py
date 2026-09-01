from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/feal-linear-cryptanalysis"
IMAGE = (
    "alexgshaw/feal-linear-cryptanalysis@"
    "sha256:ea78749a8422c6228d26c8753f45906a6a2df089906764b7e3c3e27e8f718ee7"
)
ORACLE_ROOT = PACK / "v2" / "hidden" / "feal-linear-cryptanalysis" / "oracle"
ORACLE = ORACLE_ROOT / "oracle.py"
SOURCE_VERIFIER = (
    PACK
    / "hidden"
    / "feal-linear-cryptanalysis"
    / "tests"
    / "test_outputs.py"
)
EXPECTED_SHA256 = "849f9e33e7848d138d8af9880653b6f582c469f992a3ae77625786abc59068e7"
REFERENCE = (ORACLE_ROOT / "plaintexts.txt").read_text(encoding="ascii")
EXPECTED = tuple(REFERENCE.split())


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_plaintexts(tmp_path: Path, content: str | bytes):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "attack.py").write_text("raise SystemExit('excluded')\n")
    target = workspace / "plaintexts.txt"
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8", newline="")
    else:
        target.write_bytes(content)
    return verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "store",
        run_seed="feal-linear-qualification",
    )


def source_accepts(content: str) -> bool:
    source = load_module(SOURCE_VERIFIER, "feal_linear_source_semantics")
    return all(expected in content for expected in source.soln.split())


def test_feal_linear_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert task.environment.timeout_seconds == 1800
    assert not task.assets
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.id == "plaintexts_artifact"
    assert check.artifacts[0].parser == "securebench.utf8-text/v1"
    assert not task.verification.resources.runtime
    candidate = task.verification.candidate
    assert candidate.max_total_files == 1
    assert candidate.max_total_bytes == 16_384
    assert [(item.id, item.path, item.max_bytes) for item in candidate.files] == [
        ("plaintexts", "/app/plaintexts.txt", 16_384)
    ]
    assert {
        path.relative_to(ORACLE_ROOT).as_posix()
        for path in ORACLE_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    } == {"oracle.py", "oracle.yaml", "plaintexts.txt"}


def test_host_plaintexts_are_exactly_the_source_verifier_values():
    source = load_module(SOURCE_VERIFIER, "feal_linear_source_values")
    oracle = load_module(ORACLE, "feal_linear_oracle_values")

    assert EXPECTED == tuple(source.soln.split())
    assert EXPECTED == oracle.load_expected_plaintexts()
    assert len(EXPECTED) == len(set(EXPECTED)) == 100
    assert all(value.isascii() and value.isdecimal() for value in EXPECTED)
    assert len(REFERENCE.encode("ascii")) == 2_047
    assert hashlib.sha256(REFERENCE.encode("ascii")).hexdigest() == EXPECTED_SHA256


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(REFERENCE, id="line_order"),
        pytest.param("".join(EXPECTED), id="concatenated_without_delimiters"),
        pytest.param(",".join(reversed(EXPECTED)), id="reversed_and_comma_separated"),
        pytest.param("claim:pass\x00" + REFERENCE + "extra", id="extra_text_and_nul"),
        pytest.param(REFERENCE + REFERENCE, id="duplicates"),
    ],
)
def test_source_accepted_variants_pass_real_artifact_path(tmp_path, content):
    assert source_accepts(content)

    result, candidate, store = verify_plaintexts(tmp_path, content)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["plaintexts"]
    assert "attack.py" not in str(manifest.payload)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("\n".join(EXPECTED[:-1]), id="one_plaintext_missing"),
        pytest.param(
            "\n".join((str(int(EXPECTED[0]) + 1), *EXPECTED[1:])),
            id="one_plaintext_changed",
        ),
        pytest.param("\n".join(hex(int(value)) for value in EXPECTED), id="hex_values"),
        pytest.param("PASS", id="forged_verdict"),
        pytest.param('{"verdict":"pass","score":1}', id="structured_claim"),
        pytest.param("", id="empty"),
    ],
)
def test_targeted_plaintext_mutants_and_claims_fail(tmp_path, content):
    assert not source_accepts(content)

    result, _, _ = verify_plaintexts(tmp_path, content)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [
        "missing_expected_plaintext"
    ]


def test_invalid_utf8_is_candidate_evidence_not_infrastructure(tmp_path):
    result, _, _ = verify_plaintexts(tmp_path, REFERENCE.encode() + b"\xff")

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == ["invalid_utf8"]


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_plaintexts(tmp_path, REFERENCE)
    replay = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="feal-linear-replay",
    )

    assert first.status == replay.status == "passed"
    assert first.candidate_digest == replay.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("content", "expected_status"),
    [
        pytest.param(REFERENCE, "passed", id="reference"),
        pytest.param("".join(EXPECTED), "passed", id="source_concatenation"),
        pytest.param(",".join(reversed(EXPECTED)), "passed", id="source_reordering"),
        pytest.param("\n".join(EXPECTED[:-1]), "failed", id="missing_one"),
        pytest.param(
            "\n".join((str(int(EXPECTED[0]) + 1), *EXPECTED[1:])),
            "failed",
            id="changed_one",
        ),
        pytest.param('{"verdict":"pass"}', "failed", id="forged_verdict"),
    ],
)
def test_pinned_agent_capture_and_replay_matrix(tmp_path, content, expected_status):
    script = (
        "from pathlib import Path;"
        f"Path('/app/plaintexts.txt').write_text({content!r},encoding='utf-8')"
    )
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("python3", "-c", script),
        run_seed=f"feal-linear-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
