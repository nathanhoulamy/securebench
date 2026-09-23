"""Build a host-only reference gBlock for the protein-assembly conversion.

Qualification material: it constructs one correct candidate so that gate 2
(reference success) can be proven. It is never mounted into an Agent or
Evaluation environment, and it is not the scoring Oracle.

The fusion protein is FLAG - donor - DHFR - acceptor - SNAP with a pure GS
linker between each pair. Reverse translation picks, at each codon, the
synonymous codon that keeps the trailing 50-nucleotide GC count nearest the
midpoint of the required [15, 35] band, which is what makes the window
constraint satisfiable across the AT-rich FLAG start and the GC-rich linkers.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORACLE = HERE.parent / "oracle" / "oracle.py"

spec = importlib.util.spec_from_file_location("protein_assembly_oracle", ORACLE)
oracle_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle_module)

WINDOW = oracle_module.WINDOW
TARGET_GC = (oracle_module.MIN_WINDOW_GC + oracle_module.MAX_WINDOW_GC) / 2

SYNONYMS: dict[str, list[str]] = {}
for codon, amino in oracle_module.CODON_TABLE.items():
    SYNONYMS.setdefault(amino, []).append(codon)

LINKER = "GGSGS"  # 5 aa, inside the required 5..20 band


def reverse_translate(protein: str) -> str:
    nucleotides: list[str] = []
    for amino in protein:
        best, best_cost = None, None
        for codon in sorted(SYNONYMS[amino]):
            trial = nucleotides + list(codon)
            window = trial[-WINDOW:]
            gc = sum(base in "gc" for base in window)
            # Scale the target when the sequence is still shorter than a window.
            target = TARGET_GC * min(len(window), WINDOW) / WINDOW
            cost = abs(gc - target)
            if best_cost is None or cost < best_cost:
                best, best_cost = codon, cost
        nucleotides.extend(best)
    return "".join(nucleotides)


def build() -> str:
    order = oracle_module.ORDER
    protein = LINKER.join(oracle_module.SEGMENTS[name] for name in order)
    return reverse_translate(protein)


def main() -> None:
    gblock = build()
    verdict = oracle_module.ProteinAssemblyOracle()._check(gblock + "\n")
    if verdict:
        raise SystemExit(f"generated reference is not accepted: {verdict}")
    destination = HERE / "reference.txt"
    destination.write_text(gblock + "\n", encoding="utf-8")
    print(f"wrote {destination} ({len(gblock)} nt)")


if __name__ == "__main__":
    main()
