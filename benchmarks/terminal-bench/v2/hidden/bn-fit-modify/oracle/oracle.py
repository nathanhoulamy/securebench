"""Host-only Oracle for the bn-fit-modify artifact conversion."""

from __future__ import annotations

import json
import math
import sys
from statistics import NormalDist
from typing import Any


EXPECTED_ARTIFACTS = {"learned_dag", "intervened_dag", "final_sample"}
LEARNED_EDGES = {
    ("U", "M"),
    ("U", "Y"),
    ("U", "D"),
    ("U", "R"),
    ("Y", "D"),
    ("R", "M"),
}
INTERVENED_EDGES = LEARNED_EDGES - {("U", "Y")}
SAMPLE_COLUMNS = {"U", "R", "Y", "M", "D"}
SAMPLE_ROWS = 10_000
EXPECTED_D_MEAN = -12.2965135 + 0.5495886 * 50.47989
EXPECTED_D_STD = ((0.5495886**2) * 10.68515**2 + 14.0916**2) ** 0.5
# scipy.stats.kstwo.ppf(0.999, 10000) under the original scipy==1.16.1
# verifier. For a continuous null, p >= 0.001 iff the observed D is no larger.
MAX_KS_STATISTIC = 0.01947748045729969


class BnFitOracle:
    def __init__(self) -> None:
        self.outcomes: dict[str, bool] = {}
        self.failures: list[str] = []

    def evaluate(self, evidence: dict[str, Any]) -> None:
        artifact_id = evidence.get("artifact_id")
        if not isinstance(artifact_id, str) or artifact_id not in EXPECTED_ARTIFACTS:
            self.failures.append("unexpected_artifact")
            return
        if artifact_id in self.outcomes:
            self.outcomes[artifact_id] = False
            self.failures.append(f"{artifact_id}:duplicate_evidence")
            return
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            code = error.get("code") if isinstance(error, dict) else "artifact_rejected"
            self.outcomes[artifact_id] = False
            self.failures.append(f"{artifact_id}:{code}")
            return

        table = _table(evidence.get("parsed_value"))
        if table is None:
            self.outcomes[artifact_id] = False
            self.failures.append(f"{artifact_id}:invalid_table")
            return
        header, rows = table
        if artifact_id == "learned_dag":
            failure = _check_edges(header, rows, LEARNED_EDGES)
        elif artifact_id == "intervened_dag":
            failure = _check_edges(header, rows, INTERVENED_EDGES)
        else:
            failure = _check_sample(header, rows)
        self.outcomes[artifact_id] = failure is None
        if failure is not None:
            self.failures.append(f"{artifact_id}:{failure}")

    def verdict(self) -> dict[str, Any]:
        missing = EXPECTED_ARTIFACTS - set(self.outcomes)
        failures = [*self.failures, *(f"{name}:missing_evidence" for name in sorted(missing))]
        passed = not failures and all(self.outcomes.values())
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {"bn_outputs_artifact": passed},
                "public_diagnostics": {
                    "message": (
                        "Bayesian-network artifacts satisfy the source checks"
                        if passed
                        else "Bayesian-network artifacts did not satisfy the source checks"
                    ),
                    "failure_categories": sorted(set(failures)),
                },
            },
        }


def _table(value: Any) -> tuple[list[str], list[list[str]]] | None:
    if not isinstance(value, dict) or set(value) != {"header", "rows"}:
        return None
    header, rows = value.get("header"), value.get("rows")
    if (
        not isinstance(header, list)
        or not all(isinstance(item, str) for item in header)
        or not isinstance(rows, list)
        or not all(
            isinstance(row, list)
            and len(row) == len(header)
            and all(isinstance(item, str) for item in row)
            for row in rows
        )
    ):
        return None
    return header, rows


def _check_edges(
    header: list[str],
    rows: list[list[str]],
    expected: set[tuple[str, str]],
) -> str | None:
    if not {"from", "to"} <= set(header):
        return "missing_edge_columns"
    from_index, to_index = header.index("from"), header.index("to")
    observed = {(row[from_index], row[to_index]) for row in rows}
    if observed != expected:
        return "incorrect_edges"
    return None


def _check_sample(header: list[str], rows: list[list[str]]) -> str | None:
    if len(header) != len(SAMPLE_COLUMNS) or set(header) != SAMPLE_COLUMNS:
        return "incorrect_sample_columns"
    if len(rows) != SAMPLE_ROWS:
        return "incorrect_sample_row_count"
    d_index = header.index("D")
    values: list[float] = []
    for row in rows:
        try:
            number = float(row[d_index])
        except (TypeError, ValueError, OverflowError):
            return "invalid_d_value"
        if not math.isfinite(number):
            return "invalid_d_value"
        values.append(number)
    if _ks_statistic(values, EXPECTED_D_MEAN, EXPECTED_D_STD) > MAX_KS_STATISTIC:
        return "d_distribution_mismatch"
    return None


def _ks_statistic(values: list[float], mean: float, std: float) -> float:
    distribution = NormalDist(mean, std)
    ordered = sorted(values)
    count = len(ordered)
    d_plus = 0.0
    d_minus = 0.0
    for index, value in enumerate(ordered, start=1):
        cumulative = distribution.cdf(value)
        d_plus = max(d_plus, index / count - cumulative)
        d_minus = max(d_minus, cumulative - (index - 1) / count)
    return max(d_plus, d_minus)


def main() -> None:
    oracle = BnFitOracle()
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
