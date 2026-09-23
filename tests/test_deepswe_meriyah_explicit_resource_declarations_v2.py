"""Real-capture Docker qualification for
``deep-swe/meriyah-explicit-resource-declarations``.

The second TypeScript DeepSWE conversion (after ``ink-grid-box-layout``), and
the first that exercises a compiler/parser Candidate. The Oracle drives a
bounded, assertion-free parse adapter (candidate's own patched
``src/parser.ts``, executed via the project's own offline ``vite-node``
transform -- the same Vite/esbuild pipeline Vitest itself uses, since this
image does not ship ``tsx``) through 55 declarative source-snippet challenges:
one per upstream F2P assertion (49 nodes, each on its own exact source text --
basic/await `using` declarations, for-of/for-await-of placement, initializer
expression kinds, script/module/async scope rules, the stated error-priority
rule, every required error substring, and destructuring rejection) plus a
handful of P2P regression cases guarding the newline/`next`-sensitive
identifier fallback, and one P2P case for the one non-F2P for-await-of error
assertion `test.patch` also carries.
The Oracle compares the candidate's actual AST/error output against fields it
derives itself from the public instruction and `test.patch`'s semantics --
never the whole AST, and never copied from the hidden test file.
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


NAME = "meriyah-explicit-resource-declarations"
HIDDEN = Path(__file__).resolve().parents[1] / "benchmarks/deep-swe/v2/hidden" / NAME
ORACLE_MODULE = load_module(HIDDEN / "oracle" / "oracle.py", "meriyah_using_oracle")


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
    assert task.input["repo"] == "meriyah/meriyah"
    assert task.input["base_commit"] == "d141eb14a40b79c04d1b1db5c20c6afa3844c0d9"
    assert task.environment.agent_network.mode == "none"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
        assert "oracle.py" not in view
    assert "adapters/meriyah-explicit-resource-declarations" not in str(task.view_for("agent"))
    assert "adapters/meriyah-explicit-resource-declarations" in str(task.view_for("evaluation_runtime"))


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


# The upstream gold patch also updates a hidden Vitest snapshot file -- the
# instruction itself notes that the pre-existing `using foo = null` snapshot
# changes once `using` becomes a keyword. That path is excluded from the v2
# Candidate (it lives under `test/**`, matches `exclude_paths`, and plays no
# role in this conversion's Oracle-driven verification), so it must be
# reverted to the baseline content before capture -- exactly as excluding it
# always would for an Agent-drawn patch.
EXCLUDED_REFERENCE_PATHS = ("test/parser/miscellaneous/__snapshots__/commonjs.ts.snap",)


def _revert_excluded_reference_paths(workspace: Path) -> None:
    subprocess.run(
        ["git", "-C", str(workspace), "checkout", "HEAD", "--", *EXCLUDED_REFERENCE_PATHS],
        check=True,
    )


@DOCKER_INTEGRATION
def test_reference_passes_in_fresh_evaluations(tmp_path, baseline):
    """Gate 2: the upstream gold solution passes, >=2 fresh Evaluations."""
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True,
        mutate=_revert_excluded_reference_paths, run_seed=f"{NAME}-reference",
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
    """Gate 3 (generic): drop the biggest non-test file of the gold patch.

    ``src/parser.ts`` carries the entire declaration/for-statement parsing
    change; ``token.ts``/``common.ts``/``errors.ts``/``estree.ts`` still add
    the ``using`` keyword token, binding-kind flags, error strings, and the
    AST type, so this is a plausible almost-there submission (wired the
    supporting pieces, forgot to actually hook up the parser).
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "src/parser.ts"
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


def _mutate_parser(old: str, new: str, *, count: int = 1):
    def mutate(workspace: Path) -> None:
        _revert_excluded_reference_paths(workspace)
        path = workspace / "src/parser.ts"
        text = path.read_text()
        assert text.count(old) == count, (old, text.count(old))
        path.write_text(text.replace(old, new))

    return mutate


