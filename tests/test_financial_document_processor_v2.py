from __future__ import annotations

import ast
import csv
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import shutil

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck, DirectoryTreeEntry
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/financial-document-processor"
IMAGE = (
    "alexgshaw/financial-document-processor@"
    "sha256:ef6c9cfaaf14cdd200163008a188d5baa9f626f3bfb8d3e7d6f30c08518e6251"
)
SOURCE_DOCUMENTS = PACK / "docker" / "financial-document-processor" / "documents"
SOURCE_VERIFIER = (
    PACK
    / "hidden"
    / "financial-document-processor"
    / "tests"
    / "test_outputs.py"
)
ORACLE_ROOT = (
    PACK / "v2" / "hidden" / "financial-document-processor" / "oracle"
)
EXPECTED_PATH = ORACLE_ROOT / "expected.json"
EXPECTED_SHA256 = "ca1802441451ea1e2e9b0fba77766ee45604777a254925c26a532c4932aef351"
EXPECTED = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
INVOICE_BY_SHA256 = {item["sha256"]: item for item in EXPECTED["invoices"]}
OTHER_SHA256 = {item["sha256"] for item in EXPECTED["others"]}


def compiled_task():
    return load_terminal_task(TASK_ID)


def source_assignment(name: str):
    tree = ast.parse(SOURCE_VERIFIER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"source assignment not found: {name}")


def document_identity(path: Path) -> tuple[str, str]:
    content = path.read_bytes()
    return hashlib.sha256(content).hexdigest(), hashlib.sha512(content).hexdigest()


def reference_summary(invoice_names: dict[str, str], *, newline: str = "\n") -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator=newline)
    writer.writerow(["filename", "total_amount", "vat_amount"])
    for digest, filename in sorted(invoice_names.items(), key=lambda item: item[1]):
        expected = INVOICE_BY_SHA256[digest]
        vat = "" if expected["vat_amount"] == "0" else expected["vat_amount"]
        writer.writerow([filename, expected["total_amount"], vat])
    writer.writerow(
        [
            "total",
            EXPECTED["totals"]["total_amount"],
            EXPECTED["totals"]["vat_amount"],
        ]
    )
    return output.getvalue()


def reference_workspace(tmp_path: Path) -> tuple[Path, dict[str, str], list[str]]:
    workspace = tmp_path / "workspace"
    invoices = workspace / "invoices"
    others = workspace / "other"
    documents = workspace / "documents"
    invoices.mkdir(parents=True)
    others.mkdir()
    documents.mkdir()
    invoice_names: dict[str, str] = {}
    other_names: list[str] = []
    for source in sorted(SOURCE_DOCUMENTS.iterdir()):
        digest, _ = document_identity(source)
        if digest in INVOICE_BY_SHA256:
            shutil.copyfile(source, invoices / source.name)
            invoice_names[digest] = source.name
        else:
            assert digest in OTHER_SHA256
            shutil.copyfile(source, others / source.name)
            other_names.append(source.name)
    (invoices / "summary.csv").write_text(
        reference_summary(invoice_names),
        encoding="utf-8",
        newline="",
    )
    (workspace / "ocr-cache.bin").write_bytes(b"excluded")
    return workspace, invoice_names, other_names


def verify_reference(tmp_path: Path, mutate=None):
    workspace, invoice_names, other_names = reference_workspace(tmp_path)
    if mutate is not None:
        mutate(workspace, invoice_names, other_names)
    result, candidate, store = verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "store",
        run_seed="financial-document-qualification",
    )
    return result, candidate, store


def test_financial_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert task.environment.timeout_seconds == 1200
    assert not task.assets
    assert not task.verification.resources.runtime
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.id == "document_state_artifact"
    assert [(artifact.id, artifact.parser) for artifact in check.artifacts] == [
        ("invoices_tree", "securebench.tree-manifest/v1"),
        ("other_tree", "securebench.tree-manifest/v1"),
        ("documents_tree", "securebench.tree-manifest/v1"),
        ("summary_csv", "securebench.utf8-text/v1"),
    ]
    assert check.artifacts[-1].source.entry == "invoices"
    assert check.artifacts[-1].source.subpath == "summary.csv"
    candidate = task.verification.candidate
    assert candidate.max_total_files == 80
    assert candidate.max_total_bytes == 20 * 1024 * 1024
    assert all(isinstance(entry, DirectoryTreeEntry) for entry in candidate.files)
    assert [(entry.id, entry.path) for entry in candidate.files] == [
        ("invoices", "/app/invoices"),
        ("other", "/app/other"),
        ("documents", "/app/documents"),
    ]
    assert {
        path.relative_to(ORACLE_ROOT).as_posix()
        for path in ORACLE_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    } == {"expected.json", "oracle.py", "oracle.yaml"}


