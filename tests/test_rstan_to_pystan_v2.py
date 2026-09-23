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
    load_module,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/rstan-to-pystan"
IMAGE = "sha256:2dd475590dc4601966f516e546a982adfa711c23b211547c83d4de2a9e60a141"
ORACLE = PACK / "v2" / "hidden" / "rstan-to-pystan" / "oracle" / "oracle.py"
SOURCE_VERIFIER = PACK / "hidden" / "rstan-to-pystan" / "tests" / "test_outputs.py"

# Midpoints of each accepted range: a correct PyStan conversion lands here.
REFERENCE = {
    "alpha": "1.09\n",
    "sigma": "0.1345\n",
    "rho": "0.585\n0.943\n1.50\n",
    "beta": "-0.035\n-0.815\n0.42\n",
}
NAMES = ("alpha", "sigma", "rho", "beta")


def compiled_task():
    return load_terminal_task(TASK_ID)


def oracle_module():
    return load_module(ORACLE, "rstan_to_pystan_oracle_under_test")


def verify_estimates(tmp_path: Path, files: dict[str, str | bytes]):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "pystan_analysis.py").write_text("excluded", encoding="utf-8")
    for name, content in files.items():
        target = workspace / f"{name}_est.csv"
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return verify_workspace(
        task, workspace, tmp_path / "store", run_seed="rstan-to-pystan-test-seed"
    )


def assert_candidate_failure(tmp_path: Path, files, category: str):
    result, _, _ = verify_estimates(tmp_path, files)

    assert result.status == "failed", result
    assert result.score == 0.0
    assert result.infrastructure_error is None, result
    assert category in result.public_diagnostics["failure_categories"], result


def with_override(**overrides) -> dict[str, str]:
    files = dict(REFERENCE)
    files.update(overrides)
    return files


def test_rstan_row_is_bounded_split_and_executable():
    task = compiled_task()
    validate_executable_task(task)

    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    # The task requires installing PyStan 3.10.0.
    assert task.environment.agent_network.mode == "restricted"
    assert task.environment.agent_network.allowed_domains == (
        "pypi.org",
        "pythonhosted.org",
    )

    candidate = task.verification.candidate
    assert isinstance(candidate, FileBundleCandidate)
    assert [entry.id for entry in candidate.files] == list(NAMES)
    assert [entry.path for entry in candidate.files] == [
        f"/app/{name}_est.csv" for name in NAMES
    ]

    (check,) = task.verification.checks
    assert isinstance(check, ArtifactCheck)
    assert check.id == "posterior_estimates_artifact"
    assert {artifact.id for artifact in check.artifacts} == set(NAMES)
    assert all(a.parser == "securebench.utf8-text/v1" for a in check.artifacts)

    assert task.verification.oracle == "host.task_oracle"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "oracle" not in view
        assert "1.08" not in view


def test_oracle_ranges_match_the_source_verifier():
    module = oracle_module()
    source = SOURCE_VERIFIER.read_text(encoding="utf-8")

    assert module.ALPHA_RANGE == (1.08, 1.1)
    assert module.SIGMA_RANGE == (0.133, 0.136)
    assert module.RHO_RANGES == ((0.57, 0.6), (0.886, 1.0), (1.49, 1.51))
    assert module.BETA_RANGES == ((-0.07, 0.0), (-0.83, -0.8), (0.41, 0.43))

    assert "1.08, 1.1" in source
    assert "0.133, 0.136" in source
    # The source writes the vector bounds as tuples, using bare "0" for 0.0.
    for low, high in module.RHO_RANGES + module.BETA_RANGES:
        rendered = [f"({low}, {high})"]
        if high == int(high):
            rendered.append(f"({low}, {int(high)})")
        if low == int(low):
            rendered.append(f"({int(low)}, {high})")
        assert any(text in source for text in rendered), (low, high)


def test_dropped_source_assertion_is_documented_in_the_oracle():
    """The R/RStan absence probe cannot be decided from captured artifacts.

    The source shells out to `R` inside the candidate's own filesystem. That is a
    property of the environment, not of any artifact, so the conversion drops it
    as an explicit semantic change rather than faking it with a base image that
    happens to lack R.
    """
    module_source = ORACLE.read_text(encoding="utf-8")
    source = SOURCE_VERIFIER.read_text(encoding="utf-8")

    assert "def test_r_rstan_not_installed" in source
    # The source probes the live environment with subprocesses rather than
    # reading any artifact.
    assert "subprocess.run(" in source
    assert '"R"' in source
    assert "library(rstan)" in source
    assert "DOCUMENTED SEMANTIC CHANGE" in module_source
    assert "test_r_rstan_not_installed" in module_source

    task = compiled_task()
    assert task.metadata["conversion"]["verdict"] == "semantic_change"


