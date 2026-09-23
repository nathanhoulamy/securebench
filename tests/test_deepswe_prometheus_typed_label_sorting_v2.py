"""Real-capture Docker qualification for `prometheus-typed-label-sorting`.

The Evaluation adapter builds the candidate's own promql package into a small
Go driver (see
``benchmarks/deep-swe/v2/evaluation_inputs/prometheus-typed-label-sorting/adapter/driver.go``)
and exercises `sort_by_label`/`sort_by_label_desc` the way any Prometheus user
would: through the exported promql.Engine, evaluating a real PromQL query.
Every expected order, secret label pool, and comparator implementation lives
in the host Oracle
(``benchmarks/deep-swe/v2/hidden/prometheus-typed-label-sorting/oracle/oracle.py``),
which is never mounted into the Agent or Evaluation environment.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.verification.json_data import json_digest
from securebench.verification.models import ChallengeEvidence
from securebench.verification.oracle import OracleProcessSession
from tests.deepswe_qualification import HIDDEN, deep_task, materialize_baseline, reference_patch, verify_patch
from tests.qualification_support import DOCKER_INTEGRATION

NAME = "prometheus-typed-label-sorting"
CHECK_ID = "sort_by_label_behavior"


def test_row_preflights_and_keeps_the_reference_host_only():
    task = deep_task(NAME)
    validate_executable_task(task)

    assert task.family == "repo_patch"
    assert task.verification.candidate.type == "git_patch"
    assert task.input["base_commit"] == "8b25b26a7653d9c7444f217a7f2ae9b327bda921"
    assert re.fullmatch(r"[0-9a-f]{40}", task.input["base_commit"])
    assert task.environment.agent_network.mode == "none"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
        assert "oracle.py" not in view
    # The adapter is mounted into the Evaluation runtime, never into the Agent.
    assert "adapter.py" not in str(task.view_for("agent"))
    assert "driver.go" not in str(task.view_for("agent"))


def test_reference_patch_is_the_pinned_upstream_solution():
    import hashlib

    patch = reference_patch(NAME)
    provenance = json.loads((patch.parent / "provenance.json").read_text())

    assert provenance["source_revision"] == "e016041a6ccf8da29906afc9a3f5a8df940a1f78"
    assert provenance["source_path"] == f"tasks/{NAME}/solution/solution.patch"
    assert provenance["sha256"] == hashlib.sha256(patch.read_bytes()).hexdigest()
    assert provenance["baseline_commit"] == deep_task(NAME).input["base_commit"]


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp(f"{NAME}-baseline") / "app"
    return materialize_baseline(NAME, root)


@DOCKER_INTEGRATION
def test_base_fails_through_the_real_capture_path(tmp_path, baseline):
    """Gate 1: the unmodified base commit must not pass, with no infra error."""
    outcome = verify_patch(NAME, baseline, tmp_path, run_seed=f"{NAME}-base")

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_reference_passes_in_fresh_evaluations(tmp_path, baseline):
    """Gate 2: the upstream solution passes, across >=2 fresh Evaluations."""
    outcome = verify_patch(NAME, baseline, tmp_path, reference=True, run_seed=f"{NAME}-reference")

    assert outcome.status == "passed", (
        outcome.result,
        [item.observation for item in outcome.evidence
         if item.observation and item.observation.get("status") != "observed"],
    )
    assert not outcome.infrastructure_errors, outcome.evidence
    assert len(outcome.evidence) >= 2
    assert len(set(outcome.evaluation_ids)) == len(outcome.evaluation_ids)
    assert all(item.status == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_reference_passes_a_second_fresh_run(tmp_path, baseline):
    """Gate 2, repeated with a distinct run_seed: distinct Evaluation IDs again."""
    outcome = verify_patch(NAME, baseline, tmp_path, reference=True, run_seed=f"{NAME}-reference-two")

    assert outcome.status == "passed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert all(item.status == "observed" for item in outcome.evidence)


def _file_diffs(patch_text: str) -> list[tuple[str, str]]:
    chunks = re.split(r"(?m)^(?=diff --git )", patch_text)
    pairs = []
    for chunk in chunks:
        match = re.match(r"diff --git a/(\S+) b/\S+", chunk)
        if match:
            pairs.append((match.group(1), chunk))
    return pairs


def _apply(workspace: Path, diff_text: str) -> None:
    if not diff_text:
        return
    subprocess.run(
        ["git", "-C", str(workspace), "apply", "--whitespace=nowarn", "-"],
        input=diff_text.encode(), check=True,
    )


@DOCKER_INTEGRATION
def test_incomplete_implementation_mutant_fails(tmp_path, baseline):
    """Gate 3 (generic): drop the largest non-test file of the gold patch.

    That file is ``promql/sort_by_label_multitype_compare.go``, which defines
    every parser/comparator the rest of the gold patch calls; dropping it
    leaves an uncompilable candidate.
    """
    diffs = _file_diffs(reference_patch(NAME).read_text())
    assert diffs, "reference patch has no changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    kept = "".join(diff for path, diff in diffs if path != dropped)

    outcome = verify_patch(
        NAME, baseline, tmp_path,
        mutate=lambda workspace: _apply(workspace, kept),
        run_seed=f"{NAME}-partial-{dropped}",
    )

    assert outcome.status == "failed", (dropped, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_mutant_leading_whitespace_precedence_fails(tmp_path, baseline):
    """Targets: 'Values with leading whitespace ... must sort before all
    other values' -- a near-miss that stops special-casing the
    leading-whitespace group, so it no longer sorts ahead of typed values
    such as +Inf.
    """
    def mutate(workspace: Path) -> None:
        path = workspace / "promql" / "sort_by_label_multitype_compare.go"
        text = path.read_text()
        old = "func mixedMultiTypeGroup(raw string, typed bool) int {\n\tif hasLeadingMultiTypeSpace(raw) {\n\t\treturn 0\n\t}"
        assert text.count(old) == 1
        replacement = "func mixedMultiTypeGroup(raw string, typed bool) int {\n\tif hasLeadingMultiTypeSpace(raw) {\n\t\treturn 3\n\t}"
        path.write_text(text.replace(old, replacement, 1))

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-leading-whitespace",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert any(item.observation and item.observation.get("status") == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_mutant_cidr_prefix_length_direction_fails(tmp_path, baseline):
    """Targets: 'For CIDRs with equal network address bytes, smaller prefix
    lengths must sort first' -- a near-miss that reverses the prefix-length
    comparison direction.
    """
    def mutate(workspace: Path) -> None:
        path = workspace / "promql" / "sort_by_label_multitype_compare.go"
        text = path.read_text()
        old = "\tif a.Bits() < b.Bits() {\n\t\treturn -1\n\t}\n\tif a.Bits() > b.Bits() {\n\t\treturn 1\n\t}\n\treturn 0\n}"
        assert text.count(old) == 1
        replacement = "\tif a.Bits() < b.Bits() {\n\t\treturn 1\n\t}\n\tif a.Bits() > b.Bits() {\n\t\treturn -1\n\t}\n\treturn 0\n}"
        path.write_text(text.replace(old, replacement, 1))

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-cidr-prefix-direction",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert any(item.observation and item.observation.get("status") == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_mutant_huge_magnitude_order_fails(tmp_path, baseline):
    """Targets: 'all magnitude comparisons must preserve order for
    arbitrarily large values without loss of precision' -- a near-miss that
    drops the coefficient digit count from the magnitude-order estimate, so
    numbers whose coefficients have different digit counts (as in the
    huge-magnitude cases, e.g. a 24-digit integer versus ``1e+24``) compare
    incorrectly.
    """
    def mutate(workspace: Path) -> None:
        path = workspace / "promql" / "sort_by_label_multitype_compare.go"
        text = path.read_text()
        old = (
            "\torderA := a.exponent + decimalDigitCount(a.coefficient)\n"
            "\torderB := b.exponent + decimalDigitCount(b.coefficient)"
        )
        assert text.count(old) == 1
        replacement = "\torderA := a.exponent\n\torderB := b.exponent"
        path.write_text(text.replace(old, replacement, 1))

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-huge-magnitude",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert any(item.observation and item.observation.get("status") == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_mutant_equal_typed_natural_tie_break_removed_fails(tmp_path, baseline):
    """Targets: 'When two parsed typed values are equal, break ties by
    natural ordering of the original label strings' -- a near-miss that
    treats equal-typed values as fully equal instead, so the tie-break falls
    through to the (here, unpredictable) full label-set comparison instead of
    the specified natural-order rule.
    """
    def mutate(workspace: Path) -> None:
        path = workspace / "promql" / "sort_by_label_multitype_compare.go"
        text = path.read_text()
        old = (
            "\t\tif cmp != 0 {\n"
            "\t\t\treturn cmp\n"
            "\t\t}\n"
            "\t\treturn compareNaturalMultiType(a, b)\n"
            "\t}\n"
            "\tif parsedA.ok != parsedB.ok {"
        )
        assert text.count(old) == 1
        replacement = (
            "\t\tif cmp != 0 {\n"
            "\t\t\treturn cmp\n"
            "\t\t}\n"
            "\t\treturn 0\n"
            "\t}\n"
            "\tif parsedA.ok != parsedB.ok {"
        )
        path.write_text(text.replace(old, replacement, 1))

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-equal-typed-tie-break",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert any(item.observation and item.observation.get("status") == "observed" for item in outcome.evidence)


# --- Gate 4: the Oracle rejects forged/malformed evidence, driven directly -

def _honest_observation(context):
    """The exact observation an honest candidate would produce for one
    Oracle case, from the case_context's own recorded expectation. Deep-copied
    so corrupting the returned observation below can never also corrupt the
    ``case_context`` that gets round-tripped back to the Oracle.
    """
    return {"status": "observed", "order": copy.deepcopy(context["expected"]),
            "warning_count": 0, "run_error": ""}


def _oracle_evidence(task, index, observation, *, status="observed"):
    challenge_id = f"challenge-gate4-{index}"
    evaluation_id = f"evaluation-gate4-{index}"
    failed = status != "observed"
    return ChallengeEvidence(
        check_id=task.verification.checks[0].id,
        challenge_id=challenge_id,
        evaluation_id=evaluation_id,
        challenge_index=index,
        challenge_digest=json_digest({}),
        status=status,
        exit_status=None if failed else 0,
        observation=None if failed else observation,
        observation_bytes=0 if failed else len(json.dumps(observation)),
        failure_source="candidate" if failed else None,
        failure_code="forged_candidate_error" if failed else None,
        failure_message="gate 4 synthetic candidate_error" if failed else None,
        trusted_helper_evidence=(),
    )


def _drive(task, *, corrupt=None):
    """Replay every Oracle case, honestly by default.

    ``corrupt(index, context, observation, evidence_kwargs)`` may mutate the
    observation dict or the ``evidence_kwargs`` dict in place before the
    evidence is built and sent, to model one adversarial or malformed
    candidate response. No Docker or candidate code is involved here: this
    drives the real Oracle subprocess directly with synthetic evidence.
    """
    with OracleProcessSession(HIDDEN / NAME / "oracle") as session:
        session.initialize(task, run_seed=f"{NAME}-gate4")
        index = 0
        while (
            case := session.next_challenge(
                CHECK_ID, "host.task_oracle", {"max_cases": 16, "max_case_bytes": 65536},
            )
        ) is not None:
            observation = _honest_observation(case.context)
            evidence_kwargs = {"status": "observed"}
            if corrupt is not None:
                corrupt(index, case.context, observation, evidence_kwargs)
            session.evaluate_challenge(
                CHECK_ID, case.context,
                _oracle_evidence(task, index, observation, **evidence_kwargs),
            )
            index += 1
        return session.finalize()


def test_oracle_accepts_every_honest_observation():
    verdict = _drive(deep_task(NAME))
    assert verdict.passed is True


def test_oracle_rejects_a_forged_order():
    """Gate 4: an 'observed' evidence item that reports the wrong order for
    the case is rejected."""
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0 and len(observation["order"]) >= 2:
            observation["order"][0], observation["order"][1] = (
                observation["order"][1], observation["order"][0],
            )

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_malformed_observation_wrong_shape():
    """A malformed observation (missing required 'status' field) must not
    pass, for whichever case it lands on, since the Oracle checks observation
    shape before inspecting per-case fields."""
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0:
            del observation["status"]

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_candidate_error_status():
    """Non-'observed' evidence status must never be silently treated as a
    pass."""
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0:
            evidence_kwargs["status"] = "candidate_error"

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_observation_carrying_a_nonempty_run_error():
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0:
            observation["run_error"] = "unexpected error"

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_unexpected_annotations():
    """The upstream test suite asserts nil annotations on every case
    (``require.Nil(t, anns)``); a candidate that reports warnings must not
    pass."""
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0:
            observation["warning_count"] = 1

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_an_extra_or_missing_order_entry():
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0:
            observation["order"] = observation["order"][:-1]

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False
