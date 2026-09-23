"""Host-only Oracle for the protein-assembly artifact conversion.

Reproduces the source verifier's predicate over /app/gblock.txt exactly:

  * exactly one line, after the source's per-line rstrip();
  * the line matches ``[atcg]+`` once lowercased, and is at most 3000 nt;
  * translating frame 0 with the standard genetic code yields the five scored
    segments in the order FLAG - donor - DHFR - acceptor - SNAP;
  * the FLAG segment starts at index 0 and the SNAP segment ends the protein,
    so nothing may flank the fusion;
  * each of the four inter-segment linkers is pure ``[GS]`` and 5..20 aa long;
  * every 50-nucleotide window has a GC count in [15, 35] (30%-70%).

The expected segment sequences stay host-side. Translation is done here rather
than trusted from the candidate, so a candidate cannot assert its own protein.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any


NUCLEOTIDES = re.compile(r"[atcg]+")
LINKER = re.compile(r"[GS]+")
MAX_NUCLEOTIDES = 3000
WINDOW = 50
MIN_WINDOW_GC = 15
MAX_WINDOW_GC = 35
MIN_LINKER = 5
MAX_LINKER = 20

# Standard genetic code, frame 0. Stop codons translate to "*", matching
# Bio.Seq.translate(), so an in-frame stop breaks the segment matches.
BASES = "tcag"
AMINO_ACIDS = (
    "FFLLSSSSYY**CC*W"
    "LLLLPPPPHHQQRRRR"
    "IIIMTTTTNNKKSSRR"
    "VVVVAAAADDEEGGGG"
)
CODON_TABLE = {
    first + second + third: AMINO_ACIDS[index]
    for index, (first, second, third) in enumerate(
        (a, b, c) for a in BASES for b in BASES for c in BASES
    )
}

# Scored segments, in required N-to-C order.
SEGMENTS = {
    "FLAG": (
        "DYKDDDDK"
    ),
    "DONOR": (
        "GSSHHHHHHSSGENLYFQGHMVSKGEELFTGVVPILVELDGDVNGHKFSVRGEGEGDATN"
        "GKLTLKFICTTGKLPVPWPTLVTTFGYGVACFSRYPDHMKQHDFFKSAMPEGYVQERTIS"
        "FKDDGTYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNFNSHNVYITADKQKN"
        "GIKANFKIRHNVEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSHQSALSKDPNEKRDHMV"
        "LLEFVTAAGITHGMDELYK"
    ),
    "DHFR": (
        "ISLIAALAVDRVIGMENAMPWNLPADLAWFKRNTLNKPVIMGRHTWESIGRPLPGRKNII"
        "LSSQPGTDDRVTWVKSVDEAIAACGDVPEIMVIGGGRVYEQFLPKAQKLYLTHIDAEVEG"
        "DTHFPDYEPDDWESVFSEFHDADAQNSHSYCFEILERR"
    ),
    "ACCEPTOR": (
        "VSKGEEDNMAIIKEFMRFKVHMEGSVNGHEFEIEGEGEGRPYEGTQTAKLKVTKGGPLPF"
        "AWDILSPQFMYGSKAYVKHPADIPDYLKLSFPEGFKWERVMNFEDGGVVTVTQDSSLQDG"
        "EFIYKVKLRGTNFPSDGPVMQKKTMGWEASSERMYPEDGALKGEIKQRLKLKDGGHYDAE"
        "VKTTYKAKKPVQLPGAYNVNIKLDITSHNEDYTIVEQYERAEGRHSTGGMDELYK"
    ),
    "SNAP": (
        "GPGSDKDCEMKRTTLDSPLGKLELSGCEQGLHEIIFLGKGTSAADAVEVPAPAAVLGGPE"
        "PLMQATAWLNAYFHQPEAIEEFPVPALHHPVFQQESFTRQVLWKLLKVVKFGEVISYSHL"
        "AALAGNPAATAAVKTALSGNPVPILIPCHRVVQGDLDVGGYEGGLAVKEWLLAHEGHRLG"
        "KR"
    ),
}
ORDER = ["FLAG", "DONOR", "DHFR", "ACCEPTOR", "SNAP"]


def translate(gblock: str) -> str:
    """Translate frame 0, ignoring a trailing partial codon as Biopython does."""
    return "".join(
        CODON_TABLE[gblock[i:i + 3]]
        for i in range(0, len(gblock) - len(gblock) % 3, 3)
    )


def split_source_lines(text: str) -> list[str]:
    """Reproduce ``[line.rstrip() for line in f]`` on the candidate bytes."""
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return [line.rstrip() for line in lines]


class ProteinAssemblyOracle:
    def __init__(self) -> None:
        self.evaluated = False
        self.passed = False
        self.failure = "not_evaluated"

    def _check(self, text: str) -> str:
        lines = split_source_lines(text)
        if len(lines) != 1:
            return "invalid_line_count"
        gblock = lines[0].lower()
        if not gblock or NUCLEOTIDES.fullmatch(gblock) is None:
            return "invalid_nucleotide_alphabet"
        if len(gblock) > MAX_NUCLEOTIDES:
            return "gblock_too_long"

        protein = translate(gblock)
        indices = {name: protein.find(seq) for name, seq in SEGMENTS.items()}
        if any(index < 0 for index in indices.values()):
            return "missing_segment"
        ordered = [indices[name] for name in ORDER]
        if ordered != sorted(ordered) or len(set(ordered)) != len(ordered):
            return "segments_out_of_order"
        if indices["FLAG"] != 0:
            return "gblock_does_not_start_with_flag"

        for current, following in zip(ORDER, ORDER[1:]):
            start = indices[current] + len(SEGMENTS[current])
            linker = protein[start:indices[following]]
            if LINKER.fullmatch(linker) is None:
                return "linker_not_gs"
            if not MIN_LINKER <= len(linker) <= MAX_LINKER:
                return "linker_length_out_of_range"

        if indices["SNAP"] + len(SEGMENTS["SNAP"]) != len(protein):
            return "gblock_does_not_end_with_snap"

        gc = sum(base in "gc" for base in gblock[:WINDOW])
        if not MIN_WINDOW_GC <= gc <= MAX_WINDOW_GC:
            return "gc_content_out_of_range"
        for index in range(WINDOW, len(gblock)):
            gc += (gblock[index] in "gc") - (gblock[index - WINDOW] in "gc")
            if not MIN_WINDOW_GC <= gc <= MAX_WINDOW_GC:
                return "gc_content_out_of_range"
        return ""

    def evaluate(self, evidence: dict[str, Any]) -> None:
        self.evaluated = True
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            self.failure = (
                str(error.get("code", "artifact_rejected"))
                if isinstance(error, dict)
                else "artifact_rejected"
            )
            return
        text = evidence.get("parsed_value")
        if not isinstance(text, str):
            self.failure = "invalid_text"
            return
        self.failure = self._check(text)
        self.passed = self.failure == ""

    def verdict(self) -> dict[str, Any]:
        passed = self.evaluated and self.passed
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {"gblock_artifact": passed},
                "public_diagnostics": {
                    "message": (
                        "gBlock encodes the required fusion protein"
                        if passed
                        else "gBlock does not satisfy the fusion-protein requirements"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = ProteinAssemblyOracle()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "initialize":
                response = {"type": "ack"}
            elif operation == "evaluate_artifact":
                evidence = request.get("evidence")
                if not isinstance(evidence, dict):
                    raise ValueError("artifact evidence required")
                oracle.evaluate(evidence)
                response = {"type": "ack"}
            elif operation == "finalize":
                response = oracle.verdict()
            else:
                raise ValueError("unsupported operation")
        except Exception:
            response = {"type": "error"}
        print(json.dumps(response, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
