"""Real-capture Docker qualification for ``etree-xml-diff-patch``.

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
``tests/test_deepswe_task_task_graph_export_v2.py``.
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


NAME = "etree-xml-diff-patch"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "etree_diff_patch_behavior"


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
    assert provenance["sha256"] == __import__("hashlib").sha256(patch.read_bytes()).hexdigest()
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

    None of ``Diff``/``GeneratePatch``/``ApplyPatch``/``ReversePatch``/
    ``Merge3Way``/``ElementsDeepEqual``/``DiffSummary`` exist at the base
    commit, so the adapter's driver (which calls them directly, exactly as
    the upstream test suite in ``diff_test.go`` does) fails to build -- a
    legitimate "candidate incomplete" signal, not an infrastructure error.
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

    ``diff.go`` is the largest new file the gold solution adds (the diff
    engine itself: options, LCS-based child diffing, identity matching);
    without it the package fails to build (``Diff``, ``DiffOptions`` and the
    ``OpType``/``IdentityMode`` constants all live there), so even the
    adapter's own driver fails to build.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(NAME).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "diff.go", dropped
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
def test_op_add_uses_element_path_not_parent_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: ``OpAdd.Path`` must be the *parent* element path
    (instruction.md: "For OpAdd, DiffOperation.Path stores the parent
    element path."). This mutant appends the new child's own tag onto the
    add operation's path (a classic off-by-one on "whose path is this"),
    which every ``diff_op_add_parent_path`` challenge case is built to catch
    while every other add-producing diff case still detects an add op with
    some path.
    """
    # There are two `OpAdd` sites in diff.go's diffChildrenOrdered: one
    # (commented "// Real addition") inside the mid-loop branch, and one
    # (uncommented) in the trailing branch handling elements after the last
    # LCS match. `diff_op_add_parent_path`'s fixture (`<root><a>1</a></root>`
    # -> `<root><a>1</a><b>2</b></root>`) exercises the *trailing* branch, so
    # both are mutated for a complete "OpAdd path is wrong" bug.
    commented_old = (
        "\t\t\t\t\t// Real addition\n"
        "\t\t\t\t\tctx.addOp(DiffOperation{\n"
        "\t\t\t\t\t\tType:     OpAdd,\n"
        "\t\t\t\t\t\tPath:     path,\n"
        "\t\t\t\t\t\tNewValue: targetChildren[targetPos].Copy(),\n"
        "\t\t\t\t\t})\n"
    )
    commented_new = (
        "\t\t\t\t\t// Real addition (mutant: path incorrectly includes the child tag)\n"
        "\t\t\t\t\tctx.addOp(DiffOperation{\n"
        "\t\t\t\t\t\tType:     OpAdd,\n"
        "\t\t\t\t\t\tPath:     path + \"/\" + targetChildren[targetPos].Tag,\n"
        "\t\t\t\t\t\tNewValue: targetChildren[targetPos].Copy(),\n"
        "\t\t\t\t\t})\n"
    )
    trailing_old = (
        "\t\t\t\t} else {\n"
        "\t\t\t\t\tctx.addOp(DiffOperation{\n"
        "\t\t\t\t\t\tType:     OpAdd,\n"
        "\t\t\t\t\t\tPath:     path,\n"
        "\t\t\t\t\t\tNewValue: targetChildren[targetPos].Copy(),\n"
        "\t\t\t\t\t})\n"
        "\t\t\t\t}\n"
        "\t\t\t\ttargetPos++\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )
    trailing_new = (
        "\t\t\t\t} else {\n"
        "\t\t\t\t\t// mutant: path incorrectly includes the child tag\n"
        "\t\t\t\t\tctx.addOp(DiffOperation{\n"
        "\t\t\t\t\t\tType:     OpAdd,\n"
        "\t\t\t\t\t\tPath:     path + \"/\" + targetChildren[targetPos].Tag,\n"
        "\t\t\t\t\t\tNewValue: targetChildren[targetPos].Copy(),\n"
        "\t\t\t\t\t})\n"
        "\t\t\t\t}\n"
        "\t\t\t\ttargetPos++\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "diff.go", commented_old, commented_new)
        _apply_gold_then_edit(workspace, "diff.go", trailing_old, trailing_new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-add-path",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_new_attribute_encoding_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: a brand-new attribute (nil ``OldValue``) must serialize as
    ``<add sel="path" type="attribute" name="attrname">value</add>``, never
    with a ``/@attrname`` selector suffix (instruction.md is explicit about
    this distinction from the *existing*-attribute ``<replace>`` case). This
    mutant collapses both branches into the ``/@attrname`` form, which is a
    plausible near-miss for anyone who does not track OldValue nil-ness
    separately in GeneratePatch.
    """
    old = (
        "\t\tcase OpUpdateAttr:\n"
        "\t\t\tif op.NewValue == nil {\n"
        "\t\t\t\t// Remove attribute\n"
        "\t\t\t\tremove := diff.CreateElement(\"remove\")\n"
        "\t\t\t\tremove.CreateAttr(\"sel\", fmt.Sprintf(\"%s/@%s\", op.Path, op.AttrName))\n"
        "\t\t\t} else if op.OldValue == nil {\n"
        "\t\t\t\t// Add attribute\n"
        "\t\t\t\tadd := diff.CreateElement(\"add\")\n"
        "\t\t\t\tadd.CreateAttr(\"sel\", op.Path)\n"
        "\t\t\t\tadd.CreateAttr(\"type\", \"attribute\")\n"
        "\t\t\t\tadd.CreateAttr(\"name\", op.AttrName)\n"
        "\t\t\t\tadd.SetText(fmt.Sprintf(\"%v\", op.NewValue))\n"
        "\t\t\t} else {"
    )
    new = (
        "\t\tcase OpUpdateAttr:\n"
        "\t\t\tif op.NewValue == nil {\n"
        "\t\t\t\t// Remove attribute\n"
        "\t\t\t\tremove := diff.CreateElement(\"remove\")\n"
        "\t\t\t\tremove.CreateAttr(\"sel\", fmt.Sprintf(\"%s/@%s\", op.Path, op.AttrName))\n"
        "\t\t\t} else if false {\n"
        "\t\t\t\t// Add attribute (mutant: branch disabled, always falls through to replace)\n"
        "\t\t\t\tadd := diff.CreateElement(\"add\")\n"
        "\t\t\t\tadd.CreateAttr(\"sel\", op.Path)\n"
        "\t\t\t\tadd.CreateAttr(\"type\", \"attribute\")\n"
        "\t\t\t\tadd.CreateAttr(\"name\", op.AttrName)\n"
        "\t\t\t\tadd.SetText(fmt.Sprintf(\"%v\", op.NewValue))\n"
        "\t\t\t} else {"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "patch.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-attr-add-encoding",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_reverse_patch_keeps_original_order_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: ``ReversePatch`` must process operations in *reverse*
    order (instruction.md: "Reverse order."). This mutant walks the original
    patch's operations forwards instead of backwards, which the
    ``rp_reverse_order`` challenge case (two distinct ops, first reversed op
    must come from the *last* original op) is built to catch, while
    single-operation reverse cases still pass.
    """
    old = (
        "\t// Process operations in reverse order\n"
        "\tops := root.ChildElements()\n"
        "\tfor i := len(ops) - 1; i >= 0; i-- {\n"
        "\t\top := ops[i]"
    )
    new = (
        "\t// Process operations (mutant: forward order, not reversed)\n"
        "\tops := root.ChildElements()\n"
        "\tfor i := 0; i < len(ops); i++ {\n"
        "\t\top := ops[i]"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "reverse.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-reverse-order",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_merge_metadata_not_populated_mutant_fails(tmp_path, baseline):
    """Gate 3, axis: ``Merge3Way`` must populate the result's ``Metadata`` with
    ``merge.base``/``merge.ours``/``merge.theirs`` root tags (instruction.md
    is explicit about the three keys). This mutant removes that population
    entirely while leaving every other merge behavior (application,
    conflicts, resolution) intact -- a near-miss for anyone who treats
    ``Metadata`` as optional bookkeeping.
    """
    old = (
        "\t// Populate merge metadata\n"
        "\tresult.Metadata = map[string]string{}\n"
        "\tif baseRoot := base.Root(); baseRoot != nil {\n"
        "\t\tresult.Metadata[\"merge.base\"] = baseRoot.Tag\n"
        "\t}\n"
        "\tif oursRoot := ours.Root(); oursRoot != nil {\n"
        "\t\tresult.Metadata[\"merge.ours\"] = oursRoot.Tag\n"
        "\t}\n"
        "\tif theirsRoot := theirs.Root(); theirsRoot != nil {\n"
        "\t\tresult.Metadata[\"merge.theirs\"] = theirsRoot.Tag\n"
        "\t}\n"
    )
    new = (
        "\t// Populate merge metadata (mutant: intentionally skipped)\n"
    )

    def mutate(workspace: Path) -> None:
        _apply_gold_then_edit(workspace, "merge.go", old, new)

    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-merge-metadata",
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
        "etree_xml_diff_patch_oracle", oracle_root / "oracle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return task, oracle_root, module


def _honest_result(scenario_id, scenario_def, module):
    """Build a genuinely correct ``result_json`` payload for one scenario, by
    construction from the Oracle's own expectations -- not by re-deriving
    them independently, since this is only meant to prove the Oracle accepts
    a truthful observation (and rejects a dishonest one), not to duplicate
    the Oracle's own correctness logic.
    """
    kind = scenario_def["kind"]
    expected = scenario_def["expected"]

    if kind == "deep_equal":
        payload = {"func_result": expected["func_result"], "method_result": expected["method_result"]}
    elif kind == "default_options":
        payload = dict(expected)
    elif kind == "type_strings":
        payload = {
            "op_type_add": "add", "op_type_remove": "remove", "op_type_replace": "replace",
            "op_type_move": "move", "op_type_update_attr": "update-attr",
            "op_type_update_text": "update-text",
            "conflict_both_modified": "both-modified", "conflict_modify_delete": "modify-delete",
            "conflict_structural": "structural",
            "add_operation_string": "ADD /root/item",
            "move_operation_string": "MOVE /root/a[1] -> /root/a[2]",
            "text_operation_string": "UPDATE-TEXT /root/item[1]: <nil> -> <nil>",
            "attr_operation_string": "UPDATE-ATTR /root/item[@id]: <nil> -> <nil>",
        }
    elif kind == "diff":
        if expected.get("expect_error"):
            payload = {"error": "diff: nil document provided", "ops": []}
        else:
            ops = []
            if "has_op" in expected:
                op = dict(expected["has_op"])
                entry = {"type": op.get("type", "add"), "path": op.get("path_in", [""])[0]
                         if "path_in" in op else op.get("path", ""),
                         "old_path": "", "new_path": "", "attr_name": "",
                         "old_value_kind": "nil", "old_value_str": "", "old_value_tag": "",
                         "old_value_text": "",
                         "new_value_kind": "string" if "new_value_str" in op else "nil",
                         "new_value_str": op.get("new_value_str", ""),
                         "new_value_tag": "", "new_value_text": ""}
                ops.append(entry)
            elif "has_type" in expected:
                ops.append({"type": expected["has_type"], "path": "/root/x", "old_path": "",
                            "new_path": "", "attr_name": "", "old_value_kind": "nil",
                            "old_value_str": "", "old_value_tag": "", "old_value_text": "",
                            "new_value_kind": "nil", "new_value_str": "", "new_value_tag": "",
                            "new_value_text": ""})
            elif expected.get("min_op_count", 0) >= 1 or "no_attr_names" in expected:
                ops.append({"type": "update_attr", "path": "/root", "old_path": "", "new_path": "",
                            "attr_name": "b", "old_value_kind": "string", "old_value_str": "2",
                            "old_value_tag": "", "old_value_text": "",
                            "new_value_kind": "string", "new_value_str": "Y",
                            "new_value_tag": "", "new_value_text": ""})
            payload = {"error": "", "ops": ops}
    elif kind == "generate_patch":
        xml_parts = ['<?xml version="1.0" encoding="UTF-8"?><diff xmlns="urn:ietf:params:xml:ns:patch-ops">']
        xml_parts.extend(expected.get("contains", []))
        xml_parts.append("</diff>")
        payload = {"xml": "".join(xml_parts)}
    elif kind == "apply_patch":
        if expected.get("expect_error"):
            payload = {"error": "patch: nil document provided", "child_tags": [],
                       "inspect_found": False, "inspect_tag": "", "inspect_text": "",
                       "inspect_attr_exists": False, "inspect_attr_value": ""}
        else:
            payload = {"error": "", "child_tags": expected.get("child_tags", []),
                       "inspect_found": expected.get("inspect_found", False),
                       "inspect_tag": expected.get("inspect_tag", ""),
                       "inspect_text": expected.get("inspect_text", ""),
                       "inspect_attr_exists": expected.get("inspect_attr_exists", False),
                       "inspect_attr_value": expected.get("inspect_attr_value", "")}
    elif kind == "reverse_patch":
        if expected.get("expect_error"):
            payload = {"error": "reverse: nil patch document", "xml": "", "child_tags": []}
        else:
            text = "<diff>" + "".join(expected.get("contains", [])) + "</diff>"
            child_tags = []
            if "first_child_tag" in expected:
                child_tags = [expected["first_child_tag"]] * max(expected.get("min_child_tags", 1), 1)
            payload = {"error": "", "xml": text, "child_tags": child_tags}
    elif kind == "merge3way":
        if expected.get("expect_error"):
            payload = {"error": "merge: nil document provided", "inspect_found": [],
                       "inspect_text": [], "has_metadata": False, "metadata": {}, "conflicts": []}
        else:
            conflicts = []
            conflict_types = expected.get("conflict_types") or (
                [expected["has_conflict_type"]] if expected.get("has_conflict_type") else []
            )
            for conflict_type in conflict_types:
                conflicts.append({"path": "/root/item", "type": conflict_type,
                                   "resolved": bool(expected.get("all_resolved")),
                                   "resolution_kind": "string", "resolution_str": "ours"})
            if expected.get("all_resolved") and not conflicts:
                conflicts.append({"path": "/root/item", "type": "both_modified",
                                   "resolved": True, "resolution_kind": "string",
                                   "resolution_str": "ours"})
            n = expected.get("conflicts_count")
            if n is not None:
                conflicts = conflicts[:n]
                while len(conflicts) < n:
                    conflicts.append({"path": "/root/item", "type": "both_modified",
                                       "resolved": False, "resolution_kind": "nil", "resolution_str": ""})
            inspect_found = []
            inspect_text = []
            for _, expect_found, expect_text in expected.get("inspect", []):
                inspect_found.append(expect_found)
                inspect_text.append(expect_text if expect_text is not None else "")
            payload = {"error": "", "inspect_found": inspect_found, "inspect_text": inspect_text,
                       "has_metadata": expected.get("has_metadata", False),
                       "metadata": expected.get("metadata", {}) if expected.get("has_metadata") else {},
                       "conflicts": conflicts}
    elif kind == "merge_conflict_resolve":
        payload = dict(expected)
    elif kind == "diff_summary":
        base = {"additions": 0, "removals": 0, "modifications": 0, "moves": 0, "total": 0,
                "has_changes": False, "string": "0 additions, 0 removals, 0 modifications, 0 moves"}
        base.update(expected)
        payload = base
    elif kind == "pipeline":
        if expected.get("expect_error"):
            payload = {"error": "diff: nil document provided", "applied_xml": "",
                       "inspect_found": [], "inspect_text": []}
        else:
            applied = "".join(expected.get("contains", []))
            inspect_found = []
            inspect_text = []
            for _, expect_found, expect_text in expected.get("inspect", []):
                inspect_found.append(expect_found)
                inspect_text.append(expect_text if expect_text is not None else "")
            payload = {"error": "", "applied_xml": applied, "inspect_found": inspect_found,
                       "inspect_text": inspect_text}
    else:
        raise AssertionError(f"unknown scenario kind {kind!r}")

    return {"id": scenario_id, "status": "observed", "result_json": json.dumps(payload), "error": ""}


def _drive(task, oracle_root, module, *, corrupt=None):
    """Replay every Oracle case, honestly by default.

    ``corrupt(index, context, results, observation_kwargs, evidence_kwargs)``
    may mutate the list of per-step result dicts, the ``build_exit_code``/
    ``build_stderr`` overrides, or the evidence-level ``status`` in place
    before the evidence is sent, to model one adversarial or malformed
    candidate response.
    """
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="etree-xml-diff-patch-gate4")
        index = 0
        while (
            case := session.next_challenge(
                CHECK_ID, "host.task_oracle", {"max_cases": 8, "max_case_bytes": 262144}
            )
        ) is not None:
            context = case.context
            results = [
                _honest_result(sid, module.SCENARIOS[sid], module)
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


def test_oracle_rejects_flipped_deep_equal_result():
    """A candidate that reports the opposite boolean for a deep-equality
    check (e.g. claims two structurally-different elements are equal) must
    be rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "eq_diff_tag":
                payload = json.loads(result["result_json"])
                payload["func_result"] = True
                payload["method_result"] = True
                result["result_json"] = json.dumps(payload)
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "eq_diff_tag scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_wrong_generate_patch_selector():
    """The ``gp_sel_format`` case requires the generated patch XML to contain
    specific ``sel="..."`` selectors; a candidate that mangles one must be
    rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "gp_sel_format":
                payload = json.loads(result["result_json"])
                payload["xml"] = payload["xml"].replace('sel="/root/item[2]"', 'sel="/root/item"')
                result["result_json"] = json.dumps(payload)
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "gp_sel_format scenario was not scheduled"
    assert verdict.passed is False


def test_oracle_rejects_missing_merge_metadata():
    """The ``m_metadata`` case requires the exact ``merge.base``/``merge.ours``/
    ``merge.theirs`` keys; a candidate that omits metadata entirely must be
    rejected.
    """
    done = {"applied": False}

    def corrupt(index, context, results, observation_kwargs, evidence_kwargs):
        if done["applied"]:
            return
        for result in results:
            if result["id"] == "m_metadata":
                payload = json.loads(result["result_json"])
                payload["has_metadata"] = False
                payload["metadata"] = {}
                result["result_json"] = json.dumps(payload)
                done["applied"] = True
                return

    task, oracle_root, module = _load_oracle_module()
    verdict = _drive(task, oracle_root, module, corrupt=corrupt)
    assert done["applied"], "m_metadata scenario was not scheduled"
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
