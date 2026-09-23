"""Qualification for `deep-swe/returns-validated-error-accumulation`.

Follows the pattern established by `test_deepswe_narwhals_rolling_window_suite_v2.py`
(real-capture Docker replay for Gates 1 and 2, and the generic file-drop
mutant) and `test_pilot_conversions_v2.py` (Oracle-level driving for Gate 4's
malformed-evidence rejection). Gate 3's three targeted mutants are real code
edits applied on top of the upstream gold solution (`returns/validated.py`)
and replayed through the real capture -> Evaluation -> Oracle path in Docker
(`verify_patch(..., reference=True, mutate=<hand edit>)`); each was first
confirmed, outside Docker (running the adapter's own `_observe` directly
inside a container of the pinned image against the mutated `/app` tree), to
flip exactly the case(s) on its intended semantic axis and no others
(playbook defect #8) -- see the dossier's "Implemented v2 conversion" section
for that verification log.
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
NAME = "returns-validated-error-accumulation"
CHECK_ID = "validated_behavior"


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

    `returns.validated` does not exist at the base commit, so every case's
    `import returns.validated` (or `returns.converters.result_to_validated`,
    `returns.methods.cond`'s `ValidatedLikeN` branch, etc.) raises
    `ModuleNotFoundError`/`AttributeError` inside the adapter, which reports
    `run_error` for every one of the 57 cases.
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


def _mutate_invalid_apply_short_circuits(workspace: Path) -> None:
    """Axis: `apply` error accumulation (test_apply_invalid_invalid_accumulates,
    test_apply_accumulates_*, Fold.collect via apply, combine/combine_n,
    cond accumulation -- everything that depends on `Invalid.apply`
    concatenating both sides' errors instead of short-circuiting like
    `Result.apply` does).

    `Invalid.apply` drops the `isinstance(container, Invalid)` accumulation
    branch entirely and always returns `self` -- exactly the "copied
    `Result`'s apply" near-miss the instruction explicitly warns is wrong.
    Confirmed (outside Docker, direct adapter run against this exact edit)
    to flip 13 of the 57 cases -- every one that depends on the
    both-Invalid accumulation branch (apply binary/chain, combine,
    combine_n, `accumulated_to_result`, `decorator_accumulate`, pointfree
    apply, `Fold.collect`/`loop`, cond accumulate) -- and no others.
    """
    target = workspace / "returns" / "validated.py"
    _replace_once(
        target,
        "        def apply(self, container):\n"
        "            \"\"\"Accumulates errors when both sides are ``Invalid``.\"\"\"\n"
        "            if isinstance(container, Invalid):\n"
        "                return Invalid((*self._inner_value, *container._inner_value))\n"
        "            return self\n",
        "        def apply(self, container):\n"
        "            \"\"\"Accumulates errors when both sides are ``Invalid``.\"\"\"\n"
        "            return self  # BUG: drops error accumulation, short-circuits like Result\n",
    )


def _mutate_swap_forgets_tuple_wrap(workspace: Path) -> None:
    """Axis: `swap` on `Valid` (test_swap_valid / test_swap_repr / the
    instruction's explicit "Valid(x) into Invalid((x,))" requirement).

    `Valid.swap` stops wrapping the value in a 1-tuple before constructing
    `Invalid`, so `Valid(42).swap()` becomes `Invalid(42)` instead of
    `Invalid((42,))` -- a plausible off-by-one a candidate could ship (the
    error channel type is `tuple[..., ...]`, but the raw value is passed
    through). Confirmed (outside Docker) to flip exactly the `swap_valid`
    case, crashing when the adapter iterates the non-tuple `.failure()`.
    """
    target = workspace / "returns" / "validated.py"
    _replace_once(
        target,
        "    def swap(self):\n"
        "        \"\"\"Valid swaps to :class:`Invalid` with value wrapped in tuple.\"\"\"\n"
        "        return Invalid((self._inner_value,))\n",
        "    def swap(self):\n"
        "        \"\"\"Valid swaps to :class:`Invalid` with value wrapped in tuple.\"\"\"\n"
        "        return Invalid(self._inner_value)  # BUG: forgets the 1-tuple wrap\n",
    )


def _mutate_alt_applies_to_first_element_only(workspace: Path) -> None:
    """Axis: `alt` element-wise mapping over the error tuple
    (test_alt_invalid_multiple / test_bimap_invalid_multi / the
    instruction's explicit "apply the provided function to each individual
    error element" requirement).

    `Invalid.alt` repeats the transform of the *first* error element instead
    of mapping each element independently -- correct only when there is
    exactly one error, silently wrong for two or more. Confirmed (outside
    Docker) to flip exactly the two-or-more-error `alt`/`bimap` cases
    (`alt_invalid_multi`, `bimap_invalid_multi`) and no others.
    """
    target = workspace / "returns" / "validated.py"
    _replace_once(
        target,
        "        def alt(self, function):\n"
        "            \"\"\"Applies function to each individual error in the tuple.\"\"\"\n"
        "            return Invalid(tuple(function(err) for err in self._inner_value))\n",
        "        def alt(self, function):\n"
        "            \"\"\"Applies function to each individual error in the tuple.\"\"\"\n"
        "            return Invalid(tuple(function(self._inner_value[0]) for _ in self._inner_value))  # BUG\n",
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_invalid_apply_short_circuits,
        _mutate_swap_forgets_tuple_wrap,
        _mutate_alt_applies_to_first_element_only,
    ],
    ids=["apply-short-circuits", "swap-forgets-tuple", "alt-first-element-only"],
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
    `case.context`), never from running `returns` -- this exists to
    exercise the Oracle's comparison logic directly for the
    malformed-evidence gate.
    """
    if expected.get("raised"):
        result_kind, result_value = "none", None
    else:
        result_kind = expected.get("result_kind", "none")
        result_value = expected.get("result_value")
    extra = expected.get("extra", {})
    if expected.get("extra_compare") == "laws":
        extra = {
            "laws_checked": len(expected["required_laws"]),
            "laws_names": list(expected["required_laws"]),
            "laws_failed": [],
            "all_passed": True,
        }
    return {
        "status": "observed",
        "result_kind": result_kind,
        "result_value_json": json.dumps(result_value, sort_keys=True, separators=(",", ":")),
        "extra_json": json.dumps(extra, sort_keys=True, separators=(",", ":")),
        "raised": expected.get("raised", False),
        "raised_error_type": expected.get("raised_error_type", ""),
        "raised_message": "reference" if expected.get("raised") else "",
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
        while (case := session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 65536})) is not None:
            observation = _reference_observation(case.context["expected"])
            session.evaluate_challenge(
                CHECK_ID, case.context, _evidence(case.challenge, observation, index),
            )
            index += 1
        verdict = session.finalize()
    assert verdict.passed is True, verdict
    assert index >= 50


def test_forged_status_observed_with_missing_fields_is_rejected():
    """A malformed observation (missing every op-specific field) must not pass."""
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged")
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 65536})
        assert case is not None
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-0",
            evaluation_id="evaluation-forged-0",
            challenge_index=0,
            challenge_digest=json_digest(case.challenge),
            status="observed",
            exit_status=0,
            observation={"status": "observed"},  # missing result_kind/result_value_json/extra_json/etc.
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
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 65536})
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
    uses when the candidate's code raised inside the Evaluation, e.g. the
    base commit's missing `returns.validated` module). The Oracle must key
    off that embedded status, not just the envelope.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged-3")
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 65536})
        assert case is not None
        observation = _reference_observation(case.context["expected"])
        observation["status"] = "run_error"
        observation["error_type"] = "ModuleNotFoundError"
        observation["error_message"] = "No module named 'returns.validated'"
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


