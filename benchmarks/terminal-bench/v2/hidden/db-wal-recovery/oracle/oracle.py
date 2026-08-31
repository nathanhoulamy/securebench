"""Host-only Oracle for the db-wal-recovery artifact conversion."""

from __future__ import annotations

import json
import sys
from typing import Any


CHECK_ID = "recovered_artifact"
ARTIFACT_ID = "recovered"
EXPECTED_IDS = list(range(1, 12))
EXPECTED_NAMES = {
    3: "cherry",
    4: "date",
    5: "elderberry",
    6: "fig",
    7: "grape",
    8: "honeydew",
    9: "kiwi",
    10: "lemon",
    11: "mango",
}


class WalRecoveryOracle:
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
        rows = evidence.get("parsed_value")
        if not isinstance(rows, list):
            self.failure = "root_not_array"
            return
        if not rows:
            self.failure = "empty_recovery"
            return
        for row in rows:
            if not isinstance(row, dict) or not {"id", "name", "value"} <= set(row):
                self.failure = "invalid_row_shape"
                return
            # Match the source verifier's isinstance(..., int) semantics, which
            # intentionally also accept JSON booleans as Python integers.
            if (
                not isinstance(row["id"], int)
                or not isinstance(row["name"], str)
                or not isinstance(row["value"], int)
            ):
                self.failure = "invalid_row_type"
                return

        ids = [row["id"] for row in rows]
        if ids != sorted(ids):
            self.failure = "records_not_sorted"
            return
        if len(rows) != 11 or ids != EXPECTED_IDS:
            self.failure = "incomplete_recovery"
            return
        if len(ids) != len(set(ids)):
            self.failure = "duplicate_ids"
            return

        by_id = {row["id"]: row for row in rows}
        if by_id[1]["value"] != 150 or by_id[2]["value"] != 250:
            self.failure = "missing_wal_updates"
            return
        if any(by_id[row_id]["name"] != name for row_id, name in EXPECTED_NAMES.items()):
            self.failure = "incorrect_record_names"
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
                        "Recovered records satisfy the source checks"
                        if passed
                        else "Recovered records are missing or incorrect"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = WalRecoveryOracle()
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