def test_host_expectations_are_derived_from_source_verifier_and_public_documents():
    source_invoices = source_assignment("expected_original_documents") - {"summary.csv"}
    source_others = source_assignment("expected_original_others")
    source_data = source_assignment("expected_data")
    assert hashlib.sha256(EXPECTED_PATH.read_bytes()).hexdigest() == EXPECTED_SHA256
    assert len(EXPECTED["invoices"]) == 10
    assert len(EXPECTED["others"]) == 7
    assert {item["sha512"] for item in EXPECTED["invoices"]} == source_invoices
    assert {item["sha512"] for item in EXPECTED["others"]} == source_others

    observed_pairs = {document_identity(path) for path in SOURCE_DOCUMENTS.iterdir()}
    expected_pairs = {
        (item["sha256"], item["sha512"])
        for item in (*EXPECTED["invoices"], *EXPECTED["others"])
    }
    assert observed_pairs == expected_pairs
    for item in EXPECTED["invoices"]:
        source = source_data[item["sha512"]]
        assert Decimal(item["total_amount"]) == Decimal(str(source["total_amount"]))
        expected_vat = source["vat_amount"] if source["vat_amount"] != "" else 0
        assert Decimal(item["vat_amount"]) == Decimal(str(expected_vat))
    assert Decimal(EXPECTED["totals"]["total_amount"]) == Decimal(
        str(source_data["total"]["total_amount"])
    )
    assert Decimal(EXPECTED["totals"]["vat_amount"]) == Decimal(
        str(source_data["total"]["vat_amount"])
    )


@pytest.mark.parametrize(
    ("actual", "expected", "blank_is_zero", "source_result"),
    [
        ("81315.20", "81315.20", False, True),
        ("81315.209", "81315.20", False, True),
        ("81315.21", "81315.20", False, False),
        ("6204.199", "6204.19", False, True),
        ("6204.20", "6204.19", False, False),
        ("nan", "6204.19", False, False),
        ("inf", "6204.19", False, False),
        ("", "0", True, True),
        ("NA", "0", True, True),
        ("<NA>", "0", True, True),
        ("NULL", "0", True, True),
    ],
)
def test_oracle_numeric_tolerance_uses_source_pandas_and_float_predicates(
    actual, expected, blank_is_zero, source_result
):
    oracle = load_module(ORACLE_ROOT / "oracle.py", "financial_oracle_numbers")

    assert oracle.source_number_matches(
        actual,
        expected,
        blank_is_zero=blank_is_zero,
    ) is source_result


