"""Bounded Primer3-compatible oligonucleotide melting temperatures."""

from __future__ import annotations

import math


MAX_OLIGO_BASES = 64

# SantaLucia 1998 nearest-neighbor parameters, represented with the same
# integer scaling used by Primer3: dH in -100 cal/mol and dS in
# -0.1 cal/(K mol).
_SANTALUCIA_DH_DS = {
    "AA": (79, 222),
    "AC": (84, 224),
    "AG": (78, 210),
    "AT": (72, 204),
    "CA": (85, 227),
    "CC": (80, 199),
    "CG": (106, 272),
    "CT": (78, 210),
    "GA": (82, 222),
    "GC": (98, 244),
    "GG": (80, 199),
    "GT": (84, 224),
    "TA": (72, 213),
    "TC": (82, 222),
    "TG": (85, 227),
    "TT": (79, 222),
}

_COMPLEMENT = str.maketrans("ACGT", "TGCA")
_DNA_NM = 500.0
_MONOVALENT_MM = 50.0
_DIVALENT_MM = 2.0
_DNTP_MM = 0.8
_GAS_CONSTANT = 1.987
_KELVIN_OFFSET = 273.15


def primer3_oligotm_v1(sequence: str) -> float:
    """Return Primer3 ``oligotm`` Tm for the reviewed fixed parameter set.

    This implements ``-tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500`` without
    invoking a host executable. Input is restricted to a short unambiguous DNA
    oligo so hostile candidate text cannot select another algorithm or consume
    unbounded resources.
    """
    if not isinstance(sequence, str):
        raise TypeError("oligo must be text")
    oligo = sequence.upper()
    if not 2 <= len(oligo) <= MAX_OLIGO_BASES:
        raise ValueError("oligo length is outside the supported bound")
    if any(base not in "ACGT" for base in oligo):
        raise ValueError("oligo must contain only A, C, G, and T")

    symmetric = oligo == oligo.translate(_COMPLEMENT)[::-1]
    enthalpy = 0
    entropy = 14 if symmetric else 0

    for terminal in (oligo[0], oligo[-1]):
        if terminal in "AT":
            enthalpy -= 23
            entropy -= 41
        else:
            enthalpy -= 1
            entropy += 28

    for index in range(len(oligo) - 1):
        pair_enthalpy, pair_entropy = _SANTALUCIA_DH_DS[
            oligo[index : index + 2]
        ]
        enthalpy += pair_enthalpy
        entropy += pair_entropy

    delta_h = enthalpy * -100.0
    delta_s = entropy * -0.1
    effective_monovalent_mm = _MONOVALENT_MM + 120.0 * math.sqrt(
        max(0.0, _DIVALENT_MM - _DNTP_MM)
    )
    delta_s += 0.368 * (len(oligo) - 1) * math.log(
        effective_monovalent_mm / 1000.0
    )
    concentration_divisor = 1_000_000_000.0 if symmetric else 4_000_000_000.0
    return (
        delta_h
        / (delta_s + _GAS_CONSTANT * math.log(_DNA_NM / concentration_divisor))
        - _KELVIN_OFFSET
    )
