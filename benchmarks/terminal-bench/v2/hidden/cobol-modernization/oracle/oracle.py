"""Host-only Oracle for cobol-modernization transaction behavior."""

from __future__ import annotations

import hashlib
import json
import random
import sys
from typing import Any


CHECK_ID = "transaction_behavior"
OUTPUT_NAMES = ("accounts", "books", "transactions")
USER_NAMES = {
    "U001": "John Doe".ljust(20),
    "U002": "Jane Smith".ljust(20),
    "U003": "Bob Wilson".ljust(20),
}
BOOK_TITLES = {
    "B001": "Python Basics".ljust(20),
    "B002": "COBOL Guide".ljust(20),
    "B003": "Java Tutorial".ljust(20),
}
ORIGINAL_INPUTS = (
    "U001U003B0030000000020",
    "U002U001B0030000000050",
    "U002U001B0010000000150",
)


def render_accounts(balances: dict[str, int]) -> str:
    return "".join(
        f"{user_id}{USER_NAMES[user_id]}{balances[user_id]:010d}"
        for user_id in USER_NAMES
    )


def render_books(owners: dict[str, str]) -> str:
    return "".join(
        f"{book_id}{BOOK_TITLES[book_id]}{owners[book_id]}"
        for book_id in BOOK_TITLES
    )


def apply_transactions(
    balances: dict[str, int],
    owners: dict[str, str],
    initial_transactions: str,
    inputs: tuple[str, ...],
) -> dict[str, str]:
    balances = dict(balances)
    owners = dict(owners)
    transactions = initial_transactions
    for input_record in inputs:
        buyer = input_record[0:4]
        seller = input_record[4:8]
        book = input_record[8:12]
        amount = int(input_record[12:22])
        if (
            buyer not in balances
            or seller not in balances
            or book not in owners
            or owners[book] != seller
        ):
            continue
        balances[buyer] -= amount
        balances[seller] += amount
        owners[book] = buyer
        transactions += f"{book}{amount:010d}{seller}{buyer}"
    return {
        "accounts": render_accounts(balances),
        "books": render_books(owners),
        "transactions": transactions,
    }