def test_oracle_pins_the_exact_pandas_2_3_2_default_na_vocabulary():
    oracle = load_module(ORACLE_ROOT / "oracle.py", "financial_oracle_na_values")

    assert oracle.PANDAS_2_3_2_DEFAULT_NA_VALUES == {
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


def test_reference_state_passes_and_excludes_unrelated_workspace_files(tmp_path):
    result, candidate, store = verify_reference(tmp_path)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert [entry["id"] for entry in manifest.payload["entries"]] == [
        "invoices",
        "other",
        "documents",
    ]
    assert "ocr-cache.bin" not in str(manifest.payload)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param("duplicates", id="duplicate_document_hashes"),
        pytest.param("ignored_files", id="ignored_json_and_nested_files"),
        pytest.param("all_totals", id="eleven_duplicate_total_rows"),
        pytest.param("reordered_crlf", id="reordered_rows_and_crlf"),
    ],
)
def test_source_accepted_final_state_quirks_pass(tmp_path, mutation):
    def mutate(workspace, invoice_names, other_names):
        invoices = workspace / "invoices"
        others = workspace / "other"
        if mutation == "duplicates":
            first_invoice = next(iter(invoice_names.values()))
            shutil.copyfile(invoices / first_invoice, invoices / f"copy-{first_invoice}")
            first_other = other_names[0]
            shutil.copyfile(others / first_other, others / f"copy-{first_other}")
        elif mutation == "ignored_files":
            (invoices / "ignored.json").write_text('{"verdict":"pass"}')
            (invoices / "nested").mkdir()
            (invoices / "nested" / "ignored.bin").write_bytes(b"ignored")
            (others / "nested").mkdir()
            (others / "nested" / "ignored.bin").write_bytes(b"ignored")
            (workspace / "documents" / "nested").mkdir()
            (workspace / "documents" / "nested" / "ignored.bin").write_bytes(b"ignored")
        elif mutation == "all_totals":
            rows = "filename,total_amount,vat_amount\n" + (
                "total,81315.20,5402.48\n" * 11
            )
            (invoices / "summary.csv").write_text(rows)
        elif mutation == "reordered_crlf":
            summary = reference_summary(invoice_names, newline="\r\n")
            lines = summary.splitlines()
            rows = list(reversed(lines[1:-1])) + [lines[-1]]
            (invoices / "summary.csv").write_bytes(
                (lines[0] + "\r\n" + "\r\n".join(rows) + "\r\n").encode()
            )
        else:
            raise AssertionError(mutation)

    result, _, _ = verify_reference(tmp_path, mutate)
    assert result.status == "passed", result


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        ("misplaced", "incorrect_invoice_placement"),
        ("modified", "incorrect_invoice_placement"),
        ("documents_not_empty", "documents_not_empty"),
        ("header", "incorrect_summary_header"),
        ("row_count", "incorrect_summary_row_count"),
        ("wrong_total", "incorrect_total_amount"),
        ("wrong_vat", "incorrect_vat_amount"),
        ("unknown_file", "unexpected_summary_file"),
        ("path_traversal", "unsafe_summary_filename"),
        ("pandas_na_filename", "unsafe_summary_filename"),
    ],
)
def test_targeted_state_and_summary_mutants_fail(tmp_path, mutation, failure):
    def mutate(workspace, invoice_names, other_names):
        invoices = workspace / "invoices"
        summary = invoices / "summary.csv"
        first_name = next(iter(invoice_names.values()))
        if mutation == "misplaced":
            shutil.move(invoices / first_name, workspace / "other" / first_name)
        elif mutation == "modified":
            with (invoices / first_name).open("ab") as stream:
                stream.write(b"mutant")
        elif mutation == "documents_not_empty":
            shutil.copyfile(invoices / first_name, workspace / "documents" / first_name)
        elif mutation == "header":
            summary.write_text(summary.read_text().replace("vat_amount", "tax_amount", 1))
        elif mutation == "row_count":
            summary.write_text("\n".join(summary.read_text().splitlines()[:-1]) + "\n")
        elif mutation == "wrong_total":
            summary.write_text(summary.read_text().replace("81315.20", "81315.22"))
        elif mutation == "wrong_vat":
            summary.write_text(summary.read_text().replace("5402.48", "5402.50"))
        elif mutation == "unknown_file":
            summary.write_text(summary.read_text().replace(first_name, "unknown.pdf", 1))
        elif mutation == "path_traversal":
            summary.write_text(
                summary.read_text().replace(
                    first_name,
                    f"../invoices/{first_name}",
                    1,
                )
            )
        elif mutation == "pandas_na_filename":
            (invoices / first_name).rename(invoices / "NA")
            summary.write_text(summary.read_text().replace(first_name, "NA", 1))
        else:
            raise AssertionError(mutation)

    result, _, _ = verify_reference(tmp_path, mutate)
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [failure]


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        ("missing", "summary_csv:artifact_missing"),
        ("directory", "summary_csv:artifact_wrong_type"),
        ("invalid_utf8", "summary_csv:invalid_utf8"),
    ],
)
def test_nested_summary_candidate_errors_fail_closed(tmp_path, mutation, failure):
    def mutate(workspace, invoice_names, other_names):
        summary = workspace / "invoices" / "summary.csv"
        summary.unlink()
        if mutation == "directory":
            summary.mkdir()
        elif mutation == "invalid_utf8":
            summary.write_bytes(b"\xff")
        elif mutation != "missing":
            raise AssertionError(mutation)

    result, _, _ = verify_reference(tmp_path, mutate)
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [failure]