def test_reviewed_reference_passes_real_capture_parser_and_oracle(tmp_path):
    result, candidate, store = verify_estimates(tmp_path, REFERENCE)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert {e["id"] for e in manifest.payload["entries"]} == set(NAMES)
    assert "pystan_analysis.py" not in json.dumps(manifest.payload)


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        pytest.param(
            with_override(alpha="1.09,extra,junk\n"),
            "the source takes only the first comma-separated token for scalars",
            id="scalar_trailing_columns_ignored",
        ),
        pytest.param(
            with_override(rho="0.585,ignored\n0.943,ignored\n1.50,ignored\n"),
            "the source takes only column 0 of each vector row",
            id="vector_extra_columns_ignored",
        ),
        pytest.param(
            with_override(rho="0.585\n\n0.943\n\n1.50\n"),
            "the source skips empty rows",
            id="blank_rows_skipped",
        ),
        pytest.param(
            with_override(alpha="   1.09   "),
            "the source strips surrounding whitespace",
            id="whitespace_padded_scalar",
        ),
        pytest.param(
            with_override(alpha="1.08\n", sigma="0.136\n"),
            "range bounds are inclusive in the source",
            id="inclusive_bounds",
        ),
    ],
)
def test_source_parsing_quirks_are_preserved(tmp_path, files, reason):
    result, _, _ = verify_estimates(tmp_path, files)

    assert result.status == "passed", f"{reason}: {result}"


@pytest.mark.parametrize(
    ("files", "category"),
    [
        pytest.param(
            with_override(alpha="1.11\n"), "alpha_out_of_range", id="alpha_above"
        ),
        pytest.param(
            with_override(alpha="1.07\n"), "alpha_out_of_range", id="alpha_below"
        ),
        pytest.param(
            with_override(sigma="0.14\n"), "sigma_out_of_range", id="sigma_above"
        ),
        pytest.param(
            with_override(rho="0.585\n0.943\n1.52\n"),
            "rho_out_of_range",
            id="rho_third_above",
        ),
        pytest.param(
            with_override(rho="1.50\n0.943\n0.585\n"),
            "rho_out_of_range",
            id="rho_reversed_order",
        ),
        pytest.param(
            with_override(beta="0.035\n-0.815\n0.42\n"),
            "beta_out_of_range",
            id="beta_sign_flipped",
        ),
        pytest.param(
            with_override(rho="0.585\n0.943\n"), "rho_wrong_length", id="rho_too_short"
        ),
        pytest.param(
            with_override(rho="0.585\n0.943\n1.50\n1.50\n"),
            "rho_wrong_length",
            id="rho_too_long",
        ),
        pytest.param(
            with_override(alpha="not-a-number\n"), "alpha_unparsable", id="alpha_text"
        ),
        pytest.param(
            with_override(alpha=""), "alpha_unparsable", id="alpha_empty"
        ),
        pytest.param(
            with_override(beta="nan\n-0.815\n0.42\n"),
            "beta_not_finite",
            id="beta_nan",
        ),
        pytest.param(
            with_override(alpha="inf\n"), "alpha_not_finite", id="alpha_infinite"
        ),
    ],
)
def test_targeted_semantic_mutants_fail(tmp_path, files, category):
    assert_candidate_failure(tmp_path, files, category)


@pytest.mark.parametrize(
    ("files", "category"),
    [
        pytest.param(
            with_override(alpha=b"\xff\xfe"), "invalid_utf8", id="invalid_utf8"
        ),
        pytest.param(
            with_override(alpha=b'{"verdict":"pass"}'),
            "alpha_unparsable",
            id="forged_verdict",
        ),
    ],
)
def test_malformed_and_forged_artifacts_fail(tmp_path, files, category):
    assert_candidate_failure(tmp_path, files, category)


@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
@pytest.mark.parametrize("target", NAMES)
def test_malicious_candidate_filesystem_shapes_are_rejected_at_capture(
    tmp_path, attack, target
):
    assert_file_bundle_capture_rejected(
        compiled_task(), tmp_path, attack=attack, target_id=target
    )


def test_missing_deliverable_scores_as_candidate_failure():
    assert_missing_candidate_failure(
        compiled_task(),
        run_seed="rstan-to-pystan-missing",
        check_ids=("posterior_estimates_artifact",),
    )


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_estimates(tmp_path, REFERENCE)
    second = VerificationEngine().verify(
        compiled_task(), candidate, store, run_seed="rstan-to-pystan-replay"
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
def test_base_image_without_deliverables_is_rejected_at_capture(tmp_path):
    assert_base_capture_rejected(compiled_task(), tmp_path, command=("true",))


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("alpha", "expected_status"),
    [
        pytest.param("1.09", "passed", id="reference"),
        pytest.param("2.5", "failed", id="alpha_out_of_range"),
    ],
)
def test_pinned_agent_capture_and_verification(tmp_path, alpha, expected_status):
    script = (
        f"printf '%s\\n' '{alpha}' > /app/alpha_est.csv; "
        "printf '%s\\n' '0.1345' > /app/sigma_est.csv; "
        "printf '0.585\\n0.943\\n1.50\\n' > /app/rho_est.csv; "
        "printf -- '-0.035\\n-0.815\\n0.42\\n' > /app/beta_est.csv"
    )
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", script),
        run_seed=f"rstan-to-pystan-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
