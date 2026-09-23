"""Real-capture Docker qualification for ``task-task-graph-export``.

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
``tests/test_deepswe_bandit_structured_nosec_directives_v2.py``.
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


NAME = "task-task-graph-export"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "task_graph_behavior"


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

    ``graph.go`` and ``Executor.Graph``/``WithGraphFormat``/``WithGraphReverse``/
    ``WithGraphNoStatus`` do not exist at the base commit, so the adapter's
    driver (which calls them directly, exactly as the upstream test helpers
    do) fails to build -- a legitimate "candidate incomplete" signal, not an
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

    ``graph.go`` is the only new file the gold solution adds and is by far the
    largest hunk (roots, nodes, edges, depth groups, longest path, and all
    three renderers live there); without it ``Executor.Graph`` does not exist,
    so even the adapter's own driver (which calls it exactly as the upstream
    test suite does) fails to build.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "graph.go", dropped
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
def test_unsorted_deps_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: ``deps`` must be a *sorted* array (instruction.md: "'deps'
    as a sorted array of all outgoing task names"). This mutant drops the
    ``sort.Strings(depNames)`` call, so nodes with more than one outgoing edge
    (for example ``mixed``'s ``pipeline`` -> [build,lint,package,test], or
    ``simple_chain``/``diamond``) report deps in traversal/insertion order
    instead -- a classic near-miss for anyone who forgets sorting is part of
    the contract, not an implementation detail.
    """
    old = (
        "\t\t// Sort dep names alphabetically\n"
        "\t\tsort.Strings(depNames)"
    )
    new = "\t\t// Sort dep names alphabetically (intentionally skipped)"

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "graph.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-unsorted-deps",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_cycle_error_missing_keyword_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: cycle errors must contain the word "cycle" (instruction.md:
    "If the dependency graph has a cycle, return an error containing the word
    cycle and naming the tasks involved."). This mutant renames the message to
    "dependency loop detected", a wording change that preserves every other
    behavior (still an error, still names both tasks) but drops the one
    literal word the instruction requires.
    """
    old = 'return fmt.Errorf("task: dependency cycle detected involving: %s"'
    new = 'return fmt.Errorf("task: dependency loop detected involving: %s"'

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "graph.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-cycle-keyword",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_dot_missing_dashed_style_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: up-to-date nodes must render with ``style=dashed`` in DOT
    output (instruction.md: "Up-to-date nodes get style=dashed."). This
    mutant disables the dashed branch unconditionally, so DOT output for an
    up-to-date node looks identical to a stale one -- a near-miss that gets
    every other part of DOT rendering (digraph header, quoting, edges) right.
    """
    old = "if node.UpToDate != nil && *node.UpToDate {"
    new = "if false && node.UpToDate != nil && *node.UpToDate {"

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "graph.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-dot-dashed",
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


def _honest_json_result(scenario_id, expected):
    nodes = {}
    for name, spec in expected["nodes"].items():
        node = {
            "name": name,
            "desc": spec["desc"],
            "location": {"taskfile": "Taskfile.yml", "line": 3, "column": 3},
            "deps": list(spec["deps"]),
            "method": "checksum",
        }
        if not expected["no_status"]:
            node["up_to_date"] = False
        nodes[name] = node

    edges = []
    for frm, to, typ in expected.get("edges", []):
        edge = {"from": frm, "to": to, "type": typ}
        vars_map = expected.get("edges_vars", {}).get((frm, to))
        if vars_map is not None:
            edge["vars"] = dict(vars_map)
        edges.append(edge)

    if "depth_groups" in expected:
        depth_groups = expected["depth_groups"]
    elif "depth_groups_min_len" in expected:
        depth_groups = [expected["depth_groups_first"]]
        while len(depth_groups) < expected["depth_groups_min_len"]:
            depth_groups.append([f"_pad{len(depth_groups)}"])
    else:
        depth_groups = [[name] for name in nodes]

    if "longest_path" in expected:
        longest_path = expected["longest_path"]
    elif "longest_path_len" in expected:
        count = expected["longest_path_len"]
        longest_path = (
            [expected["longest_path_first"]] + ["_mid"] * (count - 2) + [expected["longest_path_last"]]
        )
    elif "longest_path_min_len" in expected:
        count = expected["longest_path_min_len"]
        longest_path = [expected["longest_path_first"]] + ["_mid"] * (count - 1)
    else:
        longest_path = list(nodes)[:1]

    payload = json.dumps({
        "roots": expected["roots"], "nodes": nodes, "edges": edges,
        "depth_groups": depth_groups, "longest_path": longest_path,
    })
    return {"id": scenario_id, "status": "observed", "stdout": payload, "error": ""}


# A fixed, self-contained honest text-tree fixture matching the
# ``text_format`` scenario's Oracle assertions (first line "top", two
# indented children, one "(repeated)" leaf, exactly two occurrences of the
# repeated node's name, and no re-expansion after the repeated marker).
_HONEST_TEXT = "top\n  left\n    bottom\n  right\n    bottom (repeated)\n"


def _honest_result(scenario_id, scenario_def):
    kind = scenario_def["kind"]
    expected = scenario_def["expected"]
    if kind == "error":
        message = "task: dependency involving " + " ".join(expected["contains"])
        return {"id": scenario_id, "status": "graph_error", "stdout": "", "error": message}
    if kind == "json":
        return _honest_json_result(scenario_id, expected)
    if kind == "dot":
        text = "digraph tasks {\n" + "\n".join(expected["contains"]) + "\n}\n"
        return {"id": scenario_id, "status": "observed", "stdout": text, "error": ""}
    if kind == "text":
        return {"id": scenario_id, "status": "observed", "stdout": _HONEST_TEXT, "error": ""}
    raise AssertionError(f"unknown scenario kind {kind!r}")


def _load_oracle_module():
    task = deep_task(NAME)
    oracle_root = Path(
        task.resources.resources["host.task_oracle"].value["source_path"]
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "task_task_graph_export_oracle", oracle_root / "oracle.py"
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
        session.initialize(task, run_seed="task-graph-export-gate4")
        index = 0
        while (
            case := session.next_challenge(
                CHECK_ID, "host.task_oracle", {"max_cases": 8, "max_case_bytes": 65536}
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


def test_oracle_rejects_wrong_node_deps():
    """Findings alone are not sufficient: ``deps`` must exactly match the
    sorted set instruction.md requires for each node.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["status"] != "observed":
                continue
            try:
                payload = json.loads(result["stdout"])
            except (ValueError, TypeError):
                continue
            for name, node in payload.get("nodes", {}).items():
                if node.get("deps"):
                    node["deps"] = list(reversed(node["deps"])) + ["forged-extra-dep"]
                    result["stdout"] = json.dumps(payload)
                    done["applied"] = True
                    return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "no case with a non-empty deps list was found"
    assert verdict.passed is False


def test_oracle_rejects_cycle_error_missing_cycle_word():
    """The cycle scenario's error text must literally contain "cycle" and both
    task names; a rephrased message that drops one of those must be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "cycle" and result["status"] == "graph_error":
                result["error"] = "task: dependency loop detected involving task-a, task-b"
                done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "no cycle scenario was scheduled"
    assert verdict.passed is False


def test_oracle_rejects_dot_output_missing_dashed_style():
    """The status/DOT scenario requires "dashed" to appear; a candidate that
    never emits it (or that reports success without it) must be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "dot_dashed" and result["status"] == "observed":
                result["stdout"] = result["stdout"].replace("dashed", "solid")
                done["applied"] = True

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "no dot_dashed scenario was scheduled"
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
