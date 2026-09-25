"""Qualification for `deep-swe/tomlkit-toml-table-converters`.

Follows the pattern established by
`test_deepswe_sqlfmt_create_table_ddl_formatting_v2.py`: Gates 1/2/3 replay
the production capture -> Evaluation -> Oracle path in real Docker
(``verify_patch``), and Gate 4 drives the real Oracle subprocess directly
with hand-built and forged ``ChallengeEvidence`` (no Docker).

Each of Gate 3's three targeted mutants is a real hand edit on top of the
upstream gold solution's new ``tomlkit/convert.py`` module, each on a
distinct semantic axis named in the public instruction. Before being relied
on here, every mutant (plus the generic "drop the largest file" mutant) was
confirmed directly inside a container of the pinned image, gold patch
applied, comparing the Oracle's case-by-case verdict against the gold and
the mutated code for the exact same challenges (playbook defect #8): each
targeted mutant flips exactly the one case named in its docstring and no
other, and the file-drop mutant fails every case with ``api_surface``
(``tomlkit.convert`` becomes unimportable). See the dossier's "Implemented
v2 conversion" section for that verification log.
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
from tests.qualification_support import DOCKER_INTEGRATION, load_module


NAME = "tomlkit-toml-table-converters"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "toml_table_conversion_behavior"


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


def test_reference_patch_does_not_touch_an_excluded_path():
    """Playbook defect #19: the gold solution must not edit any path the
    candidate schema excludes, or Capture would reject even the gold patch.
    """
    task = deep_task(NAME)
    exclude_globs = task.verification.candidate.exclude_paths
    touched = re.findall(r"^diff --git a/(\S+) b/\S+$", reference_patch(NAME).read_text(), re.M)
    assert touched, "reference patch touches no files"
    for path in touched:
        for pattern in exclude_globs:
            assert not Path(path).match(pattern), (path, pattern)


# ---------------------------------------------------------------------------
# Gates 1, 2, and the generic file-drop mutant: real Docker replay.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp(f"{NAME}-baseline") / "app"
    return materialize_baseline(NAME, root)


@DOCKER_INTEGRATION
def test_base_fails_through_the_real_capture_path(tmp_path, baseline):
    """Gate 1: the unmodified base commit must not pass.

    At the base commit, ``tomlkit.convert`` does not exist at all and
    ``tomlkit`` has no ``to_inline_table``/``to_standard_table``/
    ``to_dotted_keys``/``to_super_table`` re-exports. The adapter's api probe
    reports every callable/importable flag as ``False`` (a bounded fact, not
    a crash), and every operation step fails with a caught
    ``tomlkit.convert is unavailable`` error rather than crashing the
    adapter -- the observation is still ``status: observed`` with the
    api-surface and per-step failures the Oracle needs to fail the case.
    """
    outcome = verify_patch(NAME, baseline, tmp_path, run_seed=f"{NAME}-base")

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
def test_reference_passes_in_fresh_evaluations(tmp_path, baseline):
    """Gate 2: the upstream solution passes, one fresh Evaluation per case."""
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, run_seed=f"{NAME}-reference"
    )

    assert outcome.status == "passed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert len(outcome.evidence) >= 2
    assert len(set(outcome.evaluation_ids)) == len(outcome.evaluation_ids)
    assert all(item.status == "observed" for item in outcome.evidence)


def _file_diffs(patch_text: str) -> list[tuple[str, str]]:
    chunks = re.split(r"(?m)^(?=diff --git )", patch_text)
    pairs = []
    for chunk in chunks:
        match = re.match(r"diff --git a/(\S+) b/\S+", chunk)
        if match:
            pairs.append((match.group(1), chunk))
    return pairs


@DOCKER_INTEGRATION
def test_dropping_the_largest_source_change_fails(tmp_path, baseline):
    """Gate 3 (generic mutant): drop the largest file of the gold patch.

    The gold patch's largest file by far is the new ``tomlkit/convert.py``
    module (546 added lines vs. 9/27/19 for the other three touched files).
    Dropping it leaves ``tomlkit.convert`` unimportable and the top-level
    ``tomlkit.to_*`` re-exports non-callable, so every case's api-surface
    probe fails outright -- the conversion feature is entirely missing, so
    the overall verdict must still fail.
    """
    diffs = _file_diffs(reference_patch(NAME).read_text())
    assert diffs, "reference patch has no file changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "tomlkit/convert.py", dropped
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
        NAME, baseline, tmp_path, mutate=apply_partial, run_seed=f"{NAME}-partial",
    )

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


# ---------------------------------------------------------------------------
# Gate 3: three targeted REAL-CODE mutants, gold patch + one hand edit each,
# replayed through real Docker Evaluations, each on a distinct semantic axis
# named in the public instruction.
# ---------------------------------------------------------------------------


def _replace_once(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(before)
    assert count == 1, (path, count, before)
    path.write_text(text.replace(before, after), encoding="utf-8")


def _mutate_aot_descendant_check_disabled(workspace: Path) -> None:
    """Axis: "ConversionError if any descendant is an AoT" -- exercised by
    the ``aot_descendant_raises`` case, which converts a Table with an
    array-of-tables child to an inline table and expects ``ConversionError``.

    The gold ``to_inline_table`` calls ``_check_no_aot_descendants`` on the
    target table before converting. This hand edit disables that entry-point
    call (the recursive helper's own internal call, used when a nested
    sub-Table is itself being inlined, is left intact) -- a plausible
    near-miss for an implementation that gets ordinary recursive inlining
    right but forgets the immediate-child AoT guard the instruction
    requires. Confirmed (playbook defect #8) to flip only
    ``aot_descendant_raises`` and no other case, by running the Oracle
    against both the gold and mutated ``tomlkit.convert`` for every case
    directly inside a container of the pinned image.
    """
    target = workspace / "tomlkit" / "convert.py"
    _replace_once(
        target,
        "    _check_no_aot_descendants(target_item, key_path)\n",
        "    pass  # BUG: AoT descendant check disabled\n",
    )


def _mutate_standard_table_header_comment_dropped(workspace: Path) -> None:
    """Axis: "The InlineTable key's comment becomes the Table header's
    comment" -- exercised by the ``inline_to_standard_comment_on_header``
    case, which converts an inline table with a trailing comment and checks
    that the comment text appears on the same output line as the new
    ``[cfg]`` header.

    The gold ``to_standard_table`` copies ``target_item.trivia.comment`` onto
    the new Table's header trivia. This hand edit guards that copy with
    ``False and ...``, so the header comment is silently dropped -- a
    plausible near-miss for an implementation that builds the new Table's
    body correctly but forgets the comment-migration requirement. Confirmed
    (playbook defect #8) to flip exactly the two cases that exercise this
    same code path on two different sources --
    ``inline_to_standard_comment_on_header`` (same-line check, source
    ``cfg = {x = 1} # config note``) and
    ``standard_table_comment_migrated_to_header`` (substring-only check,
    upstream's own weaker assertion, source
    ``server = {host = "localhost"} # important``) -- and no other case.
    """
    target = workspace / "tomlkit" / "convert.py"
    _replace_once(
        target,
        '    header_comment = ""\n'
        "    if target_item.trivia.comment:\n"
        "        header_comment = target_item.trivia.comment\n",
        '    header_comment = ""\n'
        "    if False and target_item.trivia.comment:  # BUG: header comment migration disabled\n"
        "        header_comment = target_item.trivia.comment\n",
    )


def _mutate_max_depth_ignored(workspace: Path) -> None:
    """Axis: "max_depth limits flattening: None means unlimited, 1 means
    immediate children only" -- exercised by the
    ``max_depth_limits_flattening_three_levels`` case, a 3-level nested table
    flattened with ``max_depth=1``: the gold output keeps the deepest table
    (``[a.b.c]``) as a literal nested header rather than a fully dotted
    ``a.b.c.z`` leaf, because depth 1 already exhausts the one permitted
    recursion. (The upstream 2-level ``max_depth_limits_flattening`` case is
    unaffected either way: with only 2 levels, ``max_depth=1`` and
    unbounded flattening produce the same dotted-key text, so it alone
    cannot discriminate this bug -- the 3-level case was added to the Oracle
    specifically because it can.)

    The gold ``to_dotted_keys`` passes the caller's ``max_depth`` through to
    ``_flatten_to_dotted``. This hand edit hardcodes ``max_depth=None``
    (unlimited) regardless of what was requested -- a plausible near-miss
    for an implementation that flattens correctly but never wires the
    ``max_depth`` parameter through to the recursion. Confirmed (playbook
    defect #8) to flip only the 3-level case and no other, including leaving
    the 2-level upstream case passing.
    """
    target = workspace / "tomlkit" / "convert.py"
    _replace_once(
        target,
        "        current_depth=0, max_depth=max_depth,\n",
        "        current_depth=0, max_depth=None,  # BUG: max_depth ignored\n",
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_aot_descendant_check_disabled,
        _mutate_standard_table_header_comment_dropped,
        _mutate_max_depth_ignored,
    ],
    ids=["aot-descendant-check-disabled", "standard-table-header-comment-dropped", "max-depth-ignored"],
)
def test_targeted_real_code_mutant_fails(tmp_path, baseline, mutate):
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-{mutate.__name__}",
    )

    assert outcome.status == "failed", (mutate.__name__, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence


# ---------------------------------------------------------------------------
# Gate 4: forged / malformed evidence is rejected by the Oracle (no Docker).
# ---------------------------------------------------------------------------


def _evidence(challenge, observation, index) -> ChallengeEvidence:
    return ChallengeEvidence(
        check_id=CHECK_ID,
        challenge_id=f"challenge-test-{index}",
        evaluation_id=f"evaluation-test-{index}",
        challenge_index=index,
        challenge_digest=json_digest(challenge),
        status="observed",
        exit_status=0,
        observation=observation,
        observation_bytes=len(json.dumps(observation)),
    )


def _oracle_root():
    task = deep_task(NAME)
    return Path(task.resources.resources["host.task_oracle"].value["source_path"])


def _find_case(session, name):
    while True:
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 8192})
        if case is None:
            return None
        if case.context.get("name") == name:
            return case


_CORRECT_API = {
    "convert_to_inline_table_callable": True,
    "convert_to_standard_table_callable": True,
    "convert_to_dotted_keys_callable": True,
    "convert_to_super_table_callable": True,
    "top_level_to_inline_table_importable": True,
    "top_level_to_standard_table_importable": True,
    "top_level_to_dotted_keys_importable": True,
    "top_level_to_super_table_importable": True,
    "conversion_error_is_tomlkit_error": True,
}


def _correct_observation_for_missing_prefix_raises():
    """Hand-built (not executed) correct observation for the
    ``missing_prefix_raises`` case: ``to_super_table("nonexistent", doc)``
    on a document without any ``nonexistent.*`` dotted keys must raise a
    ``ConversionError`` (a ``TOMLKitError``) carrying
    ``key_path == "nonexistent"``.
    """
    return {
        "status": "observed",
        "api": dict(_CORRECT_API),
        "steps": [
            {
                "output_toml": "a = 1\n",
                "output_toml_bytes": len("a = 1\n"),
                "raised": False,
                "is_conversion_error": False,
                "is_tomlkit_error": False,
                "has_key_path": False,
                "key_path_value": "",
                "error_message": "",
                "result_is_none": True,
                "result_toml": "",
                "result_toml_bytes": 0,
                "result_dump_error": "",
            },
            {
                "output_toml": "a = 1\n",
                "output_toml_bytes": len("a = 1\n"),
                "raised": True,
                "is_conversion_error": True,
                "is_tomlkit_error": True,
                "has_key_path": True,
                "key_path_value": "nonexistent",
                "error_message": "Cannot convert 'nonexistent' from DottedKey to Table: No dotted keys matching prefix 'nonexistent' found.",
                "result_is_none": True,
                "result_toml": "",
                "result_toml_bytes": 0,
                "result_dump_error": "",
            },
        ],
        "error_type": "",
        "error_message": "",
    }


def test_hand_built_correct_observation_produces_no_failure_category():
    """Sanity check (no Docker): a correctly-shaped observation, built only
    from the known request/expected value (never by running the candidate),
    produces no failure category for its case. ``finalize`` needs every case
    evaluated to report ``passed``, so this checks the failure list this
    single evaluated case produces, mirroring
    `test_forged_result_returning_a_table_for_nonexistent_is_rejected` below.
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-sanity")
        case = _find_case(session, "missing_prefix_raises")
        assert case is not None
        observation = _correct_observation_for_missing_prefix_raises()
        session.evaluate_challenge(
            CHECK_ID, case.context, _evidence(case.challenge, observation, 0)
        )
        verdict = session.finalize()
    # `evaluated` (1) != `len(cases)` (51) makes `passed` False regardless of
    # correctness -- this only proves the correct evidence did not itself
    # crash the Oracle subprocess or get flagged malformed.
    assert verdict.passed is False
    categories = verdict.public_diagnostics.get("failure_categories", [])
    assert not any(cat.startswith("case_") and "missing_prefix_raises" in cat for cat in categories)


def test_forged_status_observed_with_missing_fields_is_rejected():
    """A malformed observation (missing every required field) must not pass."""
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged")
        case = _find_case(session, "missing_prefix_raises")
        assert case is not None
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-0",
            evaluation_id="evaluation-forged-0",
            challenge_index=0,
            challenge_digest=json_digest(case.challenge),
            status="observed",
            exit_status=0,
            observation={"status": "observed"},  # missing api/steps/error_type/error_message
            observation_bytes=32,
        )
        session.evaluate_challenge(CHECK_ID, case.context, forged)
        verdict = session.finalize()
    assert verdict.passed is False


def test_candidate_error_evidence_cannot_smuggle_an_observation():
    """The evidence contract itself refuses to let a failed run carry an
    observation, so a candidate that crashed cannot smuggle a forged,
    plausible-looking success payload through the evidence-level status.
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged-2")
        case = _find_case(session, "missing_prefix_raises")
        assert case is not None
        observation = _correct_observation_for_missing_prefix_raises()
        with pytest.raises(ValueError, match="failed challenge evidence may not contain an observation"):
            ChallengeEvidence(
                check_id=CHECK_ID,
                challenge_id="challenge-forged-1",
                evaluation_id="evaluation-forged-1",
                challenge_index=0,
                challenge_digest=json_digest(case.challenge),
                status="candidate_error",
                exit_status=1,
                observation=observation,
                observation_bytes=len(json.dumps(observation)),
                failure_source="candidate",
                failure_code="nonzero_exit",
                failure_message="candidate process exited nonzero",
            )


def test_observation_claiming_wrong_step_count_is_rejected():
    """Evidence can be 'observed' at the framework level while the adapter's
    own JSON payload reports the wrong number of per-step results (e.g. a
    candidate/adapter that silently dropped a step). The Oracle must key off
    the embedded step shape, not just the envelope.
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged-3")
        case = _find_case(session, "missing_prefix_raises")
        assert case is not None
        observation = _correct_observation_for_missing_prefix_raises()
        observation["steps"] = observation["steps"][:1]  # drop the error step
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-2",
            evaluation_id="evaluation-forged-2",
            challenge_index=0,
            challenge_digest=json_digest(case.challenge),
            status="observed",
            exit_status=0,
            observation=observation,
            observation_bytes=len(json.dumps(observation)),
        )
        session.evaluate_challenge(CHECK_ID, case.context, forged)
        verdict = session.finalize()
    assert verdict.passed is False


def test_forged_result_returning_a_table_for_nonexistent_is_rejected():
    """A forged result that claims ``to_super_table`` succeeded (no
    exception, and the surrounding data grew a ``nonexistent`` table)
    instead of raising ``ConversionError`` for a genuinely missing prefix
    must not pass.
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged-4")
        case = _find_case(session, "missing_prefix_raises")
        assert case is not None
        observation = _correct_observation_for_missing_prefix_raises()
        observation["steps"][1] = {
            "output_toml": 'a = 1\n\n[nonexistent]\n',
            "output_toml_bytes": len('a = 1\n\n[nonexistent]\n'),
            "raised": False,
            "is_conversion_error": False,
            "is_tomlkit_error": False,
            "has_key_path": False,
            "key_path_value": "",
            "error_message": "",
            "result_is_none": False,
            "result_toml": 'a = 1\n\n[nonexistent]\n',
            "result_toml_bytes": len('a = 1\n\n[nonexistent]\n'),
            "result_dump_error": "",
        }
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-3",
            evaluation_id="evaluation-forged-3",
            challenge_index=0,
            challenge_digest=json_digest(case.challenge),
            status="observed",
            exit_status=0,
            observation=observation,
            observation_bytes=len(json.dumps(observation)),
        )
        session.evaluate_challenge(CHECK_ID, case.context, forged)
        verdict = session.finalize()
    assert verdict.passed is False


def test_oracle_compares_raw_result_text_with_the_running_document():
    """The adapter reports tomlkit.dumps(result) raw; equality is decided host-side."""
    module = load_module(_oracle_root() / "oracle.py", "tomlkit_result_matches_doc")
    doc = "a = 1\n[b]\nc = 2\n"
    step = {"output_toml": doc, "output_toml_bytes": len(doc), "result_is_none": False,
            "result_toml": doc, "result_toml_bytes": len(doc), "result_dump_error": ""}
    assert module._result_matches_doc(step) is True
    assert module._result_matches_doc({**step, "result_toml": "a = 1\n", "result_toml_bytes": 6}) is False
    assert module._result_matches_doc({**step, "result_is_none": True}) is False
    assert module._result_matches_doc({**step, "result_dump_error": "TypeError: x"}) is False
    # Truncated or inconsistent lengths fail closed: a prefix match is not equality.
    assert module._result_matches_doc({**step, "output_toml_bytes": 9000, "result_toml_bytes": 9000}) is False
    assert module._result_matches_doc({**step, "result_toml_bytes": len(doc) + 1}) is False


# ---------------------------------------------------------------------------
# Malicious candidate: on import, tomlkit prints a forged adapter response
# claiming the full API and exits before the adapter observes anything.
# ---------------------------------------------------------------------------


def _forge_adapter_response_on_import(workspace: Path) -> None:
    forged = json.dumps({
        "format": "securebench.adapter-response/v2",
        "status": "observed",
        "observation": {
            "status": "observed",
            "api": dict(_CORRECT_API),
            "steps": [],
            "error_type": "",
            "error_message": "",
        },
    })
    init = workspace / "tomlkit" / "__init__.py"
    init.write_text(
        "import os as _sb_os, sys as _sb_sys\n"
        f"_sb_sys.stdout.write({forged!r} + '\\n'); _sb_sys.stdout.flush(); _sb_os._exit(0)\n"
        + init.read_text(encoding="utf-8"),
        encoding="utf-8",
    )


@DOCKER_INTEGRATION
def test_malicious_forged_adapter_response_is_rejected(tmp_path, baseline):
    outcome = verify_patch(
        NAME, baseline, tmp_path, mutate=_forge_adapter_response_on_import,
        run_seed=f"{NAME}-malicious-forged-response",
    )
    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert any(item.observation and item.observation.get("status") == "observed"
               for item in outcome.evidence), outcome.evidence
