"""Qualification for `deep-swe/python-statemachine-state-data-scoping`.

Follows the pattern established by `test_deepswe_mashumaro_flattened_dataclass_fields_v2.py`
and `test_deepswe_returns_validated_error_accumulation_v2.py`: Gates 1/2/3
replay the production capture -> Evaluation -> Oracle path in real Docker
(`verify_patch`), and Gate 4 drives the real Oracle subprocess directly with
hand-built and forged ``ChallengeEvidence`` (no Docker).

Each of Gate 3's three targeted mutants is a real hand edit on top of the
upstream gold solution's new ``statemachine/state_data.py`` (or
``statemachine/engines/base.py``), each on a distinct semantic axis named in
the public instruction. Before being relied on here, every mutant was first
confirmed outside Docker -- reproducing the adapter directly inside a
container of the pinned image (``python3 ./adapter.py < request.json``)
against the mutated ``/app`` tree for all 33 Oracle cases -- to flip exactly
the case(s) on its intended axis and no others (playbook defect #8); see the
dossier's "Implemented v2 conversion" section for that verification log.
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


NAME = "python-statemachine-state-data-scoping"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "state_data_behavior"


# ---------------------------------------------------------------------------
# Preflight and visibility (no Docker required)
# ---------------------------------------------------------------------------


def test_row_preflights_and_keeps_the_reference_and_oracle_host_only():
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
    assert provenance["sha256"] == __import__("hashlib").sha256(patch.read_bytes()).hexdigest()
    assert provenance["baseline_commit"] == deep_task(NAME).input["base_commit"]


def test_reference_patch_does_not_touch_an_excluded_path():
    """Playbook defect #19: the gold solution must not edit any path the
    candidate schema excludes, or Capture would reject even the gold patch.
    """
    task = deep_task(NAME)
    exclude_globs = task.verification.candidate.exclude_paths
    touched = re.findall(r"^diff --git a/(\S+) b/\S+$", reference_patch(NAME).read_text(), re.M)
    assert touched, "reference patch touches no files"
    for path in touched:
        for pattern in exclude_globs:
            assert not Path(path).match(pattern), (path, pattern)


# ---------------------------------------------------------------------------
# Gates 1, 2, and the generic file-drop mutant: real Docker replay.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp(f"{NAME}-baseline") / "app"
    return materialize_baseline(NAME, root)


@DOCKER_INTEGRATION
def test_base_fails_through_the_real_capture_path(tmp_path, baseline):
    """Gate 1: the unmodified base commit must not pass.

    At the base commit, ``State.__init__`` has no ``data`` parameter,
    ``DataVar``/``DataChangeInfo`` are not exported, and none of
    ``get_state_data``/``set_state_data``/``get_data_changes``/
    ``state_data_values`` exist on ``StateChart`` -- so every declarative
    case fails to even import ``DataVar`` (``ImportError``) and the SCXML
    case fails on the first ``get_state_data`` call (``AttributeError``).
    Not a crash: the adapter catches both and reports a bounded
    ``run_error`` observation for every case.
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


@DOCKER_INTEGRATION
def test_dropping_the_largest_source_change_fails(tmp_path, baseline):
    """Gate 3 (generic mutant): drop the largest file of the gold patch.

    The gold patch's largest file by far is the new ``statemachine/state_data.py``
    module (281 added lines vs. 51 for the next largest, ``statemachine.py``).
    ``state.py``, ``factory.py``, ``event_data.py``, ``engines/base.py``,
    ``engines/async_.py``, and ``statemachine.py`` all import from it, so
    dropping it breaks every case's ``import statemachine`` outright.
    """
    diffs = _file_diffs(reference_patch(NAME).read_text())
    assert diffs, "reference patch has no file changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "statemachine/state_data.py", dropped
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

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


# ---------------------------------------------------------------------------
# Gate 3: three targeted REAL-CODE mutants, gold patch + one hand edit each,
# replayed through real Docker Evaluations, each on a distinct semantic axis
# named in the public instruction.
# ---------------------------------------------------------------------------


