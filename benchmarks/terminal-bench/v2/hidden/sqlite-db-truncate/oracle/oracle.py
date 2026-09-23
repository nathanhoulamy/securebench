"""Host-only Oracle for the sqlite-db-truncate artifact conversion."""

from __future__ import annotations

import json
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
        # Mirrors the source verifier exactly:
        #   soln_tuples = {(item["word"], item["value"]) for item in soln}
        #   data_tuples = {(item["word"], item["value"]) for item in data}
        #   matches = soln_tuples & data_tuples
        # Upstream never inspects the type of ``word``/``value``: a row whose
        # types do not match the expected recovery is simply not present in
        # the intersection, it does not disqualify the candidate. Only a
        # shape that would raise in upstream's own comprehension (a missing
        # key, because ``item["word"]`` is a ``KeyError``, or an unhashable
        # ``value`` such as a list/dict, because the set literal cannot hold
        # it) is treated as a failure here, matching upstream's crash.
        recovered: set[tuple[Any, Any]] = set()
        for row in rows:
            if not isinstance(row, dict) or "word" not in row or "value" not in row:
                self.failure = "invalid_row_shape"
                return
            pair = (row["word"], row["value"])
            try:
                hash(pair)
            except TypeError:
                self.failure = "invalid_row_shape"
                return
            recovered.add(pair)
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
