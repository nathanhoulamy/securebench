"""Host-only Oracle for the distribution-search artifact conversion."""

from __future__ import annotations

import json
import math
import sys
from typing import Any


CHECK_ID = "distribution_artifact"
ARTIFACT_ID = "distribution"
EXPECTED_SIZE = 150_000
TARGET_KL = 10.0
KL_TOLERANCE = 0.001
SUM_TOLERANCE = 1e-5


class DistributionOracle:
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
        parsed = evidence.get("parsed_value")
        if not isinstance(parsed, dict) or parsed.get("format") != "npy":
            self.failure = "invalid_distribution_artifact"
            return
        if parsed.get("shape") != [EXPECTED_SIZE] or parsed.get("count") != EXPECTED_SIZE:
            self.failure = "incorrect_distribution_shape"
            return
        statistics = parsed.get("statistics")
        if not isinstance(statistics, dict):
            self.failure = "invalid_distribution_statistics"
            return
        if statistics.get("all_finite") is not True:
            self.failure = "non_finite_probabilities"
            return
        if statistics.get("all_positive") is not True:
            self.failure = "non_positive_probabilities"
            return
        maximum = _finite_number(statistics.get("maximum"))
        total = _finite_number(statistics.get("sum"))
        sum_log = _finite_number(statistics.get("sum_log"))
        sum_x_log_x = _finite_number(statistics.get("sum_x_log_x"))
        if None in {maximum, total, sum_log, sum_x_log_x}:
            self.failure = "invalid_distribution_statistics"
            return
        assert maximum is not None
        assert total is not None
        assert sum_log is not None
        assert sum_x_log_x is not None
        if maximum > 1.0:
            self.failure = "probability_above_one"
            return
        if abs(total - 1.0) >= SUM_TOLERANCE:
            self.failure = "distribution_not_normalized"
            return

        forward = sum_x_log_x / total - math.log(total) + math.log(EXPECTED_SIZE)
        backward = (
            -math.log(EXPECTED_SIZE)
            - sum_log / EXPECTED_SIZE
            + math.log(total)
        )
        if not math.isfinite(forward) or abs(forward - TARGET_KL) > KL_TOLERANCE:
            self.failure = "forward_kl_out_of_tolerance"
            return
        if not math.isfinite(backward) or abs(backward - TARGET_KL) > KL_TOLERANCE:
            self.failure = "backward_kl_out_of_tolerance"
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
                        "Distribution satisfies the declared constraints"
                        if passed
                        else "Distribution is missing or does not satisfy the constraints"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def main() -> None:
    oracle = DistributionOracle()
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
