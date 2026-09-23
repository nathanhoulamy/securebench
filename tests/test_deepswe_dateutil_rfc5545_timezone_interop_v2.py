"""Qualification for `deep-swe/dateutil-rfc5545-timezone-interop`.

Follows the pattern established by `test_deepswe_first_wave_replay_v2.py`
(real-capture Docker replay for Gates 1/2 and the generic file-drop mutant)
and `test_pilot_conversions_v2.py` (Oracle-level driving for the targeted,
distinct-axis mutants required by Gate 3, and for Gate 4's malformed-evidence
rejection). The Oracle-level driver below builds observations directly from
the same `expected` data the host Oracle's own case generator produces, so it
never needs the candidate's `dateutil` package -- it is not a reimplementation
of the feature, just a way to exercise the Oracle's own comparison logic
without paying for a Docker Evaluation per case.
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
NAME = "dateutil-rfc5545-timezone-interop"
CHECK_ID = "rrule_rfc5545_timezone_behavior"


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
    """Gate 1: the unmodified base commit must not pass."""
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

    The gold patch only touches one non-test file
    (`src/dateutil/rrule.py`), so this mutant is equivalent to shipping no
    implementation at all -- the same shape of near-miss the playbook asks
    for regardless of how many files a conversion's gold patch touches.
    """
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
# Oracle-level driving (no Docker): reference passes, targeted mutants fail,
# and forged/malformed evidence is rejected.


_EMPTY_OCC = {"iso": "", "has_tz": False, "utc_offset_minutes": 0, "tzname": ""}


def _fill_occ(occ: dict) -> dict:
    return {
        "iso": occ["iso"], "has_tz": occ["has_tz"],
        "utc_offset_minutes": occ["utc_offset_minutes"], "tzname": "",
    }


def _base_observation() -> dict:
    return {
        "status": "observed", "error_type": "", "error_message": "", "raised": False,
        "text_a": "", "text_b": "",
        "occurrences_a": [], "occurrences_b": [],
        "props": {
            "dtstart": dict(_EMPTY_OCC), "freq": -1, "interval": 0, "count_value": -1,
            "has_until": False, "until": dict(_EMPTY_OCC),
        },
        "counts": {"rrules": 0, "rdates": 0, "exrules": 0, "exdates": 0},
        "tuple_flags": {
            "rrules_is_tuple": True, "rdates_is_tuple": True,
            "exrules_is_tuple": True, "exdates_is_tuple": True,
        },
        "bool_a": False, "bool_b": False,
    }


