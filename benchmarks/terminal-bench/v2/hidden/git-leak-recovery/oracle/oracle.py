"""Host-only Oracle for Git leak recovery artifacts."""

from __future__ import annotations

import json
import sys
from typing import Any


CHECK_ID = "git_recovery_artifact"
ARTIFACT_IDS = {"repository", "recovered_secret"}
EXPECTED_SECRET = "secret[lost_and_found_in_git]"
REQUIRED_COMMIT_TEXT = "chore: init e665d1a2-04a7-4e61-b523-e897e231d9cc"
EXPECTED_WORKTREE = [
    {
        "path": "README.md",
        "size": 26,
        "blob": "sha256:f7488e6fb98964f9ce599691223b5985d637e34abf35cae86e06017d585c2bd1",
    }
]


def source_normalize(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def repository_failure(value: Any) -> str | None:
    if not isinstance(value, dict) or value.get("format") != "git-repository":
        return "malformed_repository_observation"
    objects = value.get("objects")
    worktree = value.get("worktree")
    if not isinstance(objects, list) or not isinstance(worktree, list):
        return "malformed_repository_observation"
    if worktree != EXPECTED_WORKTREE:
        return "repository_contents_changed"

    required_commit_found = False
    for item in objects:
        if not isinstance(item, dict):
            return "malformed_repository_observation"
        if set(item) != {"oid", "kind", "size", "reachable", "content"}:
            return "malformed_repository_observation"
        kind = item.get("kind")
        reachable = item.get("reachable")
        content = item.get("content")
        if kind not in {"blob", "commit", "tag", "tree"} or not isinstance(reachable, bool) or not isinstance(content, str):
            return "malformed_repository_observation"
        if "secret[" in content:
            return "secret_remains_in_git_objects"
        if kind == "commit" and reachable:
            if "secret[" in content.lower():
                return "secret_remains_in_reachable_history"
            if REQUIRED_COMMIT_TEXT in content:
                required_commit_found = True
    if not required_commit_found:
        return "required_commit_not_preserved"
    return None


class GitLeakRecoveryOracle:
    def __init__(self) -> None:
        self.observations: dict[str, Any] = {}
        self.failures: list[str] = []

    def initialize(self) -> None:
        self.observations = {}
        self.failures = []

    def evaluate(self, evidence: dict[str, Any]) -> None:
        artifact_id = evidence.get("artifact_id")
        if evidence.get("check_id") != CHECK_ID or artifact_id not in ARTIFACT_IDS:
            self.failures.append("uncorrelated_artifact")
            return
        assert isinstance(artifact_id, str)
        if artifact_id in self.observations:
            self.failures.append("duplicate_artifact")
            return
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            code = str(error.get("code", "artifact_rejected")) if isinstance(error, dict) else "artifact_rejected"
            self.failures.append(f"{artifact_id}:{code}")
            return
        self.observations[artifact_id] = evidence.get("parsed_value")

    def verdict(self) -> dict[str, Any]:
        failures = list(self.failures)
        if not failures and set(self.observations) != ARTIFACT_IDS:
            failures.append("missing_artifact")
        if not failures:
            recovered = self.observations["recovered_secret"]
            if not isinstance(recovered, str) or source_normalize(recovered) != EXPECTED_SECRET:
                failures.append("incorrect_recovered_secret")
            repository_problem = repository_failure(self.observations["repository"])
            if repository_problem is not None:
                failures.append(repository_problem)
        passed = not failures
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {CHECK_ID: passed},
                "public_diagnostics": {
                    "message": "Secret was recovered and removed from the preserved repository" if passed else "Git leak recovery artifacts are incorrect",
                    "failure_categories": failures,
                },
            },
        }


def main() -> None:
    oracle = GitLeakRecoveryOracle()
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
                    raise ValueError("artifact evidence is malformed")
                oracle.evaluate(evidence)
                response = {"type": "ack"}
            elif operation == "finalize":
                response = oracle.verdict()
            else:
                raise ValueError("unsupported operation")
        except (AssertionError, KeyError, TypeError, ValueError):
            response = {
                "type": "verdict",
                "verdict": {
                    "passed": False,
                    "score": 0.0,
                    "check_outcomes": {CHECK_ID: False},
                    "public_diagnostics": {
                        "message": "Git leak recovery evidence is malformed",
                        "failure_categories": ["malformed_evidence"],
                    },
                },
            }
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
