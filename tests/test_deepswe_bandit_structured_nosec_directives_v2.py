"""Real-capture Docker qualification for ``bandit-structured-nosec-directives``.

Gate 1/2/3 replay the production path (see ``tests/deepswe_qualification.py``):
a workspace is cloned from the materialised pinned baseline, the upstream gold
solution (``qualification/reference.patch``) is optionally applied, targeted
source-level mutants are optionally layered on top, and the result is captured
as a real ``git_patch`` candidate and verified through fresh Evaluation
containers using the real Oracle process.

Gate 4 drives the Oracle directly with synthetic ``ChallengeEvidence`` (no
Docker involved) to prove it rejects forged and malformed candidate
observations, the same pattern used for the pilot rows in
``tests/test_pilot_conversions_v2.py``.
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


NAME = "bandit-structured-nosec-directives"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "nosec_directive_behavior"


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
# Docker-backed gates 1, 2, 3
# ---------------------------------------------------------------------------


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
    """Gate 2: the upstream gold solution passes, one fresh Evaluation per case."""
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, run_seed=f"{NAME}-reference"
    )

    assert outcome.status == "passed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert len(outcome.evidence) >= 2
    assert len(set(outcome.evaluation_ids)) == len(outcome.evaluation_ids)
    assert all(item.status == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_reference_passes_again_with_a_different_run_seed(tmp_path, baseline):
    """Second independent replay: distinct Evaluation IDs from the first run too."""
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, run_seed=f"{NAME}-reference-second"
    )

    assert outcome.status == "passed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert all(item.status == "observed" for item in outcome.evidence)


def _file_diffs(patch_text: str) -> list[tuple[str, str]]:
    """Split a unified git patch into (path, per-file diff) pairs."""
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
def test_incomplete_implementation_mutant_fails(tmp_path, baseline):
    """Gate 3 (generic): drop the largest non-test file of the gold patch.

    ``nosec_parse.py`` is the largest new file the gold solution adds; without
    it ``bandit/core/nosec.py`` (which imports it) fails at import time, and in
    turn ``bandit/core/manager.py`` (which imports ``nosec``) fails too, so the
    candidate's own ``bandit`` CLI cannot even start.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped.endswith("nosec_parse.py"), dropped
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
        NAME, baseline, tmp_path, mutate=apply_partial,
        run_seed=f"{NAME}-partial-{dropped}",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


def _apply_gold_then_edit(workspace: Path, relative_path: str, old: str, new: str) -> None:
    """Apply the gold solution (via the ``reference=True`` path already taken by
    ``verify_patch`` before calling ``mutate``) and then hand-edit one file to
    break a single, distinct semantic axis. Each mutation is a plausible
    near-miss reachable by an agent that mostly understood the spec, not a
    syntax error.
    """
    target = workspace / relative_path
    text = target.read_text()
    assert old in text, f"expected pattern not found in {relative_path}"
    target.write_text(text.replace(old, new, 1))


