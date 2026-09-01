"""Host-only Oracle for the financial document final-state artifact."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import sys
from typing import Any


CHECK_ID = "document_state_artifact"
ARTIFACT_IDS = {
    "invoices_tree",
    "other_tree",
    "documents_tree",
    "summary_csv",
}
EXPECTED_SHA256 = "ca1802441451ea1e2e9b0fba77766ee45604777a254925c26a532c4932aef351"
TOLERANCE = 0.01
PANDAS_2_3_2_DEFAULT_NA_VALUES = frozenset(
    {
        "",
        "#N/A",
        "#N/A N/A",
        "#NA",
        "-1.#IND",
        "-1.#QNAN",
        "-NaN",
        "-nan",
        "1.#IND",
        "1.#QNAN",
        "<NA>",
        "N/A",
        "NA",
        "NULL",
        "NaN",
        "None",
        "n/a",
        "nan",
        "null",
    }
)


def load_expected() -> dict[str, Any]:
    content = (Path(__file__).resolve().parent / "expected.json").read_bytes()
    if hashlib.sha256(content).hexdigest() != EXPECTED_SHA256:
        raise ValueError("expected financial corpus integrity check failed")
    value = json.loads(content)
    if not isinstance(value, dict) or set(value) != {"invoices", "others", "totals"}:
        raise ValueError("expected financial corpus is malformed")
    return value


def immediate_regular_files(tree: Any) -> dict[str, str]:
    if not isinstance(tree, dict) or not isinstance(tree.get("nodes"), list):
        raise ValueError("tree observation is malformed")
    files: dict[str, str] = {}
    for node in tree["nodes"]:
        if not isinstance(node, dict):
            raise ValueError("tree node is malformed")
        path = node.get("path")
        kind = node.get("kind")
        if not isinstance(path, str) or not isinstance(kind, str):
            raise ValueError("tree node fields are malformed")
        if "/" in path or kind != "regular_file":
            continue
        blob = node.get("blob")
        if not isinstance(blob, str) or not blob.startswith("sha256:"):
            raise ValueError("tree file digest is malformed")
        files[path] = blob
    return files


def safe_invoice_name(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and value not in PANDAS_2_3_2_DEFAULT_NA_VALUES
        and not path.is_absolute()
        and len(path.parts) == 1
        and path.name == value
        and "\\" not in value
        and "\x00" not in value
    )


def source_number_matches(
    value: str,
    expected: str,
    *,
    blank_is_zero: bool = False,
) -> bool:
    if blank_is_zero and value in PANDAS_2_3_2_DEFAULT_NA_VALUES:
        value = "0"
    try:
        actual_number = float(value)
        expected_number = float(expected)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(actual_number)
        and abs(actual_number - expected_number) < TOLERANCE
    )


def summary_failure(
    content: str,
    invoice_files: dict[str, str],
    expected: dict[str, Any],
) -> str | None:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    try:
        reader = csv.DictReader(io.StringIO(normalized, newline=""))
        if reader.fieldnames != ["filename", "total_amount", "vat_amount"]:
            return "incorrect_summary_header"
        rows = list(reader)
    except (csv.Error, UnicodeError):
        return "malformed_summary_csv"
    if len(rows) != 11:
        return "incorrect_summary_row_count"
    invoice_expected = {
        "sha256:" + item["sha256"]: item for item in expected["invoices"]
    }
    for row in rows:
        if set(row) != {"filename", "total_amount", "vat_amount"}:
            return "malformed_summary_csv"
        filename = row.get("filename")
        total_amount = row.get("total_amount")
        vat_amount = row.get("vat_amount")
        if not all(isinstance(value, str) for value in (filename, total_amount, vat_amount)):
            return "malformed_summary_csv"
        assert isinstance(filename, str)
        assert isinstance(total_amount, str)
        assert isinstance(vat_amount, str)
        if filename == "total":
            row_expected = expected["totals"]
        else:
            if not safe_invoice_name(filename):
                return "unsafe_summary_filename"
            digest = invoice_files.get(filename)
            row_expected = invoice_expected.get(digest)
            if row_expected is None:
                return "unexpected_summary_file"
        if not source_number_matches(total_amount, row_expected["total_amount"]):
            return "incorrect_total_amount"
        if not source_number_matches(
            vat_amount,
            row_expected["vat_amount"],
            blank_is_zero=True,
        ):
            return "incorrect_vat_amount"
    return None


def score_observations(observations: dict[str, Any], expected: dict[str, Any]) -> str | None:
    try:
        invoices = immediate_regular_files(observations["invoices_tree"])
        others = immediate_regular_files(observations["other_tree"])
        documents = immediate_regular_files(observations["documents_tree"])
    except (KeyError, ValueError):
        return "malformed_tree_observation"

    invoice_hashes = {
        digest for name, digest in invoices.items() if not name.endswith(".json")
    }
    invoice_hashes.discard(invoices.get("summary.csv"))
    expected_invoices = {"sha256:" + item["sha256"] for item in expected["invoices"]}
    if invoice_hashes != expected_invoices or "summary.csv" not in invoices:
        return "incorrect_invoice_placement"

    other_hashes = set(others.values())
    expected_others = {"sha256:" + item["sha256"] for item in expected["others"]}
    if other_hashes != expected_others:
        return "incorrect_other_placement"
    if documents:
        return "documents_not_empty"

    summary = observations.get("summary_csv")
    if not isinstance(summary, str):
        return "malformed_summary_csv"
    summary_invoice_files = {
        name: digest
        for name, digest in invoices.items()
        if name != "summary.csv" and not name.endswith(".json")
    }
    return summary_failure(summary, summary_invoice_files, expected)


class FinancialDocumentOracle:
    def __init__(self) -> None:
        self.expected: dict[str, Any] = {}
        self.observations: dict[str, Any] = {}
        self.failure = "not_evaluated"

    def initialize(self) -> None:
        self.expected = load_expected()
        self.observations = {}
        self.failure = "not_evaluated"

    def evaluate(self, evidence: dict[str, Any]) -> None:
        if self.failure != "not_evaluated":
            return
        artifact_id = evidence.get("artifact_id")
        if evidence.get("check_id") != CHECK_ID or artifact_id not in ARTIFACT_IDS:
            self.failure = "uncorrelated_artifact"
            return
        assert isinstance(artifact_id, str)
        if artifact_id in self.observations:
            self.failure = "duplicate_artifact"
            return
        if evidence.get("status") != "observed":
            error = evidence.get("error")
            code = (
                str(error.get("code", "artifact_rejected"))
                if isinstance(error, dict)
                else "artifact_rejected"
            )
            self.failure = f"{artifact_id}:{code}"
            return
        self.observations[artifact_id] = evidence.get("parsed_value")

    def verdict(self) -> dict[str, Any]:
        failure = self.failure
        if failure == "not_evaluated" and set(self.observations) == ARTIFACT_IDS:
            failure = score_observations(self.observations, self.expected) or ""
        passed = failure == ""
        return {
            "type": "verdict",
            "verdict": {
                "passed": passed,
                "score": 1.0 if passed else 0.0,
                "check_outcomes": {CHECK_ID: passed},
                "public_diagnostics": {
                    "message": (
                        "Financial document state matches the source requirements"
                        if passed
                        else "Financial document placement or summary is incorrect"
                    ),
                    "failure_categories": [] if passed else [failure],
                },
            },
        }


def main() -> None:
    oracle = FinancialDocumentOracle()
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
