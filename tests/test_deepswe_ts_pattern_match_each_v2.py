"""Real-capture Docker qualification for
``deep-swe/ts-pattern-match-each``.

The third TypeScript DeepSWE conversion (after ``ink-grid-box-layout`` and
``meriyah-explicit-resource-declarations``), and the first that carries a
genuine semantic-change disposition: the pinned upstream suite mixes Jest
runtime assertions with compile-time ``@ts-expect-error``/``Expect<Equal<...>>``
type assertions inside the same test file, executed by the same candidate
process. Split verification separates these into two challenge kinds that
share one protocol/adapter:

* ``runtime`` cases interpret a bounded declarative
  pattern/clause/guard/result program (built from the public instruction's
  described semantics) through a Jest test file copied into the pinned
  project's own ``tests/`` tree, run via the project's own offline
  ``npx jest <path> --no-coverage`` -- exactly how ``tests/test.sh`` invokes
  the hidden suite -- because this image ships ``jest``/``ts-jest`` but
  neither ``tsx`` nor ``vite-node`` (playbook defect #17).
* ``type`` cases compile one bounded, hand-authored TypeScript probe module
  against the candidate's patched ``src`` with the project's own
  ``tsc --strict --noEmit`` (its own ``check`` script), reusing the pinned
  suite's own ``Equal``/``Expect``/``@ts-expect-error`` mechanism so the
  Oracle's expectation reduces to "compiles with zero diagnostics" -- the
  semantic content lives entirely in which assertions the Oracle embeds in
  the probe source, never in the adapter.

The Oracle computes every runtime expectation with its own independent
Python reference implementation of the matching semantics (never copied from
``test.patch``, never derived by running the gold patch).
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


NAME = "ts-pattern-match-each"
HIDDEN = Path(__file__).resolve().parents[1] / "benchmarks/deep-swe/v2/hidden" / NAME
ORACLE_MODULE = load_module(HIDDEN / "oracle" / "oracle.py", "ts_pattern_match_each_oracle")


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
    assert task.input["repo"] == "gvergnaud/ts-pattern"
    assert task.input["base_commit"] == "f66fc061fde4f764b113ededa09be63dae564159"
    assert task.environment.agent_network.mode == "none"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
        assert "oracle.py" not in view
    assert "adapters/ts-pattern-match-each" not in str(task.view_for("agent"))
    assert "adapters/ts-pattern-match-each" in str(task.view_for("evaluation_runtime"))


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

    ``src/types/Match.ts`` (the new ``MatchEach`` type definitions, the
    single largest hunk in the gold patch) is dropped; ``src/match-each.ts``,
    ``src/internals/helpers.ts``, ``src/match.ts`` and ``src/index.ts`` are
    kept, so the runtime implementation still imports a now-missing
    ``MatchEach`` type -- a plausible almost-there submission (wired the
    runtime mechanism, forgot to actually ship its public types).
    """
    diffs = _file_diffs(reference_patch(NAME).read_text())
    assert diffs
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "src/types/Match.ts"
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


def _mutate_file(relpath: str, old: str, new: str, *, count: int = 1):
    def mutate(workspace: Path) -> None:
        path = workspace / relpath
        text = path.read_text()
        assert text.count(old) == count, (relpath, old, text.count(old))
        path.write_text(text.replace(old, new))

    return mutate


