from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ProtocolCheck
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_command_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/extract-elf"
IMAGE = (
    "alexgshaw/extract-elf@"
    "sha256:6932e4cb318464307eacd497ef8dc617eaf551b6a90231f815ec0b911895cfed"
)
ADAPTER = PACK / "v2" / "evaluation_inputs" / "extract-elf" / "adapter"
ORACLE = PACK / "v2" / "hidden" / "extract-elf" / "oracle" / "oracle.py"
SOURCE_VERIFIER = PACK / "hidden" / "extract-elf" / "tests" / "test_outputs.py"
CASE_DIGESTS = {
    "arguments.elf": "b43fdc21e9103d6e1d924a312f50d1c2edcb3a148896e35da46a8cac659aa80c",
    "functions.elf": "2fee5485a493ca00cd067dc0da1c957fc3250af8cd1fd2883d4b9724b04c3c40",
    "hello.elf": "90db2f0afd5b3ff4d719b829b322b2558c67e79523aeb4c057e811522ccc7c05",
    "sections.elf": "84abf6e1d1da385bbd6b37e138d0794da18354ad1b874f9275247b0510b0b3a5",
}


def compiled_task():
    return load_terminal_task(TASK_ID)


def reference_script() -> str:
    source = load_module(SOURCE_VERIFIER, "extract_elf_source_reference")
    return source.REF.strip()


def mutate_reference(replacement: str) -> str:
    original = "console.log(JSON.stringify(memoryOutput));"
    reference = reference_script()
    assert reference.count(original) == 1
    return reference.replace(original, replacement)


def observed_evidence(
    context: dict,
    output: object,
    *,
    evaluation_id: str,
) -> dict:
    stdout = output if isinstance(output, str) else json.dumps(output)
    return {
        "check_id": "extractor_behavior",
        "status": "observed",
        "evaluation_id": evaluation_id,
        "challenge": {
            "index": context["case_index"],
            "digest": context["challenge_digest"],
        },
        "observation": {"exit_code": 0, "stdout": stdout, "stderr": ""},
    }


