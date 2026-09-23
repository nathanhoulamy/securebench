"""Host-only Oracle for the raman-fitting artifact conversion.

The source verifier reads /app/results.json and checks eight fitted parameters
against fixed expectations. The tolerance KIND differs per parameter and is
reproduced exactly here:

  G.x0        absolute, < 5
  G.gamma     absolute, < 1
  G.amplitude relative, |1 - a/expected| < 0.05
  G.offset    relative, |1 - o/expected| < 0.10
  2D.x0       relative, |1 - x/expected| < 0.05   (relative, unlike G.x0)
  2D.gamma    absolute, < 1
  2D.amplitude relative, < 0.05
  2D.offset   relative, < 0.10

Expected values and tolerances stay host-side. The fitting method itself is not
scored, only the reported parameters.
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any


ABSOLUTE = "absolute"
RELATIVE = "relative"

# peak -> parameter -> (expected, tolerance, kind)
EXPECTED = {
    "G": {
        "x0": (1580.3, 5.0, ABSOLUTE),
        "gamma": (9.06, 1.0, ABSOLUTE),
        "amplitude": (8382.69, 0.05, RELATIVE),
        "offset": (5561.03, 0.10, RELATIVE),
    },
    "2D": {
        "x0": (2670.08, 0.05, RELATIVE),
        "gamma": (17.52, 1.0, ABSOLUTE),
        "amplitude": (12314.42, 0.05, RELATIVE),
        "offset": (1239.09, 0.10, RELATIVE),
    },
}


class RamanFittingOracle:
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
        document = evidence.get("parsed_value")
        if not isinstance(document, dict):
            self.failure = "root_not_object"
            return
        for peak, parameters in EXPECTED.items():
            section = document.get(peak)
            if not isinstance(section, dict):
                self.failure = "missing_peak"
                return
            for name, (expected, tolerance, kind) in parameters.items():
                raw = section.get(name)
                # JSON true/false are ints in Python; reject them explicitly.
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    self.failure = "invalid_parameter_type"
                    return
                observed = float(raw)
                if not math.isfinite(observed):
                    self.failure = "non_finite_parameter"
                    return
                if kind == ABSOLUTE:
                    ok = abs(observed - expected) < tolerance
                else:
                    ok = abs(1.0 - observed / expected) < tolerance
                if not ok:
                    self.failure = f"{peak}_{name}_out_of_tolerance"
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
                "check_outcomes": {"fit_results_artifact": passed},
                "public_diagnostics": {
                    "message": (
                        "Fitted G and 2D parameters are within tolerance"
                        if passed
                        else "Fitted parameters are missing or out of tolerance"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = RamanFittingOracle()
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
