"""Real-capture Docker qualification for
``deep-swe/obsidian-linter-auto-table-of-contents``.

A TypeScript-library conversion whose public surface is
``Rule#apply(text, options)`` on obsidian-linter's single new ``AutoToc``
rule builder: a pure, synchronous Markdown-in/Markdown-out transform driven
by a Markdown document and a complete options object. ``driver.test.ts`` is
copied into the pinned project's own ``__tests__/`` tree and run through the
project's own offline ``npx jest``, for the same reason as the sibling
``obsidian-linter-scoped-ignore-markers`` conversion: this pnpm-managed
project reaches transitive (non-hoisted) dependencies that only jest's own
pnpm-aware resolver finds offline (playbook defect #17: check what the image
actually ships).

The Oracle's case corpus (``build_cases()`` in ``oracle.py``) is transcribed
verbatim from the upstream hidden test file this task adds
(``tests/test.patch``'s ``__tests__/auto-toc.test.ts``): every
``before``/``after``/``options`` triple was captured by mechanically
intercepting the upstream ``ruleTest`` helper's own
``expect(rule.apply(testCase.before, options)).toBe(testCase.after)``
assertion under the pinned image's own jest (dedent-expanding the actual
template literals), never retyped or derived by running the gold patch
(playbook defect #9). All 41 upstream F2P assertions are included. Unlike
the sibling conversion, ``tests/test.patch`` here adds only the one new test
file and touches no existing test, so there is no companion P2P tail from
the same hidden file.
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


NAME = "obsidian-linter-auto-table-of-contents"
HIDDEN = Path(__file__).resolve().parents[1] / "benchmarks/deep-swe/v2/hidden" / NAME
ORACLE_MODULE = load_module(HIDDEN / "oracle" / "oracle.py", "obsidian_linter_auto_table_of_contents_oracle")


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
    assert "adapters/obsidian-linter-auto-table-of-contents" not in str(task.view_for("agent"))
    assert "adapters/obsidian-linter-auto-table-of-contents" in str(task.view_for("evaluation_runtime"))


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

    ``src/utils/toc.ts`` (254 added lines -- the entire TOC generation,
    anchor-building, and heading-extraction implementation, marginally the
    largest hunk in the gold patch; the next largest is
    ``src/rules/auto-toc.ts`` at 247 lines) is dropped, while
    ``src/rules/auto-toc.ts``, ``src/rules/rule-builder.ts``,
    ``src/rules-runner.ts`` and ``src/lang/locale/en.ts`` are kept, so
    ``src/rules/auto-toc.ts`` imports a module that no longer exists -- a
    plausible almost-there submission (wired the rule up but never committed
    the new utility file).
    """
    diffs = _file_diffs(reference_patch(NAME).read_text())
    assert diffs
    dropped, _ = max(diffs, key=lambda pair: pair[1].count("\n+"))
    assert dropped == "src/utils/toc.ts"
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


def _mutate_toc(old: str, new: str, *, count: int = 1):
    return _mutate_file("src/utils/toc.ts", old, new, count=count)