def reference_observation(op: str, expected: dict) -> dict:
    """A correct-by-construction observation for one Oracle case.

    Built only from the `expected` data the Oracle's own case generator
    produced (visible in `case.context`), never from a reimplementation of
    dateutil -- this exists to exercise the Oracle's comparison logic
    directly, the same role `drive_cattrs`/`drive_fd`/`drive_updo` play for
    the other converted rows.
    """
    obs = _base_observation()
    if op in ("rdate_parse", "vcalendar_parse"):
        obs["occurrences_a"] = [_fill_occ(o) for o in expected["occurrences"]]
    elif op == "multiple_timezones_error":
        obs["raised"] = True
        obs["error_type"] = "ValueError"
        obs["error_message"] = "date property specifies multiple timezones"
    elif op == "ruleset_from_str":
        obs["bool_a"] = expected["is_ruleset"]
        obs["occurrences_a"] = [_fill_occ(o) for o in expected["occurrences"]]
    elif op == "rrule_str_roundtrip":
        text = "\n".join(expected["substrings"])
        obs["text_a"] = text
        occ = [_fill_occ(o) for o in expected["occurrences"]]
        obs["occurrences_a"] = occ
        obs["occurrences_b"] = occ
    elif op == "rrule_eq_hash":
        obs["bool_a"] = expected["eq"]
        obs["bool_b"] = expected["hash_equal"] if expected["check_hash"] else False
    elif op == "rrule_repr_reconstruct":
        obs["text_a"] = " ".join(expected["substrings"])
        obs["occurrences_a"] = []
        obs["occurrences_b"] = []
    elif op == "rrule_properties_ical":
        obs["props"] = {
            "dtstart": _fill_occ(expected["dtstart"]),
            "freq": expected["freq"], "interval": expected["interval"],
            "count_value": expected["count_value"], "has_until": expected["has_until"],
            "until": _fill_occ(expected["until"]) if expected["has_until"] else dict(_EMPTY_OCC),
        }
        obs["text_a"] = "\n".join(expected["ical_substrings"])
        obs["occurrences_b"] = [_fill_occ(o) for o in expected["occurrences"]]
    elif op == "ruleset_str_props":
        if "first_line_exact" in expected:
            text = expected["first_line_exact"]
            extra = expected["dtstart_count"] - text.count("DTSTART")
            if extra > 0:
                text += "\n" + "\n".join("DTSTART" for _ in range(extra))
        elif "order" in expected:
            lines = [prefix + "X" for prefix in expected["order"]]
            text = "\n".join(lines) + "\n" + "\n".join(expected.get("str_substrings", []))
        else:
            text = "\n".join(expected.get("str_substrings", []))
        obs["text_a"] = text
        obs["text_b"] = "\n".join(expected.get("repr_substrings", []))
        if "counts" in expected:
            obs["counts"] = expected["counts"]
        obs["bool_a"] = True
        if "occurrences" in expected:
            obs["occurrences_a"] = [_fill_occ(o) for o in expected["occurrences"]]
    elif op == "ruleset_equality":
        obs["bool_a"] = expected["eq"]
    elif op == "ruleset_copy":
        obs["bool_a"] = expected["is_new_object"]
        obs["bool_b"] = expected["eq_to_original"]
        occ = [_fill_occ(o) for o in expected["occurrences"]]
        obs["occurrences_a"] = occ
        obs["occurrences_b"] = occ
    elif op == "ruleset_combine":
        obs["counts"] = expected["counts"]
        obs["occurrences_a"] = [_fill_occ(o) for o in expected["occurrences"]]
    elif op == "ruleset_type_mismatch":
        obs["bool_a"] = expected["union_raises_type_error"]
        obs["bool_b"] = expected["subtract_raises_type_error"]
    elif op == "ruleset_to_ical":
        text = "\n".join(expected.get("substrings", []))
        if "vtimezone_count" in expected:
            text += "\n" + "\n".join("BEGIN:VTIMEZONE" for _ in range(expected["vtimezone_count"]))
        obs["text_a"] = text
        obs["occurrences_b"] = [_fill_occ(o) for o in expected["occurrences"]]
    else:
        raise AssertionError("unhandled op in test driver: " + op)
    return obs


def _evidence(task, challenge, context, observation, index) -> ChallengeEvidence:
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


def drive_dateutil(task, *, tweak=None):
    """Replay every Oracle case with a reference-correct observation.

    `tweak(index, op, observation)` mutates one case's observation in place
    to model a specific wrong candidate behaviour.
    """
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="dateutil-qualification")
        index = 0
        while (case := session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})) is not None:
            op = case.context["op"]
            expected = case.context["expected"]
            observation = reference_observation(op, expected)
            if tweak is not None:
                tweak(index, op, observation)
            session.evaluate_challenge(
                CHECK_ID, case.context, _evidence(task, case.challenge, case.context, observation, index),
            )
            index += 1
        return session.finalize()


def test_reference_observations_pass_every_oracle_case():
    verdict = drive_dateutil(deep_task(NAME))
    assert verdict.passed is True, verdict


# -- Gate 3: at least three targeted mutants, each a distinct semantic axis. --


def test_mutant_wrong_rdate_tzid_offset_fails():
    """Axis: RDATE/TZID resolution (testStrSetRDateWithTZID and friends).

    A candidate that silently drops the TZID on an RDATE (returns it naive
    instead of zone-aware) must be rejected.
    """

    def break_rdate_tzid(index, op, observation):
        if op == "rdate_parse" and observation["occurrences_a"]:
            observation["occurrences_a"][-1]["has_tz"] = False
            observation["occurrences_a"][-1]["utc_offset_minutes"] = 0

    verdict = drive_dateutil(deep_task(NAME), tweak=break_rdate_tzid)
    assert verdict.passed is False


