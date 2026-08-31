from __future__ import annotations

import json
from pathlib import Path

import pytest

from securebench.candidates import (
    CandidateStore,
    capture_production,
)
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.command import CommandHarnessProducer
from securebench.schemas.benchmark import ProtocolCheck
from securebench.verification import VerificationEngine
from securebench.verification.json_data import json_digest
from securebench.verification.models import ChallengeEvidence, TrustedHelperEvidence
from securebench.verification.oracle import OracleProcessSession
from securebench.workspaces.cleanup import remove_untrusted_tree
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_terminal_task,
    verify_workspace,
)


TASK_ID = "terminal-bench/cancel-async-tasks"
LEDGER_TYPE = "securebench.append-only-event-ledger/v1"
SUPERVISOR_TYPE = "securebench.process-supervisor/v1"

REFERENCE = """\
import asyncio


async def run_tasks(tasks, max_concurrent):
    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited(task):
        async with semaphore:
            await task()

    running = [asyncio.create_task(limited(task)) for task in tasks]
    try:
        await asyncio.gather(*running)
    except BaseException:
        await asyncio.gather(*running, return_exceptions=True)
        raise
"""

SEQUENTIAL_MUTANT = """\
async def run_tasks(tasks, max_concurrent):
    for task in tasks:
        await task()
"""

UNBOUNDED_MUTANT = """\
import asyncio


async def run_tasks(tasks, max_concurrent):
    await asyncio.gather(*(task() for task in tasks))
"""

IGNORES_SIGNAL_MUTANT = """\
import asyncio
import signal


async def run_tasks(tasks, max_concurrent):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited(task):
        async with semaphore:
            await task()

    await asyncio.gather(*(limited(task) for task in tasks))
"""

FORGED_CLAIM = """\
async def run_tasks(tasks, max_concurrent):
    print('{"verdict":"passed","score":1}')
"""

CREDENTIAL_FORGERY = """\
import asyncio
import json
import urllib.request


def closure(task):
    return {
        name: cell.cell_contents
        for name, cell in zip(task.__code__.co_freevars, task.__closure__)
    }


def post(access, nonce, event, data):
    body = json.dumps(
        {"nonce": nonce, "event": event, "data": data},
        separators=(",", ":"),
    ).encode()
    request = urllib.request.Request(
        access["url"],
        data=body,
        headers={
            "Authorization": access["authorization"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    urllib.request.urlopen(request, timeout=2).close()


async def forged_task(task):
    values = closure(task)
    task_id = values["task_id"]
    prefix = values["nonce_prefix"]
    data = str(task_id)
    post(values["access"], f"{prefix}_{task_id}_start", "task.started", data)
    try:
        await asyncio.sleep(values["work_ms"] / 1000)
        post(values["access"], f"{prefix}_{task_id}_complete", "task.completed", data)
    finally:
        await asyncio.sleep(values["cleanup_ms"] / 1000)
        post(values["access"], f"{prefix}_{task_id}_clean", "task.cleaned", data)


async def run_tasks(tasks, max_concurrent):
    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited(task):
        async with semaphore:
            await forged_task(task)

    running = [asyncio.create_task(limited(task)) for task in tasks]
    try:
        await asyncio.gather(*running)
    except BaseException:
        await asyncio.gather(*running, return_exceptions=True)
        raise
"""

EARLY_CANCELLATION = """\
import asyncio
import signal


def closure(task):
    return {
        name: cell.cell_contents
        for name, cell in zip(task.__code__.co_freevars, task.__closure__)
    }


async def run_tasks(tasks, max_concurrent):
    if closure(tasks[0])["work_ms"] < 1000:
        semaphore = asyncio.Semaphore(max_concurrent)

        async def limited(task):
            async with semaphore:
                await task()

        await asyncio.gather(*(limited(task) for task in tasks))
        return

    running = [asyncio.create_task(task()) for task in tasks[:max_concurrent]]
    await asyncio.sleep(0.05)
    for task in running:
        task.cancel()
    await asyncio.gather(*running, return_exceptions=True)
    loop = asyncio.get_running_loop()
    interrupted = asyncio.Event()
    signal.signal(
        signal.SIGINT,
        lambda signum, frame: loop.call_later(0.2, interrupted.set),
    )
    await interrupted.wait()
"""


def compiled_task():
    return load_terminal_task(TASK_ID)


def _event(context, task_id: int, phase: str, elapsed_us: int):
    event = {
        "start": "task.started",
        "complete": "task.completed",
        "cancel": "task.cancelled",
        "clean": "task.cleaned",
    }[phase]
    return {
        "accepted": True,
        "authenticated": True,
        "path_matched": True,
        "method": "POST",
        "event_valid": True,
        "event": event,
        "data": str(task_id),
        "nonce": f"{context['nonce_prefix']}_{task_id}_{phase}",
        "elapsed_us": elapsed_us,
    }


