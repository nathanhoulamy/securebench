"""Real-capture Docker qualification for `termenv-preserve-ansi-resets`.

The Evaluation adapter compiles and runs a small Go driver (see
``benchmarks/deep-swe/v2/evaluation_inputs/termenv-preserve-ansi-resets/adapter/driver.go``)
that exercises only the public termenv/ansi surface named in the public
instruction. Every expected byte string, token classification, width, and
boolean lives in the host Oracle (``benchmarks/deep-swe/v2/hidden/termenv-preserve-ansi-resets/oracle/oracle.py``),
which is never mounted into the Agent or Evaluation environment.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.verification.json_data import json_digest
from securebench.verification.models import ChallengeEvidence
from securebench.verification.oracle import OracleProcessSession
from tests.deepswe_qualification import HIDDEN, deep_task, materialize_baseline, reference_patch, verify_patch
from tests.qualification_support import DOCKER_INTEGRATION

NAME = "termenv-preserve-ansi-resets"


def test_row_preflights_and_keeps_the_reference_host_only():
    task = deep_task(NAME)
    validate_executable_task(task)

    assert task.family == "repo_patch"
    assert task.verification.candidate.type == "git_patch"
    assert task.input["base_commit"] == "368a3572b8146cc038b3f240da6792003d7e42c5"
    assert re.fullmatch(r"[0-9a-f]{40}", task.input["base_commit"])
    assert task.environment.agent_network.mode == "none"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
        assert "oracle.py" not in view
    # The adapter is mounted into the Evaluation runtime, never into the Agent.
    assert "adapter.py" not in str(task.view_for("agent"))


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
    import subprocess

    if not diff_text:
        return
    subprocess.run(
        ["git", "-C", str(workspace), "apply", "--whitespace=nowarn", "-"],
        input=diff_text.encode(), check=True,
    )


@DOCKER_INTEGRATION
def test_incomplete_implementation_mutant_fails(tmp_path, baseline):
    """Gate 3 (generic): drop the largest non-test file of the gold patch."""
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
def test_mutant_reset_detection_only_full_reset_fails(tmp_path, baseline):
    """Targets: 'Treat as reset ESC[m and any ESC[...m where any parameter
    parses to 0' -- a near-miss that only recognizes the bare ``ESC[m``/``ESC[0m``
    forms and misses compound resets like ``ESC[1;0;31m``.
    """
    def mutate(workspace: Path) -> None:
        path = workspace / "ansi" / "parser.go"
        text = path.read_text()
        old = "func sgrIsReset(raw string) bool {"
        assert text.count(old) == 1
        replacement = (
            "func sgrIsReset(raw string) bool {\n"
            "\treturn raw == \"\\x1b[m\" || raw == \"\\x1b[0m\"\n"
            "}\n\nfunc unusedSgrIsReset(raw string) bool {"
        )
        path.write_text(text.replace(old, replacement, 1))

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-reset-detection",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert any(item.observation and item.observation.get("status") == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_mutant_no_reopen_after_reset_fails(tmp_path, baseline):
    """Targets: 'When preserve-resets is enabled, re-open the enclosing style
    after each reset run' -- a near-miss that preserves the reset bytes but
    never re-opens the style afterward.
    """
    def mutate(workspace: Path) -> None:
        path = workspace / "ansi" / "util.go"
        text = path.read_text()
        old = "if opts.PreserveResets {\n\t\t\t\tpendingReopen = true\n\t\t\t}"
        assert text.count(old) == 1
        path.write_text(text.replace(old, "if false && opts.PreserveResets {\n\t\t\t\tpendingReopen = true\n\t\t\t}", 1))

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-no-reopen",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert any(item.observation and item.observation.get("status") == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_mutant_no_split_guarantee_fails(tmp_path, baseline):
    """Targets: 'Truncation must never split CSI/OSC sequences; they have zero
    visible width' -- a near-miss that charges CSI/OSC raw bytes toward the
    visible-width budget instead of treating them as zero width, which can
    cut a control sequence mid-token.
    """
    def mutate(workspace: Path) -> None:
        path = workspace / "ansi" / "util.go"
        text = path.read_text()
        old = "\t\tcase TokenSGR:\n\t\t\tb.WriteString(tok.Raw)\n\t\t\tsgrActive = true"
        assert text.count(old) == 1
        replacement = (
            "\t\tcase TokenSGR:\n"
            "\t\t\tif visible+1 > maxTextWidth {\n"
            "\t\t\t\ttruncated = true\n"
            "\t\t\t\tbreak\n"
            "\t\t\t}\n"
            "\t\t\tb.WriteString(tok.Raw)\n"
            "\t\t\tsgrActive = true"
        )
        path.write_text(text.replace(old, replacement, 1))

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-no-split",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert any(item.observation and item.observation.get("status") == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_mutant_hyperlink_not_closed_fails(tmp_path, baseline):
    """Targets: 'Close open OSC 8 hyperlinks' -- a near-miss that drops the
    synthetic close sequence at truncation time.
    """
    def mutate(workspace: Path) -> None:
        path = workspace / "ansi" / "util.go"
        text = path.read_text()
        old = "\t\tif hl.IsOpen() {\n\t\t\tb.WriteString(hl.CloseSeq())\n\t\t\thl.Close()\n\t\t}"
        assert text.count(old) == 1
        path.write_text(text.replace(old, "\t\tif false && hl.IsOpen() {\n\t\t\tb.WriteString(hl.CloseSeq())\n\t\t\thl.Close()\n\t\t}", 1))

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-hyperlink-not-closed",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert any(item.observation and item.observation.get("status") == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_mutant_ascii_style_truncate_emits_tail_fails(tmp_path, baseline):
    """Targets: 'Under Ascii, Style.Truncate returns plain text without tail'
    -- a near-miss that appends the tail under the Ascii profile anyway.
    """
    def mutate(workspace: Path) -> None:
        path = workspace / "style.go"
        text = path.read_text()
        marker = "\t\treturn b.String()\n\t}\n\n\treturn TruncateANSI(t.String(), maxWidth, opts)"
        assert text.count(marker) == 1
        replacement = (
            "\t\tresult := b.String()\n"
            "\t\tif opts.Tail != \"\" {\n"
            "\t\t\tresult += opts.Tail\n"
            "\t\t}\n"
            "\t\treturn result\n"
            "\t}\n\n\treturn TruncateANSI(t.String(), maxWidth, opts)"
        )
        path.write_text(text.replace(marker, replacement, 1))

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-ascii-tail",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert any(item.observation and item.observation.get("status") == "observed" for item in outcome.evidence)


CHECK_ID = "ansi_behavior"


def _honest_observation(context):
    """Build the exact observation an honest candidate would produce for one
    Oracle case, from the case_context's own recorded expectation.

    ``expected`` is deep-copied so that corrupting the returned observation
    (as the Gate 4 tests below do) can never also corrupt the ``case_context``
    that gets round-tripped back to the Oracle in ``evaluate_challenge``.
    """
    import copy

    observation = {"status": "observed", "text": "", "width": 0, "has_ansi": False,
                    "tokens": [], "error": ""}
    check, expected = context["check"], context["expected"]
    if check == "tokens":
        observation["tokens"] = copy.deepcopy(expected)
    elif check == "text":
        observation["text"] = expected
    elif check == "width":
        observation["width"] = expected
    elif check == "has_ansi":
        observation["has_ansi"] = expected
    # "no_panic" and "no_split" are satisfied by the empty-text default above.
    return observation


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


def _drive(task, *, corrupt=None):
    """Replay every Oracle case, honestly by default.

    ``corrupt(index, context, observation, evidence_kwargs)`` may mutate the
    observation dict or the ``evidence_kwargs`` dict in place before the
    evidence is built and sent, to model one adversarial or malformed
    candidate response. No Docker or candidate code is involved: this drives
    the real Oracle subprocess directly with synthetic evidence.
    """
    with OracleProcessSession(HIDDEN / NAME / "oracle") as session:
        session.initialize(task, run_seed=f"{NAME}-gate4")
        index = 0
        while (
            case := session.next_challenge(
                CHECK_ID, "host.task_oracle", {"max_cases": 40, "max_case_bytes": 8192},
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


def test_oracle_accepts_every_honest_observation():
    verdict = _drive(deep_task(NAME))
    assert verdict.passed is True


def test_oracle_rejects_a_forged_text_answer():
    """Gate 4: a forged 'observed' evidence item with the wrong text/width/
    has_ansi/tokens value for a 'text'-checked case is rejected."""
    def corrupt(index, context, observation, evidence_kwargs):
        if context["check"] == "text":
            observation["text"] = observation["text"] + "-forged"

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_a_forged_token_classification():
    def corrupt(index, context, observation, evidence_kwargs):
        if context["check"] == "tokens" and observation["tokens"]:
            observation["tokens"][0]["type"] = "text"

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_malformed_observation_wrong_shape():
    """A malformed observation (missing required 'status' field) must not pass,
    for whichever case it lands on, since the Oracle checks observation shape
    before inspecting per-check fields."""
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0:
            del observation["status"]

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_candidate_error_status():
    """Non-'observed' evidence status must never be silently treated as a pass."""
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0:
            evidence_kwargs["status"] = "candidate_error"

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_observation_carrying_a_nonempty_error():
    def corrupt(index, context, observation, evidence_kwargs):
        if index == 0:
            observation["error"] = "unexpected error"

    verdict = _drive(deep_task(NAME), corrupt=corrupt)
    assert verdict.passed is False