SEMANTIC_MUTANTS = {
    # Axis: AST `kind` label assignment -- swaps 'using' and 'await using' in
    # the shared node-building helper, so every declaration reports the
    # wrong ESTree `kind` string.
    "kind-label-swap": _mutate_parser(
        "  return kind === BindingKind.AwaitUsing ? 'await using' : 'using';",
        "  return kind === BindingKind.AwaitUsing ? 'using' : 'await using';",
    ),
    # Axis: error priority -- `await using` at script top level (and in a
    # sync function) must report the async-context error, not the
    # script-global-scope error. This mutant reports the wrong one.
    "await-using-error-priority": _mutate_parser(
        "      if (checkUsingBindingStart(parser)) {\n"
        "        if (!isAsyncOrModule) {\n"
        "          parser.report(Errors.AwaitUsingNotInAsync);\n"
        "        }",
        "      if (checkUsingBindingStart(parser)) {\n"
        "        if (!isAsyncOrModule) {\n"
        "          parser.report(Errors.UsingInScriptGlobal);\n"
        "        }",
    ),
    # Axis: newline sensitivity -- a UsingDeclaration requires no
    # LineTerminator between `using` and the binding identifier; this drops
    # that guard so `using` is (wrongly) still treated as a declaration
    # keyword across a line break.
    "newline-sensitivity-dropped": _mutate_parser(
        "  return (\n"
        "    (parser.getToken() & Token.IsIdentifier) !== 0 &&\n"
        "    (parser.flags & Flags.NewLine) === 0\n"
        "  );\n"
        "}",
        "  return (parser.getToken() & Token.IsIdentifier) !== 0;\n}",
    ),
    # Axis: for-of/for-await-of placement -- `using`/`await using` heads are
    # never recognised in a for-statement, so every for-of/for-await-of case
    # falls back to ordinary for-of parsing (or a parse error).
    "for-of-using-disabled": _mutate_parser(
        "  if (!parser.options.next) return null;",
        "  return null;",
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
    # At least one Evaluation genuinely parsed/errored (as opposed to every
    # case erroring out on infrastructure grounds, which would not
    # demonstrate that the Oracle actually caught the *semantic* defect).
    assert any(
        item.observation and item.observation.get("status") in ("parsed", "error")
        for item in outcome.evidence
    )


# ---------------------------------------------------------------------------
# Gate 4: forged / malformed observations are rejected by the Oracle directly.
# ---------------------------------------------------------------------------


def _oracle_with_cases():
    oracle = ORACLE_MODULE.MeriyahUsingOracle()
    oracle.initialize({"run_seed": "qualification"})
    return oracle


def _good_observation(case, gold_by_id):
    result = gold_by_id[case["id"]]
    if result["status"] == "parsed":
        observation = {"status": "parsed", "ast_json": json.dumps(result["ast"]), "error_message": ""}
    else:
        observation = {"status": "error", "ast_json": "", "error_message": result["error_message"]}
    return {"status": "observed", "observation": observation}


@pytest.fixture(scope="module")
def gold_by_id():
    """Host-side (no Docker) gold parse results, used only to build evidence
    shapes for direct Oracle unit tests. Computed once via the pinned
    upstream repository is out of scope for a non-Docker test, so this
    fixture instead re-derives the exact same AST/error text the qualified
    Docker gates already proved the reference Candidate produces, by
    constructing it from the same field checks each case asserts -- i.e. it
    builds the minimal AST/error shape each case's own checks require, which
    is sufficient to unit test Oracle-side forgery/malformation handling
    without re-parsing JavaScript on the host.
    """
    import importlib.util

    sys.path.insert(0, str(HIDDEN / "oracle"))
    try:
        module = ORACLE_MODULE
        cases = module.build_cases()
    finally:
        sys.path.pop(0)

    def build_minimal(case):
        expect = case["expect"]
        if expect["mode"] == "error":
            return {"status": "error", "error_message": expect["contains"][0]}
        ast: dict = {}

        def set_path(root, path, value):
            node = root
            for step, nxt in zip(path, path[1:] + (None,)):
                if nxt is None:
                    if isinstance(step, int):
                        while len(node) <= step:
                            node.append({})
                        node[step] = value
                    else:
                        node[step] = value
                    return
                if isinstance(nxt, int):
                    default = []
                else:
                    default = {}
                if isinstance(step, int):
                    while len(node) <= step:
                        node.append(default if not isinstance(default, dict) else {})
                    if not isinstance(node[step], (dict, list)):
                        node[step] = default
                    node = node[step]
                else:
                    if step not in node or not isinstance(node[step], (dict, list)):
                        node[step] = default
                    node = node[step]

        for path, expected in expect["checks"]:
            if isinstance(expected, dict):
                # Structural predicates (e.g. "is a 2-element list") can't be
                # inverted into a concrete value; the malformed/forged-attack
                # tests below don't rely on these particular cases.
                continue
            set_path(ast, path, expected)
        return {"status": "parsed", "ast": ast}

    return {case["id"]: build_minimal(case) for case in cases}


def test_challenges_contain_no_grading_directives_or_expectations():
    oracle_a = _oracle_with_cases()
    oracle_b = ORACLE_MODULE.MeriyahUsingOracle()
    oracle_b.initialize({"run_seed": "different-seed"})
    assert len(oracle_a.cases) == len(oracle_b.cases) == 55
    for case in oracle_a.cases:
        assert set(case["challenge"]) == {"source", "module", "next"}
        challenge_text = str(case["challenge"])
        assert "expect" not in challenge_text
        assert len(json.dumps(case["challenge"]).encode()) < 8192


def test_oracle_accepts_the_well_formed_case_set(gold_by_id):
    oracle = _oracle_with_cases()
    for case in oracle.cases:
        if any(isinstance(expected, dict) for _, expected in case["expect"].get("checks", ())):
            continue
        oracle.evaluate({"id": case["id"], "expect": case["expect"]}, _good_observation(case, gold_by_id))
    # Only cases without a callable predicate were exercised above; check
    # those all matched cleanly (structural-predicate cases are covered by
    # the real Docker gates instead, which use the genuine candidate AST).
    assert oracle.failures == []


def test_oracle_requires_every_case_and_rejects_repeats(gold_by_id):
    oracle = _oracle_with_cases()
    assert not oracle.verdict()["verdict"]["passed"]
    simple_cases = [
        case for case in oracle.cases
        if not any(isinstance(expected, dict) for _, expected in case["expect"].get("checks", ()))
    ]
    for case in simple_cases[:-1]:
        oracle.evaluate({"id": case["id"], "expect": case["expect"]}, _good_observation(case, gold_by_id))
    assert not oracle.verdict()["verdict"]["passed"]


@pytest.mark.parametrize("attack", [
    "wrong_kind", "wrong_name", "status_mismatch_parsed_claims_error",
    "status_mismatch_error_claims_parsed", "candidate_error_status",
    "claims_observed_but_wrong_shape", "non_string_ast_json",
    "oversized_ast_json", "malformed_ast_json", "top_level_candidate_error",
    "wrong_error_substring", "error_priority_violation",
])
def test_oracle_rejects_forged_or_malformed_observations(attack, gold_by_id):
    oracle = _oracle_with_cases()
    parsed_case = next(
        c for c in oracle.cases
        if c["expect"]["mode"] == "parsed"
        and not any(isinstance(expected, dict) for _, expected in c["expect"]["checks"])
    )
    priority_case = next(c for c in oracle.cases if c["id"] == "err-await-using-script-top")
    named_case = next(c for c in oracle.cases if c["id"] == "using-forof-script-top")

    case = parsed_case
    evidence = _good_observation(case, gold_by_id)

    if attack == "wrong_kind":
        ast = json.loads(evidence["observation"]["ast_json"])
        path, expected = next(
            (p, e) for p, e in case["expect"]["checks"] if isinstance(e, str) and e in ("using", "await using")
        )
        node = ast
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = "await using" if expected == "using" else "using"
        evidence["observation"]["ast_json"] = json.dumps(ast)
    elif attack == "wrong_name":
        case = named_case
        evidence = _good_observation(case, gold_by_id)
        ast = json.loads(evidence["observation"]["ast_json"])
        path, expected = next(
            (p, e) for p, e in case["expect"]["checks"] if isinstance(e, str) and p[-1] == "name"
        )
        node = ast
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = expected + "_forged"
        evidence["observation"]["ast_json"] = json.dumps(ast)
    elif attack == "status_mismatch_parsed_claims_error":
        evidence["observation"] = {"status": "error", "ast_json": "", "error_message": "forged"}
    elif attack == "status_mismatch_error_claims_parsed":
        evidence = _good_observation(priority_case, gold_by_id)
        evidence["observation"] = {"status": "parsed", "ast_json": "{}", "error_message": ""}
        case = priority_case
    elif attack == "candidate_error_status":
        evidence["observation"] = {"status": "error", "ast_json": "", "error_message": "boom"}
    elif attack == "claims_observed_but_wrong_shape":
        evidence["observation"] = {"status": "parsed", "ast_json": 12345, "error_message": ""}
    elif attack == "non_string_ast_json":
        evidence["observation"]["ast_json"] = None
    elif attack == "oversized_ast_json":
        evidence["observation"]["ast_json"] = evidence["observation"]["ast_json"][:-1] + ("x" * 20000) + "}"
    elif attack == "malformed_ast_json":
        evidence["observation"]["ast_json"] = "{not valid json"
    elif attack == "top_level_candidate_error":
        evidence["status"] = "candidate_error"
    elif attack == "wrong_error_substring":
        case = priority_case
        evidence = _good_observation(case, gold_by_id)
        evidence["observation"]["error_message"] = "completely unrelated message"
    elif attack == "error_priority_violation":
        case = priority_case
        evidence = _good_observation(case, gold_by_id)
        evidence["observation"]["error_message"] = (
            "'using' declarations are not allowed in the global scope of scripts "
            "and only allowed inside async functions and modules"
        )

    oracle.evaluate({"id": case["id"], "expect": case["expect"]}, evidence)
    assert oracle.failures, attack
    assert not oracle.verdict()["verdict"]["passed"]