def test_forged_result_value_with_wrong_length_is_rejected():
    """A forged `result_value_json` with the right shape but the wrong
    length (a truncated error tuple, e.g. dropping accumulated errors) must
    not pass the Oracle's comparison for an exact-compare case.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged-4")
        case = None
        while True:
            candidate = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 65536})
            if candidate is None:
                break
            expected = candidate.context["expected"]
            if expected.get("compare") == "exact" and expected.get("result_kind") == "invalid" and len(expected.get("result_value") or []) > 1:
                case = candidate
                break
        assert case is not None
        observation = _reference_observation(case.context["expected"])
        observation["result_value_json"] = json.dumps([case.context["expected"]["result_value"][0]])
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


def test_forged_laws_checked_below_threshold_is_rejected():
    """A forged `laws_check` observation reporting `all_passed: True` but a
    suspiciously low `laws_checked` count (as a stubbed-out `laws()` classmethod
    that registers no laws would produce) must not pass.
    """
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged-5")
        case = None
        while True:
            candidate = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 65536})
            if candidate is None:
                break
            if candidate.context["expected"].get("extra_compare") == "laws":
                case = candidate
                break
        assert case is not None
        observation = _reference_observation(case.context["expected"])
        observation["extra_json"] = json.dumps({"laws_checked": 0, "laws_names": [], "laws_failed": [], "all_passed": True})
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-4",
            evaluation_id="evaluation-forged-4",
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


def test_forged_laws_missing_one_upstream_law_is_rejected():
    """Every one of upstream's 16 F2P law tests must be generated; passing a
    smaller set (for example a hierarchy missing one interface) is rejected."""
    task = deep_task(NAME)
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed=f"{NAME}-forged-6")
        case = None
        while True:
            candidate = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 65536})
            if candidate is None:
                break
            if candidate.context["expected"].get("extra_compare") == "laws":
                case = candidate
                break
        assert case is not None
        names = list(case.context["expected"]["required_laws"])[1:]
        observation = _reference_observation(case.context["expected"])
        observation["extra_json"] = json.dumps(
            {"laws_checked": len(names), "laws_names": names, "laws_failed": [], "all_passed": True}
        )
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-6",
            evaluation_id="evaluation-forged-6",
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
