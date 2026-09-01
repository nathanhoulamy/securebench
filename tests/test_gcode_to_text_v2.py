from __future__ import annotations

import ast
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
TASK_ID = "terminal-bench/gcode-to-text"
IMAGE = (
    "alexgshaw/gcode-to-text@"
    "sha256:0979ef40c6a3e8c4e7ab5b6c2524c74625a84799e15cd45dd98dcf83b11efd4d"
)
ORACLE_ROOT = PACK / "v2" / "hidden" / "gcode-to-text" / "oracle"
ORACLE = ORACLE_ROOT / "oracle.py"
SOURCE_VERIFIER = PACK / "hidden" / "gcode-to-text" / "tests" / "test_outputs.py"
EXPECTED = "flag{gc0d3_iz_ch4LLenGiNg}"
INPUT_BYTES = 1_661_422
INPUT_SHA256 = "17f1dfca4f3b02bf8917c02b32688282b92af51e4d1351cde0f814cbe85c6193"


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_text(tmp_path: Path, content: str | bytes):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "out.txt"
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8", newline="")
    else:
        target.write_bytes(content)
    return verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "store",
        run_seed="gcode-to-text-qualification",
    )


def artifact_evidence(value: str) -> dict:
    return {
        "check_id": "decoded_text_artifact",
        "artifact_id": "decoded_text",
        "status": "observed",
        "parsed_value": value,
    }


def test_gcode_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert task.environment.timeout_seconds == 900
    assert not task.assets
    assert not task.verification.resources.runtime
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.id == "decoded_text_artifact"
    assert [(item.id, item.parser, item.limits.max_bytes) for item in check.artifacts] == [
        ("decoded_text", "securebench.utf8-text/v1", 4096)
    ]
    candidate = task.verification.candidate
    assert candidate.max_total_files == 1
    assert candidate.max_total_bytes == 4096
    assert [(item.id, item.path, item.max_bytes) for item in candidate.files] == [
        ("decoded_text", "/app/out.txt", 4096)
    ]
    assert {
        path.relative_to(ORACLE_ROOT).as_posix()
        for path in ORACLE_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    } == {"oracle.py", "oracle.yaml"}


def test_host_expectation_and_normalization_match_source_verifier():
    tree = ast.parse(SOURCE_VERIFIER.read_text(encoding="utf-8"))
    source_strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    oracle = load_module(ORACLE, "gcode_to_text_source_semantics")

    assert EXPECTED in source_strings
    assert oracle.EXPECTED_TEXT == EXPECTED
    assert oracle.source_normalize("\r\n\u2003" + EXPECTED + "\u2002\r") == EXPECTED
    assert oracle.source_normalize(EXPECTED[:8] + "\r" + EXPECTED[8:]) != EXPECTED


@pytest.mark.parametrize(
    "content",
    [
        EXPECTED,
        "  \t\r\n" + EXPECTED + "\n\v\f ",
        "\u2003" + EXPECTED + "\u2002",
        "\x1c" + EXPECTED + "\x1f",
    ],
)
def test_source_accepted_whitespace_variants_pass(tmp_path, content):
    result, candidate, store = verify_text(tmp_path, content)

    assert result.status == "passed", result
    assert result.candidate_digest == candidate.digest
    assert len(store.load_candidate(candidate.digest).payload["entries"]) == 1


@pytest.mark.parametrize(
    "content",
    [
        EXPECTED.lower(),
        EXPECTED.replace("_", " ", 1),
        "decoded: " + EXPECTED,
        EXPECTED + " extra",
        "PASS",
        '{"verdict":"passed","score":1}',
        "",
    ],
)
def test_targeted_mutants_and_forged_claims_fail(tmp_path, content):
    result, _, _ = verify_text(tmp_path, content)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [
        "incorrect_decoded_text"
    ]


def test_invalid_utf8_is_candidate_evidence_not_infrastructure(tmp_path):
    result, _, _ = verify_text(tmp_path, EXPECTED.encode() + b"\xff")

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == ["invalid_utf8"]


def test_oracle_rejects_duplicate_and_uncorrelated_artifacts():
    module = load_module(ORACLE, "gcode_to_text_oracle_correlation")
    oracle = module.GcodeTextOracle()
    oracle.initialize()
    oracle.evaluate(artifact_evidence(EXPECTED))
    oracle.evaluate(artifact_evidence(EXPECTED))

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is False
    assert verdict["check_outcomes"] == {"decoded_text_artifact": False}
    assert verdict["public_diagnostics"]["failure_categories"] == [
        "duplicate_artifact"
    ]

    oracle.initialize()
    evidence = artifact_evidence(EXPECTED)
    evidence["artifact_id"] = "unexpected"
    oracle.evaluate(evidence)
    assert oracle.verdict()["verdict"]["passed"] is False


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_text(tmp_path, EXPECTED)
    replay = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="gcode-to-text-replay",
    )

    assert first.status == replay.status == "passed"
    assert first.candidate_digest == replay.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
def test_pinned_input_identity_and_reference_pass(tmp_path):
    script = (
        "from pathlib import Path;import hashlib;"
        "p=Path('/app/text.gcode');b=p.read_bytes();"
        f"assert len(b)=={INPUT_BYTES};"
        f"assert hashlib.sha256(b).hexdigest()=='{INPUT_SHA256}';"
        f"Path('/app/out.txt').write_text({EXPECTED!r},encoding='utf-8')"
    )
    result, candidate, store = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("python3", "-c", script),
        run_seed="gcode-to-text-pinned-reference",
    )
    replay = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="gcode-to-text-pinned-reference",
    )

    assert result.status == replay.status == "passed"
    assert result.candidate_digest == replay.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "content",
    [
        pytest.param(EXPECTED.lower(), id="wrong-case"),
        pytest.param("PASS", id="forged-pass"),
        pytest.param('{"verdict":"passed"}', id="structured-claim"),
    ],
)
def test_pinned_semantic_and_forged_mutants_fail(tmp_path, content):
    script = f"from pathlib import Path;Path('/app/out.txt').write_text({content!r})"
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("python3", "-c", script),
        run_seed="gcode-to-text-pinned-mutant",
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
