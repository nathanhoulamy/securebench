"""Host-only Oracle for the chess-best-move artifact conversion."""

from __future__ import annotations

import json
import sys
from typing import Any


CHECK_ID = "moves_artifact"
EXPECTED_MOVES = ("e2e4", "g2g4")


class ChessMoveOracle:
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
        value = evidence.get("parsed_value")
        if not isinstance(value, str):
            self.failure = "invalid_text"
            return
        self.passed = sorted(value.strip().split()) == list(EXPECTED_MOVES)
        self.failure = "" if self.passed else "incorrect_move_set"

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
                        "Move artifact contains the complete winning move set"
                        if passed
                        else "Move artifact is missing or incorrect"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = ChessMoveOracle()
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
