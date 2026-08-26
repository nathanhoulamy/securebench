from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

from securebench.sandboxes import (
    CommandResult,
    ContainerSignalObservation,
    DockerSandbox,
    DockerSandboxError,
    DockerSupervisionReport,
    ScheduledContainerSignal,
)
from securebench.sandboxes.docker import _DockerSignalSupervisor
from securebench.schemas.benchmark import TrustedHelperSpec
from securebench.verification.models import VerificationInfrastructureError
from securebench.verification.trusted_helpers import (
    HTTP_REQUEST_RECORDER_IMAGE,
    PROCESS_SUPERVISOR_TYPE,
    ProcessSupervisorRuntime,
    TrustedHelperEvaluation,
    _validate_process_supervisor_evidence,
    default_trusted_helper_catalog,
    process_supervisor_contract,
)


def _helper(*, max_signals: int = 4, max_delay_ms: int = 2000):
    return TrustedHelperSpec.model_validate(
        {
            "name": "process_control",
            "type": PROCESS_SUPERVISOR_TYPE,
            "limits": {
                "max_signals": max_signals,
                "max_delay_ms": max_delay_ms,
            },
        }
    )


def _settings():
    return {
        "signals": [
            {"signal": "SIGINT", "after_ms": 100},
            {"signal": "SIGTERM", "after_ms": 500},
        ]
    }


def test_process_supervisor_is_host_only_and_uses_no_guest_credential():
    contract = process_supervisor_contract()
    assert contract.helper_access == "none"
    assert contract.credentials == "none"
    assert set(contract.capabilities) == {
        "deliver_signals",
        "inspect_process_lifecycle",
        "inspect_monotonic_timing",
    }
    catalog = default_trusted_helper_catalog()
    helper = _helper()
    assert catalog.runtime_factory(helper.type) is ProcessSupervisorRuntime
    catalog.validate_declaration(helper)
    catalog.validate_settings(contract, _settings())
    catalog.validate_runtime_settings(helper.type, _settings())
    catalog.validate_runtime_declaration(helper, _settings())


def test_process_only_evaluation_creates_no_guest_network_or_access_credential(monkeypatch):
    helper = _helper()
    evaluation = TrustedHelperEvaluation(
        task=SimpleNamespace(),  # settings are absent, so no task resource is read
        check=SimpleNamespace(trusted_helpers=(helper,)),
        catalog=default_trusted_helper_catalog(),
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
    )
    monkeypatch.setattr(
        "securebench.verification.trusted_helpers._run_docker",
        lambda *args, **kwargs: pytest.fail("a host-only helper must not create a network"),
    )
    try:
        access = evaluation.start()
        assert access == {"process_control": {"type": PROCESS_SUPERVISOR_TYPE}}
        assert evaluation.network == "none"
        assert evaluation.evaluation_environment() == {}
    finally:
        evaluation.close()


def test_helper_evaluation_closes_owned_runtimes_on_keyboard_interrupt(monkeypatch):
    helper = _helper()
    evaluation = TrustedHelperEvaluation(
        task=SimpleNamespace(),
        check=SimpleNamespace(trusted_helpers=(helper,)),
        catalog=default_trusted_helper_catalog(),
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
    )
    closed: list[ProcessSupervisorRuntime] = []

    def interrupted_start(runtime, alias):
        raise KeyboardInterrupt

    def record_close(runtime):
        closed.append(runtime)

    monkeypatch.setattr(ProcessSupervisorRuntime, "start", interrupted_start)
    monkeypatch.setattr(ProcessSupervisorRuntime, "close", record_close)

    with pytest.raises(KeyboardInterrupt):
        evaluation.start()

    assert len(closed) == 1
    assert evaluation._runtimes == []


