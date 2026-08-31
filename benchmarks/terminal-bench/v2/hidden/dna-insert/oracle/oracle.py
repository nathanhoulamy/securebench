"""Host-only Oracle for the dna-insert artifact conversion."""

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
DNA = re.compile(r"[acgt]+")
COMPLEMENT = str.maketrans("acgt", "tgca")


class PrimerFailure(ValueError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


def _load_insertion_context() -> tuple[str, str, str]:
    lines = Path(__file__).with_name("sequences.fasta").read_text(
        encoding="ascii"
    ).splitlines()
    if len(lines) != 4 or lines[0] != ">input" or lines[2] != ">output":
        raise RuntimeError("invalid trusted sequence fixture")
    input_sequence, output_sequence = lines[1], lines[3]
    if (
        DNA.fullmatch(input_sequence) is None
        or DNA.fullmatch(output_sequence) is None
        or len(output_sequence) <= len(input_sequence)
    ):
        raise RuntimeError("invalid trusted sequence fixture")

    insertion_length = len(output_sequence) - len(input_sequence)
    positions = [
        position
        for position in range(len(input_sequence) + 1)
        if (
            output_sequence[:position]
            + output_sequence[position + insertion_length :]
            == input_sequence
        )
    ]
    if not positions:
        raise RuntimeError("invalid trusted insertion context")

    # Repeated bases at a junction can make several deletion boundaries
    # reconstruct the input. The source verifier selects the earliest one.
    position = positions[0]
    left = input_sequence[:position]
    right = input_sequence[position:]
    insertion = output_sequence[position : position + insertion_length]
    if (
        not insertion
        or len(left) < 45
        or len(right) < 45
        or output_sequence != left + insertion + right
    ):
        raise RuntimeError("invalid trusted insertion context")
    return left, insertion, right


VECTOR_LEFT, INSERTION, VECTOR_RIGHT = _load_insertion_context()


def _reverse_complement(sequence: str) -> str:
    return sequence.translate(COMPLEMENT)[::-1]


def _candidate_lines(text: str) -> list[str]:
    return [line.rstrip() for line in io.StringIO(text, newline=None)]


def _validate_primers(text: str) -> None:
    lines = _candidate_lines(text)
    if len(lines) != 4:
        raise PrimerFailure("invalid_line_count")

    forward_primer = lines[1].lower()
    reverse_primer = lines[3].lower()
    if DNA.fullmatch(forward_primer) is None:
        raise PrimerFailure("invalid_forward_primer")
    if DNA.fullmatch(reverse_primer) is None:
        raise PrimerFailure("invalid_reverse_primer")

    concatenated = _reverse_complement(reverse_primer) + forward_primer
    insertion_start = concatenated.find(INSERTION)
    if insertion_start == -1:
        raise PrimerFailure("insert_missing")
    insertion_end = insertion_start + len(INSERTION)
    annealed_reverse = concatenated[:insertion_start]
    annealed_forward = concatenated[insertion_end:]

    if not 15 <= len(annealed_forward) <= 45:
        raise PrimerFailure("forward_annealing_length")
    if not 15 <= len(annealed_reverse) <= 45:
        raise PrimerFailure("reverse_annealing_length")
    if VECTOR_LEFT[-len(annealed_reverse) :] != annealed_reverse:
        raise PrimerFailure("reverse_vector_overlap")
    if VECTOR_RIGHT[: len(annealed_forward)] != annealed_forward:
        raise PrimerFailure("forward_vector_overlap")

    forward_tm = primer3_oligotm_v1(annealed_forward)
    reverse_tm = primer3_oligotm_v1(_reverse_complement(annealed_reverse))
    if not 58 <= forward_tm <= 72:
        raise PrimerFailure("forward_tm_out_of_range")
    if not 58 <= reverse_tm <= 72:
        raise PrimerFailure("reverse_tm_out_of_range")
    if abs(forward_tm - reverse_tm) > 5:
        raise PrimerFailure("primer_pair_tm_mismatch")


class DnaInsertOracle:
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
                        "Primers satisfy the declared insertion constraints"
                        if passed
                        else "Primers are missing or do not satisfy the insertion constraints"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = DnaInsertOracle()
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
