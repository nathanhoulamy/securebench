"""Real-capture Docker qualification for
``deep-swe/csstree-shorthand-expansion-compression``.

A pure-JavaScript-library conversion: the public surface is two synchronous
``Lexer`` methods (``expandShorthand``/``compressShorthand``), no async
behaviour, no DOM, and no compile-time type assertions. The pinned image
ships plain ``node`` (v24) plus ``mocha``/``esbuild`` -- no ``tsx``,
``vite-node``, or ``jest`` -- but none of those are needed: ``driver.mjs``
is a bare ``node`` ESM script that imports the candidate's own
``/app/lib/index.js`` by absolute path and calls the two methods directly
(playbook defect #17: check what the image actually ships before reaching
for a framework it doesn't have).

The Oracle's case corpus (``build_cases()`` in ``oracle.py``) is transcribed
verbatim from the upstream regression suite's own literal fixtures
(``tests/test.patch``'s ``lib/__tests/shorthand.js``), never derived by
running the gold patch (playbook defect #9).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
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


NAME = "csstree-shorthand-expansion-compression"
HIDDEN = Path(__file__).resolve().parents[1] / "benchmarks/deep-swe/v2/hidden" / NAME
ORACLE_MODULE = load_module(HIDDEN / "oracle" / "oracle.py", "csstree_shorthand_expansion_compression_oracle")


def _file_diffs(patch_text: str) -> list[tuple[str, str]]:
    chunks = re.split(r"(?m)^(?=diff --git )", patch_text)
    pairs = []
    for chunk in chunks:
        match = re.match(r"diff --git a/(\S+) b/\S+", chunk)
        if match:
            pairs.append((match.group(1), chunk))
    return pairs


def test_preflights_and_keeps_reference_and_oracle_host_only():
    task = deep_task(NAME)
    validate_executable_task(task)

    assert task.family == "repo_patch"
    assert task.input["repo"] == "csstree/csstree"
    assert task.input["base_commit"] == "88e3d965c0b1628642a30a841745b410d6835052"
    assert task.environment.agent_network.mode == "none"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
        assert "oracle.py" not in view
    assert "adapters/csstree-shorthand-expansion-compression" not in str(task.view_for("agent"))
    assert "adapters/csstree-shorthand-expansion-compression" in str(task.view_for("evaluation_runtime"))


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
    """Gate 2: the upstream gold solution passes, >=2 fresh Evaluations."""
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, run_seed=f"{NAME}-reference",
    )
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
    """Gate 3 (generic): drop the biggest file of the gold patch.

    ``lib/lexer/shorthand.js`` (the ``expandShorthand``/``compressShorthand``
    implementations themselves, 393 added lines -- the single largest hunk
    in the gold patch) is dropped; ``lib/lexer/Lexer.js`` and
    ``lib/lexer/shorthand-config.js`` are kept, so ``Lexer.js`` imports a
    module that no longer exists -- a plausible almost-there submission
    (wired the config data and the public methods but never wrote the
    algorithm, or forgot to `git add` the file).
    """
    diffs = _file_diffs(reference_patch(NAME).read_text())
    assert diffs
    dropped, _ = max(diffs, key=lambda pair: pair[1].count("\n+"))
    assert dropped == "lib/lexer/shorthand.js"
    kept = "".join(diff for path, diff in diffs if path != dropped)

    def apply_partial(workspace: Path) -> None:
        subprocess.run(
            ["git", "-C", str(workspace), "apply", "--whitespace=nowarn", "-"],
            input=kept.encode(), check=True,
        )

    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=apply_partial, run_seed=f"{NAME}-partial-{dropped.replace('/', '-')}",
    )
    assert outcome.status == "failed", (dropped, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence


def _mutate_file(relpath: str, old: str, new: str, *, count: int = 1):
    def mutate(workspace: Path) -> None:
        path = workspace / relpath
        text = path.read_text()
        assert text.count(old) == count, (relpath, old, text.count(old))
        path.write_text(text.replace(old, new))

    return mutate


SEMANTIC_MUTANTS = {
    # Axis: box-model compression's 3-value branch must collapse to 3
    # values exactly when right === left (top differs from bottom) -- this
    # mutant instead gates that branch on `top === left`, a plausible
    # variable mix-up between two of the four box-model positions. Caught
    # by margin-compress-right-left-match-top-differs-bottom (falls through
    # to the 4-value branch and emits a spurious 4th value).
    "compress-box-model-wrong-3-value-condition": _mutate_file(
        "lib/lexer/shorthand.js",
        "    if (top === bottom && right === left) return top + ' ' + right;\n"
        "    if (right === left) return top + ' ' + right + ' ' + bottom;\n",
        "    if (top === bottom && right === left) return top + ' ' + right;\n"
        "    if (top === left) return top + ' ' + right + ' ' + bottom;\n",
    ),
    # Axis: background-color must apply only to the final comma-separated
    # layer, staying a single (non-joined) value -- this mutant instead
    # collects it for every layer and joins it like the other longhands, a
    # plausible mistake of applying the general per-layer-join rule to the
    # one longhand the spec singles out as an exception. Only observable
    # with more than one layer, which
    # background-expand-multi-layer-color-final drives explicitly (a
    # single-layer background is unaffected, since joining one element is a
    # no-op).
    "background-color-joined-across-layers": _mutate_file(
        "lib/lexer/shorthand.js",
        "        if (isFinal) {\n"
        "            const colorFrags = matchFragments(lexer, layerValue, layerMatch, 'Property', 'background-color');\n"
        "            if (colorFrags.length > 0) {\n"
        "                perLonghand['background-color'].push(generateFragment(colorFrags[0], gen));\n"
        "            } else {\n"
        "                perLonghand['background-color'].push(getInitial('background-color'));\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "\n"
        "    const result = {};\n"
        "    for (const lh of BACKGROUND_LONGHANDS) {\n"
        "        if (lh === 'background-color') {\n"
        "            result[lh] = perLonghand[lh][0];\n"
        "        } else {\n"
        "            result[lh] = perLonghand[lh].join(', ');\n"
        "        }\n"
        "    }\n",
        "        {\n"
        "            const colorFrags = matchFragments(lexer, layerValue, layerMatch, 'Property', 'background-color');\n"
        "            if (colorFrags.length > 0) {\n"
        "                perLonghand['background-color'].push(generateFragment(colorFrags[0], gen));\n"
        "            } else {\n"
        "                perLonghand['background-color'].push(getInitial('background-color'));\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "\n"
        "    const result = {};\n"
        "    for (const lh of BACKGROUND_LONGHANDS) {\n"
        "        result[lh] = perLonghand[lh].join(', ');\n"
        "    }\n",
    ),
    # Axis: the font shorthand's compression must join font-size and
    # line-height with `/` and no spaces, distinct from every other
    # longhand's plain space join -- this mutant drops the special case
    # entirely (a plausible copy-paste from the generic `compressComponent`
    # concatenation used for border-top/outline/etc., forgetting font's one
    # exception). Caught by font-compress and round-trip-font.
    "font-drops-slash-join": _mutate_file(
        "lib/lexer/shorthand.js",
        "    if (propertyName === 'font') {\n"
        "        const parts = [];\n"
        "        for (const lh of longhands) {\n"
        "            if (lh === 'line-height') {\n"
        "                parts[parts.length - 1] += '/' + longhandValues[lh];\n"
        "            } else {\n"
        "                parts.push(longhandValues[lh]);\n"
        "            }\n"
        "        }\n"
        "        return parts.join(' ');\n"
        "    }\n",
        "    if (propertyName === 'font') {\n"
        "        const parts = [];\n"
        "        for (const lh of longhands) {\n"
        "            parts.push(longhandValues[lh]);\n"
        "        }\n"
        "        return parts.join(' ');\n"
        "    }\n",
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

    def _observed(evidence_item) -> bool:
        if not evidence_item.observation:
            return False
        raw = evidence_item.observation.get("observation_json")
        if not isinstance(raw, str):
            return False
        try:
            return json.loads(raw).get("status") == "observed"
        except (ValueError, TypeError):
            return False

    # At least one Evaluation genuinely ran (as opposed to every case
    # erroring out on infrastructure grounds, which would not demonstrate
    # that the Oracle actually caught the *semantic* defect).
    assert any(_observed(item) for item in outcome.evidence)


# ---------------------------------------------------------------------------
# Gate 4: forged / malformed observations are rejected by the Oracle directly.
# ---------------------------------------------------------------------------


def _oracle_with_cases():
    oracle = ORACLE_MODULE.ShorthandOracle()
    oracle.initialize({"run_seed": "qualification"})
    return oracle


def _good_result(case):
    return {item_id: spec["value"] for item_id, spec in case["expect"].items()}


def _good_evidence(case):
    observation = {"op": "batch", "status": "observed", "error": "", "result": _good_result(case)}
    return {"status": "observed", "observation": {"observation_json": json.dumps(observation)}}


def _find_case(cases, case_id):
    return next(c for c in cases if c["id"] == case_id)


def _context(case):
    return {"id": case["id"], "op": case["op"], "expect": case["expect"]}


def test_challenges_contain_no_grading_directives_or_expectations():
    oracle = _oracle_with_cases()
    assert len(oracle.cases) == 18
    # Restores every one of the 79 upstream F2P assertions (playbook #20):
    # bundling several items into one batch Evaluation is a transport-level
    # grouping, never a dropped assertion.
    assert sum(len(case["expect"]) for case in oracle.cases) == 79
    for case in oracle.cases:
        assert set(case["challenge"]) == {"program_json"}
        challenge_text = case["challenge"]["program_json"]
        assert len(challenge_text.encode()) < 2048
        # No grading directive or expected-answer marker of any kind
        # crosses into the Evaluation environment (AGENTS.md): each item in
        # the batch carries only id/op/property/value/longhands/
        # fork_properties, never an "expect" field.
        assert '"expect"' not in challenge_text


def test_oracle_accepts_the_well_formed_case_set():
    oracle = _oracle_with_cases()
    for case in oracle.cases:
        oracle.evaluate(_context(case), _good_evidence(case))
    assert oracle.failures == []
    assert oracle.verdict()["verdict"]["passed"]


def test_oracle_requires_every_case_and_rejects_repeats():
    oracle = _oracle_with_cases()
    assert not oracle.verdict()["verdict"]["passed"]
    for case in oracle.cases[:-1]:
        oracle.evaluate(_context(case), _good_evidence(case))
    assert not oracle.verdict()["verdict"]["passed"]

    oracle_b = _oracle_with_cases()
    first = oracle_b.cases[0]
    good = _good_evidence(first)
    ctx = _context(first)
    oracle_b.evaluate(ctx, good)
    oracle_b.evaluate(ctx, good)
    assert "repeated_case" in oracle_b.failures
    assert not oracle_b.verdict()["verdict"]["passed"]


@pytest.mark.parametrize("attack", [
    "item_value_tampered", "item_extra_key_injected", "item_missing_key",
    "item_wrong_type_for_expand", "item_wrong_type_for_compress",
    "item_null_forged_for_non_null_case", "item_non_null_forged_for_null_case",
    "missing_item_id", "extra_item_id_injected",
    "top_level_candidate_error", "malformed_observation_json", "oversized_observation_json",
])
def test_oracle_rejects_forged_or_malformed_observations(attack):
    oracle = _oracle_with_cases()
    expand_case = _find_case(oracle.cases, "component-expand")
    compress_case = _find_case(oracle.cases, "component-compress")
    null_expand_case = _find_case(oracle.cases, "error-expand")

    case = expand_case
    result = _good_result(case)

    if attack == "item_value_tampered":
        result["border-top-full"] = dict(result["border-top-full"])
        result["border-top-full"]["border-top-color"] = "blue"
    elif attack == "item_extra_key_injected":
        result["border-top-full"] = dict(result["border-top-full"])
        result["border-top-full"]["bogus-longhand"] = "1px"
    elif attack == "item_missing_key":
        result["border-top-full"] = dict(result["border-top-full"])
        del result["border-top-full"]["border-top-color"]
    elif attack == "item_wrong_type_for_expand":
        result["border-top-full"] = "1px solid red"
    elif attack == "item_wrong_type_for_compress":
        case = compress_case
        result = _good_result(case)
        result["border-top"] = {"border-top-width": "1px"}
    elif attack == "item_null_forged_for_non_null_case":
        result["border-top-full"] = None
    elif attack == "item_non_null_forged_for_null_case":
        case = null_expand_case
        result = _good_result(case)
        result["non-shorthand-property"] = {"color": "red"}
    elif attack == "missing_item_id":
        del result[next(iter(result))]
    elif attack == "extra_item_id_injected":
        result["bogus-item-id"] = "anything"

    observation = {"op": "batch", "status": "observed", "error": "", "result": result}
    evidence = {"status": "observed", "observation": {"observation_json": json.dumps(observation)}}

    if attack == "top_level_candidate_error":
        evidence["status"] = "candidate_error"
    elif attack == "malformed_observation_json":
        evidence["observation"]["observation_json"] = "{not valid json"
    elif attack == "oversized_observation_json":
        evidence["observation"]["observation_json"] = (
            evidence["observation"]["observation_json"][:-1] + ("x" * 20000) + "}"
        )

    oracle.evaluate(_context(case), evidence)
    assert oracle.failures, attack
    assert not oracle.verdict()["verdict"]["passed"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
