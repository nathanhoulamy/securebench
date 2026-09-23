"""Real-capture Docker qualification for `deep-swe/pest-character-class-coalescing`.

Follows the pattern established by `tests/test_deepswe_first_wave_replay_v2.py`:
a real patch is captured from a stopped workspace and replayed into fresh
Evaluations of the pinned image, judged by the real Oracle process. Gate 4
(forged/malformed adapter observations rejected) is a unit-level test that
drives the real Oracle module directly, per the conversion playbook.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from tests.deepswe_qualification import (
    HIDDEN,
    deep_task,
    materialize_baseline,
    reference_patch,
    verify_patch,
)
from tests.qualification_support import DOCKER_INTEGRATION, load_module


NAME = "pest-character-class-coalescing"


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


def _apply_reference_then(workspace: Path, edit) -> None:
    """Apply the pinned upstream solution, then a targeted hand-edit mutation."""
    subprocess.run(
        ["git", "-C", str(workspace), "apply", "--whitespace=nowarn",
         str(reference_patch(NAME))],
        check=True,
    )
    edit(workspace)


def _replace_once(path: Path, needle: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(needle)
    assert count == 1, f"expected exactly one occurrence of {needle!r} in {path}, found {count}"
    path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")


def _coalescer_path(workspace: Path) -> Path:
    return workspace / "meta" / "src" / "optimizer" / "coalescer.rs"


# ---------------------------------------------------------------------------
# Row shape and visibility.
# ---------------------------------------------------------------------------

def test_row_preflights_and_keeps_the_reference_host_only():
    task = deep_task(NAME)
    validate_executable_task(task)

    assert task.family == "repo_patch"
    assert task.verification.candidate.type == "git_patch"
    assert re.fullmatch(r"[0-9a-f]{40}", task.input["base_commit"])
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
    assert "adapter" not in str(task.view_for("agent"))


def test_reference_patch_is_the_pinned_upstream_solution():
    import hashlib

    patch = reference_patch(NAME)
    provenance = json.loads((patch.parent / "provenance.json").read_text())

    assert provenance["source_revision"] == "e016041a6ccf8da29906afc9a3f5a8df940a1f78"
    assert provenance["source_path"] == f"tasks/{NAME}/solution/solution.patch"
    assert provenance["sha256"] == hashlib.sha256(patch.read_bytes()).hexdigest()
    assert provenance["baseline_commit"] == deep_task(NAME).input["base_commit"]


# ---------------------------------------------------------------------------
# Gates 1-3, real Docker.
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
    """Gates 2 and 5: the upstream solution passes, one fresh Evaluation per case."""
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, run_seed=f"{NAME}-reference"
    )

    assert outcome.status == "passed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert len(outcome.evidence) >= 2
    assert len(set(outcome.evaluation_ids)) == len(outcome.evidence)
    assert all(item.status == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_dropping_the_largest_non_test_file_fails(tmp_path, baseline):
    """Gate 3, generic mutant: drop the largest non-test source change.

    Models an almost-correct submission that implements most of the feature
    but misses one file of it -- here, the coalescer module itself.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "meta/src/optimizer/coalescer.rs", dropped
    kept = "".join(diff for path, diff in diffs if path != dropped)

    def apply_partial(workspace: Path) -> None:
        if not kept:
            return
        subprocess.run(
            ["git", "-C", str(workspace), "apply", "--whitespace=nowarn", "-"],
            input=kept.encode(), check=True,
        )

    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=apply_partial,
        run_seed=f"{NAME}-partial-{dropped}",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_benefit_check_off_by_one_mutant_fails(tmp_path, baseline):
    """Gate 3, targeted mutant 1: coalesce even when merging is not beneficial.

    Targets "a coalesced result is emitted only when merging produces fewer
    ranges than the original alternative count" -- upstream axis exercised by
    `full_chain_non_beneficial_with_ranges` / `insens_two_chars_non_beneficial`
    / `range_same_start_end_with_different_char_stays_choice`.
    """
    def edit(workspace: Path) -> None:
        _replace_once(
            _coalescer_path(workspace),
            "if merged.len() >= alt_count {",
            "if merged.len() > alt_count {",
        )

    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=lambda w: _apply_reference_then(w, edit),
        run_seed=f"{NAME}-mutant-benefit",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_case_insensitive_expansion_disabled_mutant_fails(tmp_path, baseline):
    """Gate 3, targeted mutant 2: never expand Insens to both letter cases.

    Targets "case-insensitive alphabetic characters expand to cover both
    letter cases" -- upstream axis exercised by
    `three_insens_chars_expand_to_charclass` / `all_insens_adjacent_both_cases`.
    """
    def edit(workspace: Path) -> None:
        _replace_once(
            _coalescer_path(workspace),
            "if c.is_ascii_alphabetic() {",
            "if false {",
        )

    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=lambda w: _apply_reference_then(w, edit),
        run_seed=f"{NAME}-mutant-insens",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_partial_run_threshold_lowered_mutant_fails(tmp_path, baseline):
    """Gate 3, targeted mutant 3: coalesce partial runs of two, not just three+.

    Targets "contiguous runs of three or more qualifying alternatives are
    coalesced" -- upstream axis exercised by `partial_run_of_two_not_coalesced`.
    """
    def edit(workspace: Path) -> None:
        _replace_once(
            _coalescer_path(workspace),
            "if *run_count >= 3 {",
            "if *run_count >= 2 {",
        )

    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=lambda w: _apply_reference_then(w, edit),
        run_seed=f"{NAME}-mutant-partial-threshold",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


