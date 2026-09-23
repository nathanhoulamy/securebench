"""Real-capture Docker qualification for ``deep-swe/ink-grid-box-layout``.

The first TypeScript DeepSWE conversion. The Oracle drives a bounded,
assertion-free Ink renderer (candidate's own patched ``src``, executed via the
project's own offline ``tsx`` toolchain) through 25 declarative grid/flex
challenges shaped after every upstream F2P semantic axis, and compares the
candidate's actual rendered terminal cells against positions the Oracle
derives itself from the track-sizing rules in the public instruction -- never
from ``tests/test.patch``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from tests.deepswe_qualification import (
    deep_task,
    materialize_baseline,
    reference_patch,
    verify_patch,
)
from tests.qualification_support import DOCKER_INTEGRATION, load_module


NAME = "ink-grid-box-layout"
HIDDEN = Path(__file__).resolve().parents[1] / "benchmarks/deep-swe/v2/hidden" / NAME
ORACLE_MODULE = load_module(HIDDEN / "oracle" / "oracle.py", "ink_grid_oracle")


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
    return "test" in lowered.split("/")[-1] or lowered.startswith("test/")


def test_preflights_and_keeps_reference_and_oracle_host_only():
    task = deep_task(NAME)
    validate_executable_task(task)

    assert task.family == "repo_patch"
    assert task.input["repo"] == "vadimdemedes/ink"
    assert task.input["base_commit"] == "0cea59169ef0f3f83e4aa7fbedbff9d165646472"
    assert task.environment.agent_network.mode == "none"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
        assert "oracle.py" not in view
    assert "adapters/ink-grid-box-layout" not in str(task.view_for("agent"))
    assert "adapters/ink-grid-box-layout" in str(task.view_for("evaluation_runtime"))


def test_reference_patch_is_the_pinned_upstream_solution():
    import hashlib
    import json

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
    """Gate 2: the upstream gold solution passes, >=2 fresh Evaluations."""
    outcome = verify_patch(NAME, baseline, tmp_path, reference=True, run_seed=f"{NAME}-reference")
    assert outcome.status == "passed", (
        outcome.result,
        [item.observation for item in outcome.evidence if item.observation],
    )
    assert not outcome.infrastructure_errors, outcome.evidence
    assert len(outcome.evidence) >= 2
    assert len(set(outcome.evaluation_ids)) == len(outcome.evaluation_ids)
    assert all(item.status == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
def test_dropping_the_largest_source_file_fails(tmp_path, baseline):
    """Gate 3 (generic): drop the biggest non-test file of the gold patch.

    ``src/grid-layout.ts`` is the whole track-sizing/placement implementation;
    ``renderer.ts`` still imports it, so removing it alone is a plausible
    almost-there submission (wired the call sites, forgot the module).
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "src/grid-layout.ts"
    kept = "".join(diff for path, diff in diffs if path != dropped)

    def apply_partial(workspace: Path) -> None:
        subprocess.run(
            ["git", "-C", str(workspace), "apply", "--whitespace=nowarn", "-"],
            input=kept.encode(), check=True,
        )

    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=apply_partial, run_seed=f"{NAME}-partial-{dropped}",
    )
    assert outcome.status == "failed", (dropped, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence


def _mutate_grid_layout(old: str, new: str, *, count: int = 1):
    def mutate(workspace: Path) -> None:
        path = workspace / "src/grid-layout.ts"
        text = path.read_text()
        assert text.count(old) == count, (old, text.count(old))
        path.write_text(text.replace(old, new))

    return mutate


SEMANTIC_MUTANTS = {
    # Axis: fr-track proportional distribution (equal and weighted fr, and the
    # fr side of minmax) -- rounds growth up instead of down.
    "fr-rounding": _mutate_grid_layout(
        "Math.floor((remaining * track.value) / frTotal)",
        "Math.ceil((remaining * track.value) / frTotal)",
    ),
    # Axis: minmax() with a fixed maximum -- drops the cap so a minmax track
    # consumes all remaining space instead of stopping at its declared max.
    "minmax-fixed-cap-dropped": _mutate_grid_layout(
        "const cap = Math.min(track.max.value, track.min + remaining);\n"
        "\t            sizes[i] = Math.max(track.min, cap);",
        "sizes[i] = track.min + remaining;",
    ),
    # Axis: auto-placement occupied-cell skipping -- explicit placements no
    # longer block auto-placed siblings from landing on the same cell.
    "auto-placement-ignores-occupied-cells": _mutate_grid_layout(
        "if (autoCol < numCols && grid[autoRow] && !grid[autoRow]![autoCol]) {",
        "if (autoCol < numCols) {",
    ),
    # Axis: "start / end" span parsing -- off-by-one widens every span by one
    # extra track.
    "span-off-by-one": _mutate_grid_layout(
        "return { start, span: Math.max(1, end - start) };",
        "return { start, span: Math.max(1, end - start + 1) };",
    ),
    # Axis: row gap application -- columnGap/gap still apply to columns, but
    # rowGap (and the gap shorthand on the row axis) is silently dropped.
    "row-gap-dropped": _mutate_grid_layout(
        "const rowGap = style.rowGap ?? style.gap ?? 0;",
        "const rowGap = 0;",
    ),
}


@DOCKER_INTEGRATION
@pytest.mark.parametrize("mutant", sorted(SEMANTIC_MUTANTS))
def test_semantic_mutants_fail(tmp_path, baseline, mutant):
    """Gate 3: each mutant is a plausible near-miss on a distinct semantic axis."""
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True,
        mutate=SEMANTIC_MUTANTS[mutant], run_seed=f"{NAME}-mutant-{mutant}",
    )
    assert outcome.status == "failed", (mutant, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence
    # At least one Evaluation genuinely rendered and disagreed with the Oracle
    # (as opposed to every case erroring out, which would not demonstrate that
    # the Oracle actually caught the *semantic* defect).
    assert any(
        item.observation and item.observation.get("status") == "observed"
        for item in outcome.evidence
    )


# ---------------------------------------------------------------------------
# Gate 4: forged / malformed observations are rejected by the Oracle directly.
# ---------------------------------------------------------------------------


def _oracle_with_cases():
    oracle = ORACLE_MODULE.InkGridOracle()
    oracle.initialize({"run_seed": "qualification"})
    return oracle


def _good_observation(case):
    total = case["expected"]["total_lines"]
    by_line: dict[int, list] = {}
    for marker in case["expected"]["markers"]:
        by_line.setdefault(marker["line"], []).append(marker)
    lines = []
    for index in range(total):
        line = ""
        for marker in sorted(by_line.get(index, []), key=lambda item: item["col"]):
            line = line.ljust(marker["col"]) + marker["text"]
        lines.append(line)
    return {"status": "observed", "observation": {"status": "observed", "error": "", "lines": lines}}


def test_challenges_contain_no_grading_directives_or_expectations():
    oracle_a = _oracle_with_cases()
    oracle_b = ORACLE_MODULE.InkGridOracle()
    oracle_b.initialize({"run_seed": "different-seed"})
    assert len(oracle_a.cases) == len(oracle_b.cases) == 25
    assert oracle_a.cases != oracle_b.cases  # text markers differ per run_seed
    for case in oracle_a.cases:
        assert set(case["challenge"]) == {"columns", "root"}
        challenge_text = str(case["challenge"])
        assert "expected" not in challenge_text
        import json as _json
        assert len(_json.dumps(case["challenge"]).encode()) < 8192


def test_oracle_accepts_the_well_formed_case_set():
    oracle = _oracle_with_cases()
    for case in oracle.cases:
        oracle.evaluate({"id": case["id"], "expected": case["expected"]}, _good_observation(case))
    assert oracle.failures == []
    assert oracle.verdict()["verdict"]["passed"] is True


def test_oracle_requires_every_case_and_rejects_repeats():
    oracle = _oracle_with_cases()
    assert not oracle.verdict()["verdict"]["passed"]
    for case in oracle.cases[:-1]:
        oracle.evaluate({"id": case["id"], "expected": case["expected"]}, _good_observation(case))
    assert not oracle.verdict()["verdict"]["passed"]
    last = oracle.cases[-1]
    oracle.evaluate({"id": last["id"], "expected": last["expected"]}, _good_observation(last))
    assert oracle.verdict()["verdict"]["passed"]
    oracle.evaluate({"id": last["id"], "expected": last["expected"]}, _good_observation(last))
    assert "repeated_case" in oracle.failures
    assert not oracle.verdict()["verdict"]["passed"]


@pytest.mark.parametrize("attack", [
    "wrong_column", "wrong_line", "missing_marker", "extra_lines", "missing_lines",
    "candidate_error_status", "claims_observed_but_wrong_shape", "non_string_line",
    "oversized_line", "boolean_line_count", "top_level_candidate_error",
])
def test_oracle_rejects_forged_or_malformed_observations(attack):
    oracle = _oracle_with_cases()
    # A case with >=2 lines and >=2 markers so every attack below (including
    # swapping two lines) actually perturbs something observable.
    case = next(c for c in oracle.cases if c["id"] == "auto-row-overflow")
    assert case["expected"]["total_lines"] >= 2 and len(case["expected"]["markers"]) >= 2
    evidence = _good_observation(case)
    lines = evidence["observation"]["lines"]

    if attack == "wrong_column":
        marker = case["expected"]["markers"][0]
        line = lines[marker["line"]]
        lines[marker["line"]] = " " + line
    elif attack == "wrong_line":
        marker = case["expected"]["markers"][0]
        other = (marker["line"] + 1) % len(lines)
        lines[marker["line"]], lines[other] = lines[other], lines[marker["line"]]
    elif attack == "missing_marker":
        marker = case["expected"]["markers"][0]
        lines[marker["line"]] = ""
    elif attack == "extra_lines":
        lines.append("")
    elif attack == "missing_lines":
        del lines[-1]
    elif attack == "candidate_error_status":
        evidence["observation"] = {"status": "error", "error": "boom", "lines": []}
    elif attack == "claims_observed_but_wrong_shape":
        evidence["observation"] = {"status": "observed", "error": "", "lines": "not-a-list"}
    elif attack == "non_string_line":
        lines[0] = 12345
    elif attack == "oversized_line":
        lines[0] = lines[0] + "x" * 5000
    elif attack == "boolean_line_count":
        evidence["observation"]["lines"] = True
    elif attack == "top_level_candidate_error":
        evidence["status"] = "candidate_error"

    oracle.evaluate({"id": case["id"], "expected": case["expected"]}, evidence)
    assert oracle.failures, attack
    assert not oracle.verdict()["verdict"]["passed"]
