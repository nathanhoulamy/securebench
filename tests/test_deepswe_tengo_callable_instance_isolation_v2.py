"""Real-capture Docker qualification for ``tengo-callable-instance-isolation``.

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
``tests/test_deepswe_tengo_destructuring_bindings_v2.py``.
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


NAME = "tengo-callable-instance-isolation"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "tengo_callable_instance_behavior"
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

    At the base commit, ``*tengo.CompiledFunction`` already reports
    ``CanCall() == true`` but has no ``Call`` override, so it falls back to
    ``ObjectImpl.Call``, which silently returns ``(nil, nil)`` for every
    invocation -- no error, no execution, no error-argument-count checking.
    Every challenge scenario that calls a compiled function from Go
    therefore diverges from its expected observation (wrong value, missing
    error, or unmutated global), and ``Compiled.Set``'s base-commit shallow
    ``obj.Copy()`` leaves cross-instance closures aliased instead of
    isolated. This is a legitimate "candidate incomplete" signal, not an
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

    ``call.go`` is a wholly new file and carries almost the entire gold
    solution (617 added lines): ``compiledFunctionEnv``, the runtime object
    binder, ``CompiledFunction.Call``, the direct-call VM construction, the
    runtime-error frame formatter, and every clone helper
    (``compiledCloneState``, ``cloneCompiledGlobals``,
    ``cloneObjectIntoCompiled``, ``requiresRuntimeClone``). Dropping it while
    keeping the small ``objects.go``/``script.go``/``vm.go`` hunks (which
    reference symbols call.go defines, such as ``compiledFunctionEnv``,
    ``cloneCompiledGlobals`` and ``v.formatRuntimeError``) leaves the package
    unable to build, so every challenge case fails through a build error --
    a legitimate "candidate incomplete" signal, not an infrastructure error.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "call.go", dropped
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
def test_set_no_longer_deep_clones_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: cross-instance ``Set`` must deep-clone callable state
    (instruction.md: "Cloned compiled instances and callable values assigned
    into another compiled instance must keep isolated state; calling or
    mutating through one instance must not affect the source instance.").
    This mutant deletes ``Compiled.Set``'s ``requiresRuntimeClone`` guard in
    script.go, so a callable (or a composite value containing one) assigned
    across instances is stored by reference instead of being cloned into the
    destination's runtime -- a plausible near-miss for anyone who implements
    ``Set`` isolation only for ``Clone`` and forgets the symmetric case.
    """
    old = (
        "\tif requiresRuntimeClone(obj) {\n"
        "\t\tobj = cloneObjectIntoCompiled(c.bytecode, c.globals, c.maxAllocs, obj)\n"
        "\t}\n"
    )
    new = (
        "\t// mutant: cross-instance Set no longer deep-clones callable state\n"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "script.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-set-no-clone",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_clone_leaves_simple_functions_unbound_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: every callable reachable from a clone/transfer, not only
    ones that capture locals, must be rebound to the destination's runtime
    (instruction.md: "Apply the same isolation recursively to every callable
    reachable inside transferred arrays or maps, not only the top-level
    assigned value."). ``call.go``'s ``cloneCompiledFunction`` special-cases
    a function with no captured free variables (for example a plain
    top-level ``func(step) { count += step; ... }``) as needing no rebinding
    -- a plausible near-miss reasoning "it captures nothing, so there is
    nothing to isolate," which ignores that it still resolves *globals*
    through whichever runtime environment it is bound to. This mutant
    returns such a function unbound (the original instance's own object),
    so calling it after a clone or cross-instance ``Set`` still mutates the
    *source* instance's globals instead of the destination's.
    """
    old = (
        "\tif len(obj.Free) == 0 {\n"
        "\t\tclone := s.env.bindFunction(obj)\n"
        "\t\ts.compiled[obj] = clone\n"
        "\t\treturn clone\n"
        "\t}\n"
    )
    new = (
        "\tif len(obj.Free) == 0 {\n"
        "\t\t// mutant: zero-free-var functions are left bound to the\n"
        "\t\t// source instance's runtime environment instead of rebound.\n"
        "\t\tclone := obj\n"
        "\t\ts.compiled[obj] = clone\n"
        "\t\treturn clone\n"
        "\t}\n"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "call.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-clone-unbound",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_call_error_drops_runtime_prefix_and_position_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: a Go-side call's runtime error must keep the same
    ``Runtime Error:`` prefix and ``(main):N:`` source-position frames an
    in-script call gets (instruction.md: "... executes with the same
    globals, imports, closure captures, variadic behavior, recursion,
    return values, and runtime error formatting as an in-script call.").
    ``call.go``'s ``formatCompiledFunctionCallError`` wraps the raw VM error
    through ``formatRuntimeErrorForFrames`` to add that prefix and the
    frame-position chain; this mutant skips the wrapping and returns the
    raw ``v.err`` -- a plausible near-miss for anyone who gets the call
    semantics and return values right but forgets that the *error path*
    needs the same formatting as ``Compiled.Run()``'s own top-level error
    (which is a distinct axis from both the cross-instance ``Set`` clone
    mutant and the ``Clone``-rebinding mutant above: it is about error
    *presentation* on an otherwise-successful call dispatch, not state
    isolation).
    """
    old = (
        "func (v *VM) formatCompiledFunctionCallError() error {\n"
        "\terr := v.formatRuntimeErrorForFrames(1)\n"
        "\tif err != nil {\n"
        "\t\treturn err\n"
        "\t}\n"
        "\treturn v.err\n"
        "}\n"
    )
    new = (
        "func (v *VM) formatCompiledFunctionCallError() error {\n"
        "\t// mutant: runtime-error prefix/position formatting skipped entirely\n"
        "\treturn v.err\n"
        "}\n"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "call.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-call-error-format",
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
        "tengo_callable_instance_isolation_oracle", oracle_root / "oracle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return task, oracle_root, module


def _honest_result(check, module):
    """Build a genuinely correct result payload for one check, directly from
    the Oracle's own recorded expectation -- not by re-deriving Tengo
    semantics independently, since this is only meant to prove the Oracle
    accepts a truthful observation (and rejects a dishonest one), not to
    duplicate the Oracle's own correctness logic.
    """
    result_id = check["result_id"]
    check_type = check["type"]
    op = result_id.rsplit("::", 1)[-1]

    if check_type == "status_only":
        return {"id": result_id, "op": op, "status": check["status"], "error": "",
                "value": {"kind": "none", "value": "", "callable": False}}
    if check_type == "error":
        contains = check["contains"]
        error_text = " ".join(contains) if contains else "runtime error"
        return {"id": result_id, "op": op, "status": check["status"], "error": error_text,
                "value": {"kind": "none", "value": "", "callable": False}}
    if check_type == "nil":
        return {"id": result_id, "op": op, "status": "observed", "error": "",
                "value": {"kind": "nil", "value": "", "callable": False}}
    if check_type == "int":
        return {"id": result_id, "op": op, "status": "observed", "error": "",
                "value": {"kind": "int", "value": check["value"],
                          "callable": bool(check.get("callable"))}}
    if check_type == "string":
        return {"id": result_id, "op": op, "status": "observed", "error": "",
                "value": {"kind": "string", "value": check["value"],
                          "callable": bool(check.get("callable"))}}
    if check_type == "float":
        return {"id": result_id, "op": op, "status": "observed", "error": "",
                "value": {"kind": "float", "value": repr(check["value"]),
                          "callable": bool(check.get("callable"))}}
    if check_type == "callable":
        return {"id": result_id, "op": op, "status": "observed", "error": "",
                "value": {"kind": "other", "value": "", "callable": bool(check["callable"])}}
    raise AssertionError(f"unknown check type: {check_type}")


def _drive(task, oracle_root, module, *, corrupt=None):
    """Replay every Oracle case, honestly by default.

    ``corrupt(index, context, results, observation_kwargs, evidence_kwargs)``
    may mutate the list of per-op result dicts, the ``build_exit_code``/
    ``build_stderr`` overrides, or the evidence-level ``status`` in place
    before the evidence is sent, to model one adversarial or malformed
    candidate response.
    """
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="tengo-callable-instance-isolation-gate4")
        index = 0
        while (case := session.next_challenge(CHECK_ID, "host.task_oracle", BOUNDS)) is not None:
            context = case.context
            results = [_honest_result(check, module) for check in context["checks"]]
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
    """A candidate that reports a wrong return value for a basic Go-side
    call (claims ``adder(20, 22)`` came out to something other than 42)
    must be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        target = "global_function_can_be_called_from_go::r1"
        for result in results:
            if result["id"] == target:
                result["value"] = {"kind": "int", "value": "999", "callable": False}
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "global_function_can_be_called_from_go scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_stale_cross_instance_mutation():
    """The ``set_rebinds_global_callables_to_destination_compiled`` scenario
    requires the *source* instance's global to stay at 0 after calling the
    rebound callable through the *destination* instance (isolation); a
    candidate that reports the source instance's global was mutated too
    must be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        target = "set_rebinds_global_callables_to_destination_compiled::r3"
        for result in results:
            if result["id"] == target:
                result["value"] = {"kind": "int", "value": "5", "callable": False}
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "set_rebinds_global_callables_to_destination_compiled scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_wrong_runtime_error_substring():
    """The ``wrong_argument_count_reports_runtime_style_error`` scenario
    requires the call error to contain the exact upstream substring; a
    candidate that reports a call error without it must be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        target = "wrong_argument_count_reports_runtime_style_error::r1"
        for result in results:
            if result["id"] == target:
                result["error"] = "some other error"
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "wrong_argument_count_reports_runtime_style_error scenario was not scheduled"
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
    """A per-op result missing the required ``error`` field must be rejected
    rather than crash the Oracle or be silently ignored into a pass.
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
