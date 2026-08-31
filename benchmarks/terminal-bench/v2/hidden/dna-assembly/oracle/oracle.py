"""Host-only Oracle for the dna-assembly artifact conversion."""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path
from typing import Any

from securebench.verification.oligotm import primer3_oligotm_v1


CHECK_ID = "primers_artifact"
ARTIFACT_ID = "primers"
REQUIRED_PRIMERS = (
    "input_fwd",
    "input_rev",
    "egfp_fwd",
    "egfp_rev",
    "flag_fwd",
    "flag_rev",
    "snap_fwd",
    "snap_rev",
)
DNA = re.compile(r"[atcg]+")
COMPLEMENT = str.maketrans("acgt", "tgca")


class PrimerFailure(ValueError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def _load_sequences() -> dict[str, str]:
    lines = Path(__file__).with_name("sequences.fasta").read_text(
        encoding="ascii"
    ).splitlines()
    if len(lines) != 10:
        raise RuntimeError("invalid trusted sequence fixture")
    sequences: dict[str, str] = {}
    for index in range(0, len(lines), 2):
        header = lines[index]
        sequence = lines[index + 1]
        if not header.startswith(">") or DNA.fullmatch(sequence) is None:
            raise RuntimeError("invalid trusted sequence fixture")
        sequences[header[1:]] = sequence
    if set(sequences) != {"input", "egfp", "flag", "snap", "output"}:
        raise RuntimeError("invalid trusted sequence fixture")
    return sequences


SEQUENCES = _load_sequences()


def _reverse_complement(sequence: str) -> str:
    return sequence.translate(COMPLEMENT)[::-1]


def _candidate_lines(text: str) -> list[str]:
    # Match text-mode universal-newline iteration and the source verifier's
    # per-line rstrip behavior.
    return [line.rstrip() for line in io.StringIO(text, newline=None)]


def _parse_primers(text: str) -> dict[str, str]:
    lines = _candidate_lines(text)
    if len(lines) != 16:
        raise PrimerFailure("invalid_line_count")

    primers: dict[str, str] = {}
    for index in range(0, len(lines), 2):
        header = lines[index]
        primer = lines[index + 1].lower()
        if not header.startswith(">"):
            raise PrimerFailure("invalid_primer_header")
        if DNA.fullmatch(primer) is None:
            raise PrimerFailure("invalid_primer_sequence")
        primers[header[1:]] = primer

    if any(name not in primers for name in REQUIRED_PRIMERS):
        raise PrimerFailure("missing_required_primer")
    return primers


def _parse_bsai_primer(primer: str) -> tuple[str, str]:
    site_start = primer.find("ggtctc")
    if site_start == -1:
        raise PrimerFailure("missing_bsai_site")
    if site_start < 1:
        raise PrimerFailure("missing_bsai_clamp")
    overhang_start = site_start + len("ggtctc") + 1
    if len(primer) < overhang_start + 5:
        raise PrimerFailure("incomplete_bsai_primer")
    return primer[overhang_start : overhang_start + 4], primer[overhang_start + 4 :]


def _make_fragment(
    template: str,
    forward_primer: str,
    reverse_primer: str,
    *,
    circular: bool = False,
) -> tuple[str, str, str]:
    forward_overhang, forward_binding = _parse_bsai_primer(forward_primer)
    reverse_overhang, reverse_binding = _parse_bsai_primer(reverse_primer)
    reverse_binding_rc = _reverse_complement(reverse_binding)

    searched_template = template + template if circular else template
    start = searched_template.find(forward_binding)
    if start == -1:
        raise PrimerFailure("forward_binding_site_missing")
    start_after = start + len(forward_binding)
    end = searched_template.find(reverse_binding_rc, start_after)
    if end == -1:
        raise PrimerFailure("reverse_binding_site_missing")

    maximum_forward_overlap = min(4, start)
    forward_overlap = next(
        (
            count
            for count in range(maximum_forward_overlap, 0, -1)
            if searched_template[start - count : start] == forward_overhang[-count:]
        ),
        0,
    )
    forward_annealing = searched_template[
        start - forward_overlap : start + len(forward_binding)
    ]

    right = end + len(reverse_binding_rc)
    maximum_reverse_overlap = min(4, len(searched_template) - right)
    reverse_overlap = next(
        (
            count
            for count in range(maximum_reverse_overlap, 0, -1)
            if searched_template[right : right + count]
            == _reverse_complement(reverse_overhang[-count:])
        ),
        0,
    )
    reverse_annealing = searched_template[end : right + reverse_overlap]

    if not 15 <= len(forward_annealing) <= 45:
        raise PrimerFailure("forward_annealing_length")
    if not 15 <= len(reverse_annealing) <= 45:
        raise PrimerFailure("reverse_annealing_length")

    forward_tm = primer3_oligotm_v1(forward_annealing)
    reverse_tm = primer3_oligotm_v1(reverse_annealing)
    if not 58 <= forward_tm <= 72:
        raise PrimerFailure("forward_tm_out_of_range")
    if not 58 <= reverse_tm <= 72:
        raise PrimerFailure("reverse_tm_out_of_range")
    if abs(forward_tm - reverse_tm) > 5:
        raise PrimerFailure("primer_pair_tm_mismatch")

    internal = forward_binding + searched_template[start_after:end] + reverse_binding_rc
    return forward_overhang, internal, reverse_overhang


def _validate_primers(text: str) -> None:
    primers = _parse_primers(text)
    vector_left, vector_internal, vector_right = _make_fragment(
        SEQUENCES["input"],
        primers["input_fwd"],
        primers["input_rev"],
        circular=True,
    )
    egfp_left, egfp_internal, egfp_right = _make_fragment(
        SEQUENCES["egfp"], primers["egfp_fwd"], primers["egfp_rev"]
    )
    flag_left, flag_internal, flag_right = _make_fragment(
        SEQUENCES["flag"], primers["flag_fwd"], primers["flag_rev"]
    )
    snap_left, snap_internal, snap_right = _make_fragment(
        SEQUENCES["snap"], primers["snap_fwd"], primers["snap_rev"]
    )

    if egfp_left != _reverse_complement(vector_right):
        raise PrimerFailure("vector_egfp_overhang_mismatch")
    if flag_left != _reverse_complement(egfp_right):
        raise PrimerFailure("egfp_flag_overhang_mismatch")
    if snap_left != _reverse_complement(flag_right):
        raise PrimerFailure("flag_snap_overhang_mismatch")
    if vector_left != _reverse_complement(snap_right):
        raise PrimerFailure("snap_vector_overhang_mismatch")
    if len({vector_right, egfp_right, flag_right, snap_right}) != 4:
        raise PrimerFailure("duplicate_junction_overhang")

    assembled = (
        vector_left
        + vector_internal
        + egfp_left
        + egfp_internal
        + flag_left
        + flag_internal
        + snap_left
        + snap_internal
    )
    output = SEQUENCES["output"]
    if assembled not in output + output:
        raise PrimerFailure("assembled_sequence_mismatch")


class DnaAssemblyOracle:
    def __init__(self) -> None:
        self.evaluated = False
        self.passed = False
        self.failure = "not_evaluated"

    def evaluate(self, evidence: dict[str, Any]) -> None:
        self.evaluated = True
        if (
            evidence.get("check_id") != CHECK_ID
            or evidence.get("artifact_id") != ARTIFACT_ID
        ):
            self.failure = "uncorrelated_artifact"
            return
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
            self.failure = "invalid_primers_artifact"
            return
        try:
            _validate_primers(text)
        except PrimerFailure as exc:
            self.failure = exc.category
            return

        self.passed = True
        self.failure = ""

    def verdict(self) -> dict[str, Any]:
        passed = self.evaluated and self.passed
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {CHECK_ID: passed},
                "public_diagnostics": {
                    "message": (
                        "Primers satisfy the declared assembly constraints"
                        if passed
                        else "Primers are missing or do not satisfy the assembly constraints"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = DnaAssemblyOracle()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "initialize":
                response = {"type": "ack"}
            elif operation == "evaluate_artifact":
                evidence = request.get("evidence")
                if not isinstance(evidence, dict):
                    raise ValueError("artifact evidence is required")
                oracle.evaluate(evidence)
                response = {"type": "ack"}
            elif operation == "finalize":
                response = oracle.verdict()
            else:
                raise ValueError("unsupported Oracle operation")
        except Exception:
            response = {"type": "error"}
        print(json.dumps(response, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
