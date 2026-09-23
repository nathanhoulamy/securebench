"""Real-capture Docker qualification for ``tengo-destructuring-bindings``.

Gate 1/2/3 replay the production path (see ``tests/deepswe_qualification.py``):
a workspace is cloned from the materialised pinned baseline, the upstream gold
solution (``qualification/reference.patch``) is optionally applied, targeted
source-level mutants are optionally layered on top, and the result is
captured as a real ``git_patch`` candidate and verified through fresh
Evaluation containers using the real Oracle process.

Gate 4 drives the Oracle directly with synthetic ``ChallengeEvidence`` (no
Docker involved) to prove it rejects forged and malformed candidate
observations, the same pattern used for the pilot rows in
``tests/test_pilot_conversions_v2.py`` and for
``tests/test_deepswe_etree_xml_diff_patch_v2.py``.
"""

from __future__ import annotations

import hashlib
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


NAME = "tengo-destructuring-bindings"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "tengo_destructuring_behavior"
BOUNDS = {"max_cases": 6, "max_case_bytes": 131072}


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
    """Gate 1: the unmodified base commit must not pass.

    Destructuring `:=` patterns do not parse at the base commit (`[a, b] :=
    ...` is not valid syntax before the gold patch), so every value/compile
    error/runtime error scenario the adapter's driver runs through
    `tengo.NewScript(...).Compile()` fails or diverges from the expected
    observation -- a legitimate "candidate incomplete" signal, not an
    infrastructure error.
    """
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
    """Gate 3 (generic): drop the largest non-test hunk of the gold patch.

    ``compiler.go`` carries the largest share of the gold solution (374 added
    lines): every ``Compile()``/``compileAssign`` case for ``*parser.
    ArrayPattern``/``*parser.MapPattern``, the whole pattern-compilation
    machinery (``compileArrayPatternElements``, ``compileMapPatternFields``,
    ``compileDestructuringAssign``, ...), and the function-parameter-pattern
    handling in the ``FuncLit`` case. Dropping only that hunk while keeping
    the parser/opcode/VM changes leaves the parser producing
    ``ArrayPattern``/``MapPattern`` AST nodes the compiler has no case for,
    so every destructuring scenario in the challenge suite diverges from its
    expected observation.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "compiler.go", dropped
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
def test_rest_must_be_last_check_direction_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: rest elements must be validated as *last*, not *first*
    (instruction.md: "Rest elements (`...name`) collect remaining array
    elements and must appear last in the pattern."). This mutant flips
    parser.go's placement check from "not the last element" to "not the
    first element" -- a plausible off-by-one on which position a rest
    check anchors to. It breaks both directions at once: a correctly
    trailing rest (``[first, ...rest]``) is wrongly rejected, and a rest
    that is genuinely misplaced but happens to sit first
    (``[...a, b]``) is wrongly accepted.
    """
    old = (
        "\tfor i, el := range elements {\n"
        "\t\tif _, isRest := el.(*RestExpr); isRest && i != len(elements)-1 {\n"
        "\t\t\tp.error(el.Pos(), \"rest element must be last\")\n"
        "\t\t}\n"
        "\t}\n"
    )
    new = (
        "\tfor i, el := range elements {\n"
        "\t\t// mutant: anchored to \"first\" instead of \"last\"\n"
        "\t\tif _, isRest := el.(*RestExpr); isRest && i != 0 {\n"
        "\t\t\tp.error(el.Pos(), \"rest element must be last\")\n"
        "\t\t}\n"
        "\t}\n"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "parser/parser.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-rest-last-direction",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_array_default_always_evaluated_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: array-pattern defaults must be lazy (instruction.md:
    "Default values (`name = expr`) evaluate lazily and apply only when a
    position or key does not exist in the source."). This mutant drops the
    ``OpHasKey``-guarded jump in ``compileArrayPatternElements``'s
    ``*parser.DefaultExpr`` case and always compiles (and therefore always
    evaluates) the default expression, ignoring whatever value the source
    array actually holds at that position -- a plausible near-miss for
    anyone who implements defaults as "expression, then override" instead of
    "check presence, then branch".
    """
    old = (
        "\t\tcase *parser.DefaultExpr:\n"
        "\t\t\tc.loadSymbol(node, tempSymbol)\n"
        "\t\t\tc.emit(node, parser.OpConstant, c.addConstant(&Int{Value: int64(i)}))\n"
        "\t\t\tc.emit(node, parser.OpHasKey)\n"
        "\t\t\tjumpToDefault := c.emit(node, parser.OpJumpFalsy, 0)\n"
        "\t\t\tc.loadSymbol(node, tempSymbol)\n"
        "\t\t\tc.emit(node, parser.OpConstant, c.addConstant(&Int{Value: int64(i)}))\n"
        "\t\t\tc.emit(node, parser.OpIndex)\n"
        "\t\t\tjumpEnd := c.emit(node, parser.OpJump, 0)\n"
        "\t\t\tc.changeOperand(jumpToDefault, len(c.currentInstructions()))\n"
        "\t\t\tif err := c.Compile(e.Default); err != nil {\n"
        "\t\t\t\treturn err\n"
        "\t\t\t}\n"
        "\t\t\tc.changeOperand(jumpEnd, len(c.currentInstructions()))\n"
        "\t\t\tsym, err := resolveTarget(e.Name.Name)\n"
        "\t\t\tif err != nil {\n"
        "\t\t\t\treturn err\n"
        "\t\t\t}\n"
        "\t\t\tc.storeSymbol(node, sym)\n"
    )
    new = (
        "\t\tcase *parser.DefaultExpr:\n"
        "\t\t\t// mutant: default is always evaluated, presence is never checked\n"
        "\t\t\tif err := c.Compile(e.Default); err != nil {\n"
        "\t\t\t\treturn err\n"
        "\t\t\t}\n"
        "\t\t\tsym, err := resolveTarget(e.Name.Name)\n"
        "\t\t\tif err != nil {\n"
        "\t\t\t\treturn err\n"
        "\t\t\t}\n"
        "\t\t\tc.storeSymbol(node, sym)\n"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "compiler.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-array-default-eager",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_assign_operator_restriction_removed_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: only ``:=`` may trigger destructuring (instruction.md:
    "Only `:=` triggers destructuring; `=` is invalid and existing literal
    syntax is unchanged." and the required error substring "cannot use
    destructuring with ="). This mutant deletes the parser-level guard that
    rejects an array/map pattern followed by plain ``=`` (a plausible
    near-miss for anyone who forgets `=` needs its own rejection once `:=`
    parsing works), which either silently accepts the statement or produces
    a different, unrelated parse/compile error -- either way, no longer the
    required substring.
    """
    old = (
        "\t\tif pattern != nil && p.token == token.Assign {\n"
        "\t\t\tp.error(p.pos, \"cannot use destructuring with =\")\n"
        "\t\t}\n"
    )
    new = (
        "\t\t// mutant: '=' after a pattern is no longer rejected here\n"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "parser/parser.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-assign-restriction-removed",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


# ---------------------------------------------------------------------------
# Gate 4: the Oracle rejects forged and malformed observations (no Docker)
# ---------------------------------------------------------------------------


def _oracle_evidence(task, challenge, index, observation, *, status="observed"):
    challenge_id = f"challenge-gate4-{index}"
    evaluation_id = f"evaluation-gate4-{index}"
    failed = status != "observed"
    return ChallengeEvidence(
        check_id=task.verification.checks[0].id,
        challenge_id=challenge_id,
        evaluation_id=evaluation_id,
        challenge_index=index,
        challenge_digest=json_digest(challenge),
        status=status,
        exit_status=None if failed else 0,
        observation=None if failed else observation,
        observation_bytes=0 if failed else len(json.dumps(observation)),
        failure_source="candidate" if failed else None,
        failure_code="forged_candidate_error" if failed else None,
        failure_message="gate 4 synthetic candidate_error" if failed else None,
        trusted_helper_evidence=(),
    )


def _load_oracle_module():
    task = deep_task(NAME)
    oracle_root = Path(
        task.resources.resources["host.task_oracle"].value["source_path"]
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "tengo_destructuring_bindings_oracle", oracle_root / "oracle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return task, oracle_root, module


def _honest_result(scenario_id, scenario_def):
    """Build a genuinely correct result payload for one scenario, directly
    from the Oracle's own recorded expectation -- not by re-deriving Tengo
    semantics independently, since this is only meant to prove the Oracle
    accepts a truthful observation (and rejects a dishonest one), not to
    duplicate the Oracle's own correctness logic.
    """
    kind = scenario_def["kind"]
    if kind == "compile_error":
        contains = scenario_def["expected"]["contains"]
        return {"id": scenario_id, "status": "compile_error",
                "error": contains or "compile error: destructuring rejected",
                "vars_json": "{}"}
    if kind == "runtime_error":
        contains = scenario_def["expected"]["contains"]
        return {"id": scenario_id, "status": "runtime_error",
                "error": contains or "runtime error: wrong number of arguments",
                "vars_json": "{}"}
    return {"id": scenario_id, "status": "observed", "error": "",
            "vars_json": json.dumps(scenario_def["expected"])}


def _drive(task, oracle_root, module, *, corrupt=None):
    """Replay every Oracle case, honestly by default.

    ``corrupt(index, context, results, observation_kwargs, evidence_kwargs)``
    may mutate the list of per-step result dicts, the ``build_exit_code``/
    ``build_stderr`` overrides, or the evidence-level ``status`` in place
    before the evidence is sent, to model one adversarial or malformed
    candidate response.
    """
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="tengo-destructuring-bindings-gate4")
        index = 0
        while (case := session.next_challenge(CHECK_ID, "host.task_oracle", BOUNDS)) is not None:
            context = case.context
            results = [
                _honest_result(sid, module.SCENARIOS[sid])
                for sid in context["scenario_ids"]
            ]
            observation_kwargs = {"build_exit_code": 0, "build_stderr": ""}
            evidence_kwargs = {"status": "observed"}
            if corrupt is not None:
                corrupt(index, context, results, observation_kwargs, evidence_kwargs)
            observation = {
                "build_exit_code": observation_kwargs["build_exit_code"],
                "build_stderr": observation_kwargs["build_stderr"],
                "results": results if observation_kwargs["build_exit_code"] == 0 else [],
            }
            session.evaluate_challenge(
                CHECK_ID, context,
                _oracle_evidence(task, case.challenge, index, observation, **evidence_kwargs),
            )
            index += 1
        return session.finalize()


def test_oracle_accepts_every_honest_observation():
    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module)
    assert verdict.passed is True


def test_oracle_rejects_forged_build_failure():
    """A candidate that fabricates a non-zero build exit code for the first
    case (as if it never even tried to implement the feature) must not pass,
    even though the other cases are answered honestly.
    """
    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if index == 0:
            observation_kwargs["build_exit_code"] = 1
            observation_kwargs["build_stderr"] = "boom"

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_flipped_value():
    """A candidate that reports a wrong value for a basic array-destructuring
    scenario (claims ``a + b`` came out to something other than 3) must be
    rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "basic_array_two":
                payload = json.loads(result["vars_json"])
                payload["out"] = {"kind": "int", "value": "999"}
                result["vars_json"] = json.dumps(payload)
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "basic_array_two scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_default_evaluated_when_it_should_not_be():
    """The ``default_not_evaluated_when_present`` case requires ``counter``
    to stay 0 (the default expression's side effect must not run when the
    value is present); a candidate that reports the side effect ran must be
    rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "default_not_evaluated_when_present":
                payload = json.loads(result["vars_json"])
                payload["counter"] = {"kind": "int", "value": "1"}
                result["vars_json"] = json.dumps(payload)
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "default_not_evaluated_when_present scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_wrong_compile_error_substring():
    """The ``rest_not_last_error`` case requires the compile error to contain
    ``rest element must be last``; a candidate that reports a compile error
    without that substring must be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "rest_not_last_error":
                result["error"] = "syntax error: unexpected token"
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "rest_not_last_error scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_candidate_error_status():
    """A candidate/adapter that reports non-'observed' evidence status (crash,
    timeout, infrastructure hiccup surfaced to the check level) must not be
    silently treated as a pass.
    """
    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if index == 0:
            evidence_kwargs["status"] = "candidate_error"

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_malformed_result_shape():
    """A per-step result missing the required ``error`` field must be
    rejected rather than crash the Oracle or be silently ignored into a pass.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"] or not results:
            return
        del results[0]["error"]
        done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "no case with results was found"
    assert verdict.passed is False
