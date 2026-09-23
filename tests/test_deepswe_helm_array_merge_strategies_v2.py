"""Real-capture Docker qualification for ``helm-array-merge-strategies``.

Gate 1/2/3 replay the production path (see ``tests/deepswe_qualification.py``):
a workspace is cloned from the materialised pinned baseline, the upstream gold
solution (``qualification/reference.patch``) is optionally applied, targeted
source-level mutants are optionally layered on top, and the result is
captured as a real ``git_patch`` candidate and verified through fresh
Evaluation containers using the real Oracle process.

Gate 4 drives the Oracle directly with synthetic ``ChallengeEvidence`` (no
Docker involved) to prove it rejects forged and malformed candidate
observations, the same pattern used for ``helm-unified-manifest-stream`` and
the pilot rows in ``tests/test_pilot_conversions_v2.py``.
"""

from __future__ import annotations

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


NAME = "helm-array-merge-strategies"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "merge_strategy_behavior"


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
    assert "driver_util_test.go" not in str(task.view_for("agent"))
    assert "driver_action_test.go" not in str(task.view_for("agent"))


def test_reference_patch_is_the_pinned_upstream_solution():
    import hashlib

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

    At the base commit, ``chart.Accessor`` has no ``Annotations()`` method and
    ``action.Install``/``action.Upgrade`` have no ``MergeStrategies``/
    ``MergeKeys`` fields, so the adapter's own driver test files fail to
    *build* against the util and action packages -- a legitimate "candidate
    incomplete" signal, not an infrastructure error. The lint packages still
    build (the Chartfile signature is unchanged), but never emit any merge
    strategy warning, so that case fails on its own assertions once reached.
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

    ``pkg/chart/common/util/coalesce.go`` carries essentially all of the
    merge-strategy logic (``ExtractMergeStrategies``, ``applyStrategies``,
    ``mergeArraysByKey``, ``ValidateMergeStrategies``, ``CoalesceTables-
    WithStrategies``, ...). Dropping only this hunk while keeping every other
    file's changes leaves ``pkg/action`` and the lint rule files referencing
    functions that no longer exist there (a build failure once those
    packages are reached), and leaves ``util.CoalesceValues``/``MergeValues``
    behaving exactly like the unmodified base commit for the first case that
    *does* build, so every coalesce/merge scenario mismatches the expected
    (strategy-aware) result.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "pkg/chart/common/util/coalesce.go", dropped
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
def test_append_order_reversed_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: instruction.md requires "`append` concatenates chart
    defaults before user elements". This mutant swaps the two ``append``
    calls in ``coalesce.go``'s ``appendArrays`` so user elements land first
    -- a plausible near-miss for someone who transposed the two operands --
    while every other axis (null-delete, non-array-ignore, merge-by-key,
    scoping, ...) stays correct. Verified locally against the real driver
    that this flips ``append_basic``/``append_nested``/``global_append``/
    ``merge_without_key_fallback``/``mergevalues_append``/
    ``subchart_no_inherit``/``subchart_own_strategy``.
    """
    old = (
        "\tresult := make([]any, 0, len(base)+len(additions))\n"
        "\tresult = append(result, base...)\n"
        "\tresult = append(result, additions...)\n"
        "\treturn result\n"
        "}"
    )
    new = (
        "\tresult := make([]any, 0, len(base)+len(additions))\n"
        "\tresult = append(result, additions...)\n"
        "\tresult = append(result, base...)\n"
        "\treturn result\n"
        "}"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(
            workspace, "pkg/chart/common/util/coalesce.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-append-order",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_nested_merge_key_resolution_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: instruction.md requires "The merge key itself may also
    be a dotted path into nested object fields." This mutant removes the
    dotted-path branch from ``coalesce.go``'s ``resolveNestedKey``, falling
    back to a flat map lookup for every merge key -- a plausible near-miss
    for someone who implemented top-level merge keys but never handled
    nesting. Every flat merge-key scenario (``merge_basic_key``, ``merge_
    recursive_field``, ...) still passes; only the nested-key scenario
    (``nested_merge_key``, merge key ``metadata.name``) diverges, because no
    element on either side resolves the key, so nothing matches and every
    element is treated as unkeyed.
    """
    old = (
        "func resolveNestedKey(m map[string]any, dottedKey string) (any, bool) {\n"
        "\tif !strings.Contains(dottedKey, \".\") {\n"
        "\t\tv, ok := m[dottedKey]\n"
        "\t\treturn v, ok\n"
        "\t}\n"
        "\tparts := strings.Split(dottedKey, \".\")"
    )
    new = (
        "func resolveNestedKey(m map[string]any, dottedKey string) (any, bool) {\n"
        "\tv, ok := m[dottedKey]\n"
        "\treturn v, ok\n"
        "}\n"
        "\n"
        "func resolveNestedKeyUnused(m map[string]any, dottedKey string) (any, bool) {\n"
        "\tparts := strings.Split(dottedKey, \".\")"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(
            workspace, "pkg/chart/common/util/coalesce.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-nested-key",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_cli_override_precedence_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: instruction.md requires CLI ``MergeStrategies``/
    ``MergeKeys`` to take "precedence over chart annotations for the same
    path." This mutant makes ``pkg/action/merge_strategy.go``'s
    ``mergeStrategyAnnotations`` skip a CLI override whenever the chart
    already annotates that path -- a plausible near-miss for someone who
    only handled the "no annotation yet" case -- while CLI overrides for
    genuinely un-annotated paths keep working. Only the
    ``upgrade_cli_overrides_annotation`` scenario (whose chart annotates
    ``items`` as ``append`` but the CLI asks for ``merge``/key ``id`` on a
    fixture that discriminates the two) diverges.
    """
    old = (
        "\tfor _, s := range cliStrategies {\n"
        "\t\tpath, strategy, err := parseStrategyFlag(s)\n"
        "\t\tif err != nil {\n"
        "\t\t\tcontinue\n"
        "\t\t}\n"
        "\t\tmerged[\"helm.sh/merge-strategy/\"+path] = strategy\n"
        "\t}\n"
        "\n"
        "\tfor _, k := range cliKeys {\n"
        "\t\tpath, field, err := parseStrategyFlag(k)\n"
        "\t\tif err != nil {\n"
        "\t\t\tcontinue\n"
        "\t\t}\n"
        "\t\tmerged[\"helm.sh/merge-key/\"+path] = field\n"
        "\t}"
    )
    new = (
        "\tfor _, s := range cliStrategies {\n"
        "\t\tpath, strategy, err := parseStrategyFlag(s)\n"
        "\t\tif err != nil {\n"
        "\t\t\tcontinue\n"
        "\t\t}\n"
        "\t\tif _, exists := merged[\"helm.sh/merge-strategy/\"+path]; exists {\n"
        "\t\t\tcontinue\n"
        "\t\t}\n"
        "\t\tmerged[\"helm.sh/merge-strategy/\"+path] = strategy\n"
        "\t}\n"
        "\n"
        "\tfor _, k := range cliKeys {\n"
        "\t\tpath, field, err := parseStrategyFlag(k)\n"
        "\t\tif err != nil {\n"
        "\t\t\tcontinue\n"
        "\t\t}\n"
        "\t\tif _, exists := merged[\"helm.sh/merge-key/\"+path]; exists {\n"
        "\t\t\tcontinue\n"
        "\t\t}\n"
        "\t\tmerged[\"helm.sh/merge-key/\"+path] = field\n"
        "\t}"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "pkg/action/merge_strategy.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-cli-precedence",
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


def _honest_result(scenario_id, scenario_def):
    kind = scenario_def["kind"]
    if kind in ("lint_v2", "lint_v3"):
        predicate = scenario_def["expected"]["predicate"]
        if predicate["mode"] == "absent":
            messages = []
        else:
            text = " ".join(predicate["substrings"]) + " (honest fixture text)"
            messages = [{"severity": 2, "path": "Chart.yaml", "text": text}]
        return {"id": scenario_id, "status": "observed", "error": "",
                "result_json": json.dumps(messages), "chart_values_json": ""}

    expected = scenario_def["expected"]
    result_json = json.dumps(expected["result"])
    chart_values_json = (
        json.dumps(expected["chart_values"]) if "chart_values" in expected else ""
    )
    return {"id": scenario_id, "status": "observed", "error": "",
            "result_json": result_json, "chart_values_json": chart_values_json}


def _load_oracle_module():
    task = deep_task(NAME)
    oracle_root = Path(
        task.resources.resources["host.task_oracle"].value["source_path"]
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "helm_array_merge_strategies_oracle", oracle_root / "oracle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return task, oracle_root, module


def _drive(task, oracle_root, module, *, corrupt=None):
    """Replay every Oracle case, honestly by default.

    ``corrupt(index, context, results, observation_kwargs, evidence_kwargs)``
    may mutate the list of per-scenario result dicts, the ``build_exit_code``/
    ``build_stderr`` overrides, or the evidence-level ``status`` in place
    before the evidence is sent, to model one adversarial or malformed
    candidate response.
    """
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="helm-merge-strategy-gate4")
        index = 0
        while (
            case := session.next_challenge(
                CHECK_ID, "host.task_oracle", {"max_cases": 5, "max_case_bytes": 131072}
            )
        ) is not None:
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
    even though the other cases would be answered honestly.
    """
    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if index == 0:
            observation_kwargs["build_exit_code"] = 1
            observation_kwargs["build_stderr"] = "boom"

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_wrong_append_order():
    """A candidate that reports user elements before chart defaults for a
    plain append scenario must be rejected even though the element set is
    otherwise correct.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "append_basic":
                result["result_json"] = json.dumps(
                    {"tolerations": [{"key": "gpu"}, {"key": "node-role"}]})
                done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "append_basic scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_unmerged_matched_containers():
    """A candidate that reports the matched-key element unmerged (chart and
    user versions both present, instead of one merged element with the user
    field winning) must be rejected even though every element it emits is
    individually plausible.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "merge_basic_key":
                result["result_json"] = json.dumps({"containers": [
                    {"name": "sidecar", "image": "proxy:1.0"},
                    {"name": "sidecar", "image": "proxy:2.0"},
                    {"name": "init", "image": "setup:1.0"},
                    {"name": "app", "image": "myapp:1.0"},
                ]})
                done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "merge_basic_key scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_chart_defaults_mutated():
    """A candidate whose coalesce call mutates the chart's own default
    values in place (the deep-copy requirement) must be rejected even
    though the returned coalesced result is honest.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "deepcopy_preserves_defaults":
                result["chart_values_json"] = json.dumps(
                    {"containers": [{"name": "init", "image": "setup:2.0"}]})
                done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "deepcopy_preserves_defaults scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_missing_lint_warning():
    """A candidate that never emits the required ``unsupported`` warning for
    an invalid merge strategy value must be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "lint_v2_invalid_strategy":
                result["result_json"] = json.dumps([])
                done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "lint_v2_invalid_strategy scenario was not scheduled"
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
    """A per-scenario result missing the required ``chart_values_json``
    field must be rejected rather than crash the Oracle or be silently
    ignored into a pass.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"] or not results:
            return
        del results[0]["chart_values_json"]
        done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "no case with results was found"
    assert verdict.passed is False


def _rewrite_items(scenario_id, transform):
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        for result in results:
            if result["id"] == scenario_id:
                items = json.loads(result["result_json"])["items"]
                result["result_json"] = json.dumps({"items": transform(items)})
                done["applied"] = True

    return done, corrupt


@pytest.mark.parametrize(
    "scenario_id", ["merge_nonmap_appended", "merge_missing_key_appended"]
)
def test_oracle_accepts_preserved_elements_in_any_position(scenario_id):
    """The instruction says only that non-map and key-less elements are
    "preserved"; upstream never asserts their position, so a reordered but
    otherwise correct result must pass (playbook #20: never stricter)."""
    done, corrupt = _rewrite_items(scenario_id, lambda items: list(reversed(items)))
    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"]
    assert verdict.passed is True


@pytest.mark.parametrize(
    "scenario_id", ["merge_nonmap_appended", "merge_missing_key_appended"]
)
def test_oracle_rejects_a_dropped_preserved_element(scenario_id):
    done, corrupt = _rewrite_items(scenario_id, lambda items: items[:-1])
    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"]
    assert verdict.passed is False
