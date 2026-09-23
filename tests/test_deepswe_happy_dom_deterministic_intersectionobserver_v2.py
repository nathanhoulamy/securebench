"""Real-capture Docker qualification for
``deep-swe/happy-dom-deterministic-intersectionobserver``.

The Oracle drives a bounded, assertion-free scenario (root/rootMargin/
threshold configuration, target elements with overridable bounding
rectangles, and an ordered action sequence -- observe/unobserve/set_rect/
disconnect/take_records/wait) through the Evaluation's adapter, which runs
the candidate's own patched IntersectionObserver via the pinned project's
offline vitest toolchain (a small scenario test file copied into the
project's own ``test/`` tree). The Oracle compares the candidate's actual
constructor outcome, normalized public properties, per-action outcomes, and
delivered callback batches against geometry it derives independently
(``geometry.py``) from the public instruction -- never from
``tests/test.patch`` or ``solution.patch``. Every check observes callback
*order*, *batch membership*, and *computed values* deterministically; no
Oracle decision depends on wall-clock timing (bounded settle windows are used
only as an execution technique to capture "no further delivery happened",
exactly as upstream's own hidden test does with its own grace-period waits).
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


NAME = "happy-dom-deterministic-intersectionobserver"
HIDDEN = Path(__file__).resolve().parents[1] / "benchmarks/deep-swe/v2/hidden" / NAME
ORACLE_MODULE = load_module(HIDDEN / "oracle" / "oracle.py", "happy_dom_intersection_observer_oracle")


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
    return "test" in lowered.split("/")[-1] or "/test/" in lowered


def test_preflights_and_keeps_reference_and_oracle_host_only():
    task = deep_task(NAME)
    validate_executable_task(task)

    assert task.family == "repo_patch"
    assert task.input["repo"] == "capricorn86/happy-dom"
    assert task.input["base_commit"] == "82a0888cb2c87a6123e05424b528f8e8c9b3e426"
    assert task.environment.agent_network.mode == "none"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
        assert "oracle.py" not in view
    assert f"adapters/{NAME}" not in str(task.view_for("agent"))
    assert f"adapters/{NAME}" in str(task.view_for("evaluation_runtime"))


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

    ``IntersectionObserver.ts`` is both the largest diff and the class every
    other new utility module is wired into; excluding its hunk alone reverts
    the public class back to the base commit's no-op stub while still
    shipping the (now-unused) utility modules -- a plausible "wired the
    modules, forgot to update the entry point" near miss.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "packages/happy-dom/src/intersection-observer/IntersectionObserver.ts"
    kept = "".join(diff for path, diff in diffs if path != dropped)

    def apply_partial(workspace: Path) -> None:
        subprocess.run(
            ["git", "-C", str(workspace), "apply", "--whitespace=nowarn", "-"],
            input=kept.encode(), check=True,
        )

    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=apply_partial, run_seed=f"{NAME}-partial-{Path(dropped).name}",
    )
    assert outcome.status == "failed", (dropped, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence


def _mutate_file(relative_path: str, old: str, new: str, *, count: int = 1):
    def mutate(workspace: Path) -> None:
        path = workspace / relative_path
        text = path.read_text()
        assert text.count(old) == count, (relative_path, old, text.count(old))
        path.write_text(text.replace(old, new))

    return mutate


OBSERVER_PATH = "packages/happy-dom/src/intersection-observer/IntersectionObserver.ts"
GEOMETRY_PATH = "packages/happy-dom/src/intersection-observer/utilities/IntersectionObserverGeometryUtility.ts"
MARGIN_PARSER_PATH = "packages/happy-dom/src/intersection-observer/utilities/IntersectionObserverRootMarginParser.ts"


SEMANTIC_MUTANTS = {
    # Axis: asynchronous delivery (instruction #2) -- evaluates and delivers
    # synchronously inside #queueEvaluation instead of scheduling a timer.
    "synchronous-delivery": _mutate_file(
        OBSERVER_PATH,
        "\t\tthis.#isDeliveryScheduled = true;\n"
        "\t\tthis.#deliveryTimer = this.#window.setTimeout(() => {\n"
        "\t\t\tthis.#deliveryTimer = null;\n"
        "\t\t\tthis.#isDeliveryScheduled = false;\n"
        "\t\t\tthis.#evaluateTargets();\n"
        "\t\t\tthis.#deliverRecords();\n"
        "\t\t});",
        "\t\tthis.#isDeliveryScheduled = true;\n"
        "\t\tthis.#deliveryTimer = null;\n"
        "\t\tthis.#isDeliveryScheduled = false;\n"
        "\t\tthis.#evaluateTargets();\n"
        "\t\tthis.#deliverRecords();",
    ),
    # Axis: entry order within a callback cycle (instruction #4) -- iterates
    # targets in reverse, so observe()-order is no longer preserved.
    "order-not-preserved": _mutate_file(
        OBSERVER_PATH,
        "\t\tfor (let i = 0, max = this.#targets.length; i < max; i++) {\n"
        "\t\t\tconst target = this.#targets[i];",
        "\t\tfor (let i = this.#targets.length - 1, max = this.#targets.length; i >= 0; i--) {\n"
        "\t\t\tconst target = this.#targets[i];",
    ),
    # Axis: threshold crossing (instruction #9) -- only detects upward
    # crossings, so a target whose ratio *decreases* through a threshold
    # never gets a new entry.
    "threshold-crossing-only-upward": _mutate_file(
        GEOMETRY_PATH,
        "if (crossedFromBelow || crossedFromAbove) {",
        "if (crossedFromBelow) {",
    ),
    # Axis: zero-area intersection ratio (instruction #10) -- drops the
    # zero-area special case, so a contained zero-area target gets ratio
    # NaN -> 0 instead of 1.
    "zero-area-special-case-dropped": _mutate_file(
        GEOMETRY_PATH,
        "\t\tconst targetArea = this.getArea(targetRect);\n"
        "\n"
        "\t\tif (targetArea <= 0) {\n"
        "\t\t\treturn isIntersecting ? 1 : 0;\n"
        "\t\t}\n"
        "\n"
        "\t\tconst intersectionArea",
        "\t\tconst targetArea = this.getArea(targetRect);\n"
        "\n"
        "\t\tconst intersectionArea",
    ),
    # Axis: unobserve() (instruction #11) -- becomes a no-op, so delivery
    # continues for a target after it is unobserved.
    "unobserve-is-noop": _mutate_file(
        OBSERVER_PATH,
        "\t\tthis.#targets.splice(index, 1);\n"
        "\t\tthis.#targetState.delete(target);\n"
        "\n"
        "\t\tif (!this.#targets.length) {\n"
        "\t\t\tthis.#stopPolling();\n"
        "\t\t}",
        "\t\tvoid index; // securebench mutant: unobserve() intentionally not implemented",
    ),
    # Axis: rootMargin CSS-shorthand expansion (instruction #6/#7) -- the
    # 3-value form's left margin echoes the top value instead of the
    # right/left value.
    "root-margin-3value-wrong-expansion": _mutate_file(
        MARGIN_PARSER_PATH,
        "case 3:\n"
        "\t\t\t\treturn [values[0], values[1], values[2], values[1]].map((value) => ({ ...value }));",
        "case 3:\n"
        "\t\t\t\treturn [values[0], values[1], values[2], values[0]].map((value) => ({ ...value }));",
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
    # At least one Evaluation genuinely drove the scenario and disagreed with
    # the Oracle (as opposed to every case erroring out at the harness level,
    # which would not demonstrate that the Oracle actually caught the
    # *semantic* defect).
    assert any(
        item.observation and item.observation.get("status") == "observed"
        for item in outcome.evidence
    )


# ---------------------------------------------------------------------------
# Gate 4: forged / malformed observations are rejected by the Oracle directly.
# ---------------------------------------------------------------------------


def _oracle_with_cases():
    oracle = ORACLE_MODULE.HappyDomIntersectionObserverOracle()
    oracle.initialize({"run_seed": "qualification"})
    return oracle


WINDOW_W, WINDOW_H = 1024, 768


def _root_rect_for(expect):
    from geometry import expand_rect, parse_root_margin, resolve_margin_px  # type: ignore

    if expect["root_mode"] == "viewport":
        base = {"x": 0, "y": 0, "width": WINDOW_W, "height": WINDOW_H}
    else:
        base = expect["root_rect"]
    margin = parse_root_margin(expect["margin_value"] or "0px")
    margin_px = resolve_margin_px(margin, base["width"], base["height"])
    return expand_rect(base, margin_px)


def _entry_for(target_id, rect_value, root_rect):
    from geometry import intersect  # type: ignore

    ratio, is_intersecting = intersect(rect_value, root_rect)
    return {
        "target_id": target_id, "is_intersecting": is_intersecting,
        "intersection_ratio": ratio,
        "root_bounds_width": root_rect["width"], "root_bounds_height": root_rect["height"],
    }


def _good_observation(case):
    expect = case["expect"]
    base_obs = {
        "status": "observed", "error": "",
        "constructor_threw": False, "constructor_error_name": "",
        "window_inner_width": WINDOW_W, "window_inner_height": WINDOW_H,
        "root_is_null": expect.get("root_is_null") if expect["kind"] == "constructor" else (
            case["challenge"]["root_mode"] != "element"
        ),
        "root_margin": "", "thresholds": [],
        "callback_count_before_first_wait": 0,
        "action_results": [], "batches": [], "take_records_results": [],
    }
    if expect["kind"] == "constructor":
        if expect["throws"]:
            base_obs["constructor_threw"] = True
            base_obs["constructor_error_name"] = "TypeError"
            return {"status": "observed", "observation": base_obs}
        base_obs["root_margin"] = expect["root_margin"]
        base_obs["thresholds"] = expect["thresholds"]
        return {"status": "observed", "observation": base_obs}

    base_obs["action_results"] = [
        {"threw": c["threw"], "error_name": "TypeError" if c["threw"] else ""}
        for c in expect["action_checks"]
    ]
    root_rect = _root_rect_for(expect)
    batches: list[list[dict]] = []
    for checkpoint in expect["checkpoints"]:
        if checkpoint["mode"] == "settle":
            continue
        target_count = checkpoint["target_count"]
        while len(batches) < target_count:
            batches.append([])
        entries = [_entry_for(r["target_id"], r["rect"], root_rect) for r in checkpoint["requires"]]
        if checkpoint["mode"] == "exact_batch":
            batches[checkpoint["prev_count"]] = entries
        else:
            batches[target_count - 1] = batches[target_count - 1] + entries
    base_obs["batches"] = batches
    base_obs["take_records_results"] = [
        [] if c["expect_empty"] else [_entry_for("x", {"x": 0, "y": 0, "width": 1, "height": 1}, root_rect)]
        for c in expect["take_records_checks"]
    ]
    return {"status": "observed", "observation": base_obs}


def test_challenges_contain_no_grading_directives_or_expectations():
    import json as _json

    oracle_a = _oracle_with_cases()
    oracle_b = ORACLE_MODULE.HappyDomIntersectionObserverOracle()
    oracle_b.initialize({"run_seed": "different-seed"})
    assert len(oracle_a.cases) == len(oracle_b.cases) == 26
    assert oracle_a.cases != oracle_b.cases  # geometry differs per run_seed
    for case in oracle_a.cases:
        challenge_text = _json.dumps(case["challenge"])
        assert "expect" not in challenge_text
        assert "threshold" not in _json.dumps(list(case["challenge"].keys())) or "threshold_values" in case["challenge"]
        assert len(challenge_text.encode()) < 8192


def test_oracle_accepts_the_well_formed_case_set():
    oracle = _oracle_with_cases()
    for case in oracle.cases:
        oracle.evaluate({"id": case["id"], "expect": case["expect"]}, _good_observation(case))
    assert oracle.failures == []
    assert oracle.verdict()["verdict"]["passed"] is True


def test_oracle_requires_every_case_and_rejects_repeats():
    oracle = _oracle_with_cases()
    assert not oracle.verdict()["verdict"]["passed"]
    for case in oracle.cases[:-1]:
        oracle.evaluate({"id": case["id"], "expect": case["expect"]}, _good_observation(case))
    assert not oracle.verdict()["verdict"]["passed"]
    last = oracle.cases[-1]
    oracle.evaluate({"id": last["id"], "expect": last["expect"]}, _good_observation(last))
    assert oracle.verdict()["verdict"]["passed"]
    oracle.evaluate({"id": last["id"], "expect": last["expect"]}, _good_observation(last))
    assert "repeated_case" in oracle.failures
    assert not oracle.verdict()["verdict"]["passed"]


@pytest.mark.parametrize("attack", [
    "wrong_ratio", "swapped_order", "extra_batch_after_settle", "missing_required_entry",
    "candidate_error_status", "claims_observed_but_wrong_shape", "non_bool_intersecting",
    "oversized_error_name", "top_level_candidate_error", "action_did_not_throw",
    "take_records_not_empty", "constructor_threw_unexpectedly",
])
def test_oracle_rejects_forged_or_malformed_observations(attack):
    oracle = _oracle_with_cases()

    if attack == "action_did_not_throw":
        case = next(c for c in oracle.cases if c["id"] == "observe-invalid-target-throws")
        evidence = _good_observation(case)
        evidence["observation"]["action_results"][0]["threw"] = False
        evidence["observation"]["action_results"][0]["error_name"] = ""
        oracle.evaluate({"id": case["id"], "expect": case["expect"]}, evidence)
        assert "action_threw_mismatch" in oracle.failures
        return

    if attack == "take_records_not_empty":
        case = next(c for c in oracle.cases if c["id"] == "take-records-empty-when-no-records-queued")
        evidence = _good_observation(case)
        root_rect = {"x": 0, "y": 0, "width": WINDOW_W, "height": WINDOW_H}
        evidence["observation"]["take_records_results"][0] = [
            _entry_for("x", {"x": 0, "y": 0, "width": 1, "height": 1}, root_rect)
        ]
        oracle.evaluate({"id": case["id"], "expect": case["expect"]}, evidence)
        assert "take_records_not_empty" in oracle.failures
        return

    if attack == "constructor_threw_unexpectedly":
        case = next(
            c for c in oracle.cases
            if c["expect"]["kind"] == "constructor" and not c["expect"]["throws"]
        )
        evidence = _good_observation(case)
        evidence["observation"]["constructor_threw"] = True
        oracle.evaluate({"id": case["id"], "expect": case["expect"]}, evidence)
        assert "constructor_threw_unexpectedly" in oracle.failures
        return

    # Scenario case with a two-entry membership checkpoint and a settle
    # checkpoint, so every remaining attack perturbs something observable.
    case = next(c for c in oracle.cases if c["id"] == "observe-multiple-threshold-crossings")
    evidence = _good_observation(case)
    obs = evidence["observation"]

    if attack == "wrong_ratio":
        obs["batches"][0][0]["intersection_ratio"] = 0.05
    elif attack == "swapped_order":
        order_case = next(c for c in oracle.cases if c["id"] == "observe-order-preserved-two-targets")
        evidence = _good_observation(order_case)
        evidence["observation"]["batches"][0] = list(reversed(evidence["observation"]["batches"][0]))
        oracle.evaluate({"id": order_case["id"], "expect": order_case["expect"]}, evidence)
        assert "order_mismatch" in oracle.failures
        return
    elif attack == "extra_batch_after_settle":
        settle_case = next(c for c in oracle.cases if c["id"] == "unobserve-stops-future-entries")
        evidence = _good_observation(settle_case)
        evidence["observation"]["batches"].append(evidence["observation"]["batches"][0])
        oracle.evaluate({"id": settle_case["id"], "expect": settle_case["expect"]}, evidence)
        assert "unexpected_extra_delivery" in oracle.failures
        return
    elif attack == "missing_required_entry":
        obs["batches"][0] = []
    elif attack == "candidate_error_status":
        evidence["observation"] = {
            "status": "error", "error": "boom", "constructor_threw": False,
            "constructor_error_name": "", "window_inner_width": 0, "window_inner_height": 0,
            "root_is_null": False, "root_margin": "", "thresholds": [],
            "callback_count_before_first_wait": 0, "action_results": obs["action_results"],
            "batches": [], "take_records_results": [],
        }
    elif attack == "claims_observed_but_wrong_shape":
        obs["batches"] = "not-a-list"
    elif attack == "non_bool_intersecting":
        obs["batches"][0][0]["is_intersecting"] = "true"
    elif attack == "oversized_error_name":
        obs["constructor_error_name"] = "x" * 5000
    elif attack == "top_level_candidate_error":
        evidence["status"] = "candidate_error"

    try:
        oracle.evaluate({"id": case["id"], "expect": case["expect"]}, evidence)
    except (TypeError, AttributeError):
        # A malformed observation shape that would itself crash a naive
        # Oracle is also an acceptable rejection outcome for this attack, as
        # long as the case is not silently accepted -- the adapter's own
        # schema validation is the primary defence against exactly this
        # class of forgery, and is exercised at the Docker layer.
        oracle.failures.append("malformed_observation")

    assert oracle.failures, attack
    assert not oracle.verdict()["verdict"]["passed"]


def test_oracle_rejects_forged_window_size_with_consistent_intersection():
    """Regression test for the split-verification review finding: the Oracle
    must never derive its expected viewport rectangle from the candidate's
    own reported ``window_inner_width``/``window_inner_height`` (candidate
    observations are untrusted; AGENTS.md).

    This attack is stronger than ``wrong_ratio`` above: the candidate does
    not just report a wrong number, it reports a *self-consistent* forged
    world -- a manipulated window size together with intersection results
    that are exactly what a genuine implementation would compute for that
    fake size. Before the fix, an adversarial candidate could inflate
    ``window_inner_width``/``window_inner_height`` and make the
    far-away-viewport case (which exists specifically to catch a fake
    "always intersecting" observer) report a fabricated intersection,
    because the Oracle used to build its expected root rectangle from that
    same candidate-reported size. The fix pins the expected root rectangle
    to Happy DOM's documented default viewport (1024x768) and checks the
    reported size only as a separate, non-expectation-feeding assertion.
    """
    from geometry import intersect  # type: ignore

    oracle = _oracle_with_cases()
    case = next(c for c in oracle.cases if c["id"] == "observe-initial-delivery-viewport-outside")
    assert case["challenge"]["root_mode"] == "viewport"
    target = case["challenge"]["targets"][0]
    evidence = _good_observation(case)
    obs = evidence["observation"]

    # Sanity: against the real default viewport, this target does not
    # intersect at all (it is why this case exists).
    real_root = {"x": 0, "y": 0, "width": WINDOW_W, "height": WINDOW_H}
    real_ratio, real_intersecting = intersect(target["rect"], real_root)
    assert real_intersecting is False and real_ratio == 0.0

    # Forge a wildly inflated viewport that happens to contain the target,
    # and report intersection fields that are internally consistent with
    # that fake viewport -- not just a wrong number, a coherent fake world.
    fake_w, fake_h = 2_000_000, 2_000_000
    fake_root = {"x": 0, "y": 0, "width": fake_w, "height": fake_h}
    fake_ratio, fake_intersecting = intersect(target["rect"], fake_root)
    assert fake_intersecting is True and fake_ratio == 1.0  # genuinely consistent w/ the lie

    obs["window_inner_width"] = fake_w
    obs["window_inner_height"] = fake_h
    obs["batches"][0][0] = {
        "target_id": target["id"],
        "is_intersecting": fake_intersecting,
        "intersection_ratio": fake_ratio,
        "root_bounds_width": fake_w,
        "root_bounds_height": fake_h,
    }

    oracle.evaluate({"id": case["id"], "expect": case["expect"]}, evidence)

    # Caught two ways: the separate window-size assertion, and -- even if
    # that assertion were absent -- the geometry check itself, because the
    # expected root rectangle is pinned to the real default and never seeded
    # from the candidate's own reported (fake) size.
    assert "window_size_mismatch" in oracle.failures
    assert "wrong_entry_values" in oracle.failures
    assert not oracle.verdict()["verdict"]["passed"]