def test_extract_elf_row_is_bounded_split_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert task.environment.timeout_seconds == 900
    candidate = task.verification.candidate
    assert candidate.max_total_files == 1
    assert candidate.max_total_bytes == 262_144
    assert [(item.id, item.path, item.max_bytes) for item in candidate.files] == [
        ("extractor", "/app/extract.js", 262_144)
    ]
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ProtocolCheck)
    assert check.id == "extractor_behavior"
    assert check.protocol == "securebench.elf-extractor/v1"
    assert check.challenge.max_cases == 4
    assert check.challenge.max_case_bytes == 131_072
    assert not check.trusted_helpers
    assert not check.output_artifacts

    adapter_files = {
        path.relative_to(ADAPTER).as_posix()
        for path in ADAPTER.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert adapter_files == {"adapter.py", "adapter.yaml"}


def test_hidden_case_corpus_is_bounded_and_pinned():
    directory = ORACLE.parent / "cases"
    assert {path.name for path in directory.iterdir()} == {
        *CASE_DIGESTS,
        "arguments.c",
        "functions.c",
        "hello.c",
        "sections.c",
    }
    for name, digest in CASE_DIGESTS.items():
        content = (directory / name).read_bytes()
        assert len(content) <= 65_536
        assert hashlib.sha256(content).hexdigest() == digest


def test_host_parser_matches_the_original_node_reference(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for source-reference conformance")
    script = tmp_path / "reference.js"
    script.write_text(reference_script(), encoding="utf-8")
    oracle_module = load_module(ORACLE, "extract_elf_reference_conformance")

    for elf in sorted((ORACLE.parent / "cases").glob("*.elf")):
        completed = subprocess.run(
            [node, str(script), str(elf)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == oracle_module.extract_reference_values(
            elf.read_bytes()
        )


def test_oracle_accepts_exact_coverage_boundary_and_ignored_extra_keys():
    oracle_module = load_module(ORACLE, "extract_elf_coverage_boundary")
    oracle = oracle_module.ElfExtractionOracle()
    oracle.initialize("coverage-boundary")

    while (case := oracle.next_case())["type"] == "case":
        context = case["case_context"]
        expected = oracle.cases[context["case_index"]]["expected"]
        required = math.ceil(len(expected) * 0.75)
        output = dict(list(expected.items())[:required])
        output["not-a-reference-address"] = 7
        oracle.evaluate_case(
            context,
            observed_evidence(
                context,
                output,
                evaluation_id=f"evaluation_{context['case_index']}",
            ),
        )

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is True
    assert verdict["check_outcomes"] == {"extractor_behavior": True}


@pytest.mark.parametrize(
    ("attack", "category"),
    [
        ("low_coverage", "candidate_coverage_insufficient"),
        ("wrong_word", "candidate_value_incorrect"),
        ("string_word", "candidate_value_not_integer"),
        ("forged_verdict", "candidate_value_not_integer"),
        ("invalid_json", "candidate_output_invalid"),
        ("challenge_digest", "challenge_correlation_failed"),
        ("reused_evaluation", "evaluation_not_fresh"),
    ],
)
def test_oracle_rejects_semantic_mutants_and_forged_claims(attack, category):
    oracle_module = load_module(ORACLE, f"extract_elf_oracle_{attack}")
    oracle = oracle_module.ElfExtractionOracle()
    oracle.initialize("mutant-qualification")
    reused_id = "evaluation_reused"

    while (case := oracle.next_case())["type"] == "case":
        context = case["case_context"]
        expected = oracle.cases[context["case_index"]]["expected"]
        output: object = expected
        if attack == "low_coverage":
            output = dict(list(expected.items())[: len(expected) // 2])
        elif attack == "wrong_word":
            output = dict(expected)
            first = next(iter(output))
            output[first] = (output[first] + 1) & 0xFFFF_FFFF
        elif attack == "string_word":
            output = dict(expected)
            first = next(iter(output))
            output[first] = str(output[first])
        elif attack == "forged_verdict":
            output = {"verdict": "pass", "score": 1}
        elif attack == "invalid_json":
            output = "{not-json}"
        evaluation_id = (
            reused_id
            if attack == "reused_evaluation"
            else f"evaluation_{context['case_index']}"
        )
        evidence = observed_evidence(context, output, evaluation_id=evaluation_id)
        if attack == "challenge_digest":
            evidence["challenge"]["digest"] = "sha256:" + "0" * 64
        oracle.evaluate_case(context, evidence)

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is False
    assert category in verdict["public_diagnostics"]["failure_categories"]


HALF_REFERENCE = mutate_reference(
    "const entries = Object.entries(memoryOutput);\n"
    "  console.log(JSON.stringify(Object.fromEntries("
    "entries.slice(0, Math.floor(entries.length / 2)))));"
)
WRONG_REFERENCE = mutate_reference(
    "const first = Object.keys(memoryOutput)[0];\n"
    "  memoryOutput[first] = (memoryOutput[first] + 1) >>> 0;\n"
    "  console.log(JSON.stringify(memoryOutput));"
)


def candidate_command(script: str) -> tuple[str, ...]:
    return (
        "sh",
        "-c",
        'printf "%s" "$1" > /app/extract.js',
        "securebench",
        script,
    )


@DOCKER_INTEGRATION
def test_reference_passes_fresh_pinned_evaluations_and_exact_replay(tmp_path):
    task = compiled_task()
    result, candidate, store = verify_command_candidate(
        task,
        tmp_path,
        command=candidate_command(reference_script()),
        run_seed="extract-elf-reference",
    )
    replay = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="extract-elf-reference",
    )

    assert result.status == replay.status == "passed"
    assert result.candidate_digest == replay.candidate_digest == candidate.digest
    for item in (result, replay):
        check = item.checks[0]
        assert check.cases == 4
        assert len(set(check.evidence_digests)) == 4


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "script",
    [
        pytest.param(HALF_REFERENCE, id="half-coverage"),
        pytest.param(WRONG_REFERENCE, id="wrong-known-word"),
        pytest.param('console.log(JSON.stringify({"verdict": 1}));', id="forged-verdict"),
        pytest.param('process.stdout.write("x".repeat(70000));', id="output-flood"),
    ],
)
def test_semantic_and_malicious_candidates_fail_real_pinned_evaluations(
    tmp_path, script
):
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=candidate_command(script),
        run_seed="extract-elf-mutant",
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
