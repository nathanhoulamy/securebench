from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ProtocolCheck
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/install-windows-3.11"
IMAGE = (
    "alexgshaw/install-windows-3.11@"
    "sha256:c6695097316ef8810abce0545e347e65354aef9d51d4f7f662c3242e742f6a3e"
)
ADAPTER = PACK / "v2" / "evaluation_inputs" / "install-windows-3.11" / "adapter"
HIDDEN = PACK / "v2" / "hidden" / "install-windows-3.11"
ORACLE = HIDDEN / "oracle" / "oracle.py"
QUALIFICATION = HIDDEN / "qualification"
DISK_SHA256 = "58fb76014dccf13ec048e894ca1e44773eee940ccbc71c97a2ab3d07285da553"


def compiled_task():
    return load_terminal_task(TASK_ID)


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _helper_evidence() -> dict:
    return {
        "process_control": {
            "type": "securebench.process-supervisor/v1",
            "challenge_id": "challenge_0",
            "evaluation_id": "evaluation_0",
            "truncated": False,
            "value": {
                "process": {
                    "container_started": True,
                    "started_after_ms": 2,
                    "duration_ms": 25_000,
                    "exit_code": 0,
                    "timed_out": False,
                },
                "signals": [],
            },
        }
    }


def _correct_observation(context: dict) -> dict:
    frames = []
    for index, key in enumerate(context["keys"]):
        frames.append(
            {
                "key": key,
                "width": 640,
                "height": 480,
                "different_components": 100 if index == 0 else 1,
                "total_components": 1_000,
                "sha256": "b" * 64,
                "monitor_base64": _encoded(b"(qemu)"),
                "monitor_error": "",
                "capture_error": "",
            }
        )
    return {
        "launcher_exit": 0,
        "launcher_timed_out": False,
        "qemu_processes": [
            {
                "pid": 42,
                "executable": "/app/qemu/bin/qemu-system-i386",
                "arguments": [
                    "/app/qemu/bin/qemu-system-i386",
                    "-drive",
                    "file=/app/isos/win311.img,format=raw,snapshot=on",
                    "-m",
                    "32",
                    "-vga",
                    "cirrus",
                    "-vnc",
                    ":1",
                    "-monitor",
                    "unix:/tmp/qemu-monitor.sock,server,nowait",
                    "-snapshot",
                ],
            }
        ],
        "listen_ports": [80, 5901],
        "disk_sha256_before": DISK_SHA256,
        "disk_sha256_after": DISK_SHA256,
        "disk_size_before": 268_435_456,
        "disk_size_after": 268_435_456,
        "http": {
            "status": 200,
            "body_base64": _encoded(b"<html>noVNC</html>"),
            "body_too_large": False,
            "error": "",
        },
        "monitor_base64": _encoded(b"QEMU monitor 5.2.0"),
        "monitor_error": "",
        "baseline": {
            "width": 640,
            "height": 480,
            "capture_error": "",
            "sha256": "a" * 64,
        },
        "frames": frames,
        "output_too_large": False,
        "stdout_base64": "",
        "stderr_base64": "",
    }


def _evidence(observation: dict) -> dict:
    return {
        "status": "observed",
        "challenge": {"id": "challenge_0"},
        "evaluation_id": "evaluation_0",
        "trusted_helper_evidence": _helper_evidence(),
        "observation": observation,
    }


def test_install_windows_row_is_bounded_split_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    candidate = task.verification.candidate
    assert candidate.max_total_files == 258
    assert candidate.max_total_bytes == 67_239_936
    assert [(entry.id, entry.path) for entry in candidate.files] == [
        ("launcher", "/app/start-windows.sh"),
        ("web_config", "/app/windows-web.conf"),
        ("qemu_runtime", "/app/qemu"),
    ]
    protocol = task.verification.checks[0]
    assert isinstance(protocol, ProtocolCheck)
    assert protocol.protocol == "securebench.windows-qemu/v1"
    assert protocol.challenge.max_cases == 1
    assert [helper.type for helper in protocol.trusted_helpers] == [
        "securebench.process-supervisor/v1"
    ]
    assert "stopped replay" in task.input["instructions"]

    adapter_files = {
        path.relative_to(ADAPTER).as_posix()
        for path in ADAPTER.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert adapter_files == {"adapter.py", "adapter.yaml"}


def test_public_adapter_contains_no_host_judgment_constants():
    public_text = (ADAPTER / "adapter.py").read_text()

    assert DISK_SHA256 not in public_text
    assert "minimum_change" not in public_text
    assert "verdict" not in public_text
    assert "passed" not in public_text


def test_oracle_varies_key_order_and_keeps_host_values_private():
    oracle_module = load_module(ORACLE, "windows_qemu_oracle_cases")
    orders = {
        tuple(oracle_module.build_cases(f"seed-{index}")[0]["challenge"]["keys"])
        for index in range(8)
    }
    case = oracle_module.build_cases("first")[0]

    assert len(orders) > 1
    assert set(case["challenge"]["keys"]) == {
        "f1",
        "alt-tab",
        "f10",
        "alt-f4",
        "ctrl-esc",
    }
    assert case["context"]["disk_sha256"] == DISK_SHA256
    assert "disk_sha256" not in case["challenge"]


def test_oracle_accepts_independent_correct_evidence():
    oracle_module = load_module(ORACLE, "windows_qemu_oracle_pass")
    oracle = oracle_module.WindowsQemuOracle()
    oracle.initialize("qualification")
    case = oracle.next_case()
    oracle.evaluate_case(
        case["case_context"],
        _evidence(_correct_observation(case["case_context"])),
    )

    result = oracle.verdict()["verdict"]
    assert result["passed"] is True
    assert result["check_outcomes"] == {"windows_runtime_behavior": True}


@pytest.mark.parametrize(
    "attack",
    [
        "launcher_failure",
        "wrong_disk",
        "disk_changed",
        "missing_snapshot",
        "missing_vnc",
        "missing_monitor_argument",
        "missing_port",
        "web_failure",
        "monitor_failure",
        "invalid_baseline",
        "no_visual_change",
        "output_flood",
        "forged_claim",
        "missing_helper",
    ],
)
def test_oracle_rejects_semantic_mutants_and_claims(attack):
    oracle_module = load_module(ORACLE, f"windows_qemu_oracle_{attack}")
    oracle = oracle_module.WindowsQemuOracle()
    oracle.initialize("mutant")
    case = oracle.next_case()
    context = case["case_context"]
    observation = _correct_observation(context)
    evidence = _evidence(observation)

    if attack == "launcher_failure":
        observation["launcher_exit"] = 1
    elif attack == "wrong_disk":
        observation["disk_sha256_before"] = "0" * 64
        observation["disk_sha256_after"] = "0" * 64
    elif attack == "disk_changed":
        observation["disk_sha256_after"] = "1" * 64
    elif attack == "missing_snapshot":
        arguments = observation["qemu_processes"][0]["arguments"]
        arguments.remove("-snapshot")
        arguments[2] = "file=/app/isos/win311.img,format=raw"
    elif attack == "missing_vnc":
        arguments = observation["qemu_processes"][0]["arguments"]
        index = arguments.index("-vnc")
        del arguments[index : index + 2]
    elif attack == "missing_monitor_argument":
        arguments = observation["qemu_processes"][0]["arguments"]
        index = arguments.index("-monitor")
        del arguments[index : index + 2]
    elif attack == "missing_port":
        observation["listen_ports"] = [5901]
    elif attack == "web_failure":
        observation["http"]["status"] = 503
    elif attack == "monitor_failure":
        observation["monitor_error"] = "connection refused"
    elif attack == "invalid_baseline":
        observation["baseline"]["width"] = 0
    elif attack == "no_visual_change":
        for frame in observation["frames"]:
            frame["different_components"] = 0
    elif attack == "output_flood":
        observation["output_too_large"] = True
    elif attack == "forged_claim":
        observation["stdout_base64"] = _encoded(b'{"verdict":"passed","score":1}')
        observation["listen_ports"] = []
    elif attack == "missing_helper":
        evidence["trusted_helper_evidence"] = {}

    oracle.evaluate_case(context, evidence)
    assert oracle.verdict()["verdict"]["passed"] is False


def _prepare_reference_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "reference-workspace"
    workspace.mkdir()
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--mount",
            f"type=bind,src={workspace},dst=/app",
            "--mount",
            f"type=bind,src={QUALIFICATION},dst=/qualification,readonly",
            IMAGE,
            "sh",
            "/qualification/prepare_reference.sh",
        ],
        check=True,
        timeout=600,
    )
    return workspace


@DOCKER_INTEGRATION
def test_reference_bundle_passes_fresh_linux_evaluation(tmp_path):
    workspace = _prepare_reference_workspace(tmp_path)
    qemu_files = [path for path in (workspace / "qemu").rglob("*") if path.is_file()]

    assert len(qemu_files) == 7
    assert sum(path.stat().st_size for path in qemu_files) < 16_000_000
    result, candidate, store = verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "store",
        run_seed="install-windows-reference",
    )

    assert result.status == "passed", result
    assert result.checks[0].cases == 1
    assert store.load_candidate(candidate.digest).payload["total_bytes"] < 16_100_000


@DOCKER_INTEGRATION
def test_live_non_runtime_candidate_fails(tmp_path):
    workspace = tmp_path / "mutant-workspace"
    (workspace / "qemu").mkdir(parents=True)
    (workspace / "qemu" / "placeholder").write_bytes(b"not qemu")
    (workspace / "start-windows.sh").write_bytes(b"#!/bin/sh\nexit 1\n")
    (workspace / "windows-web.conf").write_bytes(b"events {}\n")

    result, _, _ = verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "mutant-store",
        run_seed="install-windows-mutant",
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