@pytest.mark.parametrize(
    "settings",
    [
        {"signals": [{"signal": "SIGKILL", "after_ms": 100}]},
        {"signals": [{"signal": "SIGINT", "after_ms": -1}]},
        {
            "signals": [
                {"signal": "SIGTERM", "after_ms": 200},
                {"signal": "SIGINT", "after_ms": 100},
            ]
        },
        {"signals": [{"signal": "SIGINT", "after_ms": 60_001}]},
    ],
)
def test_process_supervisor_rejects_unsafe_or_ambiguous_schedules(settings):
    catalog = default_trusted_helper_catalog()
    with pytest.raises(VerificationInfrastructureError) as error:
        catalog.validate_runtime_settings(PROCESS_SUPERVISOR_TYPE, settings)
    assert error.value.code == "trusted_helper_settings_invalid"


def test_process_supervisor_enforces_row_reduced_schedule_bounds():
    catalog = default_trusted_helper_catalog()
    helper = _helper(max_signals=1, max_delay_ms=250)
    settings = _settings()

    with pytest.raises(VerificationInfrastructureError, match="exceed row limits"):
        catalog.validate_runtime_declaration(helper, settings)


class _FakeSupervisedSandbox:
    def __init__(self) -> None:
        self.calls = []

    def run_supervised(self, command, *, signals, workdir, timeout, stdin):
        self.calls.append((command, signals, workdir, timeout, stdin))
        return (
            CommandResult(command=tuple(command), exit_code=0, stdout="{}"),
            DockerSupervisionReport(
                container_started=True,
                started_after_ms=20,
                duration_ms=560,
                signals=(
                    ContainerSignalObservation(0, "SIGINT", 100, 101, True),
                    ContainerSignalObservation(1, "SIGTERM", 500, -1, False),
                ),
            ),
        )


def test_process_supervisor_owns_launch_and_returns_correlated_host_evidence():
    helper = _helper()
    runtime = ProcessSupervisorRuntime(
        helper=helper,
        contract=process_supervisor_contract(),
        settings=_settings(),
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
        network="none",
    )
    assert runtime.start("unused") == {"type": PROCESS_SUPERVISOR_TYPE}
    sandbox = _FakeSupervisedSandbox()
    result = runtime.run_evaluation(
        sandbox,  # type: ignore[arg-type]
        ("python3", "adapter.py"),
        workdir="/app",
        timeout=2.0,
        stdin=b"{}\n",
    )
    evidence = runtime.collect(default_trusted_helper_catalog())
    runtime.close()

    assert result.exit_code == 0
    assert [signal.signal for signal in sandbox.calls[0][1]] == ["SIGINT", "SIGTERM"]
    assert evidence.challenge_id == "challenge-test"
    assert evidence.evaluation_id == "evaluation-test"
    assert evidence.value["process"] == {
        "container_started": True,
        "started_after_ms": 20,
        "duration_ms": 560,
        "exit_code": 0,
        "timed_out": False,
    }
    assert evidence.value["signals"][0]["delivered"] is True
    assert evidence.value["signals"][1]["delivered"] is False
    assert "url" not in str(evidence.value)
    assert "authorization" not in str(evidence.value)


def test_process_supervisor_rejects_forged_schedule_and_timing_evidence():
    helper = _helper()
    value = {
        "process": {
            "container_started": True,
            "started_after_ms": 10,
            "duration_ms": 500,
            "exit_code": 0,
            "timed_out": False,
        },
        "signals": [
            {
                "sequence": 0,
                "signal": "SIGINT",
                "scheduled_after_ms": 100,
                "attempted_after_ms": 101,
                "delivered": True,
            },
            {
                "sequence": 1,
                "signal": "SIGTERM",
                "scheduled_after_ms": 500,
                "attempted_after_ms": -1,
                "delivered": False,
            },
        ],
    }
    value["signals"][0]["signal"] = "SIGUSR1"
    with pytest.raises(VerificationInfrastructureError, match="schedule metadata"):
        _validate_process_supervisor_evidence(helper, _settings(), value)

    value["signals"][0]["signal"] = "SIGINT"
    value["signals"][0]["attempted_after_ms"] = 99
    value["signals"][0]["delivered"] = False
    with pytest.raises(VerificationInfrastructureError, match="attempt predates"):
        _validate_process_supervisor_evidence(helper, _settings(), value)

    value["signals"][0]["attempted_after_ms"] = 100
    value["process"]["duration_ms"] = 99
    with pytest.raises(VerificationInfrastructureError, match="exceeds process duration"):
        _validate_process_supervisor_evidence(helper, _settings(), value)

    value["process"].update(container_started=False, started_after_ms=-1, duration_ms=500)
    with pytest.raises(VerificationInfrastructureError, match="before container startup"):
        _validate_process_supervisor_evidence(helper, _settings(), value)


