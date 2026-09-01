"""Host-only Oracle for the recovered personal-site files."""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Any


CHECK_ID = "recovered_files_artifact"
EXPECTED_SHA256 = {
    "about": "b672b690b9fd43c901ed5a385ebbca7cf3546716f1fead228136b1c326f1de6b",
    "layout": "fb3fad17b83338002f5fd6a99ea1ec3a662cea570f9fff9240b8abc1861be655",
}


def source_digest(value: str) -> str:
    """Reproduce the source verifier's binary ``read().strip()`` semantics."""

    return hashlib.sha256(value.encode("utf-8").strip()).hexdigest()


class FixGitOracle:
    def __init__(self) -> None:
        self.outcomes: dict[str, bool] = {}
        self.failures: list[str] = []

    def initialize(self) -> None:
        self.outcomes.clear()
        self.failures.clear()

    def evaluate(self, evidence: dict[str, Any]) -> None:
        artifact_id = evidence.get("artifact_id")
        if evidence.get("check_id") != CHECK_ID or artifact_id not in EXPECTED_SHA256:
            self.failures.append("uncorrelated_artifact")
            return
        if not isinstance(artifact_id, str) or artifact_id in self.outcomes:
            self.failures.append("duplicate_artifact")
            return
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            self.outcomes[artifact_id] = False
            self.failures.append(f"{artifact_id}:{code or 'artifact_rejected'}")
            return
        value = evidence.get("parsed_value")
        passed = (
            isinstance(value, str)
            and source_digest(value) == EXPECTED_SHA256[artifact_id]
        )
        self.outcomes[artifact_id] = passed
        if not passed:
            self.failures.append(f"incorrect_{artifact_id}_file")

    def verdict(self) -> dict[str, Any]:
        passed = (
            set(self.outcomes) == set(EXPECTED_SHA256)
            and all(self.outcomes.values())
            and not self.failures
        )
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {CHECK_ID: passed},
                "public_diagnostics": {
                    "message": (
                        "Both recovered site files match the intended lost commit"
                        if passed
                        else "One or more recovered site files are missing or incorrect"
                    ),
                    "failure_categories": sorted(set(self.failures))[:20],
                },
            },
        }


def main() -> None:
    oracle = FixGitOracle()
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
