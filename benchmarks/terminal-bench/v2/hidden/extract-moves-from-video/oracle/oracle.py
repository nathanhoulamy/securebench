"""Host-only Oracle for the Zork move-transcript artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


CHECK_ID = "solution_artifact"
ARTIFACT_ID = "solution"
EXPECTED_SHA256 = "218abc48833a22f05d5655c157c81121cc5edf333059c2c34a65788e1065eceb"


def universal_newlines(value: str) -> str:
    """Reproduce Python text-mode newline translation used by the source verifier."""

    return value.replace("\r\n", "\n").replace("\r", "\n")


def levenshtein_distance(left: str, right: str) -> int:
    """Return character-level edit distance using the source verifier's recurrence."""

    if len(left) < len(right):
        left, right = right, left
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left):
        current = [left_index + 1]
        for right_index, right_character in enumerate(right):
            current.append(
                min(
                    previous[right_index + 1] + 1,
                    current[right_index] + 1,
                    previous[right_index] + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def source_threshold_passes(actual: str, expected: str) -> bool:
    maximum_length = max(len(actual), len(expected))
    if maximum_length == 0:
        return True
    if abs(len(actual) - len(expected)) * 10 > maximum_length:
        return False
    distance = levenshtein_distance(actual, expected)
    return distance * 10 <= maximum_length


def load_expected() -> str:
    content = (Path(__file__).resolve().parent / "solution.txt").read_bytes()
    if hashlib.sha256(content).hexdigest() != EXPECTED_SHA256:
        raise ValueError("expected transcript integrity check failed")
    return content.decode("utf-8", errors="strict")


class MoveTranscriptOracle:
    def __init__(self) -> None:
        self.expected = ""
        self.evaluated = False
        self.passed = False
        self.failure = "not_evaluated"

    def initialize(self) -> None:
        self.expected = load_expected()
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
        value = evidence.get("parsed_value")
        if not isinstance(value, str):
            self.failure = "invalid_text"
            return
        actual = universal_newlines(value)
        self.passed = source_threshold_passes(actual, self.expected)
        self.failure = "" if self.passed else "similarity_below_threshold"

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
                        "Move transcript met the source similarity threshold"
                        if passed
                        else "Move transcript was missing, malformed, or insufficiently similar"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = MoveTranscriptOracle()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "initialize":
                oracle.initialize()
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
