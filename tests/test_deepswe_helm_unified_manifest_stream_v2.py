"""Real-capture Docker qualification for ``helm-unified-manifest-stream``.

Gate 1/2/3 replay the production path (see ``tests/deepswe_qualification.py``):
a workspace is cloned from the materialised pinned baseline, the upstream gold
solution (``qualification/reference.patch``) is optionally applied, targeted
source-level mutants are optionally layered on top, and the result is
captured as a real ``git_patch`` candidate and verified through fresh
Evaluation containers using the real Oracle process.

Gate 4 drives the Oracle directly with synthetic ``ChallengeEvidence`` (no
Docker involved) to prove it rejects forged and malformed candidate
observations, the same pattern used for ``task-task-graph-export`` and the
pilot rows in ``tests/test_pilot_conversions_v2.py``.
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


NAME = "helm-unified-manifest-stream"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "manifest_stream_behavior"


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
    assert "driver_test.go" not in str(task.view_for("agent"))


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

    At the base commit, ``helm template`` appends hooks after the whole
    kind-sorted manifest body instead of interleaving them by ``Source``
    path, ``helm install/upgrade --dry-run`` print a separate ``HOOKS:``
    section before ``MANIFEST:``, ``helm get manifest`` prints only
    ``rel.Manifest`` and omits hooks entirely, and upgrade dry-run still
    prints ``Happy Helming!``. Every one of those violates a numbered
    requirement in instruction.md, so the unmodified base commit fails on
    every scenario -- a legitimate "candidate incomplete" signal, not an
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
    """Gate 3 (generic): drop the largest non-test file of the gold patch.

    ``pkg/release/v1/util/manifest_stream.go`` is the only brand-new file the
    gold solution adds and is by far the largest hunk (``ParseManifestStream``,
    ``BuildManifestStream``, ``BuildManifestForInstall``,
    ``SortManifestsFromStream`` all live there); without it, every other
    changed call site (``get_manifest.go``'s ``buildManifestWithHooks``,
    ``template.go``'s skip-tests filtering, ``action.go``'s ``renderResources``
    use of ``SortManifestsWithOrder``) fails to compile, so even the adapter's
    own driver (which builds the whole ``pkg/cmd`` package exactly as the
    upstream test suite does) fails to build.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "pkg/release/v1/util/manifest_stream.go", dropped
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
def test_get_manifest_path_ordering_reversed_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: full ``Source`` paths must be ordered *lexicographically*
    (instruction.md: "orders documents by full Source path, sorted
    lexicographically"). This mutant reverses the sort in
    ``get_manifest.go``'s ``orderedPaths``, a plausible near-miss for someone
    who inverted a comparator (still "sorted", just backwards) -- deterministic
    for our fixture's three distinct paths, unlike simply dropping the sort
    call, which would only fail probabilistically under Go's randomized map
    iteration.
    """
    old = "\tsort.Strings(paths)\n\treturn paths\n}"
    new = "\tsort.Sort(sort.Reverse(sort.StringSlice(paths)))\n\treturn paths\n}"

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "pkg/cmd/get_manifest.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-reversed-paths",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_get_manifest_hook_precedence_swapped_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: when a hook and a non-hook resource share the same
    ``Source`` path, ``helm get manifest`` must place the hook first
    (instruction.md: "helm get manifest must place those hooks before
    non-hook resources"). This mutant swaps the append order in
    ``get_manifest.go``'s ``mergeEntriesByPath`` so non-hooks are written
    before hooks at a shared path -- every other ordering property (distinct
    paths still sorted, in-file order preserved) stays correct.
    """
    old = (
        "\t\tif hooks, ok := hooksByPath[path]; ok {\n"
        "\t\t\tcombined = append(combined, hooks...)\n"
        "\t\t}\n"
        "\t\tif items, ok := nonHookByPath[path]; ok {\n"
        "\t\t\tcombined = append(combined, items...)\n"
        "\t\t}"
    )
    new = (
        "\t\tif items, ok := nonHookByPath[path]; ok {\n"
        "\t\t\tcombined = append(combined, items...)\n"
        "\t\t}\n"
        "\t\tif hooks, ok := hooksByPath[path]; ok {\n"
        "\t\t\tcombined = append(combined, hooks...)\n"
        "\t\t}"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "pkg/cmd/get_manifest.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-hook-precedence",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_upgrade_happy_helming_regression_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: upgrade dry-run output must not include the
    ``Happy Helming!`` success line (instruction.md, requirement 9). This
    mutant drops the gold solution's added ``&& client.DryRunStrategy ==
    action.DryRunNone`` guard in ``upgrade.go``, restoring the pre-patch
    behavior of printing the banner unconditionally for table output --
    every other unified-stream property in the same command stays correct.
    """
    old = "if outfmt == output.Table && client.DryRunStrategy == action.DryRunNone {"
    new = "if outfmt == output.Table {"

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "pkg/cmd/upgrade.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-happy-helming",
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


def _honest_stdout(scenario_def):
    expected = scenario_def["expected"]
    parts = []
    for path, needle in expected["markers"]:
        parts.append(f"---\n# Source: {path}\n{needle}\n")
    body = "".join(parts).rstrip("\n") + "\n"
    if expected["single_manifest"]:
        body = "NAME: det-order\nMANIFEST:\n" + body
    return body


def _honest_result(scenario_id, scenario_def):
    return {"id": scenario_id, "status": "observed", "stdout": _honest_stdout(scenario_def),
            "error": ""}


def _load_oracle_module():
    task = deep_task(NAME)
    oracle_root = Path(
        task.resources.resources["host.task_oracle"].value["source_path"]
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "helm_unified_manifest_stream_oracle", oracle_root / "oracle.py"
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
        session.initialize(task, run_seed="helm-manifest-stream-gate4")
        index = 0
        while (
            case := session.next_challenge(
                CHECK_ID, "host.task_oracle", {"max_cases": 3, "max_case_bytes": 65536}
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
    even though the other cases are answered honestly.
    """
    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if index == 0:
            observation_kwargs["build_exit_code"] = 1
            observation_kwargs["build_stderr"] = "boom"

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert verdict.passed is False


def test_oracle_rejects_reordered_source_markers():
    """A candidate that emits documents out of full-``Source``-path order
    must be rejected even if every document is individually present.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "template_order":
                result["stdout"] = (
                    "---\n# Source: orderchart/templates/b-second.yaml\nname: cm-b\n"
                    "---\n# Source: orderchart/templates/a-first.yaml\nname: sa-a\n"
                    "---\n# Source: orderchart/templates/a-first.yaml\nname: cm-a2\n"
                )
                done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "template_order scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_separate_hooks_section():
    """A candidate that reintroduces a separate ``HOOKS:`` section must be
    rejected even though every document is present.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "install_dry_run_hooks":
                result["stdout"] = (
                    "NAME: det-order\nHOOKS:\n---\n"
                    "# Source: hookchart/templates/00-hook.yaml\nname: hook-a\n"
                    "MANIFEST:\n---\n# Source: hookchart/templates/01-resource.yaml\nname: sa-x\n"
                )
                done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "install_dry_run_hooks scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_happy_helming_banner():
    """Upgrade dry-run evidence containing the forbidden success banner must
    be rejected even though every document and ordering property is honest.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "upgrade_dry_run_no_happy":
                result["stdout"] = result["stdout"] + 'Release "det-order" has been upgraded. Happy Helming!\n'
                done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "upgrade_dry_run_no_happy scenario was not scheduled"
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
    """A per-scenario result missing the required ``error`` field must be
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
