"""Real-capture Docker qualification for
``mashumaro-flattened-dataclass-fields``.

Gates 1/2/3 replay the production path (see ``tests/deepswe_qualification.py``):
a workspace is cloned from the materialised pinned baseline, the upstream gold
solution (``qualification/reference.patch``) is optionally applied, targeted
source-level mutants are optionally layered on top, and the result is
captured as a real ``git_patch`` candidate and verified through fresh
Evaluation containers using the real Oracle process (``oracle.py``, whose
pack/unpack reference implementation was cross-checked by hand against the
pinned image's gold solution for every case family before being trusted --
see the dossier).

Gate 4 drives the Oracle directly with synthetic ``ChallengeEvidence`` (no
Docker involved) to prove it rejects forged and malformed candidate
observations, the same pattern used elsewhere in this benchmark
(``test_pilot_conversions_v2.py``, ``test_deepswe_narwhals_rolling_window_suite_v2.py``).
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


NAME = "mashumaro-flattened-dataclass-fields"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "flatten_field_behavior"


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
    assert provenance["sha256"] == hashlib.sha256(patch.read_bytes()).hexdigest()
    assert provenance["baseline_commit"] == deep_task(NAME).input["base_commit"]


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

    At the base commit, ``field_options`` already accepts arbitrary
    ``**kwargs`` (so ``flatten=True`` is silently accepted and ignored, not
    rejected), and mashumaro's own ``field_options(**kwargs)`` never raises
    for an unknown option -- so this is not a crash. Every flatten/prefix/
    rename case instead produces the wrong ``to_dict()`` shape (the nested
    field stays as its own sub-dict) or a ``MissingField``/decoding error on
    ``from_dict()``, since the parent-level flattened keys never existed at
    the base commit.
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

    The gold patch's largest file is the new ``mashumaro/flatten.py`` module,
    which every flatten/prefix/rename axis depends on -- dropping it leaves
    only the ``builder.py``/``exceptions.py`` hunks, which reference
    now-missing imports.
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


# ---------------------------------------------------------------------------
# Gate 3: three targeted REAL-CODE mutants, gold patch + one hand edit each,
# replayed through real Docker Evaluations, each on a distinct semantic axis.
# Verified by hand against the gold solution inside the pinned image during
# conversion (see the dossier) before being relied on here.
# ---------------------------------------------------------------------------


def _replace_once(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(before)
    assert count == 1, (path, count, before)
    path.write_text(text.replace(before, after), encoding="utf-8")


def _mutate_prefix_true_drops_underscore(workspace: Path) -> None:
    """Axis: ``flatten_prefix=True`` auto-prefix derivation
    (test_flatten_prefix_true_serialize / _deserialize / _roundtrip /
    _multiple_same_type).

    The gold ``resolve_prefix`` helper turns ``flatten_prefix=True`` into
    ``field_name + "_"``. This hand edit drops the trailing underscore, so
    ``home: Address = field(metadata=field_options(flatten=True,
    flatten_prefix=True))`` would key its flattened fields ``"homecity"``
    instead of ``"home_city"`` -- a plausible off-by-one for a candidate that
    implements the auto-prefix from scratch instead of reusing its own
    literal-prefix code path with an appended separator.
    """
    target = workspace / "mashumaro" / "flatten.py"
    _replace_once(
        target,
        "    prefix = meta.get(\"flatten_prefix\")\n"
        "    if prefix is True:\n"
        "        return field_name + \"_\"\n",
        "    prefix = meta.get(\"flatten_prefix\")\n"
        "    if prefix is True:\n"
        "        return field_name  # BUG: drops the separator\n",
    )


def _mutate_collision_detection_ignores_alias(workspace: Path) -> None:
    """Axis: collision detection must cover every alias type
    (test_flatten_collision_with_alias / test_flatten_prefix_collision_with_config_alias).

    The public instruction explicitly requires collision validation to
    include "all alias types". This hand edit makes the plain-flatten
    collision-name computation stop contributing the child field's own
    ``alias`` to the collision set, so a child field whose alias shadows a
    parent field silently no longer raises at class-creation time -- exactly
    the requirement the instruction calls out by name.
    """
    target = workspace / "mashumaro" / "flatten.py"
    _replace_once(
        target,
        "    names: Set[str] = set()\n"
        "    try:\n"
        "        for f in fields(child_type):\n"
        "            names.add(prefix + f.name)\n"
        "            metadata = f.metadata if f.metadata else {}\n"
        "            alias = metadata.get(\"alias\")\n"
        "            if alias:\n"
        "                names.add(prefix + alias)\n"
        "    except TypeError:\n"
        "        pass\n"
        "    return names\n"
        "\n"
        "\n"
        "def get_prefix_key_mapping(\n",
        "    names: Set[str] = set()\n"
        "    try:\n"
        "        for f in fields(child_type):\n"
        "            names.add(prefix + f.name)\n"
        "            # BUG: no longer considers the child field's alias\n"
        "    except TypeError:\n"
        "        pass\n"
        "    return names\n"
        "\n"
        "\n"
        "def get_prefix_key_mapping(\n",
    )


def _mutate_rename_pack_ignores_child_serialize_by_alias(workspace: Path) -> None:
    """Axis: ``flatten_rename`` output-key precedence when the child also
    uses ``serialize_by_alias`` (test_flatten_rename_partial_with_child_serialize_by_alias
    / test_flatten_rename_with_child_alias_roundtrip).

    The gold ``build_rename_pack_mapping`` picks the child's *serialized*
    key (its alias, when ``serialize_by_alias`` is set) for fields that
    aren't explicitly renamed, so an unrenamed sibling field still comes out
    under its own alias. This hand edit always uses the plain field name
    instead, which is indistinguishable from correct whenever the child
    doesn't use ``serialize_by_alias`` (most cases) but wrong exactly when it
    does.
    """
    target = workspace / "mashumaro" / "flatten.py"
    _replace_once(
        target,
        "            if by_alias and alias:\n"
        "                serialized_key = alias\n"
        "            else:\n"
        "                serialized_key = f.name\n",
        "            if False and by_alias and alias:  # BUG: never uses the alias\n"
        "                serialized_key = alias\n"
        "            else:\n"
        "                serialized_key = f.name\n",
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_prefix_true_drops_underscore,
        _mutate_collision_detection_ignores_alias,
        _mutate_rename_pack_ignores_child_serialize_by_alias,
    ],
    ids=["prefix-true-separator", "collision-alias-blind-spot", "rename-pack-alias-precedence"],
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


def _reference_observation_from_expected(expected: dict) -> dict:
    """A correct-by-construction observation built only from the `expected`
    data the Oracle's own case generator produced (visible in
    `case.context`), never by running mashumaro -- this exists to exercise
    the Oracle's comparison logic directly for the malformed-evidence gate.
    """
    units = []
    for unit in expected["units"]:
        if unit["build_raised"]:
            units.append({"build_raised": True, "build_error_type": "FlattenError", "results": []})
            continue
        results = [
            {"kind": r_expected.get("kind", ""),
             "raised": bool(r_expected["raised"]),
             "error_type": "", "error_message": "",
             "result_json": json.dumps(r_expected.get("result"), sort_keys=True) if not r_expected["raised"] else "null"}
            for r_expected in unit["results"]
        ]
        units.append({"build_raised": False, "build_error_type": "", "results": results})
    return {"status": "observed", "units_json": json.dumps(units, sort_keys=True), "error_type": "", "error_message": ""}


def _oracle_root():
    task = deep_task(NAME)
    return Path(task.resources.resources["host.task_oracle"].value["source_path"])


def test_reference_observations_pass_every_oracle_case():
    """Fast sanity check (no Docker): replaying every Oracle case with a
    reference-correct observation, built only from `expected`, passes.
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-oracle-sanity")
        index = 0
        while (case := session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 32, "max_case_bytes": 65536})) is not None:
            observation = _reference_observation_from_expected(case.context["expected"])
            session.evaluate_challenge(
                CHECK_ID, case.context, _evidence(case.challenge, observation, index),
            )
            index += 1
        verdict = session.finalize()
    assert verdict.passed is True, verdict
    assert index >= 6


