from __future__ import annotations

import hashlib
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
TASK_ID = "terminal-bench/raman-fitting"
IMAGE = "sha256:6f406edf6c8592f0704674def107cdfd46adc60efa6950b787f29891f1d41525"
SPECTRUM_SHA256 = (
    "cac96a29e73251e625cb2d17b5079250071b148e6792e0aa349632953dbfa094"
)

# The source verifier's expected fit parameters.
REFERENCE = {
    "G": {"x0": 1580.3, "gamma": 9.06, "amplitude": 8382.69, "offset": 5561.03},
    "2D": {"x0": 2670.08, "gamma": 17.52, "amplitude": 12314.42, "offset": 1239.09},
}


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_results(tmp_path: Path, content: object | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "fit.log").write_text("excluded", encoding="utf-8")
    target = workspace / "results.json"
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(json.dumps(content), encoding="utf-8")
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="raman-fitting-test-seed",
    )


def assert_candidate_failure(tmp_path: Path, content: object | bytes, category: str):
    result, _, _ = verify_results(tmp_path, content)

    assert result.status == "failed", result
    assert result.score == 0.0
    assert result.infrastructure_error is None, result
    assert category in result.public_diagnostics["failure_categories"], result
    return result


def mutate(peak: str, name: str, value: float) -> dict:
    document = {key: dict(section) for key, section in REFERENCE.items()}
    document[peak][name] = value
    return document


def test_raman_row_is_bounded_split_and_executable():
    task = compiled_task()
    validate_executable_task(task)

    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    # The spectrum ships in the image, but the bare python image has no numpy or
    # scipy, so the agent needs the package index and nothing else.
    assert task.environment.agent_network.mode == "restricted"
    assert task.environment.agent_network.allowed_domains == (
        "pypi.org",
        "pythonhosted.org",
    )

    candidate = task.verification.candidate
    assert isinstance(candidate, FileBundleCandidate)
    assert [entry.id for entry in candidate.files] == ["fit_results"]
    assert candidate.files[0].path == "/app/results.json"

    (check,) = task.verification.checks
    assert isinstance(check, ArtifactCheck)
    assert check.id == "fit_results_artifact"
    assert check.artifacts[0].parser == "securebench.strict-json/v1"

    assert task.verification.oracle == "host.task_oracle"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "oracle" not in view
        assert "8382.69" not in view


def test_oracle_encodes_exactly_the_source_expectations_and_tolerance_kinds():
    oracle_source = (
        PACK / "v2" / "hidden" / "raman-fitting" / "oracle" / "oracle.py"
    ).read_text(encoding="utf-8")
    source_verifier = (
        PACK / "hidden" / "raman-fitting" / "tests" / "test_outputs.py"
    ).read_text(encoding="utf-8")

    for peak in REFERENCE:
        for name, value in REFERENCE[peak].items():
            assert str(value) in oracle_source, (peak, name)
            assert str(value) in source_verifier, (peak, name)

    # The source uses an ABSOLUTE tolerance for G.x0 but a RELATIVE one for 2D.x0.
    # Preserving that asymmetry is the whole fidelity risk in this row.
    assert '"x0": (1580.3, 5.0, ABSOLUTE)' in oracle_source
    assert '"x0": (2670.08, 0.05, RELATIVE)' in oracle_source
    assert "abs(x0 - x0_expected) < 5" in source_verifier
    assert "abs(1 - x0 / x0_expected) < 0.05" in source_verifier


def test_public_spectrum_input_is_stable():
    spectrum = (PACK / "docker" / "raman-fitting" / "task-deps" / "graphene.dat").read_bytes()

    assert len(spectrum) == 88805
    assert hashlib.sha256(spectrum).hexdigest() == SPECTRUM_SHA256
    # The file is CRLF-delimited with European decimal-comma notation, so a
    # naive float() parse of a column fails. That is part of the task.
    assert spectrum.count(b"\r\n") == 3565
    assert spectrum.split(b"\r\n")[0] == b"47183,554644\t19261,547207"


def test_reviewed_reference_passes_real_capture_parser_and_oracle(tmp_path):
    result, candidate, store = verify_results(tmp_path, REFERENCE)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["fit_results"]
    assert "fit.log" not in json.dumps(manifest.payload)


