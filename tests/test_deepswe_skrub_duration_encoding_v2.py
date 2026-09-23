"""Qualification for `deep-swe/skrub-duration-encoding`.

Follows the pattern established by `test_deepswe_narwhals_rolling_window_suite_v2.py`
(real-capture Docker replay for Gates 1 and 2, the generic file-drop mutant, and
Oracle-level driving for Gate 4's malformed-evidence rejection). This row's Gate
3 mutants are *real code* edits applied on top of the upstream gold solution's
new `skrub/_duration_encoder.py` module and replayed through the real capture ->
Evaluation -> Oracle path in Docker (`verify_patch(..., reference=True,
mutate=<hand edit>)`), each hitting a distinct semantic axis. Every mutant, and
the gold solution itself, was first replayed manually inside the pinned image
against the real adapter/Oracle pair (outside the harness) to confirm the
Oracle's independent reference implementation of `DurationEncoder`'s
component-extraction, resolution-detection, negative-handling, and scaling
semantics (`oracle.py`) discriminates each bug precisely; see the row's
dossier for the worked cross-checks.
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
NAME = "skrub-duration-encoding"
CHECK_ID = "duration_encoder_behavior"


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

    `DurationEncoder` does not exist in `skrub` at the base commit, so every
    `encode`/`reject_column`/`not_fitted_get_feature_names`/`to_float_rejects`/
    `to_str_rejects` case fails to import it (or, for `selector_duration`,
    `TableVectorizer` doesn't yet route duration columns), and the Oracle
    rejects every one.
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
    """Gate 3 (generic mutant): drop the largest non-test file of the gold patch.

    The largest hunk is the new `skrub/_duration_encoder.py` module itself.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "skrub/_duration_encoder.py"
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
# Each was confirmed by hand (outside the harness, directly against the
# pinned image's adapter + Oracle) to discriminate only the cases on its own
# axis before being wired in here; see the dossier.


