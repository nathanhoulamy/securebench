"""Real-capture Docker qualification for
``deep-swe/obsidian-linter-scoped-ignore-markers``.

A TypeScript-library conversion whose public surface is
``Rule#apply(text)`` on four of obsidian-linter's rule builders
(``no-bare-urls``, ``proper-ellipsis``, ``header-increment``,
``trailing-spaces``): a pure, synchronous Markdown-in/Markdown-out
transform. ``driver.test.ts`` is copied into the pinned project's own
``__tests__/`` tree and run through the project's own offline ``npx jest``,
because this pnpm-managed project reaches transitive (non-hoisted)
dependencies (e.g. ``micromark-extension-frontmatter``, required indirectly
by ``src/utils/mdast.ts``, which every rule reaches via the shared
``customIgnore`` ignore-type) that only jest's own pnpm-aware resolver
finds offline; the image's own ``ts-node`` throws ``MODULE_NOT_FOUND`` on
the same specifier (playbook defect #17: check what the image actually
ships).

The Oracle's case corpus (``build_cases()`` in ``oracle.py``) is
transcribed verbatim from the upstream hidden test file this task adds
(``tests/test.patch``'s ``__tests__/scoped-ignore.test.ts``): every
``before``/``after`` pair was captured by mechanically intercepting the
upstream ``ruleTest`` helper's own
``expect(rule.apply(testCase.before, options)).toBe(testCase.after)``
assertion under the pinned image's own jest (dedent-expanding the actual
template literals), never retyped or derived by running the gold patch
(playbook defect #9). All 33 upstream F2P assertions are included, plus the
16 companion P2P assertions from the very same hidden test file (already
passing at the base commit; the pre-feature marker regex does not
recognise a marker that carries a rule list at all).
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


NAME = "obsidian-linter-scoped-ignore-markers"
HIDDEN = Path(__file__).resolve().parents[1] / "benchmarks/deep-swe/v2/hidden" / NAME
ORACLE_MODULE = load_module(HIDDEN / "oracle" / "oracle.py", "obsidian_linter_scoped_ignore_markers_oracle")


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
    assert task.input["repo"] == "platers/obsidian-linter"
    assert task.input["base_commit"] == "6393b3ab32a2ace1fc24d4b0f5e0f13a179c874f"
    assert task.environment.agent_network.mode == "none"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view
        assert "oracle.py" not in view
    assert "adapters/obsidian-linter-scoped-ignore-markers" not in str(task.view_for("agent"))
    assert "adapters/obsidian-linter-scoped-ignore-markers" in str(task.view_for("evaluation_runtime"))


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

    ``src/utils/scoped-ignore.ts`` (890 added lines -- the entire marker
    parsing/scoping/region-computation implementation, and by far the
    largest hunk in the gold patch; the next largest is the 18-line
    ``feature.md`` design note) is dropped, while ``src/rules-runner.ts``,
    ``src/rules.ts``, ``src/utils/ignore-types.ts`` and
    ``src/utils/regex.ts`` are kept, so ``src/utils/ignore-types.ts``
    imports a module that no longer exists -- a plausible almost-there
    submission (wired the call sites but never committed the new file).
    """
    diffs = _file_diffs(reference_patch(NAME).read_text())
    assert diffs
    dropped, _ = max(diffs, key=lambda pair: pair[1].count("\n+"))
    assert dropped == "src/utils/scoped-ignore.ts"
    kept = "".join(diff for path, diff in diffs if path != dropped)

    def apply_partial(workspace: Path) -> None:
        subprocess.run(
            ["git", "-C", str(workspace), "apply", "--whitespace=nowarn", "-"],
            input=kept.encode(), check=True,
        )

    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=apply_partial, run_seed=f"{NAME}-partial-{dropped.replace('/', '-')}",
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


def _mutate_scoped_ignore(old: str, new: str, *, count: int = 1):
    return _mutate_file("src/utils/scoped-ignore.ts", old, new, count=count)