@DOCKER_INTEGRATION
def test_blanket_does_not_dominate_union_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: blanket suppression must dominate a union with any
    specific selector (instruction.md: "If any applicable suppression is
    blanket, it dominates."). This mutant's ``_union`` forgets that an empty
    set means "all tests", so nesting a blanket region inside a specific one
    (or unioning a blanket region with an inline specific ``# nosec``) no
    longer suppresses everything -- a classic near-miss for anyone who treats
    "empty selector" and "no selector" as unrelated cases.
    """
    old = (
        'def _union(a, b):\n'
        '    if a is None:\n'
        '        return b\n'
        '    if b is None:\n'
        '        return a\n'
        '    if not a or not b:\n'
        '        return set()\n'
        '    return set(a) | set(b)'
    )
    new = (
        'def _union(a, b):\n'
        '    if a is None:\n'
        '        return b\n'
        '    if b is None:\n'
        '        return a\n'
        '    return set(a) | set(b)'
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "bandit/core/nosec.py", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-blanket-dominance",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_region_does_not_auto_end_at_dedent_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: an indented, unterminated ``# nosec-begin`` region must
    auto-end "when a later line has smaller indentation" (instruction.md).
    This mutant disables the dedent-triggered auto-pop, so the region instead
    leaks past the indented block it started in -- the region-scoping analogue
    of forgetting to close a block.
    """
    old = (
        '        while stack and stack[-1]["auto_end"] and stack[-1]["indent"] > current_indent:\n'
        '            stack.pop()'
    )
    new = (
        '        while False and stack and stack[-1]["auto_end"] and stack[-1]["indent"] > current_indent:\n'
        '            stack.pop()'
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "bandit/core/nosec.py", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-dedent-autoend",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_selector_intersection_behaves_like_union_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: the selector language's ``&`` (intersection) operator must
    actually intersect (instruction.md: "The operators | (union), & (intersection)
    ... are supported"). This mutant implements ``&`` as another union, a
    plausible copy-paste slip from the ``|`` branch just above it, breaking
    parenthesised precedence and the ``all & B602`` specific/blanket
    classification.
    """
    old = (
        '        right, k = _parse_unary(tokens, j + 1, extman, enabled_test_ids)\n'
        '        if right is None:\n'
        '            return None, idx\n'
        '        left = set(left) & set(right)\n'
        '        j = k'
    )
    new = (
        '        right, k = _parse_unary(tokens, j + 1, extman, enabled_test_ids)\n'
        '        if right is None:\n'
        '            return None, idx\n'
        '        left = set(left) | set(right)\n'
        '        j = k'
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "bandit/core/nosec_selector.py", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-selector-intersection",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_linerange_truncated_to_node_start_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: suppression is statement-wide (instruction.md: "If a
    multi-line statement has any suppressed line, findings for that statement
    are suppressed"). This mutant truncates ``linerange`` back to
    ``[node.lineno]`` only, losing the full multi-line span, so a suppression
    that only reaches a line other than the finding's own reported line (for
    example a mid-statement inline ``# nosec-begin`` whose effect starts on the
    call's closing-paren line) no longer applies.
    """
    old = (
        '        end = getattr(node, "end_lineno", None)\n'
        '        if isinstance(end, int) and end >= node.lineno:\n'
        '            return list(range(node.lineno, end + 1))\n'
        '        return [node.lineno]'
    )
    new = '        return [node.lineno]'

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "bandit/core/utils.py", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-linerange-truncated",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


# ---------------------------------------------------------------------------
# Gate 4: the Oracle rejects forged and malformed observations (no Docker)
# ---------------------------------------------------------------------------


def _oracle_evidence(task, case, index, observation, *, status="observed"):
    challenge_id = f"challenge-gate4-{index}"
    evaluation_id = f"evaluation-gate4-{index}"
    failed = status != "observed"
    return ChallengeEvidence(
        check_id=task.verification.checks[0].id,
        challenge_id=challenge_id,
        evaluation_id=evaluation_id,
        challenge_index=index,
        challenge_digest=json_digest(case.challenge),
        status=status,
        exit_status=None if failed else 0,
        observation=None if failed else observation,
        observation_bytes=0 if failed else len(json.dumps(observation)),
        failure_source="candidate" if failed else None,
        failure_code="forged_candidate_error" if failed else None,
        failure_message="gate 4 synthetic candidate_error" if failed else None,
        trusted_helper_evidence=(),
    )


def _honest_observation(context):
    return {
        "status": "observed",
        "findings": [
            {"test_id": test_id, "line": line}
            for test_id, line in context["expected_findings"]
        ],
        "metrics": dict(context["expected_metrics"]),
        "errors_count": 0,
        "error_message": "",
    }


def _drive(task, *, corrupt=None):
    """Replay every Oracle case, honestly by default.

    ``corrupt(index, context, observation, evidence_kwargs)`` may mutate the
    observation dict or the ``evidence_kwargs`` dict in place before the
    evidence is built and sent, to model one adversarial or malformed
    candidate response.
    """
    oracle_root = Path(
        task.resources.resources["host.task_oracle"].value["source_path"]
    )
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="bandit-nosec-gate4")
        index = 0
        while (
            case := session.next_challenge(
                CHECK_ID, "host.task_oracle",
                {"max_cases": 34, "max_case_bytes": 32768},
            )
        ) is not None:
            observation = _honest_observation(case.context)
            evidence_kwargs = {"status": "observed"}
            if corrupt is not None:
                corrupt(index, case.context, observation, evidence_kwargs)
            session.evaluate_challenge(
                CHECK_ID, case.context,
                _oracle_evidence(task, case, index, observation, **evidence_kwargs),
            )
            index += 1
        return session.finalize()


def _bandit_task():
    return deep_task(NAME)


def test_oracle_accepts_every_honest_observation():
    verdict = _drive(_bandit_task())
    assert verdict.passed is True


def test_oracle_rejects_a_forged_empty_report_impersonating_suppression():
    """An adversarial candidate that reports zero findings and zero errors for
    every case (as if every call were suppressed, or as if the file were
    empty) must not pass -- every case carries an unsuppressed control finding
    or a specific metric that this would falsify.
    """
    def corrupt(index, context, observation, evidence_kwargs):
        observation["findings"] = []
        observation["metrics"] = {"nosec": 0, "skipped_tests": 0}

    verdict = _drive(_bandit_task(), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_wrong_metrics_with_correct_findings():
    """Findings alone are not sufficient: nosec/skipped_tests classification
    (blanket vs specific) must also match, per instruction.md's metrics rule.
    """
    done = {"applied": False}

    def corrupt(index, context, observation, evidence_kwargs):
        metrics = observation["metrics"]
        if done["applied"] or metrics["nosec"] == metrics["skipped_tests"]:
            return
        observation["metrics"] = {
            "nosec": metrics["skipped_tests"],
            "skipped_tests": metrics["nosec"],
        }
        done["applied"] = True

    verdict = _drive(_bandit_task(), corrupt=corrupt)
    assert done["applied"], "no case with distinguishable metrics was found"
    assert verdict.passed is False


def test_oracle_rejects_observation_with_parse_errors_present():
    """A report that happens to match findings/metrics but also carries a
    parse error must be rejected: an error-carrying report is not a trustworthy
    measurement of suppression behavior.
    """
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0:
            observation["errors_count"] = 1

    verdict = _drive(_bandit_task(), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_candidate_error_status():
    """A candidate/adapter that reports non-'observed' evidence status (crash,
    timeout, infrastructure hiccup surfaced to the check level) must not be
    silently treated as a pass.
    """
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0:
            evidence_kwargs["status"] = "candidate_error"

    verdict = _drive(_bandit_task(), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_malformed_finding_shape():
    """A finding missing the required ``line`` field must be rejected rather
    than crash the Oracle or be silently ignored into a pass.
    """
    done = {"applied": False}

    def corrupt(index, context, observation, evidence_kwargs):
        if done["applied"] or not observation["findings"]:
            return
        del observation["findings"][0]["line"]
        done["applied"] = True

    verdict = _drive(_bandit_task(), corrupt=corrupt)
    assert done["applied"], "no case with findings was found"
    assert verdict.passed is False
