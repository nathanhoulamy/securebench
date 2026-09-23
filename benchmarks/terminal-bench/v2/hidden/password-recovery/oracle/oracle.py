"""Host-only Oracle for the password-recovery artifact conversion.

The source verifier reads /app/recovered_passwords.txt, strips the whole text,
splits it on newlines, and requires the secret password to appear as one of the
resulting lines. Extra incorrect guesses are accepted; the source applies no
penalty and no upper bound on the guess count.

The secret never enters the Agent or Evaluation environment. It is recoverable
from the disk image shipped in the pinned task image, which is what the task
asks the agent to do.
"""

from __future__ import annotations

import json
import sys
from typing import Any


EXPECTED = "8XDP5Q2RT9ZK7VB3BV4WW54"


class PasswordRecoveryOracle:
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
        if not isinstance(value, str):
            self.failure = "invalid_text"
            return
        # Reproduce the source predicate exactly: strip the whole text, then
        # split on newlines. A guess only counts as an exact whole line.
        guesses = value.strip().split("\n")
        if not guesses:
            self.failure = "no_guesses"
            return
        self.passed = EXPECTED in guesses
        self.failure = "" if self.passed else "password_not_recovered"

    def verdict(self) -> dict[str, Any]:
        passed = self.evaluated and self.passed
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {"recovered_passwords_artifact": passed},
                "public_diagnostics": {
                    "message": (
                        "Recovered password list contains the deleted password"
                        if passed
                        else "Recovered password list does not contain the password"
                    ),
                    "failure_categories": [] if passed else [self.failure],
                },
            },
        }


def main() -> None:
    oracle = PasswordRecoveryOracle()
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