SEMANTIC_MUTANTS = {
    # Axis: markers are only recognised on a standalone line (only
    # spaces/tabs plus the marker). This mutant drops the `^[\t ]*...[\t
    # ]*$` line-anchoring (and the `m` flag) from the *rule-list* disable
    # regexes, a plausible omission when adding the new rule-list capture
    # group without carrying over the anchoring `regex.ts` already fixed
    # for the plain (no-rule-list) markers. A marker embedded mid-line or
    # after other text (inside a blockquote, after prose) then gets
    # recognised anyway. Caught by
    # markers-must-be-standalone-lines-mid-line-disable-marker-is-ignored
    # and markers-must-be-standalone-lines-blockquote-prefixed-marker-is-ignored
    # (upstream P2P nodes carried in this Oracle's corpus, from the same
    # hidden __tests__/scoped-ignore.test.ts as the F2P nodes).
    "scoped-disable-regex-drops-standalone-line-anchor": _mutate_scoped_ignore(
        "const scopedDisableHTMLRegex = /^[\\t ]*<!-{2,}[\\t ]*linter-disable[\\t ]+"
        "([A-Za-z0-9, \\-]*[A-Za-z0-9][A-Za-z0-9, \\-]*)[\\t ]*-{2,}>[\\t ]*\\r?$/gm;\n"
        "const scopedDisableObsidianRegex = /^[\\t ]*%%[\\t ]*linter-disable[\\t ]+"
        "([A-Za-z0-9, \\-]*[A-Za-z0-9][A-Za-z0-9, \\-]*)[\\t ]*%%[\\t ]*\\r?$/gm;\n",
        "const scopedDisableHTMLRegex = /<!-{2,}[\\t ]*linter-disable[\\t ]+"
        "([A-Za-z0-9, \\-]*[A-Za-z0-9][A-Za-z0-9, \\-]*)[\\t ]*-{2,}>/g;\n"
        "const scopedDisableObsidianRegex = /%%[\\t ]*linter-disable[\\t ]+"
        "([A-Za-z0-9, \\-]*[A-Za-z0-9][A-Za-z0-9, \\-]*)[\\t ]*%%/g;\n",
    ),
    # Axis: markers inside YAML frontmatter, fenced/indented code, inline
    # code, and math blocks must never scope anything. This mutant makes
    # `getIgnoredRangesForScopedIgnoreMarkers` return no protected ranges
    # at all, a plausible regression from refactoring that function (or
    # from believing the shared `customIgnore` ignore-type already covers
    # this, which it does for content *replacement* but not for marker
    # *recognition*). Caught by all four
    # markers-inside-{yaml-frontmatter,fenced-code-blocks,inline-code,math-blocks}-are-ignored
    # nodes plus markers-inside-indented-code-blocks-are-ignored (upstream
    # P2P nodes, same hidden test file).
    "protected-context-detection-disabled": _mutate_scoped_ignore(
        "function getIgnoredRangesForScopedIgnoreMarkers(text: string): IndexRange[] {\n"
        "  const ranges: IndexRange[] = [];\n",
        "function getIgnoredRangesForScopedIgnoreMarkers(text: string): IndexRange[] {\n"
        "  const ranges: IndexRange[] = [];\n"
        "  return ranges;\n",
    ),
    # Axis: a rule-list `linter-enable` inside a still-open disable-all
    # scope must re-enable only the listed rule(s) for the rest of that
    # scope -- disabling all rules and selectively re-enabling one is a
    # named requirement, not just closing the whole scope. This mutant
    # drops the filter that excludes a disable-all region's rules once
    # they were selectively re-enabled, a plausible "wire the region up
    # but forget to consult `enabledRules`" mistake elsewhere in the same
    # function that correctly builds `enabledRules` in the first place.
    # Caught by disable-all-rule-list-enable-re-enables-only-listed-rule-within-the-still-open-all-scope,
    # rule-list-enable-targets-nearest-disabling-scope-... and
    # rule-list-enable-normalizes-case-removes-duplicates-and-ignores-unknown-aliases
    # (all upstream F2P nodes).
    "disable-all-selective-reenable-filter-dropped": _mutate_scoped_ignore(
        "  const disableAllWithEnabled = getCachedDisableAllRegionsWithEnabledRules(text)\n"
        "    .filter((r) => !r.enabledRules.includes(normalizedRuleAlias))\n"
        "    .map((r) => ({startIndex: r.startIndex, endIndex: r.endIndex}));\n",
        "  const disableAllWithEnabled = getCachedDisableAllRegionsWithEnabledRules(text)\n"
        "    .map((r) => ({startIndex: r.startIndex, endIndex: r.endIndex}));\n",
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

    def _observed(evidence_item) -> bool:
        if not evidence_item.observation:
            return False
        return evidence_item.observation.get("status") == "observed"

    # At least one Evaluation genuinely ran (as opposed to every case
    # erroring out on infrastructure grounds, which would not demonstrate
    # that the Oracle actually caught the *semantic* defect).
    assert any(_observed(item) for item in outcome.evidence)


# ---------------------------------------------------------------------------
# Gate 4: forged / malformed observations are rejected by the Oracle directly.
# ---------------------------------------------------------------------------


def _oracle_with_cases():
    oracle = ORACLE_MODULE.ScopedIgnoreOracle()
    oracle.initialize({"run_seed": "qualification"})
    return oracle


def _good_items(case):
    return [
        {"id": item_id, "status": "observed", "after": after, "error": ""}
        for item_id, after in case["expect"].items()
    ]


def _good_evidence(case):
    observation = {"status": "observed", "error": "", "items": _good_items(case)}
    return {"status": "observed", "observation": observation}


def _find_case(cases, case_id):
    return next(c for c in cases if c["id"] == case_id)


def _context(case):
    return {"id": case["id"], "expect": case["expect"]}


def test_challenges_contain_no_grading_directives_or_expectations():
    oracle = _oracle_with_cases()
    assert len(oracle.cases) == 4
    # Restores every one of the 33 upstream F2P assertions plus the 16
    # companion P2P assertions from the same hidden test file (playbook
    # #20/#24): bundling several items into one Evaluation is a
    # transport-level grouping, never a dropped assertion.
    assert sum(len(case["expect"]) for case in oracle.cases) == 49
    for case in oracle.cases:
        assert set(case["challenge"]) == {"items"}
        for item in case["challenge"]["items"]:
            # No grading directive or expected-answer marker of any kind
            # crosses into the Evaluation environment (AGENTS.md): each
            # item carries only id/rule/before, never an "after"/"expect"
            # field.
            assert set(item) == {"id", "rule", "before"}


def test_oracle_accepts_the_well_formed_case_set():
    oracle = _oracle_with_cases()
    for case in oracle.cases:
        oracle.evaluate(_context(case), _good_evidence(case))
    assert oracle.failures == []
    assert oracle.verdict()["verdict"]["passed"]


def test_oracle_requires_every_case_and_rejects_repeats():
    oracle = _oracle_with_cases()
    assert not oracle.verdict()["verdict"]["passed"]
    for case in oracle.cases[:-1]:
        oracle.evaluate(_context(case), _good_evidence(case))
    assert not oracle.verdict()["verdict"]["passed"]

    oracle_b = _oracle_with_cases()
    first = oracle_b.cases[0]
    good = _good_evidence(first)
    ctx = _context(first)
    oracle_b.evaluate(ctx, good)
    oracle_b.evaluate(ctx, good)
    assert "repeated_case" in oracle_b.failures
    assert not oracle_b.verdict()["verdict"]["passed"]


@pytest.mark.parametrize("attack", [
    "item_text_tampered", "item_extra_key_injected", "item_missing_key",
    "item_status_error_but_text_matches", "missing_item_id", "extra_item_id_injected",
    "duplicate_item_id", "top_level_candidate_error", "observation_status_error",
    "unexpected_observation_fields", "oversized_after_text", "wrong_item_count",
])
def test_oracle_rejects_forged_or_malformed_observations(attack):
    oracle = _oracle_with_cases()
    case = _find_case(oracle.cases, "no-bare-urls-scoped-ignore")
    items = _good_items(case)
    first_id = items[0]["id"]

    if attack == "item_text_tampered":
        items[0] = dict(items[0], after=items[0]["after"] + " ")
    elif attack == "item_extra_key_injected":
        items[0] = dict(items[0], bogus="x")
    elif attack == "item_missing_key":
        items[0] = {"id": items[0]["id"], "status": items[0]["status"], "after": items[0]["after"]}
    elif attack == "item_status_error_but_text_matches":
        items[0] = dict(items[0], status="error")
    elif attack == "missing_item_id":
        items.pop(0)
    elif attack == "extra_item_id_injected":
        items.append({"id": "bogus-item-id", "status": "observed", "after": "", "error": ""})
    elif attack == "duplicate_item_id":
        items.append(dict(items[0]))
    elif attack == "oversized_after_text":
        items[0] = dict(items[0], after="x" * 20000)
    elif attack == "wrong_item_count":
        items.pop()

    observation = {"status": "observed", "error": "", "items": items}
    evidence = {"status": "observed", "observation": observation}

    if attack == "top_level_candidate_error":
        evidence["status"] = "candidate_error"
    elif attack == "observation_status_error":
        observation["status"] = "error"
    elif attack == "unexpected_observation_fields":
        observation["bogus"] = "x"

    oracle.evaluate(_context(case), evidence)
    assert oracle.failures, (attack, first_id)
    assert not oracle.verdict()["verdict"]["passed"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
