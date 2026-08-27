from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateCaptureError,
    CandidateStore,
    HostWorkspaceFilesystem,
    capture_file_bundle,
    capture_production,
)
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.command import CommandHarnessProducer
from securebench.schemas.benchmark import ArtifactCheck, ProtocolCheck
from securebench.verification import VerificationEngine
from securebench.workspaces.cleanup import remove_untrusted_tree


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/circuit-fibsqrt"
IMAGE = (
    "alexgshaw/circuit-fibsqrt@"
    "sha256:29783439f529eaed2145592f15af7a2281161528860392a382c825489030ae3a"
)
ADAPTER = (
    PACK
    / "v2"
    / "evaluation_inputs"
    / "circuit-fibsqrt"
    / "adapter"
)
ORACLE = PACK / "v2" / "hidden" / "circuit-fibsqrt" / "oracle" / "oracle.py"
REFERENCE = Path("/tmp/securebench-circuit-reference/gates.txt")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compiled_task():
    pack = load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
    return next(task for task in compile_benchmark_pack(pack) if task.id == TASK_ID)


def _identity_circuit() -> bytes:
    return "".join(f"out{index} = out{index}\n" for index in range(32)).encode()


def _constant_circuit(value: int) -> bytes:
    return "".join(
        f"out{index} = {(value >> index) & 1}\n" for index in range(32)
    ).encode()