def _replace_once(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(before)
    assert count == 1, (path, count, before)
    path.write_text(text.replace(before, after), encoding="utf-8")


def _mutate_resolution_detection_always_coarsest(workspace: Path) -> None:
    """Axis: auto resolution detection (test_resolution_auto_hour_level /
    test_resolution_auto_minute_level / test_auto_components).

    The gold `_has_nonzero` helper reports whether any non-null value in a
    remainder column (hours/minutes/seconds/microseconds) is at least one --
    the signal `_detect_resolution`'s cascade uses to pick the finest
    meaningful granularity. This hand edit makes it always report "nothing is
    nonzero", so every duration column auto-detects to the coarsest
    resolution ("day") regardless of its actual precision -- a plausible bug
    from an inverted or short-circuited threshold check.
    """
    target = workspace / "skrub" / "_duration_encoder.py"
    _replace_once(
        target,
        "    if len(valid) == 0:\n"
        "        return False\n"
        "    return bool(np.any(np.abs(valid) >= 1.0))\n",
        "    if len(valid) == 0:\n"
        "        return False\n"
        "    return False  # BUG: never reports finer-grained information\n",
    )


def _mutate_handle_negative_clip_abs_swapped(workspace: Path) -> None:
    """Axis: `handle_negative` clip/abs treatment (test_handle_negative_clip /
    test_handle_negative_abs).

    The gold `_handle_negative_duration` dispatches `"clip"` to
    `clip_duration` (zero out negatives) and `"abs"` to `abs_duration`
    (flip sign). This hand edit swaps the two dispatch targets -- a
    plausible copy-paste mistake -- so `handle_negative="clip"` takes the
    absolute value instead of zeroing, and `handle_negative="abs"` zeros
    instead of flipping sign.
    """
    target = workspace / "skrub" / "_duration_encoder.py"
    _replace_once(
        target,
        '    if mode == "clip":\n'
        "        return sbd.clip_duration(column, datetime.timedelta(0))\n"
        '    if mode == "abs":\n'
        "        return sbd.abs_duration(column)\n",
        '    if mode == "clip":\n'
        "        return sbd.abs_duration(column)  # BUG: swapped with abs\n"
        '    if mode == "abs":\n'
        "        return sbd.clip_duration(column, datetime.timedelta(0))  # BUG: swapped with clip\n",
    )


def _mutate_minmax_scaling_drops_clip(workspace: Path) -> None:
    """Axis: minmax scaling clips unseen values (test_normalize_clips_unseen).

    The gold `_apply_scaling` minmax branch clips the scaled result to
    `[0, 1]` so values outside the training range (seen only at transform
    time) are clamped instead of extrapolated. This hand edit removes the
    `np.clip` call, so a transform value below the training minimum or
    above the training maximum produces a scaled value outside `[0, 1]`
    instead of being clamped to the boundary.
    """
    target = workspace / "skrub" / "_duration_encoder.py"
    _replace_once(
        target,
        '                    scaled = np.clip((vals - p["min"]) / span, 0.0, 1.0)\n',
        '                    scaled = (vals - p["min"]) / span  # BUG: unseen values not clipped\n',
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_resolution_detection_always_coarsest,
        _mutate_handle_negative_clip_abs_swapped,
        _mutate_minmax_scaling_drops_clip,
    ],
    ids=["resolution-detection", "handle-negative-swapped", "minmax-clip-dropped"],
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


def _load_oracle_module(oracle_root: Path):
    """Import `oracle.py` by path so this test can reuse its `compute_expected`
    reference implementation directly, the same way `_build_cases()` does, to
    build a correct-by-construction observation for any `encode` challenge.
    This does not re-derive the math independently again (that was already
    validated by hand and by real Docker replay against the gold solution;
    see the dossier) -- it exists only to exercise the Oracle's protocol and
    comparison plumbing (Gate 4) against known-correct data.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("skrub_duration_oracle_ref", oracle_root / "oracle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reference_observation(oracle_mod, challenge: dict, expected: dict) -> dict:
    """A correct-by-construction observation for one Challenge -- never from
    running skrub -- this exists to exercise the Oracle's comparison logic
    directly for the malformed-evidence gate.
    """
    kind = expected["kind"]
    empty = {
        "columns_json": "[]", "values_json": "[]", "resolution_out": "",
        "components_out_json": "[]", "scaling_params_json": "{}",
    }
    if kind == "raises":
        return {
            "status": "observed", "raised": True,
            "raised_error_type": expected["error_type"], "raised_message": "(reference)",
            **empty,
        }
    if kind == "columns_exact":
        return {
            "status": "observed", "raised": False, "raised_error_type": "", "raised_message": "",
            **{**empty, "columns_json": json.dumps(expected["columns"])},
        }
    if kind == "columns_contain":
        cols = [expected["prefix_any"] + "x"] + list(expected["must_contain"])
        return {
            "status": "observed", "raised": False, "raised_error_type": "", "raised_message": "",
            **{**empty, "columns_json": json.dumps(cols)},
        }
    # kind == "encode": recompute the full reference (columns/values/
    # resolution/components/scaling params) from the challenge itself, since
    # `expected["checks"]` only carries the specific assertions this case's
    # upstream test(s) make, not the whole picture.
    fit_us = json.loads(challenge["values_json"])
    transform_json = challenge.get("transform_values_json", "")
    out_us = json.loads(transform_json) if transform_json else fit_us
    components_spec = json.loads(challenge["components_json"])
    full = oracle_mod.compute_expected(
        fit_us, out_us, components_spec,
        challenge["resolution"], challenge["handle_negative"], challenge["scaling"] or None,
    )
    name = challenge["column_name"]
    names = [f"{name}_{c}" for c in full["components_out"]]
    values = [full["columns_values"][c] for c in full["components_out"]]
    scaling_params_json = "{}"
    if full["scaling_params"] is not None:
        scaling_params_json = json.dumps({
            f"{name}_{comp}": stats for comp, stats in full["scaling_params"].items()
        })
    return {
        "status": "observed", "raised": False, "raised_error_type": "", "raised_message": "",
        "columns_json": json.dumps(names), "values_json": json.dumps(values),
        "resolution_out": full["resolution_out"],
        "components_out_json": json.dumps(full["components_out"]),
        "scaling_params_json": scaling_params_json,
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
    oracle_mod = _load_oracle_module(oracle_root)
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-oracle-sanity")
        index = 0
        while (case := session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})) is not None:
            observation = _reference_observation(oracle_mod, case.challenge, case.context["expected"])
            session.evaluate_challenge(
                CHECK_ID, case.context, _evidence(case.challenge, observation, index),
            )
            index += 1
        verdict = session.finalize()
    assert verdict.passed is True, verdict
    assert index >= 40


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
            observation={"status": "observed"},  # missing raised/columns_json/etc.
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
        oracle_mod = _load_oracle_module(oracle_root)
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})
        assert case is not None
        observation = _reference_observation(oracle_mod, case.challenge, case.context["expected"])
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
    uses when the candidate's code raised inside the Evaluation, e.g.
    `DurationEncoder` not existing at the base commit). The Oracle must key
    off that embedded status, not just the envelope.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged-3")
        oracle_mod = _load_oracle_module(oracle_root)
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})
        assert case is not None
        observation = _reference_observation(oracle_mod, case.challenge, case.context["expected"])
        observation["status"] = "run_error"
        observation["raised_error_type"] = "ImportError"
        observation["raised_message"] = "cannot import name 'DurationEncoder' from 'skrub'"
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


_VALUE_CHECK_TYPES = {
    "value_eq", "value_lt_abs", "value_null", "value_sign",
    "aggregate_mean_lt_abs", "single_index_lt_abs",
}


def test_forged_values_with_wrong_length_is_rejected():
    """A forged `values_json` with the right shape but the wrong length (a
    truncated or padded array) must not pass the Oracle's length check.

    Picks a case whose checks actually inspect a numeric value (not every
    `encode` case does -- several only check `resolution_`/column names/
    membership, matching their upstream test, and wouldn't even decode
    `values_json`), so the forgery is guaranteed to be caught.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    oracle_mod = _load_oracle_module(oracle_root)
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged-4")
        case = None
        while True:
            candidate = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})
            if candidate is None:
                break
            expected = candidate.context["expected"]
            if expected["kind"] == "encode" and any(
                c["type"] in _VALUE_CHECK_TYPES for c in expected["checks"]
            ):
                case = candidate
                break
        assert case is not None
        observation = _reference_observation(oracle_mod, case.challenge, case.context["expected"])
        observation["values_json"] = json.dumps([[1.0]])
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