# ---------------------------------------------------------------------------
# Gate 4: forged / malformed observations are rejected by the Oracle directly.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def oracle_module():
    return load_module(
        HIDDEN / NAME / "oracle" / "oracle.py", "pest_coalescing_oracle_under_test"
    )


def _first_case(oracle_module):
    oracle = oracle_module.PestCoalescingOracle()
    oracle.initialize({})
    case = oracle.next_case()
    assert case["type"] == "case"
    return oracle, case


def _observed_evidence(observation: dict) -> dict:
    return {"status": "observed", "observation": observation}


def _base_observation(oracle_module, case) -> dict:
    """A correctly-shaped, fully-correct observation for the given case."""
    expected = case["case_context"]["expected"]
    results = []
    for scenario_id, rules in expected.items():
        results.append({
            "id": scenario_id,
            "status": "ok",
            "optimized_json": json.dumps(rules),
            "error": "",
        })
    return {
        "build_exit_code": 0,
        "build_stderr": "",
        "driver_exit_code": 0,
        "driver_stderr": "",
        "results": results,
    }


def test_oracle_accepts_a_genuinely_correct_observation(oracle_module):
    oracle, case = _first_case(oracle_module)
    observation = _base_observation(oracle_module, case)
    oracle.evaluate(case["case_context"], _observed_evidence(observation))
    assert not oracle.failures, oracle.failures


def test_oracle_rejects_wrong_optimized_tree(oracle_module):
    oracle, case = _first_case(oracle_module)
    observation = _base_observation(oracle_module, case)
    # Forge a plausible-looking but wrong tree for the first scenario: claim
    # nothing coalesced at all (as if the candidate never ran the new pass).
    first = observation["results"][0]
    forged_rules = json.loads(first["optimized_json"])
    forged_rules[0]["expr"] = {"k": "ident", "v": "definitely-not-the-real-tree"}
    first["optimized_json"] = json.dumps(forged_rules)

    oracle.evaluate(case["case_context"], _observed_evidence(observation))
    assert oracle.failures, "forged optimized tree must be rejected"


def test_oracle_rejects_malformed_json_payload(oracle_module):
    oracle, case = _first_case(oracle_module)
    observation = _base_observation(oracle_module, case)
    observation["results"][0]["optimized_json"] = "{not valid json"

    oracle.evaluate(case["case_context"], _observed_evidence(observation))
    assert oracle.failures, "malformed optimized_json must be rejected"


def test_oracle_rejects_structurally_invalid_expr_tree(oracle_module):
    oracle, case = _first_case(oracle_module)
    observation = _base_observation(oracle_module, case)
    # Well-formed JSON, but an expr object carrying an unknown/extra field, or
    # an unsupported "kind" -- a schema-valid-looking but adversarial shape.
    observation["results"][0]["optimized_json"] = json.dumps([
        {"name": "rule", "expr": {"k": "str", "v": "a", "extra_field": "smuggled"}}
    ])

    oracle.evaluate(case["case_context"], _observed_evidence(observation))
    assert oracle.failures, "an expr tree with unexpected fields must be rejected"


def test_oracle_rejects_missing_scenario_ids(oracle_module):
    oracle, case = _first_case(oracle_module)
    observation = _base_observation(oracle_module, case)
    observation["results"] = observation["results"][:-1]

    oracle.evaluate(case["case_context"], _observed_evidence(observation))
    assert oracle.failures, "dropping a scenario result must be rejected"


def test_oracle_rejects_duplicate_scenario_ids(oracle_module):
    oracle, case = _first_case(oracle_module)
    observation = _base_observation(oracle_module, case)
    observation["results"].append(dict(observation["results"][0]))

    oracle.evaluate(case["case_context"], _observed_evidence(observation))
    assert oracle.failures, "duplicated scenario ids must be rejected"


def test_oracle_rejects_non_observed_status(oracle_module):
    oracle, case = _first_case(oracle_module)
    oracle.evaluate(case["case_context"], {"status": "candidate_error", "observation": None})
    assert oracle.failures, "a non-observed evidence status must be rejected"


def test_oracle_rejects_nonzero_build_exit_code(oracle_module):
    oracle, case = _first_case(oracle_module)
    observation = _base_observation(oracle_module, case)
    observation["build_exit_code"] = 1

    oracle.evaluate(case["case_context"], _observed_evidence(observation))
    assert oracle.failures, "a failed build must be rejected even with plausible results"


def test_oracle_finalize_fails_without_evaluating_every_case(oracle_module):
    oracle = oracle_module.PestCoalescingOracle()
    oracle.initialize({})
    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is False
