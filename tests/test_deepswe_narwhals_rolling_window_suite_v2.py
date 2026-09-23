"""Qualification for `deep-swe/narwhals-rolling-window-suite`.

Follows the pattern established by `test_deepswe_first_wave_replay_v2.py`
(real-capture Docker replay for Gates 1 and 2, and the generic file-drop
mutant) and `test_pilot_conversions_v2.py` (Oracle-level driving for Gate 4's
malformed-evidence rejection). Unlike the dateutil/cattrs conversions, this
row's Gate 3 mutants are *real code* edits applied on top of the upstream
gold solution and replayed through the real capture -> Evaluation -> Oracle
path in Docker (`verify_patch(..., reference=True, mutate=<hand edit>)`),
each hitting a semantic axis the Oracle's independent rolling-window
reference implementation (`oracle.py`) was cross-checked against by hand
inside the pinned image before being written (see the dossier).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.verification.json_data import json_digest
from securebench.verification.models import ChallengeEvidence
from securebench.verification.oracle import OracleProcessSession
from tests.deepswe_qualification import (
    deep_task,
    materialize_baseline,
    reference_patch,
    verify_patch,
)
from tests.qualification_support import DOCKER_INTEGRATION


ROOT = Path(__file__).resolve().parents[1]
NAME = "narwhals-rolling-window-suite"
CHECK_ID = "rolling_window_behavior"


# --------------------------------------------------------------------------
# Preflight and visibility.


def test_row_preflights_and_keeps_hidden_material_off_both_views():
    task = deep_task(NAME)
    validate_executable_task(task)

    assert task.family == "repo_patch"
    assert task.verification.candidate.type == "git_patch"
    assert re.fullmatch(r"[0-9a-f]{40}", task.input["base_commit"])
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
        assert "oracle.py" not in view
    assert "adapter.py" not in str(task.view_for("agent"))


def test_reference_patch_is_the_pinned_upstream_solution():
    import hashlib

    patch = reference_patch(NAME)
    provenance = json.loads((patch.parent / "provenance.json").read_text())

    assert provenance["source_revision"] == "e016041a6ccf8da29906afc9a3f5a8df940a1f78"
    assert provenance["source_path"] == f"tasks/{NAME}/solution/solution.patch"
    assert provenance["sha256"] == hashlib.sha256(patch.read_bytes()).hexdigest()
    assert provenance["baseline_commit"] == deep_task(NAME).input["base_commit"]


# --------------------------------------------------------------------------
# Gates 1, 2, and the generic file-drop mutant: real Docker replay.


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp(f"{NAME}-baseline") / "app"
    return materialize_baseline(NAME, root)


@DOCKER_INTEGRATION
def test_base_fails_through_the_real_capture_path(tmp_path, baseline):
    """Gate 1: the unmodified base commit must not pass.

    `rolling_min`/`rolling_max`/`rolling_median`/`rolling_quantile` do not
    exist on `Expr`/`Series` at the base commit, so every case raises
    `AttributeError` inside the adapter, which reports `run_error`.
    """
    outcome = verify_patch(NAME, baseline, tmp_path, run_seed=f"{NAME}-base")

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_reference_passes_in_fresh_evaluations(tmp_path, baseline):
    """Gate 2: the upstream solution passes, one fresh Evaluation per case."""
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, run_seed=f"{NAME}-reference"
    )

    assert outcome.status == "passed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert len(outcome.evidence) >= 2
    assert len(set(outcome.evaluation_ids)) == len(outcome.evaluation_ids)
    assert all(item.status == "observed" for item in outcome.evidence)


def _file_diffs(patch_text: str) -> list[tuple[str, str]]:
    chunks = re.split(r"(?m)^(?=diff --git )", patch_text)
    pairs = []
    for chunk in chunks:
        match = re.match(r"diff --git a/(\S+) b/\S+", chunk)
        if match:
            pairs.append((match.group(1), chunk))
    return pairs


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    return (
        "test" in lowered.split("/")[-1]
        or "/tests/" in f"/{lowered}"
        or lowered.startswith("tests/")
    )


@DOCKER_INTEGRATION
def test_dropping_the_largest_source_change_fails(tmp_path, baseline):
    """Gate 3 (generic mutant): drop the largest non-test file of the gold patch."""
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    kept = "".join(diff for path, diff in diffs if path != dropped)

    def apply_partial(workspace: Path) -> None:
        if not kept:
            return
        subprocess.run(
            ["git", "-C", str(workspace), "apply", "--whitespace=nowarn", "-"],
            input=kept.encode(),
            check=True,
        )

    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=apply_partial, run_seed=f"{NAME}-partial",
    )

    assert outcome.status == "failed", (dropped, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence


# --------------------------------------------------------------------------
# Gate 3: three targeted REAL-CODE mutants, gold patch + one hand edit each,
# replayed through real Docker Evaluations, each on a distinct semantic axis.


def _replace_once(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(before)
    assert count == 1, (path, count, before)
    path.write_text(text.replace(before, after), encoding="utf-8")


def _mutate_median_even_window_drops_averaging(workspace: Path) -> None:
    """Axis: rolling_median even-window averaging (test_rolling_median_expr /
    test_rolling_median_hypothesis with an even-length valid window).

    The gold ArrowSeries `_median` helper averages the two middle order
    statistics for an even-count window. This hand edit instead returns just
    the upper middle element -- a plausible off-by-one a candidate could
    ship -- which is wrong whenever a window has an even number of non-null
    values (most windows in this row's cases).
    """
    target = workspace / "narwhals" / "_arrow" / "series.py"
    _replace_once(
        target,
        "            mid = count // 2\n"
        "            return (sorted_arr[mid - 1].as_py() + sorted_arr[mid].as_py()) / 2.0\n",
        "            mid = count // 2\n"
        "            return sorted_arr[mid].as_py()  # BUG: drops the lower order statistic\n",
    )


def _mutate_quantile_ignores_interpolation(workspace: Path) -> None:
    """Axis: rolling_quantile interpolation selection (test_rolling_quantile_expr_lower /
    _higher / _nearest / _midpoint).

    The gold ArrowSeries `_quantile` helper branches on the `interpolation`
    argument. This hand edit inserts an early return that always uses the
    linear formula, silently ignoring `interpolation` -- a candidate that
    forgot to plumb the parameter through would look identical for the
    default `"linear"` case but wrong for every other interpolation.
    """
    target = workspace / "narwhals" / "_arrow" / "series.py"
    _replace_once(
        target,
        "            low_val = sorted_arr[low].as_py()\n"
        "            high_val = sorted_arr[high].as_py()\n"
        "            if interpolation == \"linear\":\n",
        "            low_val = sorted_arr[low].as_py()\n"
        "            high_val = sorted_arr[high].as_py()\n"
        "            return low_val + frac * (high_val - low_val)  # BUG: ignores interpolation\n"
        "            if interpolation == \"linear\":\n",
    )


def _mutate_quantile_validation_accepts_out_of_range(workspace: Path) -> None:
    """Axis: rolling_quantile input validation (test_rolling_quantile_invalid_quantile).

    The public instruction requires `ValueError` for `quantile` outside
    `[0.0, 1.0]`. This hand edit widens the accepted range for `Expr`, so a
    clearly out-of-range value like `1.5` is silently accepted instead of
    raising.
    """
    target = workspace / "narwhals" / "expr.py"
    _replace_once(
        target,
        "        if not (0 <= quantile <= 1):\n"
        "            msg = f\"Quantile must be between 0.0 and 1.0, got {quantile}\"\n",
        "        if not (0 <= quantile <= 2):  # BUG: widened range\n"
        "            msg = f\"Quantile must be between 0.0 and 1.0, got {quantile}\"\n",
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_median_even_window_drops_averaging,
        _mutate_quantile_ignores_interpolation,
        _mutate_quantile_validation_accepts_out_of_range,
    ],
    ids=["median-even-window", "quantile-interpolation", "quantile-validation-range"],
)
def test_targeted_real_code_mutant_fails(tmp_path, baseline, mutate):
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-{mutate.__name__}",
    )

    assert outcome.status == "failed", (mutate.__name__, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence


# --------------------------------------------------------------------------
# Gate 4: forged / malformed evidence is rejected by the Oracle (no Docker).


def _reference_observation(expected: dict) -> dict:
    """A correct-by-construction observation built only from the `expected`
    data the Oracle's own case generator produced (visible in
    `case.context`), never from running narwhals -- this exists to exercise
    the Oracle's comparison logic directly for the malformed-evidence gate.
    """
    if expected["kind"] == "invalid":
        return {
            "status": "observed", "values_json": "[]",
            "raised": True, "raised_error_type": expected["error_type"],
            "raised_message": expected["message_prefix"] + " (reference)",
            "error_type": "", "error_message": "",
        }
    return {
        "status": "observed", "values_json": json.dumps(expected["values"]),
        "raised": False, "raised_error_type": "", "raised_message": "",
        "error_type": "", "error_message": "",
    }


def _evidence(challenge, observation, index) -> ChallengeEvidence:
    return ChallengeEvidence(
        check_id=CHECK_ID,
        challenge_id=f"challenge-test-{index}",
        evaluation_id=f"evaluation-test-{index}",
        challenge_index=index,
        challenge_digest=json_digest(challenge),
        status="observed",
        exit_status=0,
        observation=observation,
        observation_bytes=len(json.dumps(observation)),
    )


def test_reference_observations_pass_every_oracle_case():
    """Fast sanity check (no Docker): replaying every Oracle case with a
    reference-correct observation, built only from `expected`, passes.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-oracle-sanity")
        index = 0
        while (case := session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})) is not None:
            observation = _reference_observation(case.context["expected"])
            session.evaluate_challenge(
                CHECK_ID, case.context, _evidence(case.challenge, observation, index),
            )
            index += 1
        verdict = session.finalize()
    assert verdict.passed is True, verdict
    assert index >= 20


