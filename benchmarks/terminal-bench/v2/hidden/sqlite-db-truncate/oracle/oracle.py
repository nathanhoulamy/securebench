"""Host-only Oracle for the sqlite-db-truncate artifact conversion."""

from __future__ import annotations

import json
import math
import sys
from typing import Any


EXPECTED = {
    ("testword02", 10.0),
    ("testword03", 25.0),
    ("testword04", 42.0),
    ("testword05", 50.0),
    ("testword06", 75.0),
    ("testword07", 99.0),
    ("testword08", 99.99),
    ("testword09", 0.5),
}
MINIMUM_RECOVERED = 7


class RecoveryOracle:
    def __init__(self) -> None:
        self.evaluated = False
        self.passed = False
        self.failure = "not_evaluated"

    def evaluate(self, evidence: dict[str, Any]) -> None:
        self.evaluated = True
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            self.failure = str(error.get("code", "artifact_rejected")) if isinstance(error, dict) else "artifact_rejected"
            return
        rows = evidence.get("parsed_value")
        if not isinstance(rows, list):
            self.failure = "root_not_array"
            return
        recovered: set[tuple[str, float]] = set()
        for row in rows:
            if not isinstance(row, dict) or not {"word", "value"} <= set(row):
                self.failure = "invalid_row_shape"
                return
            word, value = row.get("word"), row.get("value")
            if not isinstance(word, str) or isinstance(value, bool) or not isinstance(value, (int, float)):
                self.failure = "invalid_row_type"
                return
            number = float(value)
            if not math.isfinite(number):
                self.failure = "non_finite_value"
                return
            recovered.add((word, number))
        count = len(recovered & EXPECTED)
        self.passed = count >= MINIMUM_RECOVERED
        self.failure = "" if self.passed else "insufficient_recovery"

    def verdict(self) -> dict[str, Any]:
        passed = self.evaluated and self.passed
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {"recovery_artifact": passed},
                "public_diagnostics": {
                    "message": "Recovered row set met the source threshold" if passed else "Recovered row set did not meet the source threshold",
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = RecoveryOracle()
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