@pytest.mark.parametrize(
    ("document", "reason"),
    [
        pytest.param(
            mutate("G", "x0", 1584.0),
            "G.x0 uses an absolute +/-5 window",
            id="g_x0_within_absolute_window",
        ),
        pytest.param(
            mutate("G", "gamma", 9.9),
            "G.gamma uses an absolute +/-1 window",
            id="g_gamma_within_window",
        ),
        pytest.param(
            mutate("G", "amplitude", 8382.69 * 1.04),
            "amplitude uses a 5% relative window",
            id="amplitude_within_relative_window",
        ),
        pytest.param(
            mutate("G", "offset", 5561.03 * 1.09),
            "offset uses a 10% relative window",
            id="offset_within_relative_window",
        ),
        pytest.param(
            {**REFERENCE, "extra": {"ignored": 1}},
            "unknown top-level keys are unscored by the source",
            id="extra_top_level_key",
        ),
        pytest.param(
            {
                peak: {**values, "note": "unscored"}
                for peak, values in REFERENCE.items()
            },
            "unknown per-peak keys are unscored by the source",
            id="extra_peak_key",
        ),
        pytest.param(
            {peak: {k: int(v) if k == "x0" else v for k, v in values.items()}
             for peak, values in REFERENCE.items()},
            "integers are accepted where floats are expected",
            id="integer_valued_x0",
        ),
    ],
)
def test_source_tolerances_and_unscored_fields_are_preserved(tmp_path, document, reason):
    result, _, _ = verify_results(tmp_path, document)

    assert result.status == "passed", f"{reason}: {result}"


@pytest.mark.parametrize(
    ("document", "category"),
    [
        pytest.param(
            mutate("G", "x0", 1586.0), "G_x0_out_of_tolerance", id="g_x0_just_outside"
        ),
        pytest.param(
            mutate("G", "gamma", 10.5), "G_gamma_out_of_tolerance", id="g_gamma_outside"
        ),
        pytest.param(
            mutate("G", "amplitude", 8382.69 * 1.06),
            "G_amplitude_out_of_tolerance",
            id="amplitude_outside",
        ),
        pytest.param(
            mutate("G", "offset", 5561.03 * 1.2),
            "G_offset_out_of_tolerance",
            id="offset_outside",
        ),
        pytest.param(
            mutate("2D", "x0", 2670.08 * 1.06),
            "2D_x0_out_of_tolerance",
            id="2d_x0_outside_relative",
        ),
        pytest.param(
            # Swapping the two peaks is the classic fitting mistake.
            {"G": REFERENCE["2D"], "2D": REFERENCE["G"]},
            "G_x0_out_of_tolerance",
            id="peaks_swapped",
        ),
        pytest.param(
            {"G": REFERENCE["G"]}, "missing_peak", id="missing_2d_peak"
        ),
        pytest.param(
            mutate("G", "x0", True), "invalid_parameter_type", id="boolean_parameter"
        ),
        pytest.param(
            mutate("G", "x0", "1580.3"), "invalid_parameter_type", id="stringified"
        ),
        pytest.param(
            {peak: {k: v for k, v in values.items() if k != "offset"}
             for peak, values in REFERENCE.items()},
            "invalid_parameter_type",
            id="missing_offset",
        ),
    ],
)
def test_targeted_semantic_mutants_fail(tmp_path, document, category):
    assert_candidate_failure(tmp_path, document, category)


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(b"not json", "invalid_json", id="malformed_json"),
        pytest.param(b"[]", "root_not_object", id="root_array"),
        pytest.param(b"\xff", "invalid_utf8", id="invalid_utf8"),
        pytest.param(
            b'{"verdict":"pass","score":1.0}', "missing_peak", id="forged_verdict"
        ),
        pytest.param(
            b'{"G":{"x0":1580.3,"x0":0,"gamma":9.06,"amplitude":8382.69,"offset":5561.03},'
            b'"2D":{"x0":2670.08,"gamma":17.52,"amplitude":12314.42,"offset":1239.09}}',
            "invalid_json",
            id="duplicate_key",
        ),
        pytest.param(
            b'{"G":{"x0":1e400,"gamma":9.06,"amplitude":8382.69,"offset":5561.03},'
            b'"2D":{"x0":2670.08,"gamma":17.52,"amplitude":12314.42,"offset":1239.09}}',
            "invalid_json",
            id="infinity_literal",
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
        compiled_task(), tmp_path, attack=attack, target_id="fit_results"
    )


def test_missing_deliverable_scores_as_candidate_failure():
    assert_missing_candidate_failure(
        compiled_task(),
        run_seed="raman-fitting-missing",
        check_ids=("fit_results_artifact",),
    )


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_results(tmp_path, REFERENCE)
    second = VerificationEngine().verify(
        compiled_task(), candidate, store, run_seed="raman-fitting-replay"
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
def test_base_image_without_deliverable_is_rejected_at_capture(tmp_path):
    assert_base_capture_rejected(compiled_task(), tmp_path, command=("true",))


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("document", "expected_status"),
    [
        pytest.param(REFERENCE, "passed", id="reference"),
        pytest.param(mutate("G", "x0", 1700.0), "failed", id="wrong_peak_position"),
    ],
)
def test_pinned_agent_capture_and_verification(tmp_path, document, expected_status):
    payload = json.dumps(document).replace("'", "'\\''")
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", f"printf '%s' '{payload}' > /app/results.json"),
        run_seed=f"raman-fitting-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
