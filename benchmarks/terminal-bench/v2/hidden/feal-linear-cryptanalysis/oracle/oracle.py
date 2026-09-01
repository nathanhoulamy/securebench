"""Host-only Oracle for the FEAL plaintext-list artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


CHECK_ID = "plaintexts_artifact"
ARTIFACT_ID = "plaintexts"
EXPECTED_SHA256 = "849f9e33e7848d138d8af9880653b6f582c469f992a3ae77625786abc59068e7"


def load_expected_plaintexts() -> tuple[str, ...]:
    content = (Path(__file__).resolve().parent / "plaintexts.txt").read_bytes()
    if hashlib.sha256(content).hexdigest() != EXPECTED_SHA256:
        raise ValueError("expected plaintext integrity check failed")
    values = tuple(content.decode("ascii", errors="strict").split())
    if (
        len(values) != 100
        or len(set(values)) != 100
        or any(not value.isascii() or not value.isdecimal() for value in values)
    ):
        raise ValueError("expected plaintext corpus is malformed")
    return values


class FealPlaintextsOracle:
    def __init__(self) -> None:
        self.expected: tuple[str, ...] = ()
        self.evaluated = False
        self.passed = False
        self.failure = "not_evaluated"

    def initialize(self) -> None:
        self.expected = load_expected_plaintexts()
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
        value = evidence.get("parsed_value")
        if not isinstance(value, str):
            self.failure = "invalid_text"
            return
        self.passed = all(plaintext in value for plaintext in self.expected)
        self.failure = "" if self.passed else "missing_expected_plaintext"

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
                        "Output contains every expected plaintext"
                        if passed
                        else "One or more expected plaintexts are missing"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = FealPlaintextsOracle()
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