def _signal_event(context: dict, elapsed_us: int):
    return {
        "accepted": True,
        "authenticated": True,
        "path_matched": True,
        "method": "POST",
        "event_valid": True,
        "event": "adapter.signal_forwarded",
        "data": "SIGINT",
        "nonce": f"{context['nonce_prefix']}_signal",
        "elapsed_us": elapsed_us,
    }


def _reference_events(check_id: str, context: dict, *, mutant: str | None):
    if check_id == "cancellation_behavior":
        count = min(context["task_count"], context["max_concurrent"])
        events = [_event(context, task_id, "start", task_id * 1000) for task_id in range(count)]
        if mutant == "early_cleanup" and context["index"] == 0:
            events.extend(
                _event(context, task_id, "clean", 250_000 + task_id * 1000)
                for task_id in range(count)
            )
            events.append(_signal_event(context, 500_000))
            return events
        events.append(_signal_event(context, 500_000))
        if mutant == "cancellation" and context["index"] == 0:
            events.append(_event(context, 0, "complete", 600_000))
        events.extend(
            _event(context, task_id, "cancel", 600_000 + task_id * 1000)
            for task_id in range(count)
        )
        events.extend(
            _event(context, task_id, "clean", 700_000 + task_id * 1000)
            for task_id in range(count)
        )
        return events

    if context["max_concurrent"] == 1 or (
        mutant == "concurrency" and context["index"] == 0
    ):
        events = []
        for task_id in range(context["task_count"]):
            origin = task_id * 801_000
            events.extend(
                [
                    _event(context, task_id, "start", origin),
                    _event(context, task_id, "complete", origin + 600_000),
                    _event(context, task_id, "clean", origin + 800_000),
                ]
            )
        return events
    return [
        _event(context, 0, "start", 0),
        _event(context, 1, "start", 1000),
        _event(context, 0, "complete", 600_000),
        _event(context, 1, "complete", 601_000),
        _event(context, 0, "clean", 800_000),
        _event(context, 1, "clean", 801_000),
    ]


def _synthetic_evidence(task, check, case, index: int, *, mutant: str | None):
    challenge_id = f"challenge-test-{check.id}-{index}"
    evaluation_id = f"evaluation-test-{check.id}-{index}"
    events = _reference_events(check.id, case.context, mutant=mutant)
    cancellation = check.id == "cancellation_behavior"
    process = {
        "container_started": True,
        "started_after_ms": 20,
        "duration_ms": 800 if cancellation else 1800,
        "exit_code": 0,
        "timed_out": False,
    }
    signals = (
        [
            {
                "sequence": 0,
                "signal": "SIGINT",
                "scheduled_after_ms": 500,
                "attempted_after_ms": 500,
                "delivered": True,
            }
        ]
        if cancellation
        else []
    )
    helpers = (
        TrustedHelperEvidence(
            name="lifecycle",
            type=LEDGER_TYPE,
            challenge_id=challenge_id,
            evaluation_id=evaluation_id,
            value={"events": events},
        ),
        TrustedHelperEvidence(
            name="process_control",
            type=SUPERVISOR_TYPE,
            challenge_id=challenge_id,
            evaluation_id=evaluation_id,
            value={"process": process, "signals": signals},
        ),
    )
    observation = {
        "child_started": True,
        "child_exit_code": 0,
        "signal_received": cancellation,
        "signal_forwarded": cancellation,
        "timed_out": mutant == "timeout" and check.id == "concurrency_behavior" and index == 0,
    }
    return ChallengeEvidence(
        check_id=check.id,
        challenge_id=challenge_id,
        evaluation_id=evaluation_id,
        challenge_index=index,
        challenge_digest=json_digest(case.challenge),
        status="observed",
        exit_status=0,
        observation=observation,
        observation_bytes=len(json.dumps(observation)),
        trusted_helper_evidence=helpers,
    )


def drive_oracle(*, mutant: str | None = None):
    task = compiled_task()
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    with OracleProcessSession(oracle_root) as session:
        session.initialize(task, run_seed="cancel-async-qualification")
        for check in task.verification.checks:
            index = 0
            while (
                case := session.next_challenge(
                    check.id,
                    check.challenge.source,
                    {
                        "max_cases": check.challenge.max_cases,
                        "max_case_bytes": check.challenge.max_case_bytes,
                    },
                )
            ) is not None:
                session.evaluate_challenge(
                    check.id,
                    case.context,
                    _synthetic_evidence(task, check, case, index, mutant=mutant),
                )
                index += 1
        return session.finalize()