def test_forged_status_observed_with_missing_fields_is_rejected():
    """A malformed observation (missing every op-specific field) must not pass."""
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged")
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})
        assert case is not None
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-0",
            evaluation_id="evaluation-forged-0",
            challenge_index=0,
            challenge_digest=json_digest(case.challenge),
            status="observed",
            exit_status=0,
            observation={"status": "observed"},  # missing values_json/raised/etc.
            observation_bytes=32,
        )
        session.evaluate_challenge(CHECK_ID, case.context, forged)
        verdict = session.finalize()
    assert verdict.passed is False


def test_candidate_error_evidence_cannot_smuggle_an_observation():
    """The evidence contract itself refuses to let a failed run carry an
    observation, so a candidate that crashed cannot smuggle a forged,
    plausible-looking success payload through the evidence-level status.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged-2")
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})
        assert case is not None
        observation = _reference_observation(case.context["expected"])
        with pytest.raises(ValueError, match="failed challenge evidence may not contain an observation"):
            ChallengeEvidence(
                check_id=CHECK_ID,
                challenge_id="challenge-forged-1",
                evaluation_id="evaluation-forged-1",
                challenge_index=0,
                challenge_digest=json_digest(case.challenge),
                status="candidate_error",
                exit_status=1,
                observation=observation,
                observation_bytes=len(json.dumps(observation)),
                failure_source="candidate",
                failure_code="nonzero_exit",
                failure_message="candidate process exited nonzero",
            )


def test_observation_claiming_run_error_internally_is_rejected():
    """Evidence can be 'observed' at the framework level while the adapter's
    own JSON payload reports an internal `run_error` (the shape the adapter
    uses when the candidate's code raised inside the Evaluation). The Oracle
    must key off that embedded status, not just the envelope.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged-3")
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})
        assert case is not None
        observation = _reference_observation(case.context["expected"])
        observation["status"] = "run_error"
        observation["error_type"] = "AttributeError"
        observation["error_message"] = "'Expr' object has no attribute 'rolling_min'"
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-2",
            evaluation_id="evaluation-forged-2",
            challenge_index=0,
            challenge_digest=json_digest(case.challenge),
            status="observed",
            exit_status=0,
            observation=observation,
            observation_bytes=len(json.dumps(observation)),
        )
        session.evaluate_challenge(CHECK_ID, case.context, forged)
        verdict = session.finalize()
    assert verdict.passed is False


def test_forged_values_with_wrong_length_is_rejected():
    """A forged `values_json` with the right shape but the wrong length (a
    truncated or padded array) must not pass the Oracle's length check.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged-4")
        case = None
        while True:
            candidate = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})
            if candidate is None:
                break
            if candidate.context["expected"]["kind"] == "values":
                case = candidate
                break
        assert case is not None
        observation = _reference_observation(case.context["expected"])
        observation["values_json"] = json.dumps([1.0])
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-3",
            evaluation_id="evaluation-forged-3",
            challenge_index=0,
            challenge_digest=json_digest(case.challenge),
            status="observed",
            exit_status=0,
            observation=observation,
            observation_bytes=len(json.dumps(observation)),
        )
        session.evaluate_challenge(CHECK_ID, case.context, forged)
        verdict = session.finalize()
    assert verdict.passed is False
