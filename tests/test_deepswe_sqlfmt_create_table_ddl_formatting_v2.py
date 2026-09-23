"""Qualification for `deep-swe/sqlfmt-create-table-ddl-formatting`.

Follows the pattern established by
`test_deepswe_python_statemachine_state_data_scoping_v2.py`: Gates 1/2/3
replay the production capture -> Evaluation -> Oracle path in real Docker
(`verify_patch`), and Gate 4 drives the real Oracle subprocess directly with
hand-built and forged ``ChallengeEvidence`` (no Docker).

Each of Gate 3's three targeted mutants is a real hand edit on top of the
upstream gold solution's new DDL support (``merger.py``, ``rules/ddl.py``,
``node_manager.py``), each on a distinct semantic axis named in the public
instruction. Before being relied on here, every mutant was confirmed to flip
exactly its intended case(s) and no others -- the ``unique`` misclassification
mutant directly inside a container of the pinned image (playbook defect #8;
gold vs. mutated ``parse_ddl_table`` output compared for the same source),
the other two through the same real-Docker path used below; see the
dossier's "Implemented v2 conversion" section for that verification log.
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


NAME = "sqlfmt-create-table-ddl-formatting"
ROW_ID = f"deep-swe/{NAME}"
CHECK_ID = "create_table_ddl_behavior"


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

    At the base commit, CREATE TABLE is not handled by any DDL-specific rule:
    it lexes as ordinary tokens, so the formatter neither indents columns nor
    lowercases keywords -- every ``format`` step's result diverges from what
    the Oracle expects -- and ``sqlfmt.ddl`` does not exist at all, so every
    ``parse_ddl``/``make_column``/``make_constraint``/``make_table`` step
    fails with ``ModuleNotFoundError``. The adapter catches every per-step
    exception and reports a bounded ``ok: false`` for that step rather than
    crashing, so the overall observation is still ``status: observed`` with
    per-step failures for the Oracle to see.
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

    The gold patch's largest file by far is the new ``sqlfmt/ddl.py`` module
    (233 added lines, more than any other file it touches). Dropping it
    leaves ``sqlfmt.ddl`` unimportable, so every ``parse_ddl``/``make_column``/
    ``make_constraint``/``make_table`` step fails outright -- the CREATE
    TABLE *formatting* behaviour is unaffected (it lives in the other files),
    but the Required Module contract is entirely missing, so the overall
    verdict must still fail.
    """
    diffs = _file_diffs(reference_patch(NAME).read_text())
    assert diffs, "reference patch has no file changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    assert dropped == "src/sqlfmt/ddl.py", dropped
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


def _mutate_columns_may_merge(workspace: Path) -> None:
    """Axis: requirement 2, "Each column on its own indented line ... All
    items within the CREATE TABLE parentheses ... are separated by commas" --
    exercised by ``structure_trailing_commas``, ``structure_column_definitions_
    indented``, ``edge_multiple_columns_not_merged``, and every fixture round
    trip (all of which have 3+ columns that must not collapse onto one line).

    The gold ``LineMerger._check_ddl_guards`` raises ``CannotMergeException``
    when more than one column/constraint heading line would be merged
    together (guard 2). This hand edit disables that guard, so a short
    CREATE TABLE body whose columns would otherwise fit within the line
    length gets merged back onto a single line -- a plausible near-miss for
    an implementation that gets column *indentation* right but forgets that
    the merger (which normally collapses short groups) must never re-collapse
    a DDL column list.
    """
    target = workspace / "src" / "sqlfmt" / "merger.py"
    _replace_once(
        target,
        "        if ddl_heading_count > 1:\n"
        "            raise CannotMergeException(\n"
        '                "Cannot merge multiple DDL column/constraint definitions"\n'
        "            )\n",
        "        if False and ddl_heading_count > 1:  # BUG: guard disabled\n"
        "            raise CannotMergeException(\n"
        '                "Cannot merge multiple DDL column/constraint definitions"\n'
        "            )\n",
    )


def _mutate_unique_table_constraint_misclassified(workspace: Path) -> None:
    """Axis: requirement 5, "Table-level constraints (PRIMARY KEY, FOREIGN
    KEY, UNIQUE, CHECK, CONSTRAINT name ...)" -- the instruction names UNIQUE
    explicitly as one of the table-level constraint keywords -- exercised by
    the ``ddl_unique_table_constraint`` case, which parses a table whose only
    table-level constraint is a bare ``unique (name)`` clause and checks
    ``constraint_count == 1`` and a "unique" keyword in ``table_constraints``.

    The gold ``ddl_table_constraint`` lexer rule in ``rules/ddl.py`` matches
    ``primary key|foreign key|unique`` followed by ``(`` as
    ``DDL_TABLE_CONSTRAINT``. This hand edit drops ``unique`` from that
    pattern -- a plausible near-miss for an implementation that gets the two
    keyword-pair constraints right but forgets ``UNIQUE`` is a single bare
    keyword needing the same table-level treatment. ``unique (name)`` is then
    lexed as ``DDL_INLINE_CONSTRAINT`` instead (still matched by the separate
    inline-constraint rule for column-level ``UNIQUE``), so
    ``parse_ddl_table`` silently drops it from ``table_constraints`` --
    ``constraint_count`` goes from 1 to 0. This was confirmed (playbook
    defect #8) to leave CREATE TABLE *formatting* output byte-identical
    (indentation/merging of the surrounding column lines is unaffected) and
    to flip only ``sqlfmt.ddl`` parsing of a bare table-level UNIQUE, by
    running both the gold and mutated ``parse_ddl_table`` directly inside a
    container of the pinned image.
    """
    target = workspace / "src" / "sqlfmt" / "rules" / "ddl.py"
    _replace_once(
        target,
        "        pattern=group(\n"
        '            r"primary\\s+key",\n'
        '            r"foreign\\s+key",\n'
        '            r"unique",\n'
        "        )\n"
        '        + group(r"\\s*\\(")',
        "        pattern=group(\n"
        '            r"primary\\s+key",\n'
        '            r"foreign\\s+key",\n'
        "            # BUG: 'unique' no longer recognised as a table-level constraint\n"
        "        )\n"
        '        + group(r"\\s*\\(")',
    )


