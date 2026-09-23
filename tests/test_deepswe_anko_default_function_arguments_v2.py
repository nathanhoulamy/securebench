"""Real-capture Docker qualification for ``anko-default-function-arguments``.

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


NAME = "anko-default-function-arguments"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "anko_default_arguments_behavior"
BOUNDS = {"max_cases": 3, "max_case_bytes": 65536}


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


def test_reference_patch_touches_no_excluded_path():
    """Defect-19 check: the gold solution must not edit a path the row
    excludes from the candidate (``core/core.go``, ``parser/default_args.go``
    (new file), ``parser/lexer.go`` -- none are test files, so this row is
    not held for that reason).
    """
    task = deep_task(NAME)
    exclude_globs = task.verification.candidate.exclude_paths
    touched = re.findall(r"(?m)^diff --git a/(\S+) b/\S+", reference_patch(NAME).read_text())
    assert touched == ["core/core.go", "parser/default_args.go", "parser/lexer.go"]

    import fnmatch

    for path in touched:
        for pattern in exclude_globs:
            assert not fnmatch.fnmatch(path, pattern), (path, pattern)


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

    Default-argument syntax (`name = expr` in a parameter list) does not
    parse at the base commit, so every "value" scenario in the challenge
    suite that declares a default either fails to parse (with a generic
    "syntax error", not the required "invalid default argument declaration"
    substring for the two scenarios that expect a parse error) or, for the
    two `load()` scenarios, fails at runtime loading a file that itself uses
    default-argument syntax -- a legitimate "candidate incomplete" signal,
    not an infrastructure error.
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
def test_missing_rewriter_file_mutant_fails(tmp_path, baseline):
    """Gate 3 (generic): drop the largest non-test file of the gold patch.

    ``parser/default_args.go`` is the entire feature: the source-rewriting
    machinery (``rewriteDefaultArgumentFunctions``, parameter parsing,
    prologue generation) that ``parser/lexer.go``'s modified ``Parse`` calls.
    Dropping it while keeping the small ``lexer.go``/``core.go`` hooks leaves
    ``rewriteDefaultArgumentFunctions`` undefined, so the candidate's own
    module fails to build -- every scenario in the challenge suite reports a
    build failure rather than a semantic divergence, which is still a
    legitimate rejection.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "parser/default_args.go", dropped
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
        run_seed=f"{NAME}-partial-{dropped.replace('/', '-')}",
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
def test_default_before_required_ordering_check_removed_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: a fixed parameter with a default cannot be followed by a
    fixed parameter without a default (instruction.md: "A fixed parameter
    with a default cannot be followed by a fixed parameter without a
    default. ... These invalid declarations should be rejected with the
    parse error `invalid default argument declaration`."). This mutant
    disables the ordering guard in ``parseDefaultArgumentParams`` (a
    plausible near-miss: the condition silently becomes dead code, as if
    someone gated it behind a flag that was never turned on), so
    ``func a(b = 1, c) { return c }`` now parses successfully instead of
    being rejected.
    """
    old = '\t\t} else if seenDefault && !param.IsVariadic {\n'
    new = '\t\t} else if false && seenDefault && !param.IsVariadic {\n'

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "parser/default_args.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-ordering-check-removed",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_default_always_assigned_ignoring_explicit_arg_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: an explicitly supplied argument must be used instead of
    the parameter's default (instruction.md: "When a call omits one or more
    trailing arguments, the missing parameters should be assigned their
    declared default values" -- implying a *provided* trailing argument must
    not be overwritten). This mutant replaces the generated
    "if len(args) > index { param = args[index] } else { param = default }"
    prologue for a defaulted fixed parameter with an unconditional
    "param = default" assignment -- a plausible near-miss for anyone who
    implements "assign the default" without gating it on whether the caller
    actually supplied that argument. A call that explicitly overrides the
    default (``a(2)``) now silently gets the default value back.
    """
    old = (
        '\t\tbuilder.WriteString(" if len(")\n'
        '\t\tbuilder.WriteString(argsName)\n'
        '\t\tbuilder.WriteString(") > ")\n'
        '\t\tbuilder.WriteString(fmt.Sprintf("%d", index))\n'
        '\t\tbuilder.WriteString(" { ")\n'
        '\t\tbuilder.WriteString(param.Name)\n'
        '\t\tbuilder.WriteString(" = ")\n'
        '\t\tbuilder.WriteString(argsName)\n'
        '\t\tbuilder.WriteString("[")\n'
        '\t\tbuilder.WriteString(fmt.Sprintf("%d", index))\n'
        '\t\tbuilder.WriteString("] } else { ")\n'
        '\t\tbuilder.WriteString(param.Name)\n'
        '\t\tbuilder.WriteString(" = ")\n'
        '\t\tbuilder.WriteString(param.Default)\n'
        '\t\tbuilder.WriteString(" };")\n'
    )
    new = (
        '\t\t// mutant: default is always assigned, ignoring whether the\n'
        '\t\t// caller actually supplied this argument\n'
        '\t\tbuilder.WriteString(" ")\n'
        '\t\tbuilder.WriteString(param.Name)\n'
        '\t\tbuilder.WriteString(" = ")\n'
        '\t\tbuilder.WriteString(param.Default)\n'
        '\t\tbuilder.WriteString(";")\n'
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "parser/default_args.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-eager-default-overwrite",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_too_many_arguments_check_removed_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: calling a function with more arguments than it declares
    must still be rejected once default arguments exist (upstream
    `TestDefaultArgumentsVisible`: ``func a(b = 1) { return b }; a(1, 2)``
    must error). This mutant disables the generated "too many arguments"
    guard for non-variadic functions (a plausible near-miss: someone adds
    default-argument support and forgets the existing arity ceiling still
    needs enforcing once the function is rewritten into a variadic wrapper),
    so an over-application now silently succeeds instead of erroring.
    """
    old = '\tif variadicIndex == -1 {\n'
    new = '\tif false && variadicIndex == -1 {\n'

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "parser/default_args.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-too-many-args-check-removed",
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
        "anko_default_function_arguments_oracle", oracle_root / "oracle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return task, oracle_root, module


def _honest_result(scenario_id, scenario_def):
    """Build a genuinely correct result payload for one scenario, directly
    from the Oracle's own recorded expectation -- not by re-deriving Anko
    semantics independently, since this is only meant to prove the Oracle
    accepts a truthful observation (and rejects a dishonest one), not to
    duplicate the Oracle's own correctness logic.
    """
    kind = scenario_def["kind"]
    if kind == "parse_error":
        contains = scenario_def["expected"]["contains"]
        return {"id": scenario_id, "status": "parse_error",
                "error": contains or "parse error: rejected",
                "result_json": "null", "vars_json": "{}"}
    if kind == "runtime_error":
        contains = scenario_def["expected"]["contains"]
        return {"id": scenario_id, "status": "runtime_error",
                "error": contains or "runtime error: wrong number of arguments",
                "result_json": "null", "vars_json": "{}"}
    return {
        "id": scenario_id, "status": "observed", "error": "",
        "result_json": json.dumps(scenario_def["expected_result"]),
        "vars_json": json.dumps(scenario_def["expected_vars"]),
    }


def _drive(task, oracle_root, module, *, corrupt=None):
    """Replay every Oracle case, honestly by default.

    ``corrupt(index, context, results, observation_kwargs, evidence_kwargs)``
    may mutate the list of per-step result dicts, the ``build_exit_code``/
    ``build_stderr`` overrides, or the evidence-level ``status`` in place
    before the evidence is sent, to model one adversarial or malformed
    candidate response.
    """
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="anko-default-function-arguments-gate4")
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
    """A candidate that reports a wrong return value for the simplest
    omitted-argument scenario (claims ``a()`` returned something other than
    1) must be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "omitted_uses_default":
                result["result_json"] = json.dumps(
                    {"kind": "int", "value": "999", "items": []}
                )
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "omitted_uses_default scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_explicit_argument_not_overriding_default():
    """The ``explicit_overrides_default`` case requires a call-time argument
    to override the parameter's default; a candidate that reports the
    default value came back anyway must be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "explicit_overrides_default":
                result["result_json"] = json.dumps(
                    {"kind": "int", "value": "1", "items": []}
                )
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "explicit_overrides_default scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_call_time_evaluation_reporting_stale_snapshot():
    """The ``default_call_time_evaluation`` case requires the default to be
    evaluated at call time (after ``seed`` was reassigned to 10, so the
    default must see 10, not the value at function-definition time); a
    candidate that reports the stale, definition-time result must be
    rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "default_call_time_evaluation":
                result["result_json"] = json.dumps(
                    {"kind": "int", "value": "5", "items": []}
                )
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "default_call_time_evaluation scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_wrong_parse_error_substring():
    """The ``invalid_default_before_required_parse_error`` case requires the
    parse error to contain ``invalid default argument declaration``; a
    candidate that reports a parse error without that substring must be
    rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "invalid_default_before_required_parse_error":
                result["error"] = "syntax error: unexpected token"
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "invalid_default_before_required_parse_error scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_missing_runtime_error_for_too_many_args():
    """The ``too_many_args_errors`` case requires a non-nil runtime error
    (matching upstream's own loose ``RunErrorFunc`` check); a candidate that
    reports "observed" (as if the call silently succeeded) must be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "too_many_args_errors":
                result["status"] = "observed"
                result["error"] = ""
                result["result_json"] = json.dumps({"kind": "int", "value": "1", "items": []})
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "too_many_args_errors scenario was not scheduled"
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
