"""Host-only Oracle for the rstan-to-pystan artifact conversion.

The source verifier has six tests. Five compare posterior means in four CSV
files against fixed inclusive ranges, and are reproduced here exactly, including
the source's two different parsing styles:

  * alpha and sigma are read as raw text: ``f.read().strip()``, then
    ``float(content.split(",")[0].strip())`` -- so trailing content after a
    comma is ignored;
  * rho and beta are read with ``csv.reader``, taking ``row[0]`` of every
    non-empty row and requiring exactly three values.

DOCUMENTED SEMANTIC CHANGE
--------------------------
The sixth source test, ``test_r_rstan_not_installed``, shells out to ``R`` and
``R --slave -e "library(rstan)"`` inside the candidate's own filesystem to prove
the agent never installed R or RStan. That is a property of the whole candidate
environment, not of any captured artifact, so it cannot be decided from the four
CSV files. It is deliberately dropped, as approved in the dossier. Using an
Evaluation image without R would only make absence a property of the harness,
not evidence about the candidate, so that shortcut is rejected too.

Consequence: a candidate that reached these numbers by installing R and RStan
would pass here and fail the original. Everything else is preserved.
"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
from typing import Any


ALPHA_RANGE = (1.08, 1.1)
SIGMA_RANGE = (0.133, 0.136)
RHO_RANGES = ((0.57, 0.6), (0.886, 1.0), (1.49, 1.51))
BETA_RANGES = ((-0.07, 0.0), (-0.83, -0.8), (0.41, 0.43))

SCALAR_ARTIFACTS = {"alpha": ALPHA_RANGE, "sigma": SIGMA_RANGE}
VECTOR_ARTIFACTS = {"rho": RHO_RANGES, "beta": BETA_RANGES}


def parse_scalar(text: str) -> float | None:
    """Reproduce the source's raw-text scalar parse."""
    content = text.strip()
    if not content:
        return None
    try:
        return float(content.split(",")[0].strip())
    except ValueError:
        return None


def parse_vector(text: str) -> list[float] | None:
    """Reproduce the source's csv.reader parse, taking column 0 of each row."""
    values: list[float] = []
    try:
        for row in csv.reader(io.StringIO(text)):
            if not row:
                continue
            try:
                values.append(float(row[0].strip()))
            except (ValueError, IndexError):
                return None
    except csv.Error:
        return None
    return values


class RStanToPyStanOracle:
    def __init__(self) -> None:
        self.observed: dict[str, Any] = {}
        self.failure = "not_evaluated"
        self.evaluated = False

    def evaluate(self, evidence: dict[str, Any]) -> None:
        self.evaluated = True
        artifact_id = evidence.get("artifact_id") or evidence.get("id")
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            code = (
                str(error.get("code", "artifact_rejected"))
                if isinstance(error, dict)
                else "artifact_rejected"
            )
            self.observed[str(artifact_id)] = ("error", code)
            return
        value = evidence.get("parsed_value")
        if not isinstance(value, str):
            self.observed[str(artifact_id)] = ("error", "invalid_text")
            return
        self.observed[str(artifact_id)] = ("text", value)

    def _decide(self) -> str:
        for name in (*SCALAR_ARTIFACTS, *VECTOR_ARTIFACTS):
            if name not in self.observed:
                return "missing_estimate_file"
            kind, payload = self.observed[name]
            if kind == "error":
                return str(payload)

        for name, (low, high) in SCALAR_ARTIFACTS.items():
            number = parse_scalar(self.observed[name][1])
            if number is None:
                return f"{name}_unparsable"
            if not math.isfinite(number):
                return f"{name}_not_finite"
            if not low <= number <= high:
                return f"{name}_out_of_range"

        for name, ranges in VECTOR_ARTIFACTS.items():
            values = parse_vector(self.observed[name][1])
            if values is None:
                return f"{name}_unparsable"
            if len(values) != len(ranges):
                return f"{name}_wrong_length"
            for number, (low, high) in zip(values, ranges):
                if not math.isfinite(number):
                    return f"{name}_not_finite"
                if not low <= number <= high:
                    return f"{name}_out_of_range"
        return ""

    def verdict(self) -> dict[str, Any]:
        failure = self._decide() if self.evaluated else "not_evaluated"
        passed = self.evaluated and failure == ""
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {"posterior_estimates_artifact": passed},
                "public_diagnostics": {
                    "message": (
                        "Posterior means fall within the expected ranges"
                        if passed
                        else "Posterior estimates are missing, malformed, or out of range"
                    ),
                    "failure_categories": [] if passed else [failure],
                },
            },
        }


def main() -> None:
    oracle = RStanToPyStanOracle()
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
