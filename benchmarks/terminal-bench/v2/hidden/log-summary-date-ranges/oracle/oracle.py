"""Host-only Oracle for the log-summary-date-ranges artifact conversion.

The source verifier parses /app/summary.csv, requires the exact header
["period", "severity", "count"], exactly fifteen data rows, and compares each
row positionally against a fixed expected table. Counts are compared as
strings, so "370.0" or " 370" do not match "370".

The expected table is derived from the deterministic log generator shipped in
the task image with the fixed reference date 2025-08-12. It is held host-side
and never enters the Agent or Evaluation environment.
"""

from __future__ import annotations

import json
import sys
from typing import Any


EXPECTED_HEADER = ["period", "severity", "count"]
EXPECTED_ROWS = [
    ["today", "ERROR", "370"],
    ["today", "WARNING", "463"],
    ["today", "INFO", "1433"],
    ["last_7_days", "ERROR", "2969"],
    ["last_7_days", "WARNING", "4020"],
    ["last_7_days", "INFO", "12203"],
    ["last_30_days", "ERROR", "9594"],
    ["last_30_days", "WARNING", "12847"],
    ["last_30_days", "INFO", "38702"],
    ["month_to_date", "ERROR", "4682"],
    ["month_to_date", "WARNING", "6327"],
    ["month_to_date", "INFO", "19420"],
    ["total", "ERROR", "14160"],
    ["total", "WARNING", "18772"],
    ["total", "INFO", "56621"],
]


class LogSummaryOracle:
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
        if not isinstance(value, dict):
            self.failure = "invalid_csv"
            return
        header = value.get("header")
        rows = value.get("rows")
        if not isinstance(header, list) or not isinstance(rows, list):
            self.failure = "invalid_csv"
            return
        if header != EXPECTED_HEADER:
            self.failure = "unexpected_header"
            return
        if len(rows) != len(EXPECTED_ROWS):
            self.failure = "unexpected_row_count"
            return
        # The source compares rows positionally, so order is scored.
        for expected, actual in zip(EXPECTED_ROWS, rows):
            if actual != expected:
                self.failure = "incorrect_row"
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
                "check_outcomes": {"summary_artifact": passed},
                "public_diagnostics": {
                    "message": (
                        "Summary matches the expected severity counts"
                        if passed
                        else "Summary does not match the expected severity counts"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = LogSummaryOracle()
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