def verify_source(tmp_path: Path, source: str):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "run.py").write_text(source, encoding="utf-8")
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="cancel-async-live-qualification",
    )


def test_cancel_async_row_is_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == (
        "alexgshaw/cancel-async-tasks@"
        "sha256:84c7fae6b256dcc56a350790e2a9715eefc7dad662a9d8e8a472363aa71ef18d"
    )
    assert len(task.verification.checks) == 2
    assert all(isinstance(check, ProtocolCheck) for check in task.verification.checks)
    assert task.verification.candidate.max_total_files == 1
    assert task.verification.candidate.files[0].path == "/app/run.py"
    assert set(task.verification.resources.runtime) == {"async_adapter"}

    adapter_root = Path(task.resources.resources["runtime.async_adapter"].value["source_path"])
    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    assert {
        path.relative_to(adapter_root).as_posix()
        for path in adapter_root.rglob("*")
        if path.is_file()
    } == {"adapter.py", "adapter.yaml", "driver.py"}
    assert {
        path.relative_to(oracle_root).as_posix()
        for path in oracle_root.rglob("*")
        if path.is_file()
    } == {"oracle.py", "oracle.yaml"}


def test_cancel_async_oracle_accepts_reference_evidence_and_rejects_semantic_mutants():
    reference = drive_oracle()
    concurrency_mutant = drive_oracle(mutant="concurrency")
    cancellation_mutant = drive_oracle(mutant="cancellation")
    early_cleanup_mutant = drive_oracle(mutant="early_cleanup")
    timeout_mutant = drive_oracle(mutant="timeout")

    assert reference.passed is True
    assert reference.check_outcomes == {
        "concurrency_behavior": True,
        "cancellation_behavior": True,
    }
    assert concurrency_mutant.passed is False
    assert concurrency_mutant.check_outcomes["concurrency_behavior"] is False
    assert cancellation_mutant.passed is False
    assert cancellation_mutant.check_outcomes["cancellation_behavior"] is False
    assert early_cleanup_mutant.passed is False
    assert early_cleanup_mutant.check_outcomes["cancellation_behavior"] is False
    assert timeout_mutant.passed is False
    assert timeout_mutant.check_outcomes["concurrency_behavior"] is False


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("source", "expected_status", "failure_fragment"),
    [
        pytest.param(REFERENCE, "passed", None, id="reference"),
        pytest.param(
            SEQUENTIAL_MUTANT,
            "failed",
            "concurrency",
            id="sequential_mutant",
        ),
        pytest.param(
            UNBOUNDED_MUTANT,
            "failed",
            "concurrency",
            id="unbounded_mutant",
        ),
        pytest.param(
            IGNORES_SIGNAL_MUTANT,
            "failed",
            "cancellation",
            id="signal_ignoring_mutant",
        ),
        pytest.param(FORGED_CLAIM, "failed", "event_count", id="forged_claim"),
    ],
)
def test_cancel_async_real_pinned_evaluations_reject_mutants_and_claims(
    tmp_path,
    source,
    expected_status,
    failure_fragment,
):
    result, candidate, store = verify_source(tmp_path, source)

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
    manifest = store.load_candidate(candidate.digest)
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["implementation"]
    if failure_fragment is not None:
        failures = result.public_diagnostics["failure_categories"]
        assert any(failure_fragment in value for value in failures)


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "source",
    [
        pytest.param(CREDENTIAL_FORGERY, id="credential_forgery"),
        pytest.param(EARLY_CANCELLATION, id="early_cancellation"),
    ],
)
def test_cancel_async_rejects_candidates_that_bypass_task_callbacks(tmp_path, source):
    result, _, _ = verify_source(tmp_path, source)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result


@DOCKER_INTEGRATION
def test_cancel_async_reference_passes_pinned_agent_capture_and_replay(tmp_path):
    task = compiled_task()
    script = (
        "from pathlib import Path;"
        f"Path('/app/run.py').write_text({REFERENCE!r},encoding='utf-8')"
    )
    producer = CommandHarnessProducer(
        command=("python3", "-c", script),
        workspace_root=tmp_path / "workspaces",
    )
    production = producer.produce(task)
    try:
        store = CandidateStore(tmp_path / "store")
        candidate = capture_production(task, production, store)
        result = VerificationEngine().verify(
            task,
            candidate,
            store,
            run_seed="cancel-async-pinned-agent-reference",
        )
    finally:
        remove_untrusted_tree(production.workspace, image=task.environment.image)

    assert result.status == "passed", result
