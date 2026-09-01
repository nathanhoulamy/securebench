"""Host-only Oracle for the decoded G-code text artifact."""

from __future__ import annotations

import json
import sys
from typing import Any


CHECK_ID = "decoded_text_artifact"
ARTIFACT_ID = "decoded_text"
EXPECTED_TEXT = "flag{gc0d3_iz_ch4LLenGiNg}"


def source_normalize(value: str) -> str:
    """Reproduce ``Path.read_text().strip()`` on the Linux source verifier."""

    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


class GcodeTextOracle:
    def __init__(self) -> None:
        self.evaluated = False
        self.passed = False
        self.failures: list[str] = []

    def initialize(self) -> None:
        self.evaluated = False
        self.passed = False
        self.failures.clear()

    def evaluate(self, evidence: dict[str, Any]) -> None:
        if self.evaluated:
            self.failures.append("duplicate_artifact")
            return
        self.evaluated = True
        if (
            evidence.get("check_id") != CHECK_ID
            or evidence.get("artifact_id") != ARTIFACT_ID
        ):
            self.failures.append("uncorrelated_artifact")
            return
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            self.failures.append(str(code or "artifact_rejected"))
            return
        value = evidence.get("parsed_value")
        if not isinstance(value, str):
            self.failures.append("invalid_text")
            return
        self.passed = source_normalize(value) == EXPECTED_TEXT
        if not self.passed:
            self.failures.append("incorrect_decoded_text")

    def verdict(self) -> dict[str, Any]:
        passed = self.evaluated and self.passed and not self.failures
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {CHECK_ID: passed},
                "public_diagnostics": {
                    "message": (
                        "Decoded G-code text is correct"
                        if passed
                        else "Decoded G-code text is missing or incorrect"
                    ),
                    "failure_categories": sorted(set(self.failures))[:20],
                },
            },
        }


def main() -> None:
    oracle = GcodeTextOracle()
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
