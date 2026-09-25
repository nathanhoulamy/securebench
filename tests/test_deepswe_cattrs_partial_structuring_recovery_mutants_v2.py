"""Targeted real-code mutant coverage for `deep-swe/cattrs-partial-structuring-recovery`.

This row was admitted (`docs/benchmark-conversions/inventory.csv`) with only
Oracle-level synthetic mutants
(`tests/test_pilot_conversions_v2.py::test_protocol_oracles_accept_reference_observations_and_reject_targeted_mutants`,
hand-built ``ChallengeEvidence``) and the generic "drop the largest non-test
file" real-code mutant
(`tests/test_deepswe_first_wave_replay_v2.py::test_incomplete_implementation_mutant_fails`)
running under real Docker. Per the conversion playbook's Gate 3, a row needs
at least three *targeted* real-code mutants -- the gold patch plus one hand
edit each, each a plausible near-miss on a distinct semantic axis taken from
the instruction or an upstream ``test.patch`` assertion -- replayed through
the real capture -> Evaluation -> Oracle path. This file adds exactly that,
following the pattern in
`tests/test_deepswe_tomlkit_toml_table_converters_v2.py`.

All three mutants hand-edit the gold `src/cattrs/partial.py` (the only
non-trivial file the solution patch adds; `src/cattrs/__init__.py` and
`src/cattrs/converters.py` only wire up the public entry points). Each
targets a distinct field/case in the Oracle's fixed case list
(`benchmarks/deep-swe/v2/hidden/cattrs-partial-structuring-recovery/oracle/oracle.py`)
and, before being wired in here, was confirmed (playbook defect #8) to flip
exactly that case's snapshot comparison and no other by tracing the
mutated control flow against the Oracle's `evaluate` method by hand and then
replaying the mutant under real Docker (see the dossier's "Review
correction: real-code mutants" section for the resulting pytest summary).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.deepswe_qualification import materialize_baseline, verify_patch
from tests.qualification_support import DOCKER_INTEGRATION


NAME = "cattrs-partial-structuring-recovery"


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp(f"{NAME}-baseline") / "app"
    return materialize_baseline(NAME, root)


def _replace_once(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(before)
    assert count == 1, (path, count, before)
    path.write_text(text.replace(before, after), encoding="utf-8")


def _mutate_nested_partial_field_misclassified(workspace: Path) -> None:
    """Axis: "if the nested object is only partially complete, use its
    partial value and mark the parent field as failed" -- exercised by the
    Oracle's ``nested_attrs`` case (challenge ``{"inner": {"x": 2, "y": 99},
    "z": 5}``), which expects ``structured_fields == ["z"]`` and
    ``failed_fields == ["inner"]`` even though a partial value for ``inner``
    was produced and used. This is also the upstream
    ``TestNestedClasses.test_nested_partial_propagates`` assertion:
    ``assert "inner" in r.failed_fields`` even though ``r.value.inner`` is
    populated with the partial nested value.

    The gold ``_build_partial_from_sets`` computes ``can_partial`` (fields
    recoverable via nested nested partial structuring) purely to decide
    whether it is even possible to assemble a value; it does not use
    ``can_partial`` to change field classification. This hand edit promotes
    every ``can_partial`` field from ``failed_fields`` into
    ``structured_fields`` before assembling the value -- a plausible
    near-miss for an implementation that reasons "we produced a value for
    it, so it succeeded" instead of following the instruction's explicit
    "mark the parent field as failed" rule. The assembled value is
    unchanged (same nested partial value is used either way), so only the
    field-set classification diverges.
    """
    target = workspace / "src" / "cattrs" / "partial.py"
    _replace_once(
        target,
        "    try:\n"
        "        partial_value = _structure_with_partial_data(\n"
        "            converter, data, cl, successful_fields, failed_fields,\n"
        "            structuring_fields, key_map\n"
        "        )\n"
        "        return _make_result(\n"
        "            converter, cl, data,\n"
        "            value=partial_value, is_complete=False,\n"
        "            structured_fields=successful_fields,\n"
        "            failed_fields=failed_fields,\n"
        "            errors=errors, error_map=error_map,\n"
        "        )\n",
        "    # BUG: fields recovered via nested partial structuring are\n"
        "    # promoted to \"structured\" instead of staying \"failed\".\n"
        "    successful_fields = successful_fields | can_partial\n"
        "    failed_fields = failed_fields - can_partial\n"
        "    try:\n"
        "        partial_value = _structure_with_partial_data(\n"
        "            converter, data, cl, successful_fields, failed_fields,\n"
        "            structuring_fields, key_map\n"
        "        )\n"
        "        return _make_result(\n"
        "            converter, cl, data,\n"
        "            value=partial_value, is_complete=False,\n"
        "            structured_fields=successful_fields,\n"
        "            failed_fields=failed_fields,\n"
        "            errors=errors, error_map=error_map,\n"
        "        )\n",
    )


def _mutate_refine_overwrites_structured_fields(workspace: Path) -> None:
    """Axis: "fixing failed fields with new data while preserving
    structured fields ... Only data for fields in failed_fields is used
    from the new data dict" -- exercised by the Oracle's refine case
    (index 9: initial ``{"a": 13, "b": 99}`` structures ``a`` and fails
    ``b``, then ``.refine({"a": 999, "b": [token]})`` must keep ``a == 13``
    while fixing ``b``). This is also the upstream
    ``TestRefine.test_preserves_successful_fields`` /
    ``test_complete_result_unchanged`` assertions
    (``assert refined.value.a == 1  # unchanged``).

    The gold ``PartialResult.refine`` only copies a key from the new
    ``data`` dict into the merged input when that field name is in
    ``self.failed_fields``. This hand edit drops that guard for
    attrs/dataclass targets, so every key the caller supplies overwrites
    the merged input regardless of whether the field already structured
    successfully -- a plausible near-miss for an implementation that
    forgets ``refine`` is meant to *repair*, not *replace*.
    """
    target = workspace / "src" / "cattrs" / "partial.py"
    _replace_once(
        target,
        "            for field_name in data:\n"
        "                if field_name in self.failed_fields:\n"
        "                    alias_key = name_to_key.get(field_name, field_name)\n"
        "                    if alias_key != field_name and alias_key in merged:\n"
        "                        del merged[alias_key]\n"
        "                    merged[alias_key] = data[field_name]\n",
        "            for field_name in data:\n"
        "                # BUG: overwrites already-structured fields too,\n"
        "                # not just failed ones.\n"
        "                alias_key = name_to_key.get(field_name, field_name)\n"
        "                if alias_key != field_name and alias_key in merged:\n"
        "                    del merged[alias_key]\n"
        "                merged[alias_key] = data[field_name]\n",
    )


def _mutate_init_false_fields_not_excluded(workspace: Path) -> None:
    """Axis: "Exclude init=False fields from structured_fields and
    failed_fields" -- exercised by the Oracle's ``init_false`` case
    (challenge ``{"a": 11}`` against a class with ``internal: int =
    field(init=False, default=7)``), which expects ``is_complete: True``,
    ``structured_fields: ["a"]``, ``failed_fields: []``. This is also the
    upstream ``TestInitFalseFields.test_attrs_init_false_excluded``
    assertion: ``assert "c" not in r.structured_fields and "c" not in
    r.failed_fields``.

    The gold ``_get_structuring_fields`` filters ``fields(cl)`` down to
    ``f.init`` fields before anything else touches them, so an ``init=False``
    field never enters the missing/structured/failed accounting at all. This
    hand edit drops that filter -- a plausible near-miss for an
    implementation that forgets ``init=False`` fields exist and iterates
    every field cattrs/dataclasses report. Because ``internal`` is absent
    from the challenge's input dict, it now counts as a *missing* field,
    flipping the case from complete/no-failures to incomplete with
    ``failed_fields: ["internal"]``.
    """
    target = workspace / "src" / "cattrs" / "partial.py"
    _replace_once(
        target,
        'def _get_structuring_fields(cl: type) -> list:\n'
        '    """Get fields that participate in structuring (init=True only)."""\n'
        '    return [f for f in fields(cl) if f.init]\n',
        'def _get_structuring_fields(cl: type) -> list:\n'
        '    """Get fields that participate in structuring (init=True only)."""\n'
        '    # BUG: no longer filters out init=False fields.\n'
        '    return list(fields(cl))\n',
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_nested_partial_field_misclassified,
        _mutate_refine_overwrites_structured_fields,
        _mutate_init_false_fields_not_excluded,
    ],
    ids=[
        "nested-partial-field-misclassified",
        "refine-overwrites-structured-fields",
        "init-false-fields-not-excluded",
    ],
)
def test_targeted_real_code_mutant_fails(tmp_path, baseline, mutate):
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-{mutate.__name__}",
    )

    assert outcome.status == "failed", (mutate.__name__, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence


# ---------------------------------------------------------------------------
# Malicious candidate: on import, the package prints a forged adapter response
# claiming success (API present, ordinary structure() correct) and exits before
# the adapter can observe anything. It must be rejected by the Oracle.
# ---------------------------------------------------------------------------

_FORGED_RESPONSE = {
    "format": "securebench.adapter-response/v2",
    "status": "observed",
    "observation": {
        "status": "observed",
        "api": {"partial_result_exported": True, "top_level_callable": True,
                "converter_method": True, "base_converter_method": True},
        "ordinary_structure": {
            "valid_input": {"outcome": "value", "value_type": "_observe.<locals>.Ordinary",
                            "value_json": '{"a":1,"b":"ok"}', "exception_type": ""},
            "invalid_input": {"outcome": "exception", "value_type": "", "value_json": "",
                              "exception_type": "ClassValidationError"},
        },
        "snapshots": [],
        "legacy_error_roundtrips": [],
        "factory_calls": 0,
        "error_type": "",
        "error_message": "",
    },
}


def _forge_adapter_response_on_import(workspace: Path) -> None:
    import json

    init = workspace / "src" / "cattrs" / "__init__.py"
    forged = json.dumps(_FORGED_RESPONSE)
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
    # The forged response really reached the Oracle as a schema-valid observation.
    assert any(item.observation and item.observation.get("status") == "observed"
               for item in outcome.evidence), outcome.evidence
