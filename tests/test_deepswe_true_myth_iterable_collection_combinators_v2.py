"""Real-capture Docker qualification for
``deep-swe/true-myth-iterable-collection-combinators``.

A TypeScript library-combinators conversion (closest precedent:
``ts-pattern-match-each``): the pinned hidden suite (``test/extras.test.ts``,
``test/traversal.test.ts``) is pure Vitest runtime behavior -- no
compile-time ``@ts-expect-error``/``Expect<Equal<...>>`` type assertions
anywhere in ``tests/test.patch`` -- so this conversion needs only one
challenge kind.

One bounded declarative "program" (an operation name plus typed
`Maybe`/`Result`/`Task` specs, built entirely by the Oracle) is interpreted
by ``driver.test.ts``, copied into the pinned project's own ``test/`` tree
(picked up by Vitest's own default ``include`` glob) and run via the
project's own offline ``npx vitest run --coverage=false
--typecheck.enabled=false <path>`` -- the closest offline equivalent of how
``tests/test.sh`` invokes the hidden suite (``npx vitest run ...``) --
because this image ships ``vitest`` (preinstalled in ``node_modules/.bin``)
but neither ``jest`` nor ``tsx``/``vite-node`` without an on-the-fly `npx`
download, which the no-network Evaluation cannot do (playbook defect #17).

The Oracle computes every expectation with its own independent Python
reference implementation of the semantics described in the public
instruction (never copied from ``test.patch``, never derived by running the
gold patch).
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


NAME = "true-myth-iterable-collection-combinators"
HIDDEN = Path(__file__).resolve().parents[1] / "benchmarks/deep-swe/v2/hidden" / NAME
ORACLE_MODULE = load_module(HIDDEN / "oracle" / "oracle.py", "true_myth_iterable_collection_combinators_oracle")


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
    assert task.input["repo"] == "true-myth/true-myth"
    assert task.input["base_commit"] == "d8fbebc75de4991a32354518beff1abf628d0b07"
    assert task.environment.agent_network.mode == "none"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
        assert "oracle.py" not in view
    assert "adapters/true-myth-iterable-collection-combinators" not in str(task.view_for("agent"))
    assert "adapters/true-myth-iterable-collection-combinators" in str(task.view_for("evaluation_runtime"))


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

    ``src/task.ts`` (the ``Task`` async-iterator, ``sequence``, ``traverse``,
    ``traverseSerial``, ``tap``, ``tapRejected``, ``retryN``, ``zip`` and
    ``zipWith`` additions -- the single largest hunk in the gold patch, 193
    added lines) is dropped; ``src/maybe.ts``, ``src/result.ts`` and
    ``src/toolbelt.ts`` are kept, so every `Maybe`/`Result`/toolbelt
    combinator is present and correct but the entire `Task` surface the
    instruction asks for is simply missing -- a plausible almost-there
    submission (did most of the work, ran out of time on `Task`).
    """
    diffs = _file_diffs(reference_patch(NAME).read_text())
    assert diffs
    dropped, _ = max(diffs, key=lambda pair: pair[1].count("\n+"))
    assert dropped == "src/task.ts"
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
    # Axis: maybe.sequence must short-circuit to Nothing on the first
    # failure -- this mutant instead silently drops Nothings and keeps
    # going, turning sequence into compact (a plausible mix-up between the
    # two "drop vs. fail on Nothing" combinators the instruction adds side
    # by side). Caught by maybe-sequence-short-circuit-generator (wrong tag,
    # wrong advance_count) and every other maybe.sequence/result.sequence
    # failure case (result.ts has the identical pattern, untouched, so this
    # mutant alone does not touch result -- the maybe-only case still
    # discriminates it).
    "sequence-does-not-short-circuit": _mutate_file(
        "src/maybe.ts",
        "  for (const m of maybes) {\n"
        "    if (m.isNothing) return nothing();\n"
        "    values.push(m.value);\n"
        "  }\n"
        "  return just(values);\n"
        "}\n"
        "\n"
        "export function traverse<T, U extends {}>(\n"
        "  fn: (t: T) => Maybe<U>\n"
        "): (arr: ReadonlyArray<T>) => Maybe<U[]>;",
        "  for (const m of maybes) {\n"
        "    if (m.isNothing) continue;\n"
        "    values.push(m.value);\n"
        "  }\n"
        "  return just(values);\n"
        "}\n"
        "\n"
        "export function traverse<T, U extends {}>(\n"
        "  fn: (t: T) => Maybe<U>\n"
        "): (arr: ReadonlyArray<T>) => Maybe<U[]>;",
    ),
    # Axis: task.sequence must assign each resolved value at its own
    # original index, not in whatever order the underlying tasks happen to
    # settle in -- this mutant pushes in completion order instead. Only
    # observable under genuinely out-of-order settlement, which
    # task-sequence-all-resolved-scrambled-order drives explicitly.
    "task-sequence-pushes-in-completion-order": _mutate_file(
        "src/task.ts",
        "        Resolved: (value) => {\n"
        "          if (hasRejected) return;\n"
        "          values[idx] = value;\n"
        "          numResolved += 1;\n"
        "          if (numResolved === total) {\n"
        "            resolve(values as unknown as T[]);\n"
        "          }\n"
        "        },",
        "        Resolved: (value) => {\n"
        "          if (hasRejected) return;\n"
        "          values.push(value);\n"
        "          numResolved += 1;\n"
        "          if (numResolved === total) {\n"
        "            resolve(values as unknown as T[]);\n"
        "          }\n"
        "        },",
    ),
    # Axis: task.retryN must retry up to N additional times on rejection --
    # this mutant gives up after the very first rejection regardless of N (a
    # plausible off-by-everything near-miss: wired the `.orElse()` retry
    # hook but dropped the remaining-attempts check entirely). Caught by
    # both the "succeeds after retries" and "exhausts all retries" cases
    # (wrong final tag/payload and wrong attempt count).
    "retryn-never-retries": _mutate_file(
        "src/task.ts",
        "  const attempt = (remaining: number): Task<T, E> =>\n"
        "    fn().orElse((reason) =>\n"
        "      remaining > 0 ? attempt(remaining - 1) : Task.reject(reason)\n"
        "    );\n"
        "  return attempt(n);",
        "  const attempt = (remaining: number): Task<T, E> =>\n"
        "    fn().orElse((reason) => Task.reject(reason));\n"
        "  return attempt(n);",
    ),
    # Axis: task.traverseSerial must process items one at a time, calling
    # the mapping function for a later item only after the earlier one has
    # settled, and must stop calling it at all once one has rejected --
    # this mutant instead reuses the eager parallel `sequence(a.map(f))`
    # implementation (i.e. confuses traverseSerial with traverse). Only
    # task-traverseserial-stops-on-first-rejection's call_trace check
    # catches this: parallel-traverse's own tests still pass identically.
    "traverseserial-runs-in-parallel": _mutate_file(
        "src/task.ts",
        "  const run = (a: ReadonlyArray<T>, f: (t: T) => Task<U, E>): Task<U[], E> => {\n"
        "    return new Task((resolve, reject) => {\n"
        "      const values: U[] = [];\n"
        "      let idx = 0;\n"
        "\n"
        "      const step = () => {\n"
        "        if (idx >= a.length) {\n"
        "          resolve(values as unknown as U[]);\n"
        "          return;\n"
        "        }\n"
        "        const item = a[idx++]!;\n"
        "        f(item).match({\n"
        "          Resolved: (value) => {\n"
        "            values.push(value);\n"
        "            step();\n"
        "          },\n"
        "          Rejected: (reason) => {\n"
        "            reject(reason as E);\n"
        "          },\n"
        "        });\n"
        "      };\n"
        "\n"
        "      step();\n"
        "    }) as unknown as Task<U[], E>;\n"
        "  };",
        "  const run = (a: ReadonlyArray<T>, f: (t: T) => Task<U, E>): Task<U[], E> => sequence(a.map(f));",
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

    assert any(_observed(item) for item in outcome.evidence)


# ---------------------------------------------------------------------------
# Gate 4: forged / malformed observations are rejected by the Oracle directly.
# ---------------------------------------------------------------------------


def _oracle_with_cases():
    oracle = ORACLE_MODULE.IterableCombinatorsOracle()
    oracle.initialize({"run_seed": "qualification"})
    return oracle


def _good_result(case):
    result = dict(case["expect"])
    if case["op"] == "traverse" and "call_trace" not in result:
        # Parallel task.traverse's invocation order is not asserted, but
        # the driver's envelope always carries the field.
        result["call_trace"] = []
    if case["op"] == "toolbelt_traverse":
        result["call_trace"] = []
    return result


def _good_evidence(case):
    observation = {"op": case["op"], "status": "observed", "error": "", "result": _good_result(case)}
    return {"status": "observed", "observation": {"observation_json": json.dumps(observation)}}


def _find_case(cases, case_id):
    return next(c for c in cases if c["id"] == case_id)


def test_challenges_contain_no_grading_directives_or_expectations():
    oracle = _oracle_with_cases()
    assert len(oracle.cases) == 49
    for case in oracle.cases:
        assert set(case["challenge"]) == {"program_json"}
        challenge_text = case["challenge"]["program_json"]
        assert '"expect"' not in challenge_text
        assert len(challenge_text.encode()) < 1024
        # No grading directive or expected-answer marker of any kind
        # crosses into the Evaluation environment (AGENTS.md).
        assert "Expect<" not in challenge_text
        assert "Equal<" not in challenge_text
        assert "@ts-expect-error" not in challenge_text


def test_oracle_accepts_the_well_formed_case_set():
    oracle = _oracle_with_cases()
    for case in oracle.cases:
        oracle.evaluate(
            {"id": case["id"], "op": case["op"], "expect": case["expect"]},
            _good_evidence(case),
        )
    assert oracle.failures == []
    assert oracle.verdict()["verdict"]["passed"]


def test_oracle_requires_every_case_and_rejects_repeats():
    oracle = _oracle_with_cases()
    assert not oracle.verdict()["verdict"]["passed"]
    for case in oracle.cases[:-1]:
        oracle.evaluate(
            {"id": case["id"], "op": case["op"], "expect": case["expect"]},
            _good_evidence(case),
        )
    assert not oracle.verdict()["verdict"]["passed"]

    oracle_b = _oracle_with_cases()
    first = oracle_b.cases[0]
    good = _good_evidence(first)
    ctx = {"id": first["id"], "op": first["op"], "expect": first["expect"]}
    oracle_b.evaluate(ctx, good)
    oracle_b.evaluate(ctx, good)
    assert "repeated_case" in oracle_b.failures
    assert not oracle_b.verdict()["verdict"]["passed"]


@pytest.mark.parametrize("attack", [
    "tag_flipped", "payload_tampered", "advance_count_tampered",
    "call_trace_tampered", "call_trace_reordered", "attempts_tampered",
    "trace_tampered", "oks_errs_swapped", "extra_field_injected",
    "missing_field", "wrong_op_claimed", "top_level_candidate_error",
    "malformed_observation_json", "oversized_observation_json",
])
def test_oracle_rejects_forged_or_malformed_observations(attack):
    oracle = _oracle_with_cases()
    seq_case = _find_case(oracle.cases, "maybe-sequence-short-circuit-generator")
    traverse_case = _find_case(oracle.cases, "result-traverse-short-circuit")
    retry_case = _find_case(oracle.cases, "task-retryn-succeeds-after-retries")
    tap_case = _find_case(oracle.cases, "task-tap-resolved-calls-and-passes-through")
    partition_case = _find_case(oracle.cases, "result-partition-mixed")

    case = seq_case
    result = _good_result(case)

    if attack == "tag_flipped":
        result["tag"] = "Just"
    elif attack == "payload_tampered":
        case = traverse_case
        result = _good_result(case)
        result["payload"] = "forged"
    elif attack == "advance_count_tampered":
        result["advance_count"] = 1
    elif attack == "call_trace_tampered":
        case = traverse_case
        result = _good_result(case)
        result["call_trace"] = result["call_trace"][:1]
    elif attack == "call_trace_reordered":
        case = traverse_case
        result = _good_result(case)
        result["call_trace"] = list(reversed(result["call_trace"]))
    elif attack == "attempts_tampered":
        case = retry_case
        result = _good_result(case)
        result["attempts"] = 1
    elif attack == "trace_tampered":
        case = tap_case
        result = _good_result(case)
        result["trace"] = []
    elif attack == "oks_errs_swapped":
        case = partition_case
        result = _good_result(case)
        result["oks"], result["errs"] = result["errs"], result["oks"]
    elif attack == "extra_field_injected":
        result["bogus"] = 1
    elif attack == "missing_field":
        del result["advance_count"]
    elif attack == "wrong_op_claimed":
        observation = {"op": "compact", "status": "observed", "error": "", "result": result}
        oracle.evaluate(
            {"id": case["id"], "op": case["op"], "expect": case["expect"]},
            {"status": "observed", "observation": {"observation_json": json.dumps(observation)}},
        )
        assert oracle.failures, attack
        assert not oracle.verdict()["verdict"]["passed"]
        return

    observation = {"op": case["op"], "status": "observed", "error": "", "result": result}
    evidence = {"status": "observed", "observation": {"observation_json": json.dumps(observation)}}

    if attack == "top_level_candidate_error":
        evidence["status"] = "candidate_error"
    elif attack == "malformed_observation_json":
        evidence["observation"]["observation_json"] = "{not valid json"
    elif attack == "oversized_observation_json":
        evidence["observation"]["observation_json"] = (
            evidence["observation"]["observation_json"][:-1] + ("x" * 20000) + "}"
        )

    oracle.evaluate({"id": case["id"], "op": case["op"], "expect": case["expect"]}, evidence)
    assert oracle.failures, attack
    assert not oracle.verdict()["verdict"]["passed"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