SEMANTIC_MUTANTS = {
    # Axis (runtime): matchEach must NOT short-circuit -- this mutant
    # reintroduces exactly that, breaking the entire premise of the feature.
    "reintroduces-short-circuit": _mutate_file(
        "src/internals/helpers.ts",
        "    const result = evaluateClause(clause, input);\n"
        "    if (result.matched) {\n"
        "      results.push(result.value);\n"
        "    }\n"
        "  }\n"
        "  return results;\n"
        "};",
        "    const result = evaluateClause(clause, input);\n"
        "    if (result.matched) {\n"
        "      results.push(result.value);\n"
        "      break;\n"
        "    }\n"
        "  }\n"
        "  return results;\n"
        "};",
    ),
    # Axis (runtime): .tap() must call its callback once per result
    # collected so far, in declaration order -- this mutant drops tap
    # entirely (a plausible near-miss: wired the clause kind, forgot the
    # callback invocation).
    "tap-dropped": _mutate_file(
        "src/internals/helpers.ts",
        "    if (clause.kind === 'tap') {\n"
        "      for (const result of results) {\n"
        "        clause.callback(result);\n"
        "      }\n"
        "      continue;\n"
        "    }",
        "    if (clause.kind === 'tap') {\n"
        "      continue;\n"
        "    }",
    ),
    # Axis (runtime): .otherwise() must NOT include the default handler's
    # result when at least one clause matched -- this mutant always appends
    # it.
    "otherwise-always-includes-default": _mutate_file(
        "src/match-each.ts",
        "  otherwise(handler: (value: input) => output): output[] {\n"
        "    const results = this.execute();\n"
        "    if (results.length === 0) {\n"
        "      return [handler(this.input)];\n"
        "    }\n"
        "    return results;\n"
        "  }",
        "  otherwise(handler: (value: input) => output): output[] {\n"
        "    const results = this.execute();\n"
        "    return [...results, handler(this.input)];\n"
        "  }",
    ),
    # Axis (type-level only): .exhaustive()'s compile-time exhaustiveness
    # constraint is dropped -- runtime behavior (throwing NonExhaustiveError)
    # is completely unaffected, so only the type protocol's cases can catch
    # this. Demonstrates the type-level distinction the runtime-only
    # protocol cannot observe is genuinely still enforced here.
    "exhaustiveness-type-constraint-dropped": _mutate_file(
        "src/types/Match.ts",
        "  exhaustive: DeepExcludeAll<i, handledCases> extends infer remainingCases\n"
        "    ? [remainingCases] extends [never]\n"
        "      ? ExhaustiveEach<o, inferredOutput>\n"
        "      : NonExhaustiveError<remainingCases>\n"
        "    : never;",
        "  exhaustive: ExhaustiveEach<o, inferredOutput>;",
    ),
    # Axis (type-level only): the `.returnType()`-only-directly-after-
    # `matchEach(...)` restriction is dropped -- again invisible at runtime.
    "returntype-guard-dropped": _mutate_file(
        "src/types/Match.ts",
        "  returnType: [inferredOutput] extends [never]\n"
        "    ? <output>() => MatchEach<i, output, handledCases, never, fullInput>\n"
        "    : TSPatternError<'calling `.returnType<T>()` is only allowed directly after `matchEach(...)`.'>;",
        "  returnType: <output>() => MatchEach<i, output, handledCases, never, fullInput>;",
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
    # At least one Evaluation genuinely ran (as opposed to every case
    # erroring out on infrastructure grounds, which would not demonstrate
    # that the Oracle actually caught the *semantic* defect). The
    # observation is a bounded JSON-encoded string envelope
    # (`{"observation_json": "..."}`), so decode it to reach its own
    # `status` field.
    def _observed(item) -> bool:
        if not item.observation:
            return False
        raw = item.observation.get("observation_json")
        if not isinstance(raw, str):
            return False
        try:
            return json.loads(raw).get("status") == "observed"
        except (ValueError, TypeError):
            return False

    assert any(_observed(item) for item in outcome.evidence)


# ---------------------------------------------------------------------------
# Gate 4: forged / malformed observations are rejected by the Oracle directly.
# ---------------------------------------------------------------------------


def _oracle_with_cases():
    oracle = ORACLE_MODULE.MatchEachOracle()
    oracle.initialize({"run_seed": "qualification"})
    return oracle


def _good_evidence(case):
    if case["kind"] == "runtime":
        expect = case["expect"]
        if expect["mode"] == "direct":
            observation = {
                "case_kind": "runtime", "status": "observed", "error": "",
                "mode": "direct", "threw": expect["threw"], "error_name": expect["error_name"],
                "results": [] if expect["threw"] else expect["results"],
                "call_trace": expect["call_trace"], "tap_traces": expect["tap_traces"],
                "calls": [], "compiled_ok": False, "diagnostics": [],
            }
        else:
            observation = {
                "case_kind": "runtime", "status": "observed", "error": "",
                "mode": "compiled", "threw": False, "error_name": "",
                "results": [], "call_trace": [], "tap_traces": [],
                "calls": expect["calls"], "compiled_ok": False, "diagnostics": [],
            }
    else:
        expected_lines = case["expect"]["expected_lines"]
        observation = {
            "case_kind": "type", "status": "observed", "error": "",
            "mode": "", "threw": False, "error_name": "",
            "results": [], "call_trace": [], "tap_traces": [], "calls": [],
            "compiled_ok": not expected_lines,
            "diagnostics": [{"code": "TS2349", "line": line} for line in expected_lines],
        }
    return {"status": "observed", "observation": {"observation_json": json.dumps(observation)}}


def _find_case(cases, case_id):
    return next(c for c in cases if c["id"] == case_id)


def test_challenges_contain_no_grading_directives_or_expectations():
    oracle = _oracle_with_cases()
    assert len(oracle.cases) == 47
    assert sum(1 for c in oracle.cases if c["kind"] == "runtime") == 38
    assert sum(1 for c in oracle.cases if c["kind"] == "type") == 9
    for case in oracle.cases:
        assert set(case["challenge"]) == {"program_json"}
        challenge_text = case["challenge"]["program_json"]
        assert '"expect"' not in challenge_text
        assert len(challenge_text.encode()) < 4096
        # Type-case probes must be assertion-free: the expected answer and
        # the grading directive must never cross into the Evaluation
        # environment (AGENTS.md). A negative property's probe carries the
        # plain offending code with no `@ts-expect-error` suppressing it,
        # and a positive property is expressed as ordinary usage rather
        # than a named `Equal<>` identity check.
        assert "Expect<" not in challenge_text
        assert "Equal<" not in challenge_text
        assert "@ts-expect-error" not in challenge_text


def test_oracle_accepts_the_well_formed_case_set():
    oracle = _oracle_with_cases()
    for case in oracle.cases:
        oracle.evaluate(
            {"id": case["id"], "kind": case["kind"], "expect": case["expect"]},
            _good_evidence(case),
        )
    assert oracle.failures == []
    assert oracle.verdict()["verdict"]["passed"]


def test_oracle_requires_every_case_and_rejects_repeats():
    oracle = _oracle_with_cases()
    assert not oracle.verdict()["verdict"]["passed"]
    for case in oracle.cases[:-1]:
        oracle.evaluate(
            {"id": case["id"], "kind": case["kind"], "expect": case["expect"]},
            _good_evidence(case),
        )
    assert not oracle.verdict()["verdict"]["passed"]

    oracle_b = _oracle_with_cases()
    first = oracle_b.cases[0]
    good = _good_evidence(first)
    ctx = {"id": first["id"], "kind": first["kind"], "expect": first["expect"]}
    oracle_b.evaluate(ctx, good)
    oracle_b.evaluate(ctx, good)
    assert "repeated_case" in oracle_b.failures
    assert not oracle_b.verdict()["verdict"]["passed"]


@pytest.mark.parametrize("attack", [
    "results_reordered", "results_tampered", "threw_flag_flipped",
    "wrong_error_name", "call_trace_tampered", "tap_trace_tampered",
    "compiled_call_status_flipped", "compiled_call_count_short",
    "type_compiled_ok_forged_true", "type_diagnostic_wrong_line",
    "type_extra_diagnostic_beyond_expected", "type_compiled_ok_forged_false_on_positive_case",
    "top_level_candidate_error", "malformed_observation_json",
    "wrong_key_set", "oversized_observation_json",
])
def test_oracle_rejects_forged_or_malformed_observations(attack):
    oracle = _oracle_with_cases()
    direct_case = _find_case(oracle.cases, "declaration-order")
    compiled_case = _find_case(oracle.cases, "compiled-to-function-guards-and-independent-selections")
    tap_case = _find_case(oracle.cases, "tap-multiple-points")
    type_case = _find_case(oracle.cases, "type-exhaustive-missing-case-is-error")
    type_positive_case = _find_case(oracle.cases, "type-with-accepts-original-input-type")

    case = direct_case
    evidence = _good_evidence(case)
    observation = json.loads(evidence["observation"]["observation_json"])

    if attack == "results_reordered":
        observation["results"] = list(reversed(observation["results"]))
    elif attack == "results_tampered":
        observation["results"] = observation["results"][:-1] + ["forged"]
    elif attack == "threw_flag_flipped":
        observation["threw"] = True
        observation["error_name"] = "NonExhaustiveError"
    elif attack == "wrong_error_name":
        case = _find_case(oracle.cases, "run-throws-nonexhaustive")
        evidence = _good_evidence(case)
        observation = json.loads(evidence["observation"]["observation_json"])
        observation["error_name"] = "Error"
    elif attack == "call_trace_tampered":
        observation["call_trace"] = observation["call_trace"][:1]
    elif attack == "tap_trace_tampered":
        case = tap_case
        evidence = _good_evidence(case)
        observation = json.loads(evidence["observation"]["observation_json"])
        observation["tap_traces"][0]["values"] = ["forged"]
    elif attack == "compiled_call_status_flipped":
        case = compiled_case
        evidence = _good_evidence(case)
        observation = json.loads(evidence["observation"]["observation_json"])
        observation["calls"][0]["status"] = "threw"
    elif attack == "compiled_call_count_short":
        case = compiled_case
        evidence = _good_evidence(case)
        observation = json.loads(evidence["observation"]["observation_json"])
        observation["calls"] = observation["calls"][:-1]
    elif attack == "type_compiled_ok_forged_true":
        # The real, correct diagnostic (at the one line this Oracle knows
        # must fail) is present, but `compiled_ok` is forged to claim the
        # probe compiled cleanly anyway.
        case = type_case
        evidence = _good_evidence(case)
        observation = json.loads(evidence["observation"]["observation_json"])
        observation["compiled_ok"] = True
    elif attack == "type_diagnostic_wrong_line":
        # A diagnostic is reported, but on a line other than the one this
        # Oracle knows must fail -- not the same defect being demonstrated.
        case = type_case
        evidence = _good_evidence(case)
        observation = json.loads(evidence["observation"]["observation_json"])
        observation["diagnostics"] = [{"code": "TS2349", "line": 3}]
    elif attack == "type_extra_diagnostic_beyond_expected":
        # The correct diagnostic is present, plus a spurious extra one on an
        # unrelated line -- violates "no diagnostic anywhere else".
        case = type_case
        evidence = _good_evidence(case)
        observation = json.loads(evidence["observation"]["observation_json"])
        observation["diagnostics"].append({"code": "TS2345", "line": 2})
    elif attack == "type_compiled_ok_forged_false_on_positive_case":
        # A clean-compile-expected positive probe: diagnostics correctly
        # empty, but `compiled_ok` forged to claim it failed.
        case = type_positive_case
        evidence = _good_evidence(case)
        observation = json.loads(evidence["observation"]["observation_json"])
        observation["compiled_ok"] = False
    elif attack == "top_level_candidate_error":
        evidence["status"] = "candidate_error"
    elif attack == "malformed_observation_json":
        evidence["observation"]["observation_json"] = "{not valid json"
    elif attack == "wrong_key_set":
        del observation["diagnostics"]
    elif attack == "oversized_observation_json":
        evidence["observation"]["observation_json"] = evidence["observation"]["observation_json"][:-1] + ("x" * 20000) + "}"

    if attack not in ("top_level_candidate_error", "malformed_observation_json", "oversized_observation_json"):
        evidence["observation"]["observation_json"] = json.dumps(observation)

    oracle.evaluate({"id": case["id"], "kind": case["kind"], "expect": case["expect"]}, evidence)
    assert oracle.failures, attack
    assert not oracle.verdict()["verdict"]["passed"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
