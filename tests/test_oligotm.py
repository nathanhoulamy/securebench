from __future__ import annotations

import pytest

from securebench.verification.oligotm import MAX_OLIGO_BASES, primer3_oligotm_v1


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        pytest.param("ATGCATGCATGCAT", 52.510059, id="mixed_nonsymmetric"),
        pytest.param("CGCGCGCGCGCGCG", 75.595151, id="gc_symmetric"),
        pytest.param("AAAAAAAAAAAAAAA", 35.909095, id="terminal_at"),
        pytest.param("GCGCGCGCGCGCGCGCGCGC", 86.919995, id="terminal_gc"),
        pytest.param(
            "ACTGACTGACTGACTGACTGACTGACTGACTGACTGACTGACT",
            75.767175,
            id="forty_five_bases",
        ),
        pytest.param("CGATCGATCGATCGATCGAT", 61.004895, id="in_range"),
        pytest.param("agctagctagctagct", 55.427367, id="lowercase_cli_semantics"),
    ],
)
def test_primer3_oligotm_v1_matches_primer3_2_6_1(sequence, expected):
    assert primer3_oligotm_v1(sequence) == pytest.approx(expected, abs=5e-7)


@pytest.mark.parametrize(
    "sequence",
    [
        "",
        "A",
        "A" * (MAX_OLIGO_BASES + 1),
        "ACGTN",
        "AC GT",
        "ACGT\x00",
        "ÁCGT",
    ],
)
def test_primer3_oligotm_v1_rejects_out_of_contract_text(sequence):
    with pytest.raises(ValueError):
        primer3_oligotm_v1(sequence)


def test_primer3_oligotm_v1_rejects_non_text():
    with pytest.raises(TypeError):
        primer3_oligotm_v1(b"ACGT")  # type: ignore[arg-type]