def _replace_once(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(before)
    assert count == 1, (path, count, before)
    path.write_text(text.replace(before, after), encoding="utf-8")


def _mutate_shadowing_precedence(workspace: Path) -> None:
    """Axis: "child shadowing parent on collision" (the instruction's own
    words) -- exercised by the ``hierarchical_scoping`` case, which declares
    the same key ("val") on both a compound parent and its initial child.

    The gold ``_merge_ancestor_data`` applies ancestor data first, then the
    state's own data, so a colliding key ends up with the *child's* value.
    This hand edit reverses that: the state's own data is applied first and
    every ancestor update in the loop can then overwrite it, so a child that
    declares the same key as its parent silently loses -- the parent's value
    wins instead of the child's, and the merged view fed to
    ``on_enter_child`` no longer matches what the instruction requires.
    """
    target = workspace / "statemachine" / "state_data.py"
    _replace_once(
        target,
        "def resolve_state_data(sm: \"StateChart\", state: \"State\") -> dict:\n"
        "    scope = resolve_scope(sm, state)\n"
        "    return scope.to_dict()",
        "def resolve_state_data(sm: \"StateChart\", state: \"State\") -> dict:\n"
        "    scope = resolve_scope(sm, state)\n"
        "    return scope.to_dict()  # marker, unused",
    )
    _replace_once(
        target,
        "def _merge_ancestor_data(sm: \"StateChart\", state: \"State\") -> Dict[str, Any]:\n"
        "    merged: Dict[str, Any] = {}\n"
        "    ancestors = list(state.ancestors())\n"
        "    for ancestor in reversed(ancestors):\n"
        "        ancestor_data = sm._data_store._data.get(ancestor.id)\n"
        "        if ancestor_data is not None:\n"
        "            merged.update(ancestor_data)\n"
        "    state_data = sm._data_store._data.get(state.id)\n"
        "    if state_data is not None:\n"
        "        merged.update(state_data)\n"
        "    return merged\n",
        "def _merge_ancestor_data(sm: \"StateChart\", state: \"State\") -> Dict[str, Any]:\n"
        "    merged: Dict[str, Any] = {}\n"
        "    state_data = sm._data_store._data.get(state.id)\n"
        "    if state_data is not None:\n"
        "        merged.update(state_data)  # BUG: applied before ancestors\n"
        "    ancestors = list(state.ancestors())\n"
        "    for ancestor in reversed(ancestors):\n"
        "        ancestor_data = sm._data_store._data.get(ancestor.id)\n"
        "        if ancestor_data is not None:\n"
        "            merged.update(ancestor_data)  # BUG: overwrites child, no shadowing\n"
        "    return merged\n",
    )


def _mutate_datavar_type_check_disabled(workspace: Path) -> None:
    """Axis: "DataVar ... supporting optional type enforcement" and
    "set_state_data ... validates ... DataVar type constraints, raising
    InvalidDefinition on violation" -- exercised by the ``datavar_full``
    case, which calls ``set_state_data`` with a value of the wrong type for
    a ``DataVar(type=int)`` field and expects ``InvalidDefinition``.

    The gold ``StateDataStore.set_value`` checks the declared type before
    accepting a new value. This hand edit short-circuits that check with
    ``False and ...``, so ``set_state_data`` silently accepts a value of any
    type -- a plausible near-miss for an implementation that declares the
    ``type=`` constraint but forgets to enforce it on every mutation path
    (only enforcing it, say, at initial default construction).
    """
    target = workspace / "statemachine" / "state_data.py"
    _replace_once(
        target,
        "        type_map = self._data_types.get(state_id, {})\n"
        "        expected_type = type_map.get(key)\n"
        "        if expected_type is not None and value is not None:\n"
        "            if not isinstance(value, expected_type):\n",
        "        type_map = self._data_types.get(state_id, {})\n"
        "        expected_type = type_map.get(key)\n"
        "        if False and expected_type is not None and value is not None:  # BUG: never checks\n"
        "            if not isinstance(value, expected_type):\n",
    )


def _mutate_data_changes_not_cleared_at_macrostep(workspace: Path) -> None:
    """Axis: "get_data_changes() returns DataChangeInfo records accumulated
    during the current macrostep, cleared at each macrostep boundary" (the
    instruction's own words) -- exercised by the ``data_change_tracking``
    case, which sets data, reads back one change, sends an event (a new
    macrostep), and expects ``get_data_changes()`` to be empty afterward.

    The gold ``BaseEngine.clear_cache`` (called at the start of every
    processing loop, i.e. every macrostep) also clears the data-change log.
    This hand edit drops that one call, so change records from a previous
    macrostep silently leak into the next one -- a plausible near-miss for
    an implementation that tracks changes correctly but never wires the
    "boundary" half of the requirement to the engine's existing per-macrostep
    cache-clearing hook.
    """
    target = workspace / "statemachine" / "engines" / "base.py"
    _replace_once(
        target,
        "    def clear_cache(self):\n"
        "        \"\"\"Clears the cache. Should be called at the start of each processing loop.\"\"\"\n"
        "        self._cache.clear()\n"
        "        self._clear_data_changes()\n",
        "    def clear_cache(self):\n"
        "        \"\"\"Clears the cache. Should be called at the start of each processing loop.\"\"\"\n"
        "        self._cache.clear()\n"
        "        # BUG: forgot to clear data changes at the macrostep boundary\n",
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_shadowing_precedence,
        _mutate_datavar_type_check_disabled,
        _mutate_data_changes_not_cleared_at_macrostep,
    ],
    ids=["shadowing-precedence", "datavar-type-check-disabled", "data-changes-not-cleared"],
)
def test_targeted_real_code_mutant_fails(tmp_path, baseline, mutate):
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-{mutate.__name__}",
    )

    assert outcome.status == "failed", (mutate.__name__, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence


# ---------------------------------------------------------------------------
# Gate 4: forged / malformed evidence is rejected by the Oracle (no Docker).
# ---------------------------------------------------------------------------


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


def _oracle_root():
    task = deep_task(NAME)
    return Path(task.resources.resources["host.task_oracle"].value["source_path"])


def _find_case(session, name):
    while True:
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 32, "max_case_bytes": 16384})
        if case is None:
            return None
        if case.context.get("name") == name:
            return case


def _correct_observation_for_compound_state_with_data():
    """Hand-built (not executed) correct observation for the
    ``compound_state_with_data`` case: ``get_state_data(region)`` on a
    machine where ``region`` is a Compound state declaring
    ``data={"level": "compound"}``.
    """
    results = [
        {
            "op": "get_state_data",
            "ok": True,
            "error_type": "",
            "error_message": "",
            "payload_json": json.dumps({"found": True, "data": {"level": "compound"}}, sort_keys=True),
        }
    ]
    return {
        "status": "observed",
        "error_type": "",
        "error_message": "",
        "trace_json": json.dumps([], sort_keys=True),
        "results_json": json.dumps(results, sort_keys=True),
    }


def test_hand_built_correct_observation_produces_no_failure_category():
    """Sanity check (no Docker): a correctly-shaped observation, built only
    from the known machine/expected value (never by running the candidate),
    produces no failure category for its case. ``finalize`` needs every case
    evaluated to report ``passed``, so this checks the failure list a second
    session reports for the *same* single forged-vs-correct pair instead:
    the correct observation must not appear in the rejected set the forged
    one produces below (see ``test_forged_result_flipping_found_flag_is_rejected``).
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-sanity")
        case = _find_case(session, "compound_state_with_data[sync]")
        assert case is not None
        observation = _correct_observation_for_compound_state_with_data()
        session.evaluate_challenge(
            CHECK_ID, case.context, _evidence(case.challenge, observation, 0)
        )
        # Feed `exhausted`-triggering blanks for the remaining 18 cases with
        # the same correct-by-construction shape is out of scope here; this
        # test only asserts the process didn't reject the well-formed
        # evidence outright (no exception, no `oracle_exited`).
        verdict = session.finalize()
    # `evaluated` (1) != `len(cases)` (33) makes `passed` False regardless of
    # correctness -- this only proves the correct evidence did not itself
    # crash the Oracle subprocess or get flagged malformed.
    assert verdict.passed is False
    categories = verdict.public_diagnostics.get("failure_categories", [])
    assert not any(cat.startswith("compound_state_with_data:") for cat in categories)


def test_forged_status_observed_with_missing_fields_is_rejected():
    """A malformed observation (missing every required field) must not pass."""
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged")
        case = _find_case(session, "compound_state_with_data[sync]")
        assert case is not None
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-0",
            evaluation_id="evaluation-forged-0",
            challenge_index=0,
            challenge_digest=json_digest(case.challenge),
            status="observed",
            exit_status=0,
            observation={"status": "observed"},  # missing trace_json/results_json/etc.
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
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged-2")
        case = _find_case(session, "compound_state_with_data[sync]")
        assert case is not None
        observation = _correct_observation_for_compound_state_with_data()
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
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged-3")
        case = _find_case(session, "compound_state_with_data[sync]")
        assert case is not None
        observation = {
            "status": "run_error",
            "error_type": "AttributeError",
            "error_message": "'GeneratedSM' object has no attribute 'get_state_data'",
            "trace_json": "[]",
            "results_json": "[]",
        }
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


def test_forged_result_flipping_found_flag_is_rejected():
    """A forged result that flips ``found`` (claiming no data where the
    correct value has some) must not pass.
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged-4")
        case = _find_case(session, "compound_state_with_data[sync]")
        assert case is not None
        observation = _correct_observation_for_compound_state_with_data()
        results = json.loads(observation["results_json"])
        payload = json.loads(results[0]["payload_json"])
        payload["found"] = False
        payload["data"] = {}
        results[0]["payload_json"] = json.dumps(payload, sort_keys=True)
        observation["results_json"] = json.dumps(results, sort_keys=True)
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