def test_forged_status_observed_with_missing_fields_is_rejected():
    """A malformed observation (missing every op-specific field) must not pass."""
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged")
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 32, "max_case_bytes": 65536})
        assert case is not None
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-0",
            evaluation_id="evaluation-forged-0",
            challenge_index=0,
            challenge_digest=json_digest(case.challenge),
            status="observed",
            exit_status=0,
            observation={"status": "observed"},  # missing units_json/error_type/etc.
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
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 32, "max_case_bytes": 65536})
        assert case is not None
        observation = _reference_observation_from_expected(case.context["expected"])
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
    uses when the candidate's code raised inside the Evaluation, for example
    a malformed challenge). The Oracle must key off that embedded status,
    not just the envelope.
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged-3")
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 32, "max_case_bytes": 65536})
        assert case is not None
        observation = {
            "status": "run_error", "units_json": "[]",
            "error_type": "ValueError", "error_message": "bad units list",
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


def test_forged_result_with_flipped_raised_flag_is_rejected():
    """A forged unit result that flips a `raised` flag (claiming a
    should-succeed action raised, or vice versa) must not pass.
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged-4")
        case = None
        while True:
            candidate = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 32, "max_case_bytes": 65536})
            if candidate is None:
                break
            units = candidate.context["expected"]["units"]
            if any(not u["build_raised"] and u["results"] for u in units):
                case = candidate
                break
        assert case is not None
        observation = _reference_observation_from_expected(case.context["expected"])
        units = json.loads(observation["units_json"])
        for unit in units:
            if not unit["build_raised"] and unit["results"]:
                unit["results"][0]["raised"] = not unit["results"][0]["raised"]
                unit["results"][0]["result_json"] = "null"
                break
        observation["units_json"] = json.dumps(units, sort_keys=True)
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