def make_case(
    balances: dict[str, int],
    owners: dict[str, str],
    inputs: tuple[str, ...],
    *,
    initial_transactions: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    challenge = {
        "initial_accounts": render_accounts(balances),
        "initial_books": render_books(owners),
        "initial_transactions": initial_transactions,
        "inputs": list(inputs),
    }
    context = {
        "expected": apply_transactions(
            balances,
            owners,
            initial_transactions,
            inputs,
        ),
        "input_count": len(inputs),
    }
    return challenge, context


def original_case() -> tuple[dict[str, Any], dict[str, Any]]:
    return make_case(
        {"U001": 1000, "U002": 2000, "U003": 1500},
        {"B001": "U001", "B002": "U002", "B003": "U003"},
        ORIGINAL_INPUTS,
    )


def seeded_cases(run_seed: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    seed = hashlib.sha256(
        ("cobol-modernization\0" + run_seed).encode("utf-8")
    ).digest()
    generator = random.Random(seed)
    user_ids = tuple(USER_NAMES)
    book_ids = tuple(BOOK_TITLES)
    cases: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for transaction_count in (1, 2, 4):
        balances = {user: generator.randrange(4_000, 9_001) for user in user_ids}
        initial_owners = {book: generator.choice(user_ids) for book in book_ids}
        current_owners = dict(initial_owners)
        inputs: list[str] = []
        for _ in range(transaction_count):
            book = generator.choice(book_ids)
            seller = current_owners[book]
            buyer = generator.choice(tuple(user for user in user_ids if user != seller))
            amount = generator.randrange(1, 251)
            inputs.append(f"{buyer}{seller}{book}{amount:010d}")
            current_owners[book] = buyer
        initial_transactions = (
            "B0020000000007U001U003" if transaction_count == 4 else ""
        )
        cases.append(
            make_case(
                balances,
                initial_owners,
                tuple(inputs),
                initial_transactions=initial_transactions,
            )
        )
    return cases


class CobolModernizationOracle:
    def __init__(self) -> None:
        self.cases: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.case_index = 0
        self.evaluated = 0
        self.passed = True
        self.evaluation_ids: set[str] = set()
        self.failures: list[str] = []

    def initialize(self, run_seed: str) -> None:
        self.cases = [original_case(), *seeded_cases(run_seed)]
        self.case_index = 0
        self.evaluated = 0
        self.passed = True
        self.evaluation_ids.clear()
        self.failures.clear()

    def evaluate_artifact(self, _evidence: dict[str, Any]) -> None:
        self.passed = False
        self.failures.append("unexpected_artifact")

    def next_case(self) -> dict[str, Any]:
        if self.case_index >= len(self.cases):
            return {"type": "exhausted"}
        challenge, context = self.cases[self.case_index]
        self.case_index += 1
        return {"type": "case", "challenge": challenge, "case_context": context}

    def evaluate_case(self, context: dict[str, Any], evidence: dict[str, Any]) -> None:
        self.evaluated += 1
        if evidence.get("status") != "observed":
            self.passed = False
            failure = evidence.get("failure")
            code = failure.get("code") if isinstance(failure, dict) else None
            self.failures.append(str(code or "candidate_execution_failed"))
            return

        evaluation_id = evidence.get("evaluation_id")
        if not isinstance(evaluation_id, str) or evaluation_id in self.evaluation_ids:
            self.passed = False
            self.failures.append("evaluation_not_fresh")
        else:
            self.evaluation_ids.add(evaluation_id)

        observation = evidence.get("observation")
        exit_codes = observation.get("exit_codes") if isinstance(observation, dict) else None
        if (
            not isinstance(exit_codes, list)
            or len(exit_codes) != context.get("input_count")
            or any(isinstance(code, bool) or not isinstance(code, int) or code != 0 for code in exit_codes)
            or observation.get("timed_out") is not False
        ):
            self.passed = False
            self.failures.append("candidate_execution_failed")

        artifacts = evidence.get("output_artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != set(OUTPUT_NAMES):
            self.passed = False
            self.failures.append("output_artifacts_missing")
            return
        challenge_record = evidence.get("challenge")
        challenge_id = (
            challenge_record.get("id") if isinstance(challenge_record, dict) else None
        )
        expected = context.get("expected")
        if not isinstance(expected, dict):
            self.passed = False
            self.failures.append("invalid_case_context")
            return
        for name in OUTPUT_NAMES:
            artifact = artifacts[name]
            if not isinstance(artifact, dict) or artifact.get("status") != "observed":
                self.passed = False
                self.failures.append("output_artifact_rejected")
                continue
            if (
                artifact.get("evaluation_id") != evaluation_id
                or artifact.get("challenge_id") != challenge_id
            ):
                self.passed = False
                self.failures.append("output_artifact_not_correlated")
                continue
            if artifact.get("parsed_value") != expected.get(name):
                self.passed = False
                self.failures.append(f"{name}_mismatch")

    def verdict(self) -> dict[str, Any]:
        behavior = (
            self.evaluated == len(self.cases)
            and len(self.evaluation_ids) == len(self.cases)
            and self.passed
        )
        return {
            "type": "verdict",
            "verdict": {
                "passed": behavior,
                "score": 1.0 if behavior else 0.0,
                "check_outcomes": {CHECK_ID: behavior},
                "public_diagnostics": {
                    "message": (
                        "Python program matched the bounded transaction scenarios"
                        if behavior
                        else "Python program behavior did not satisfy the task"
                    ),
                    "failure_categories": sorted(set(self.failures))[:20],
                },
            },
        }


def main() -> None:
    oracle = CobolModernizationOracle()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation == "initialize":
                run_seed = request.get("run_seed")
                if not isinstance(run_seed, str):
                    raise ValueError("run seed is required")
                oracle.initialize(run_seed)
                response = {"type": "ack"}
            elif operation == "evaluate_artifact":
                evidence = request.get("evidence")
                if not isinstance(evidence, dict):
                    raise ValueError("artifact evidence is required")
                oracle.evaluate_artifact(evidence)
                response = {"type": "ack"}
            elif operation == "next_case":
                if (
                    request.get("check_id") != CHECK_ID
                    or request.get("challenge_source") != "host.task_oracle"
                    or request.get("bounds")
                    != {"max_cases": 4, "max_case_bytes": 131072}
                ):
                    raise ValueError("unsupported check")
                response = oracle.next_case()
            elif operation == "evaluate_case":
                context = request.get("case_context")
                evidence = request.get("evidence")
                if (
                    request.get("check_id") != CHECK_ID
                    or not isinstance(context, dict)
                    or not isinstance(evidence, dict)
                ):
                    raise ValueError("case evidence is required")
                oracle.evaluate_case(context, evidence)
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