def test_mutant_missing_until_z_suffix_fails():
    """Axis: rrule.__str__ UNTIL formatting (testToStrUntilUTC / testToStrUntilWithTZIDAwareDtstart).

    A candidate that emits UNTIL without the RFC 5545 'Z' suffix for a UTC
    instant must be rejected.
    """

    def drop_until_z(index, op, observation):
        if op == "rrule_str_roundtrip" and "UNTIL=" in observation["text_a"] and observation["text_a"].endswith("Z"):
            observation["text_a"] = observation["text_a"][:-1]

    verdict = drive_dateutil(deep_task(NAME), tweak=drop_until_z)
    assert verdict.passed is False


def test_mutant_eq_ignores_frequency_fails():
    """Axis: rrule.__eq__ (testRruleEqualityDiffFreq).

    A candidate whose `__eq__` only compares dtstart (ignoring freq) would
    wrongly report two rrules with different frequencies as equal.
    """

    def eq_ignores_freq(index, op, observation):
        if op == "rrule_eq_hash" and observation["bool_a"] is False:
            observation["bool_a"] = True

    verdict = drive_dateutil(deep_task(NAME), tweak=eq_ignores_freq)
    assert verdict.passed is False


def test_mutant_ruleset_subtract_does_not_exclude_fails():
    """Axis: rruleset.subtract (testRulesetSubtract).

    A candidate whose `subtract` is a no-op (returns a copy of `self`
    unmodified) must be rejected: the excluded occurrence would still be
    present.
    """

    def subtract_noop(index, op, observation):
        if op == "ruleset_combine" and observation["counts"].get("exdates") == 1:
            observation["counts"]["exdates"] = 0
            observation["occurrences_a"].insert(0, {
                "iso": "1997-09-09T09:00:00", "has_tz": False,
                "utc_offset_minutes": 0, "tzname": "",
            })

    verdict = drive_dateutil(deep_task(NAME), tweak=subtract_noop)
    assert verdict.passed is False


def test_mutant_repr_not_reconstructable_fails():
    """Axis: rrule.__repr__ reconstructability (testRruleReprReconstructable).

    A candidate whose reconstructed-from-repr occurrences diverge from the
    original rrule's occurrences must be rejected.
    """

    def break_reconstruction(index, op, observation):
        if op == "rrule_repr_reconstruct" and "rrule(" in observation["text_a"]:
            observation["occurrences_a"] = [{
                "iso": "1997-09-02T09:00:00", "has_tz": False,
                "utc_offset_minutes": 0, "tzname": "",
            }]
            observation["occurrences_b"] = []

    verdict = drive_dateutil(deep_task(NAME), tweak=break_reconstruction)
    assert verdict.passed is False


# -- Gate 4: forged / malformed evidence is rejected by the Oracle. --


def test_forged_status_observed_with_missing_fields_is_rejected():
    """A malformed observation (missing every required field) must not pass."""
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="dateutil-forged")
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
            observation={"status": "observed"},  # missing every op-specific field
            observation_bytes=32,
        )
        session.evaluate_challenge(CHECK_ID, case.context, forged)
        verdict = session.finalize()
    assert verdict.passed is False


def test_candidate_error_evidence_cannot_smuggle_an_observation():
    """The evidence contract itself refuses to let a failed run carry an
    observation, so a candidate that crashed cannot smuggle a forged,
    plausible-looking success payload through the evidence-level status.
    This is a stronger property than the Oracle rejecting it after the
    fact: the malformed evidence cannot even be constructed.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="dateutil-forged-2")
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})
        assert case is not None
        observation = reference_observation(case.context["op"], case.context["expected"])
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
    own JSON payload reports an internal ``run_error`` (the shape the
    adapter uses when the candidate's code raised inside the Evaluation).
    The Oracle must key off that embedded status, not just the envelope.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="dateutil-forged-3")
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})
        assert case is not None
        observation = reference_observation(case.context["op"], case.context["expected"])
        observation["status"] = "run_error"
        observation["error_type"] = "AttributeError"
        observation["error_message"] = "module 'dateutil.rrule' has no attribute 'rruleset'"
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