def test_docker_supervisor_fails_closed_when_container_state_query_fails(monkeypatch):
    supervisor = _DockerSignalSupervisor((ScheduledContainerSignal("SIGINT", 10),))
    supervisor.bind_container("securebench-test")
    monkeypatch.setattr(
        "securebench.sandboxes.docker.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "daemon error"),
    )

    with pytest.raises(DockerSandboxError, match="query supervised container state"):
        supervisor._container_is_running()


def test_process_supervisor_requires_exactly_one_execution_before_collection():
    runtime = ProcessSupervisorRuntime(
        helper=_helper(),
        contract=process_supervisor_contract(),
        settings=_settings(),
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
        network="none",
    )
    with pytest.raises(VerificationInfrastructureError, match="before startup"):
        runtime.collect(default_trusted_helper_catalog())
    runtime.start("unused")
    with pytest.raises(VerificationInfrastructureError, match="lifecycle"):
        runtime.start("unused")
    with pytest.raises(VerificationInfrastructureError, match="before execution"):
        runtime.collect(default_trusted_helper_catalog())
    runtime.run_evaluation(
        _FakeSupervisedSandbox(),  # type: ignore[arg-type]
        ("python3", "adapter.py"),
        workdir="/app",
        timeout=2.0,
        stdin=b"{}\n",
    )
    with pytest.raises(VerificationInfrastructureError, match="lifecycle"):
        runtime.run_evaluation(
            _FakeSupervisedSandbox(),  # type: ignore[arg-type]
            ("python3", "adapter.py"),
            workdir="/app",
            timeout=2.0,
            stdin=b"{}\n",
        )


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 for the live supervisor qualification",
)
def test_process_supervisor_delivers_a_real_signal_from_outside_the_container(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = DockerSandbox(
        image=HTTP_REQUEST_RECORDER_IMAGE,
        root=workspace,
        persistent=False,
        network="none",
        read_only=True,
    )
    runtime = ProcessSupervisorRuntime(
        helper=_helper(max_signals=1, max_delay_ms=1000),
        contract=process_supervisor_contract(),
        settings={"signals": [{"signal": "SIGINT", "after_ms": 250}]},
        challenge_id="challenge-live",
        evaluation_id="evaluation-live",
        network="none",
    )
    runtime.start("unused")
    script = (
        "import signal,time;"
        "signal.signal(signal.SIGINT,lambda s,f:print('signal-seen',flush=True));"
        "time.sleep(0.8)"
    )
    try:
        result = runtime.run_evaluation(
            sandbox,
            ("python3", "-c", script),
            workdir="/workspace",
            timeout=10.0,
            stdin=b"",
        )
        evidence = runtime.collect(default_trusted_helper_catalog())
    finally:
        runtime.close()
        sandbox.close()

    assert result.exit_code == 0
    assert result.stdout.strip() == "signal-seen"
    assert evidence.value["process"]["container_started"] is True
    signal_evidence = evidence.value["signals"]
    assert len(signal_evidence) == 1
    assert signal_evidence[0]["sequence"] == 0
    assert signal_evidence[0]["signal"] == "SIGINT"
    assert signal_evidence[0]["scheduled_after_ms"] == 250
    assert signal_evidence[0]["attempted_after_ms"] >= 250
    assert signal_evidence[0]["delivered"] is True
