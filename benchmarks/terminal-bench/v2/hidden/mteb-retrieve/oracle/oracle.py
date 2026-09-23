"""Host-only Oracle for the mteb-retrieve artifact conversion.

The source verifier reads /app/result.txt with ``readlines()``, requires exactly
one line, and compares ``lines[0].strip()`` with a fixed expected string. Both
the expected answer and the comparison stay host-side.

Fidelity note: the source pins the fifth-ranked document as a literal
rather than recomputing embeddings, and so does this Oracle. The result
is correct only insofar as the upstream pinned answer is.
"""

from __future__ import annotations

import json
import sys
from typing import Any


EXPECTED = 'MTEB: Massive Text Embedding Benchmark'
CHECK_ID = "retrieved_document_artifact"


def split_source_lines(text: str) -> list[str]:
    """Reproduce ``f.readlines()`` line counting on the candidate bytes."""
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


class ExactAnswerOracle:
    def __init__(self) -> None:
        self.evaluated = False
        self.passed = False
        self.failure = "not_evaluated"

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
        lines = split_source_lines(text)
        if len(lines) != 1:
            self.failure = "invalid_line_count"
            return
        self.passed = lines[0].strip() == EXPECTED
        self.failure = "" if self.passed else "incorrect_answer"

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
                        "Answer matches the expected value"
                        if passed
                        else "Answer is missing, malformed, or incorrect"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = ExactAnswerOracle()
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