def _mutate_if_not_exists_not_lowercased(workspace: Path) -> None:
    """Axis: requirement 7, "All DDL keywords and type names lowercased"
    combined with requirement 8, "CREATE TABLE IF NOT EXISTS is supported" --
    exercised by ``edge_if_not_exists_variant``, which explicitly asserts
    ``"IF NOT EXISTS" not in result``.

    The gold ``_normalize_ddl_header`` lowercases every keyword token in the
    ``DDL_STATEMENT_START`` header except the (possibly-quoted) table name.
    This hand edit special-cases the ``if``/``not``/``exists`` tokens to keep
    their original casing -- a plausible near-miss for an implementation that
    lowercases the ``create table`` prefix and the trailing table name
    correctly but treats the optional ``IF NOT EXISTS`` clause as a separate
    code path it forgot to lowercase.
    """
    target = workspace / "src" / "sqlfmt" / "node_manager.py"
    _replace_once(
        target,
        '    keywords = " ".join(p.lower() for p in parts[:-1])\n',
        "    # BUG: IF/NOT/EXISTS tokens keep their original casing\n"
        '    keywords = " ".join(\n'
        '        p if p.lower() in ("if", "not", "exists") else p.lower() for p in parts[:-1]\n'
        "    )\n",
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_columns_may_merge,
        _mutate_unique_table_constraint_misclassified,
        _mutate_if_not_exists_not_lowercased,
    ],
    ids=["columns-may-merge", "unique-table-constraint-misclassified", "if-not-exists-not-lowercased"],
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
        case = session.next_challenge(CHECK_ID, "host.task_oracle", {"max_cases": 64, "max_case_bytes": 16384})
        if case is None:
            return None
        if case.context.get("name") == name:
            return case


def _correct_observation_for_ddl_returns_none_for_select():
    """Hand-built (not executed) correct observation for the
    ``ddl_returns_none_for_select`` case: ``parse_ddl_table`` on a plain
    ``select`` query must return ``None``.
    """
    steps = [{"op": "parse_ddl", "ok": True, "table": None}]
    return {
        "status": "observed",
        "error_type": "",
        "error_message": "",
        "results_json": json.dumps(steps, sort_keys=True),
    }


def test_hand_built_correct_observation_produces_no_failure_category():
    """Sanity check (no Docker): a correctly-shaped observation, built only
    from the known request/expected value (never by running the candidate),
    produces no failure category for its case. ``finalize`` needs every case
    evaluated to report ``passed``, so this checks the failure list this
    single evaluated case produces, mirroring
    `test_forged_result_returning_a_table_for_select_is_rejected` below.
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-sanity")
        case = _find_case(session, "ddl_returns_none_for_select")
        assert case is not None
        observation = _correct_observation_for_ddl_returns_none_for_select()
        session.evaluate_challenge(
            CHECK_ID, case.context, _evidence(case.challenge, observation, 0)
        )
        verdict = session.finalize()
    # `evaluated` (1) != `len(cases)` (49) makes `passed` False regardless of
    # correctness -- this only proves the correct evidence did not itself
    # crash the Oracle subprocess or get flagged malformed.
    assert verdict.passed is False
    categories = verdict.public_diagnostics.get("failure_categories", [])
    assert not any(cat.startswith("ddl_returns_none_for_select:") for cat in categories)


def test_forged_status_observed_with_missing_fields_is_rejected():
    """A malformed observation (missing every required field) must not pass."""
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged")
        case = _find_case(session, "ddl_returns_none_for_select")
        assert case is not None
        forged = ChallengeEvidence(
            check_id=CHECK_ID,
            challenge_id="challenge-forged-0",
            evaluation_id="evaluation-forged-0",
            challenge_index=0,
            challenge_digest=json_digest(case.challenge),
            status="observed",
            exit_status=0,
            observation={"status": "observed"},  # missing error_type/error_message/results_json
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
        case = _find_case(session, "ddl_returns_none_for_select")
        assert case is not None
        observation = _correct_observation_for_ddl_returns_none_for_select()
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
        case = _find_case(session, "ddl_returns_none_for_select")
        assert case is not None
        observation = {
            "status": "observed",
            "error_type": "",
            "error_message": "",
            "results_json": json.dumps([], sort_keys=True),  # missing the one expected step
        }
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


def test_forged_result_returning_a_table_for_select_is_rejected():
    """A forged result that claims ``parse_ddl_table`` returned a table for
    a plain ``select`` query (instead of ``None``) must not pass.
    """
    with OracleProcessSession(_oracle_root()) as session:
        session.initialize(deep_task(NAME), run_seed=f"{NAME}-forged-4")
        case = _find_case(session, "ddl_returns_none_for_select")
        assert case is not None
        steps = [
            {
                "op": "parse_ddl",
                "ok": True,
                "table": {
                    "table_name": "t",
                    "column_count": 1,
                    "constraint_count": 0,
                    "columns": [{"name": "a", "type_name": "int64", "has_inline_constraint": False}],
                    "table_constraints": [],
                    "constrained_columns": [],
                    "unconstrained_columns": ["a"],
                },
            }
        ]
        observation = {
            "status": "observed",
            "error_type": "",
            "error_message": "",
            "results_json": json.dumps(steps, sort_keys=True),
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