@pytest.fixture(scope="module")
def simulator(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("gcc")
    if compiler is None:
        pytest.skip("gcc is required for the circuit simulator qualification")
    binary = tmp_path_factory.mktemp("circuit-simulator") / "simulator"
    completed = subprocess.run(
        [
            compiler,
            "-O3",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ADAPTER / "simulator.c"),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return binary


def _run_simulator(
    simulator: Path,
    tmp_path: Path,
    content: bytes,
    input_value: int = 0,
) -> subprocess.CompletedProcess[str]:
    circuit = tmp_path / "gates.txt"
    circuit.write_bytes(content)
    return subprocess.run(
        [str(simulator), str(circuit), str(input_value)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def test_circuit_row_is_bounded_split_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.verification.candidate.max_total_files == 1
    assert task.verification.candidate.max_total_bytes == 2 * 1024 * 1024
    assert task.verification.candidate.files[0].path == "/app/gates.txt"
    assert [type(check) for check in task.verification.checks] == [
        ArtifactCheck,
        ProtocolCheck,
    ]
    protocol = task.verification.checks[1]
    assert protocol.challenge.max_cases == 32
    assert protocol.protocol == "securebench.circuit-simulator/v1"
    assert not protocol.trusted_helpers
    assert not protocol.output_artifacts

    adapter_files = {
        path.relative_to(ADAPTER).as_posix()
        for path in ADAPTER.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert adapter_files == {"adapter.py", "adapter.yaml", "simulator.c"}


def test_simulator_preserves_input_and_output_bit_order(simulator, tmp_path):
    result = _run_simulator(simulator, tmp_path, _identity_circuit(), 0xA5C3_7E19)

    assert result.returncode == 0, result.stderr
    assert int(result.stdout) == 0xA5C3_7E19


def test_simulator_supports_every_public_gate_operation(simulator, tmp_path):
    lines = [f"out{index} = out{index}" for index in range(32)]
    lines.extend(
        [
            "out32 = 0",
            "out33 = 1",
            "out34 = ~out0",
            "out35 = out0 & out1",
            "out36 = out0 | out1",
            "out37 = out0 ^ out1",
            "out38 = out1",
        ]
    )
    lines.extend(f"out{index} = 0" for index in range(39, 64))
    result = _run_simulator(simulator, tmp_path, ("\n".join(lines) + "\n").encode(), 1)

    assert result.returncode == 0, result.stderr
    assert int(result.stdout) == 0b11_0010


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (b"out0 = out0\n", "insufficient_outputs"),
        (_identity_circuit() + b"out0 = 1\n", "duplicate_signal"),
        (_identity_circuit() + b"out32000 = 0\n", "invalid_gate"),
        (_identity_circuit() + b"out31 = out32000\n", "invalid_gate"),
        (_identity_circuit() + b"out32 = __import__('os')\n", "invalid_gate"),
        (_identity_circuit() + b"\x00", "invalid_gate"),
        (_identity_circuit() + b"x" * 256 + b"\n", "gate_line_too_long"),
    ],
)
def test_simulator_rejects_malformed_and_executable_gate_text(
    simulator, tmp_path, content, error
):
    result = _run_simulator(simulator, tmp_path, content)

    assert result.returncode == 10
    assert result.stderr.strip() == error
    assert result.stdout == ""


def test_simulator_rejects_32000_physical_lines(simulator, tmp_path):
    content = _identity_circuit() + b"\n" * (32_000 - 32)
    result = _run_simulator(simulator, tmp_path, content)

    assert result.returncode == 10
    assert result.stderr.strip() == "too_many_gates"


def test_oracle_replays_original_cases_and_adds_seeded_private_cases():
    oracle_module = _load_module(ORACLE, "circuit_fibsqrt_oracle_cases")
    first = oracle_module.CircuitOracle()
    second = oracle_module.CircuitOracle()
    first.initialize("first-seed")
    second.initialize("second-seed")

    assert tuple(first.cases[:28]) == oracle_module.ORIGINAL_CASES
    assert len(first.cases) == 32
    assert len(set(first.cases)) == 32
    assert first.cases[-4:] != second.cases[-4:]
    assert all(1 <= item <= 220**2 + 1 for item in first.cases[-4:])


def test_oracle_accepts_independent_correct_evidence():
    oracle_module = _load_module(ORACLE, "circuit_fibsqrt_oracle_pass")
    oracle = oracle_module.CircuitOracle()
    oracle.initialize("qualification-seed")
    oracle.evaluate_artifact(
        {
            "check_id": "circuit_shape",
            "status": "observed",
            "parsed_value": _identity_circuit().decode(),
        }
    )
    index = 0
    while (case := oracle.next_case())["type"] == "case":
        oracle.evaluate_case(
            case["case_context"],
            {
                "status": "observed",
                "evaluation_id": f"evaluation_{index}",
                "observation": {
                    "exit_code": 0,
                    "stdout": f"{case['case_context']['expected']}\n",
                    "stderr": "",
                },
            },
        )
        index += 1

    verdict = oracle.verdict()["verdict"]
    assert verdict["passed"] is True
    assert verdict["check_outcomes"] == {
        "circuit_shape": True,
        "circuit_behavior": True,
    }


@pytest.mark.parametrize("attack", ["wrong_output", "forged_claim", "reused_evaluation"])
def test_oracle_rejects_behavior_mutants_and_claims(attack):
    oracle_module = _load_module(ORACLE, f"circuit_fibsqrt_oracle_{attack}")
    oracle = oracle_module.CircuitOracle()
    oracle.initialize("mutant-seed")
    oracle.evaluate_artifact(
        {
            "check_id": "circuit_shape",
            "status": "observed",
            "parsed_value": _identity_circuit().decode(),
        }
    )
    index = 0
    while (case := oracle.next_case())["type"] == "case":
        expected = case["case_context"]["expected"]
        observation = {"exit_code": 0, "stdout": f"{expected}\n", "stderr": ""}
        if attack == "wrong_output" and index == 5:
            observation["stdout"] = f"{expected ^ 1}\n"
        if attack == "forged_claim" and index == 5:
            observation = {
                "exit_code": 0,
                "stdout": '{"verdict":"passed","score":1}\n',
                "stderr": "",
            }
        oracle.evaluate_case(
            case["case_context"],
            {
                "status": "observed",
                "evaluation_id": "evaluation_0" if attack == "reused_evaluation" else f"evaluation_{index}",
                "observation": observation,
            },
        )
        index += 1

    assert oracle.verdict()["verdict"]["passed"] is False


def test_missing_candidate_is_scored_by_the_oracle():
    result = VerificationEngine().verify_candidate_error(
        compiled_task(),
        code="candidate_capture_rejected",
        message="Candidate capture was rejected",
        run_seed="circuit-fibsqrt-missing",
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [
        "candidate_capture_rejected"
    ]


@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
def test_capture_rejects_malicious_circuit_shapes(tmp_path, attack):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "gates.txt"
    if attack == "symlink":
        (workspace / "other.txt").write_bytes(_identity_circuit())
        target.symlink_to("other.txt")
    elif attack == "directory":
        target.mkdir()
    else:
        target.write_bytes(b"x" * (2 * 1024 * 1024 + 1))

    with pytest.raises(CandidateCaptureError):
        capture_file_bundle(
            HostWorkspaceFilesystem(workspace, guest_root="/app"),
            task.verification.candidate,
            CandidateStore(tmp_path / "store"),
            baseline_digest=task.baseline_digest,
        )


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 for pinned-image qualification",
)
def test_base_image_fails_stopped_candidate_capture(tmp_path):
    task = compiled_task()
    producer = CommandHarnessProducer(
        command=("sh", "-c", "rm -f /app/gates.txt"),
        workspace_root=tmp_path / "workspaces",
    )
    production = producer.produce(task)
    try:
        with pytest.raises(CandidateCaptureError):
            capture_production(task, production, CandidateStore(tmp_path / "store"))
    finally:
        remove_untrusted_tree(production.workspace, image=task.environment.image)


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 for pinned-image qualification",
)
def test_reference_passes_real_pinned_evaluations(tmp_path):
    if not REFERENCE.is_file():
        pytest.skip("generate the pinned upstream reference under /tmp for manual qualification")
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "gates.txt").write_bytes(REFERENCE.read_bytes())
    store = CandidateStore(tmp_path / "store")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
    )

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="circuit-fibsqrt-pinned-reference",
    )

    assert result.status == "passed", result
    behavior = next(check for check in result.checks if check.id == "circuit_behavior")
    assert behavior.cases == 32
    assert len(set(behavior.evidence_digests)) == 32


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 for pinned-image qualification",
)
def test_constant_and_identity_mutants_fail_real_pinned_evaluations(tmp_path):
    task = compiled_task()
    mutants = [
        ("constant", _constant_circuit(1)),
        ("identity", _identity_circuit()),
    ]
    if REFERENCE.is_file():
        reference = REFERENCE.read_bytes()
        assert reference.endswith(b"out20103 = out1018\n")
        mutants.append(
            (
                "reference-output-bit",
                reference.removesuffix(b"out20103 = out1018\n")
                + b"out20103 = ~out1018\n",
            )
        )
    for name, content in mutants:
        workspace = tmp_path / name
        workspace.mkdir()
        (workspace / "gates.txt").write_bytes(content)
        store = CandidateStore(tmp_path / f"store-{name}")
        candidate = capture_file_bundle(
            HostWorkspaceFilesystem(workspace, guest_root="/app"),
            task.verification.candidate,
            store,
            baseline_digest=task.baseline_digest,
        )
        result = VerificationEngine().verify(
            task,
            candidate,
            store,
            run_seed=f"circuit-fibsqrt-{name}-mutant",
        )
        assert result.status == "failed", result
        assert result.infrastructure_error is None, result


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 for pinned-image qualification",
)
def test_out_of_bounds_parser_attack_is_candidate_failure_in_real_evaluations(tmp_path):
    task = compiled_task()
    workspace = tmp_path / "parser-attack"
    workspace.mkdir()
    (workspace / "gates.txt").write_bytes(
        _identity_circuit() + b"out-1 = out0\n"
    )
    store = CandidateStore(tmp_path / "store-parser-attack")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
    )

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="circuit-fibsqrt-parser-attack",
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [
        "circuit_execution_failed"
    ]