def test_stored_directory_candidate_replays_exactly(tmp_path):
    first, candidate, store = verify_reference(tmp_path)
    replay = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="financial-document-replay",
    )

    assert first.status == replay.status == "passed"
    assert first.candidate_digest == replay.candidate_digest == candidate.digest


PINNED_REFERENCE_SCRIPT = r"""
set -eu
mkdir -p /app/invoices /app/other
printf 'filename,total_amount,vat_amount\n' > /app/invoices/summary.csv
for source in /app/documents/*; do
    digest=$(sha256sum "$source" | awk '{print $1}')
    name=${source##*/}
    case "$digest" in
        56238d4d934c433c24e53d0674f0530e11024f284e8ffcb3bb0bcc0d58850740) values='6204.19,564.02' ;;
        2c8607b9c75907077e23f45ce7bc75335a4a46e9f9aab5ee0d901b86b63e7a8e) values='9963.0,' ;;
        807a6b0b942eb2ce406db3c57a833bba539e165017c81e2b1a0a98104d213677) values='44745.59,4067.78' ;;
        c212aa5440b23e4b5e97af3c271685769b1050edd73a1ee461acce2c5998eb3c) values='797.91,72.54' ;;
        badb1930a086c35b1484463098cbfb7823beb21abae71a9fe95bf90807fa9e41) values='819.06,74.46' ;;
        53d8335a156bd0b18bd1808693cc805c39e013d9768fd7eb7497f22e18b1c5cb) values='6558.0,' ;;
        862f7d313f1233f3e44a89610a4015d861dc771ad2ba8028ad56e2d4fd37ac71) values='6860.45,623.68' ;;
        bc95a144939b7f21abd832019625a3f2c182a7abe8d57f9bd25e7c6f5d6b3ba5) values='440.0,' ;;
        d46a7397df8e7903ddef31b76c1633c4989f09b8c301e0cf87dab00cd08a4663) values='4031.0,' ;;
        570adcb1be1800cca727420b543e9c68bb7607ebaddf80524c7380560e549434) values='896.0,' ;;
        d5fc89cdc92240baa7fc6506237e3841af88880a6f57fa6e3f60b925e605fd22|0b3873d45510867d3063637d01f8e9255c4be96586b1f6b06682a208877d441c|ad8f14ad77a98d0926a68d17e5ce822c2f9d3a355ccf4a6b1ded5327c31cbb87|a51b4a78c278c1b755e674511729d8514681b94094a4130c457ed71c533a0083|ad3359faf1126b33fc587098ed3f5b722734eeb4364794eea66e10112014f25a|5ee01b997176b9124302899471651ce4d4b160f292caf79f2250e2e8324e3480|e0b8a2c7078efe82d7657f5023f01ff5498d59cca54a74ef2b6983bc979a1c54)
            mv "$source" "/app/other/$name"
            continue
            ;;
        *) exit 1 ;;
    esac
    mv "$source" "/app/invoices/$name"
    printf '%s,%s\n' "$name" "$values" >> /app/invoices/summary.csv
done
printf 'total,81315.20,5402.48\n' >> /app/invoices/summary.csv
"""


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("mutation", "expected_status"),
    [
        ("", "passed"),
        (
            "printf 'filename,total_amount,vat_amount\\n' > /app/invoices/summary.csv; "
            "i=0; while [ \"$i\" -lt 11 ]; do "
            "printf 'total,81315.20,5402.48\\n' >> /app/invoices/summary.csv; "
            "i=$((i + 1)); done",
            "passed",
        ),
        ("sed -i 's/81315.20/81315.22/' /app/invoices/summary.csv", "failed"),
        (
            "for value in /app/invoices/*; do "
            "[ \"${value##*/}\" = summary.csv ] && continue; "
            "mv \"$value\" /app/other/; break; done",
            "failed",
        ),
        ("printf '{\"verdict\":\"pass\"}' > /app/invoices/summary.csv", "failed"),
    ],
)
def test_pinned_linux_reference_and_mutant_matrix(tmp_path, mutation, expected_status):
    command = PINNED_REFERENCE_SCRIPT
    if mutation:
        command += "\n" + mutation + "\n"
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", command),
        run_seed=f"financial-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