SEMANTIC_MUTANTS = {
    # Axis: "Ensure blank lines after the start marker, after an optional
    # title line, before the end marker, and after the end marker." This
    # mutant drops one of the two blank lines around the regenerated TOC
    # content in the branch that updates an *existing* end marker (the
    # "insert a brand-new end marker" branch two lines below is left
    # correct), a plausible partial fix: getting blank-line layout right
    # only for the simpler "no end marker yet" case. Verified by direct
    # reproduction against the real gold + mutant under the pinned image's
    # own jest: 37 of the 41 upstream assertions fail (every case whose
    # `before` already carries a closing `<!-- /toc -->`), while the 4
    # cases that hit the other branch (`Only start marker present`,
    # `No TOC markers present`, `No headings matching range produces empty
    # TOC`, and the analogous empty-content path) still pass.
    "toc-content-blank-line-layout-collapsed": _mutate_toc(
        "    if (tocContent === '') {\n"
        "      return `${before}\\n\\n${after}`;\n"
        "    }\n"
        "\n"
        "    return `${before}\\n\\n${tocContent}\\n\\n${after}`;\n"
        "  }",
        "    if (tocContent === '') {\n"
        "      return `${before}\\n\\n${after}`;\n"
        "    }\n"
        "\n"
        "    return `${before}\\n${tocContent}\\n${after}`;\n"
        "  }",
    ),
    # Axis: "Exclude headings inside the TOC region" (a named public
    # instruction requirement, independent of the YAML/code/math ignore
    # boundaries). This mutant drops the `tocStart`/`tocEnd` range check in
    # `extractHeadings`, so a stale ATX heading left between the markers is
    # wrongly counted (and would itself keep reappearing in every
    # subsequent regeneration). Verified by direct reproduction: exactly
    # `headings-inside-toc-region-are-excluded-from-toc-generation` fails
    # (1 of 41), every other upstream assertion still passes, confirming
    # this mutant targets only this axis.
    "toc-region-heading-exclusion-removed": _mutate_toc(
        "    if (tocStart !== -1 && matchStart >= tocStart && matchStart < tocEnd) {\n"
        "      continue;\n"
        "    }\n"
        "\n",
        "",
    ),
    # Axis: "With useExplicitIds, a trailing {#id} provides the base
    # anchor." This mutant drops the `useExplicitIds` branch entirely, so a
    # trailing `{#custom-id}` is never parsed out of the heading text even
    # when the option is enabled -- a plausible "wired the option through
    # but never consulted it in the one place it matters" mistake, since
    # `useExplicitIds` is still read correctly everywhere else (the
    # `Boolean(options.useExplicitIds)` coercion in `auto-toc.ts` is
    # untouched). Verified by direct reproduction: exactly the two upstream
    # assertions that enable `useExplicitIds`
    # (`explicit-heading-ids-are-used-as-anchors-when-enabled` and
    # `explicit-heading-ids-are-deduplicated-when-repeated`) fail (2 of
    # 41), every other upstream assertion still passes.
    "explicit-heading-id-parsing-disabled": _mutate_toc(
        "    const headingParts = options.useExplicitIds ? parseExplicitHeadingId(heading.text) : "
        "{displayText: heading.text, explicitId: null};",
        "    const headingParts = {displayText: heading.text, explicitId: null};",
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
    oracle = ORACLE_MODULE.AutoTocOracle()
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
    assert len(oracle.cases) == 2
    # Restores every one of the 41 upstream F2P assertions (playbook
    # #20/#24): bundling several items into one Evaluation is a
    # transport-level grouping, never a dropped assertion.
    assert sum(len(case["expect"]) for case in oracle.cases) == 41
    for case in oracle.cases:
        assert set(case["challenge"]) == {"items"}
        for item in case["challenge"]["items"]:
            # No grading directive or expected-answer marker of any kind
            # crosses into the Evaluation environment (AGENTS.md): each
            # item carries only id/before/options, never an "after"/
            # "expect" field.
            assert set(item) == {"id", "before", "options"}


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
    case = _find_case(oracle.cases, "auto-toc-marker-and-options")
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


# ---------------------------------------------------------------------------
# Gate 4 (candidate level): malicious patches go through real capture and
# Evaluation and must be rejected, not reported as infrastructure errors.
# ---------------------------------------------------------------------------

_FORGED_RESULT_JS = """\
const fs = require('fs');
// Forge a well-formed "observed" result without implementing the rule: echo
// every challenge input back as its output.
try {
  const challenge = JSON.parse(fs.readFileSync(process.env.SECUREBENCH_CHALLENGE_PATH, 'utf8'));
  const items = challenge.items.map((item) => ({id: item.id, status: 'observed', after: item.before, error: ''}));
  fs.writeFileSync(process.env.SECUREBENCH_RESULT_PATH, JSON.stringify({status: 'observed', error: '', items}));
} catch (error) {}
"""


def _jest_setup_hijack(workspace: Path) -> None:
    """Install a jest setup file (outside the excluded test paths) that writes a
    forged adapter result before the real driver runs."""
    (workspace / "scripts" / "zz-securebench-hook.js").write_text(_FORGED_RESULT_JS, encoding="utf-8")
    config = workspace / "jest.config.ts"
    text = config.read_text(encoding="utf-8")
    anchor = "const config: Config.InitialOptions = {\n"
    assert text.count(anchor) == 1
    config.write_text(
        text.replace(anchor, anchor + "  setupFiles: ['<rootDir>/scripts/zz-securebench-hook.js'],\n"),
        encoding="utf-8",
    )


def _forged_driver_test(workspace: Path) -> None:
    """Ship a jest test that writes a forged result; __tests__/** is excluded
    from the captured candidate, so it must never reach Evaluation."""
    (workspace / "__tests__" / "zz_forged.test.ts").write_text(
        _FORGED_RESULT_JS.replace("const fs = require('fs');", "import * as fs from 'fs';")
        + "\nit('forged', () => {});\n",
        encoding="utf-8",
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize("attack", [
    pytest.param(_jest_setup_hijack, id="jest_setup_forged_result"),
    pytest.param(_forged_driver_test, id="forged_driver_test_file"),
])
def test_malicious_candidates_are_rejected(tmp_path, baseline, attack):
    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=attack, run_seed=f"{NAME}-malicious-{attack.__name__}",
    )
    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    if attack is _jest_setup_hijack:
        # The forged result really reached the Oracle (well-formed and
        # "observed"), so the rejection is the Oracle's, not a missing output.
        assert any(
            item.observation and item.observation.get("status") == "observed"
            for item in outcome.evidence
        ), outcome.evidence
