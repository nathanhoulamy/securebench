"""Targeted real-code mutant coverage for `deep-swe/fd-deterministic-multi-key-sorting`.

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

All three mutants hand-edit the gold `src/sort.rs` (the solution patch's new
sorting module; `src/cli.rs`, `src/config.rs`, `src/main.rs` and `src/walk.rs`
only wire the new CLI flags and config through). Each targets a distinct
scenario in the Oracle's fixed case list
(`benchmarks/deep-swe/v2/hidden/fd-deterministic-multi-key-sorting/oracle/oracle.py`)
and, before being wired in here, was confirmed (playbook defect #8) to flip
that scenario's ordering check under real Docker (see the dossier's "Review
correction: real-code mutants" section for the resulting pytest summary).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.deepswe_qualification import materialize_baseline, verify_patch
from tests.qualification_support import DOCKER_INTEGRATION


NAME = "fd-deterministic-multi-key-sorting"


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp(f"{NAME}-baseline") / "app"
    return materialize_baseline(NAME, root)


def _replace_once(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(before)
    assert count == 1, (path, count, before)
    path.write_text(text.replace(before, after), encoding="utf-8")


def _mutate_type_rank_swaps_symlink_and_file(workspace: Path) -> None:
    """Axis: "For --sort type, entries are ordered by kind: directory <
    symlink < regular file < other/unknown" -- exercised by the Oracle's
    ``type_order`` scenario (a regular file, a directory, a symlink to the
    file, and a fifo, sorted with ``--sort type``), which expects
    ``["d/", "s", "f", "p"]``: directory, then symlink, then regular file,
    then the fifo (other/unknown).

    The gold ``EntryTypeRank::rank`` assigns ``Directory => 0``,
    ``Symlink => 1``, ``File => 2``. This hand edit swaps the symlink and
    file ranks -- a plausible near-miss for an implementation that assumes
    "real" files should sort ahead of symlinks to them, contradicting the
    instruction's explicit ordering. Only the two-way tie between symlink
    and file kinds changes; directory-first and other-last are untouched.
    """
    target = workspace / "src" / "sort.rs"
    _replace_once(
        target,
        "            Self::Directory => 0,\n"
        "            Self::Symlink => 1,\n"
        "            Self::File => 2,\n",
        "            Self::Directory => 0,\n"
        "            // BUG: symlink and file ranks swapped.\n"
        "            Self::Symlink => 2,\n"
        "            Self::File => 1,\n",
    )


def _mutate_size_defined_for_non_files(workspace: Path) -> None:
    """Axis: "For --sort size, size is only defined for regular files.
    Directories, symlinks, and other non-file entries must be treated as
    missing size values" -- exercised by the Oracle's ``size_missing_last``
    scenario (a 2-byte file, an 8-byte file, an empty directory, and a
    symlink to the small file, sorted by ``--sort size
    --sort-missing-last``), which expects ``["small", "big", "folder/",
    "link"]``: both non-file entries pushed to the end by
    ``--sort-missing-last``, in path order.

    The gold ``file_size`` returns ``None`` for anything whose
    ``metadata().file_type()`` is not a regular file. This hand edit drops
    that guard, so a symlink's own raw byte size (the length of its link
    target string on Linux, here ``len("small") == 5``) is reported as a
    real size -- a plausible near-miss for an implementation that forgets
    non-file entries need special-casing and just forwards whatever the
    filesystem reports. That inserts the symlink between the two real files
    by size (2 < 5 < 8) instead of placing it after them per
    ``--sort-missing-last``.
    """
    target = workspace / "src" / "sort.rs"
    _replace_once(
        target,
        "fn file_size(entry: &DirEntry) -> Option<u64> {\n"
        "    entry.metadata().and_then(|metadata| {\n"
        "        if metadata.file_type().is_file() {\n"
        "            Some(metadata.len())\n"
        "        } else {\n"
        "            None\n"
        "        }\n"
        "    })\n"
        "}\n",
        "fn file_size(entry: &DirEntry) -> Option<u64> {\n"
        "    // BUG: no longer restricted to regular files.\n"
        "    entry.metadata().and_then(|metadata| Some(metadata.len()))\n"
        "}\n",
    )


def _mutate_natural_sort_leading_zeros(workspace: Path) -> None:
    """Axis: "Natural sort with names that have leading zeros in digit runs
    (e.g. file007 vs file7)" -- an Edge Case named verbatim in the public
    instruction, exercised by the Oracle's ``natural_leading_zeros``
    scenario (``file7.txt`` and ``file007.txt`` sorted with
    ``--sort name --sort-natural``), which expects
    ``["file007.txt", "file7.txt"]``: the digit runs "007" and "7" are
    numerically equal (both 7), so the tie falls through to the raw path
    tiebreak, where "0" sorts before "7".

    The gold ``natural_compare`` parses each digit run to a ``u128`` and
    compares the parsed values. This hand edit instead compares digit-run
    *lengths* first, falling back to a plain string comparison only when
    lengths are equal -- a plausible near-miss "longer number is bigger"
    heuristic that happens to agree with true numeric comparison whenever
    neither run has a leading zero (as in the ``natural_name`` scenario's
    ``file20``/``file9``/``file10``, which this mutant leaves passing), but
    disagrees exactly when a leading zero pads the digit run to a different
    length than an equal-valued run, as in ``natural_leading_zeros``: "007"
    (length 3) is judged greater than "7" (length 1), reversing the
    expected order.
    """
    target = workspace / "src" / "sort.rs"
    _replace_once(
        target,
        "            let a_num: u128 = a_rest[..a_len].parse().unwrap_or(u128::MAX);\n"
        "            let b_num: u128 = b_rest[..b_len].parse().unwrap_or(u128::MAX);\n"
        "            let ord = a_num.cmp(&b_num);\n",
        "            // BUG: compares digit-run length before numeric value,\n"
        "            // so leading zeros are not treated as insignificant.\n"
        "            let ord = if a_len != b_len {\n"
        "                a_len.cmp(&b_len)\n"
        "            } else {\n"
        "                a_rest[..a_len].cmp(&b_rest[..b_len])\n"
        "            };\n",
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "mutate",
    [
        _mutate_type_rank_swaps_symlink_and_file,
        _mutate_size_defined_for_non_files,
        _mutate_natural_sort_leading_zeros,
    ],
    ids=[
        "type-rank-swaps-symlink-and-file",
        "size-defined-for-non-files",
        "natural-sort-leading-zeros",
    ],
)
def test_targeted_real_code_mutant_fails(tmp_path, baseline, mutate):
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-{mutate.__name__}",
    )

    assert outcome.status == "failed", (mutate.__name__, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence
