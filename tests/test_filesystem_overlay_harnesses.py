from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateCaptureError,
    CandidateProductionError,
    CandidateProductionTimeout,
    CandidateStore,
    OverlayAgentCaptureResult,
    StoredCandidate,
)
from securebench.harnesses import claude_code, codex, command
from securebench.harnesses.claude_code import ClaudeCodeHarnessProducer, ClaudeCodeOverlay
from securebench.harnesses.codex import CodexHarnessProducer, CodexOverlay, DockerPlatform
from securebench.harnesses.command import CommandHarnessProducer
from securebench.harnesses.network import HarnessEgress
from securebench.harnesses.shared import workspace_dir_name
from securebench.sandboxes import CommandResult
from securebench.schemas.benchmark import FilesystemOverlayCandidate
from securebench.tester_config import (
    MIN_OVERLAY_WORKSPACE_BYTES,
    TesterBenchmarkSection as BenchmarkSection,
    TesterConfig as RunConfig,
    TesterDockerSection as DockerSection,
    TesterHarnessSection as HarnessSection,
    TesterRunSection as RunSection,
)
from securebench.tester_run import _OverlayExecutionCapability, _execute_task
from securebench.verification import VerificationEngine
from securebench.workspaces.overlay_quota import OverlayWorkspaceCapabilities


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"


def overlay_task():
    task = next(
        compile_benchmark_pack(
            load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
        )
    )
    candidate = FilesystemOverlayCandidate.model_validate(
        {
            "type": "filesystem_overlay",
            "include_roots": ["/app"],
            "max_changed_paths": 100,
            "max_changed_bytes": 1024 * 1024,
        }
    )
    return replace(
        task,
        verification=task.verification.model_copy(update={"candidate": candidate}),
    )


def stored_candidate(tmp_path: Path, task) -> StoredCandidate:
    return StoredCandidate(
        type="filesystem_overlay",
        digest="sha256:" + "a" * 64,
        manifest_path=tmp_path / "candidate.json",
        baseline_digest=task.baseline_digest,
    )


def successful_capture(tmp_path: Path, task) -> OverlayAgentCaptureResult:
    return OverlayAgentCaptureResult(
        candidate=stored_candidate(tmp_path, task),
        agent_result=CommandResult(command=("agent",), exit_code=0),
    )


@contextmanager
def plain_egress(*args, **kwargs):
    yield HarnessEgress(
        network="securebench-test-network",
        env={"HTTP_PROXY": "http://proxy.invalid"},
        allowed_domains=(),
    )


@contextmanager
def provider_egress(*args, **kwargs):
    yield HarnessEgress(
        network="securebench-provider-network",
        env={"HTTP_PROXY": "http://proxy.invalid"},
        allowed_domains=(),
        provider="test-provider",
        provider_base_url="http://securebench-provider-relay:8081/v1",
        provider_relay_enabled=True,
    )


def test_command_harness_routes_overlay_through_trusted_capture(monkeypatch, tmp_path):
    task = overlay_task()
    calls = []
    monkeypatch.setattr(command, "docker_egress_policy", plain_egress)
    monkeypatch.setattr(
        command,
        "run_filesystem_overlay_agent_capture",
        lambda **options: calls.append(options) or successful_capture(tmp_path, task),
    )
    producer = CommandHarnessProducer(
        command=("python", "solve.py"),
        workspace_root=tmp_path / "inputs",
    )

    result = producer.capture_filesystem_overlay(
        task,
        store=CandidateStore(tmp_path / "store"),
        storage_root=tmp_path / "quota",
        capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
    )

    assert result.candidate.type == "filesystem_overlay"
    assert len(calls) == 1
    options = calls[0]
    assert options["command"] == ("python", "solve.py")
    assert options["workdir"] == "/app"
    assert options["capacity_bytes"] == MIN_OVERLAY_WORKSPACE_BYTES
    assert options["network"] == "securebench-test-network"
    assert all(mount.read_only for mount in options["public_mounts"])
    task_file = Path(options["trusted_inputs_root"]) / "task.json"
    assert task_file.is_file()
    assert "instructions" in task_file.read_text()


@pytest.mark.parametrize("harness", ["codex", "claude_code"])
def test_model_harness_overlay_state_is_bounded_and_outside_captured_roots(
    monkeypatch,
    tmp_path,
    harness,
):
    task = overlay_task()
    calls = []
    platform = DockerPlatform(os="linux", architecture="amd64")
    tool_root = tmp_path / "tool-overlay"
    tool_root.mkdir()
    if harness == "codex":
        monkeypatch.setenv("OPENAI_API_KEY", "host-secret")
        monkeypatch.setattr(codex, "docker_provider_relay_policy", provider_egress)
        monkeypatch.setattr(
            codex,
            "codex_overlay_for_image",
            lambda image, version: CodexOverlay(tool_root, platform, version),
        )
        monkeypatch.setattr(
            codex,
            "run_filesystem_overlay_agent_capture",
            lambda **options: calls.append(options) or successful_capture(tmp_path, task),
        )
        producer = CodexHarnessProducer(
            model="gpt-test",
            workspace_root=tmp_path / "inputs",
        )
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "host-secret")
        monkeypatch.setattr(claude_code, "docker_provider_relay_policy", provider_egress)
        monkeypatch.setattr(
            claude_code,
            "claude_code_overlay_for_image",
            lambda image, version: ClaudeCodeOverlay(tool_root, platform, version),
        )
        monkeypatch.setattr(
            claude_code,
            "run_filesystem_overlay_agent_capture",
            lambda **options: calls.append(options) or successful_capture(tmp_path, task),
        )
        producer = ClaudeCodeHarnessProducer(
            model="claude-test",
            workspace_root=tmp_path / "inputs",
        )

    producer.capture_filesystem_overlay(
        task,
        store=CandidateStore(tmp_path / "store"),
        storage_root=tmp_path / "quota",
        capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
    )

    assert len(calls) == 1
    options = calls[0]
    assert "/opt/securebench/agent-inputs/task.json" in options["command"]
    assert "/tmp/securebench-" in options["command"]
    assert "/tmp/securebench-" in options["preflight_command"]
    assert options["workdir"] == "/app"
    assert options["network"] == "securebench-provider-network"
    assert all(mount.read_only for mount in options["public_mounts"])
    assert all(
        not str(mount.source).startswith("/tmp/securebench-")
        for mount in options["public_mounts"]
    )
    assert "host-secret" not in str(options)


def runner_config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        schema_version="1.0",
        run=RunSection(id="overlay-runner", output_dir=tmp_path / "run"),
        benchmark=BenchmarkSection(
            manifest=PACK / "manifest-v2.yaml",
            tasks=PACK / "tasks-v2.jsonl",
        ),
        harness=HarnessSection(type="command", config={"command": "ignored"}),
        docker=DockerSection(
            overlay_workspace_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
        ),
    )


def runner_capability(workspace_root: Path) -> _OverlayExecutionCapability:
    return _OverlayExecutionCapability(
        host=OverlayWorkspaceCapabilities("Linux", "linux", "overlay2"),
        storage_root=(workspace_root / "overlay-agents").resolve(),
    )


def test_normal_runner_captures_one_overlay_and_cleans_agent_inputs(monkeypatch, tmp_path):
    task = overlay_task()
    current = runner_config(tmp_path)
    workspace_root = current.run.output_dir / "workspaces"
    calls = []

    class Producer:
        def capture_filesystem_overlay(self, selected, **options):
            calls.append((selected, options))
            inputs = workspace_root / workspace_dir_name(selected)
            inputs.mkdir(parents=True)
            (inputs / "task.json").write_text("public")
            return successful_capture(tmp_path, selected)

    def fake_verify(self, selected, candidate, store, *, run_seed):
        return self.infrastructure_error(
            selected,
            code="test_verification",
            message="verification intentionally stubbed",
            candidate=candidate,
        )

    monkeypatch.setattr(VerificationEngine, "verify", fake_verify)
    completed = _execute_task(
        current,
        task,
        producer=Producer(),
        store=CandidateStore(tmp_path / "store"),
        workspace_root=workspace_root,
        execution_digest="sha256:" + "b" * 64,
        progress=None,
        index=1,
        total=1,
        overlay_capability=runner_capability(workspace_root),
    )

    assert len(calls) == 1
    assert calls[0][1]["storage_root"] == (workspace_root / "overlay-agents").resolve()
    assert completed.record["candidate"]["type"] == "filesystem_overlay"
    assert not (workspace_root / workspace_dir_name(task)).exists()


@pytest.mark.parametrize(
    "failure",
    ["agent", "timeout", "capture", "infrastructure"],
)
def test_normal_runner_cleans_inputs_after_overlay_failures(monkeypatch, tmp_path, failure):
    task = overlay_task()
    current = runner_config(tmp_path)
    workspace_root = current.run.output_dir / "workspaces"

    class Producer:
        def capture_filesystem_overlay(self, selected, **options):
            inputs = workspace_root / workspace_dir_name(selected)
            inputs.mkdir(parents=True)
            (inputs / "untrusted").write_text("state")
            if failure == "agent":
                raise CandidateProductionError("failed")
            if failure == "timeout":
                raise CandidateProductionTimeout(
                    CommandResult(command=("agent",), exit_code=124, timed_out=True)
                )
            if failure == "capture":
                raise CandidateCaptureError("rejected")
            raise RuntimeError("infrastructure")

    def fake_candidate_error(self, selected, *, code, message, run_seed):
        return self.infrastructure_error(selected, code=code, message=message)

    monkeypatch.setattr(VerificationEngine, "verify_candidate_error", fake_candidate_error)
    completed = _execute_task(
        current,
        task,
        producer=Producer(),
        store=CandidateStore(tmp_path / "store"),
        workspace_root=workspace_root,
        execution_digest="sha256:" + "b" * 64,
        progress=None,
        index=1,
        total=1,
        overlay_capability=runner_capability(workspace_root),
    )

    assert completed.record["status"] == "infrastructure_error"
    assert not (workspace_root / workspace_dir_name(task)).exists()
