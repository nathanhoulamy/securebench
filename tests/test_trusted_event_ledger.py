from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path
from threading import Thread

import pytest

from securebench.schemas.benchmark import TrustedHelperSpec
from securebench.verification.event_ledger_server import (
    EventLedgerHandler,
    EventLedgerState,
)
from securebench.verification.models import VerificationInfrastructureError
from securebench.verification.trusted_helpers import (
    APPEND_ONLY_EVENT_LEDGER_TYPE,
    EVENT_LEDGER_IMAGE,
    AppendOnlyEventLedgerRuntime,
    _validate_event_ledger_records,
    append_only_event_ledger_contract,
    default_trusted_helper_catalog,
)


def _state(tmp_path: Path, *, max_events: int = 8):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = {
        "challenge_id": "challenge-test",
        "evaluation_id": "evaluation-test",
        "settings": {"path": "/events"},
        "limits": {"max_events": max_events, "max_event_bytes": 128},
    }
    return EventLedgerState(config, "ledger-secret", state_dir), state_dir


class _FakeServer:
    def __init__(self, state: EventLedgerState) -> None:
        self.event_ledger_state = state


def _request(
    state: EventLedgerState,
    method: str = "POST",
    target: str = "/events",
    *,
    body: bytes | None = None,
    token: str = "ledger-secret",
    content_type: str = "application/json",
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> int:
    if body is None:
        body = json.dumps(
            {"nonce": "nonce_1", "event": "task.started", "data": "task-1"},
            separators=(",", ":"),
        ).encode()
    client, server = socket.socketpair()
    request = (
        f"{method} {target} HTTP/1.1\r\n"
        "Host: helper\r\n"
        f"Authorization: Bearer {token}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        + "".join(f"{name}: {value}\r\n" for name, value in extra_headers)
        + "Connection: close\r\n\r\n"
    ).encode("ascii") + body
    try:
        handler = Thread(
            target=EventLedgerHandler,
            args=(server, ("local", 0), _FakeServer(state)),
            daemon=True,
        )
        handler.start()
        client.sendall(request)
        client.shutdown(socket.SHUT_WR)
        handler.join(timeout=2)
        assert not handler.is_alive()
        server.shutdown(socket.SHUT_WR)
        response = b""
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            response += chunk
    finally:
        client.close()
        server.close()
    return int(response.split(b"\r\n", 1)[0].split()[1])


def _records(state_dir: Path):
    return [json.loads(line) for line in (state_dir / "events.jsonl").read_text().splitlines()]


def test_event_ledger_accepts_only_authenticated_bounded_closed_events(tmp_path):
    ledger, state_dir = _state(tmp_path, max_events=7)
    assert _request(ledger) == 202
    assert _request(ledger, token="forged") == 401
    assert _request(ledger, method="GET") == 405
    assert _request(ledger, target="/__securebench_evidence") == 404
    assert _request(ledger, body=b'{"nonce":"n","event":"x","data":"","extra":1}') == 400
    assert _request(ledger, body=b"x" * 129) == 413
    assert _request(ledger, content_type="text/plain") == 400
    assert _request(ledger) == 429

    records = _records(state_dir)
    assert [record["sequence"] for record in records] == list(range(7))
    assert [record["elapsed_us"] for record in records] == sorted(
        record["elapsed_us"] for record in records
    )
    assert records[0]["accepted"] is True
    assert records[0]["nonce"] == "nonce_1"
    assert records[0]["event"] == "task.started"
    assert records[1]["authenticated"] is False
    assert records[2]["method"] == "GET"
    assert records[3]["path_matched"] is False
    assert records[4]["event_valid"] is False
    assert records[5]["body_truncated"] is True
    assert records[6]["content_type_valid"] is False
    assert all("ledger-secret" not in json.dumps(record) for record in records)
    assert (state_dir / "truncated.flag").is_file()


def test_event_ledger_rejects_ambiguous_auth_and_framing(tmp_path):
    ledger, state_dir = _state(tmp_path, max_events=3)
    assert _request(
        ledger,
        extra_headers=(("Authorization", "Bearer ledger-secret"),),
    ) == 401
    assert _request(ledger, extra_headers=(("Content-Length", "0"),)) == 400
    assert _request(ledger, extra_headers=(("Transfer-Encoding", "chunked"),)) == 400

    records = _records(state_dir)
    assert records[0]["authenticated"] is False
    assert records[1]["body_truncated"] is True
    assert records[2]["body_truncated"] is True


def test_event_ledger_catalog_and_runtime_settings_are_closed_and_bounded():
    catalog = default_trusted_helper_catalog()
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "events",
            "type": APPEND_ONLY_EVENT_LEDGER_TYPE,
            "limits": {"max_events": 32, "max_event_bytes": 512},
        }
    )
    contract = catalog.validate_declaration(helper)
    catalog.validate_settings(contract, {"path": "/lifecycle"})
    catalog.validate_runtime_settings(helper.type, {"path": "/lifecycle"})
    assert catalog.runtime_factory(helper.type) is AppendOnlyEventLedgerRuntime

    with pytest.raises(VerificationInfrastructureError):
        catalog.validate_runtime_settings(helper.type, {"path": "https://example.test/x"})
    with pytest.raises(VerificationInfrastructureError):
        catalog.validate_settings(contract, {"path": "/events", "control": True})


def test_event_ledger_runtime_is_hardened_and_collects_correlated_evidence(
    monkeypatch,
):
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "events",
            "type": APPEND_ONLY_EVENT_LEDGER_TYPE,
            "limits": {"max_events": 4, "max_event_bytes": 128},
        }
    )
    runtime = AppendOnlyEventLedgerRuntime(
        helper=helper,
        contract=append_only_event_ledger_contract(),
        settings={"path": "/events"},
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
        network="securebench-evaluation-test",
    )
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        if command[:3] == ["docker", "run", "-d"]:
            (runtime.state_dir / "ready.json").write_text(json.dumps({"port": 8080}))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("securebench.verification.trusted_helpers.subprocess.run", fake_run)
    access = runtime.start("securebench-helper-0")
    assert access["url"] == "http://securebench-helper-0:8080/events"
    assert access["authorization"].startswith("Bearer ")
    command = commands[0]
    assert "--read-only" in command
    assert "no-new-privileges:true" in command
    assert command[command.index("--log-driver") + 1] == "none"
    assert runtime.token not in command
    assert not any(part in {"-p", "--publish", "--publish-all"} for part in command)

    body = b'{"nonce":"nonce_1","event":"task.started","data":"task-1"}'
    record = {
        "sequence": 0,
        "elapsed_us": 42,
        "challenge_id": "challenge-test",
        "evaluation_id": "evaluation-test",
        "method": "POST",
        "target": "/events",
        "target_truncated": False,
        "path_matched": True,
        "authenticated": True,
        "content_type_valid": True,
        "header_bytes": 100,
        "body_bytes": len(body),
        "declared_body_bytes": len(body),
        "body_base64": base64.b64encode(body).decode(),
        "body_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
        "body_truncated": False,
        "event_valid": True,
        "accepted": True,
        "nonce": "nonce_1",
        "event": "task.started",
        "data": "task-1",
        "response_status": 202,
    }
    (runtime.state_dir / "events.jsonl").write_text(json.dumps(record) + "\n")
    evidence = runtime.collect(default_trusted_helper_catalog())
    root = runtime.root
    runtime.close()

    assert evidence.value == {"events": [record]}
    assert evidence.challenge_id == "challenge-test"
    assert evidence.evaluation_id == "evaluation-test"
    assert commands[1][:3] == ["docker", "stop", "--time"]
    assert not root.exists()


def test_interrupted_event_ledger_start_retries_late_container_cleanup(monkeypatch):
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "events",
            "type": APPEND_ONLY_EVENT_LEDGER_TYPE,
            "limits": {"max_events": 4, "max_event_bytes": 128},
        }
    )
    runtime = AppendOnlyEventLedgerRuntime(
        helper=helper,
        contract=append_only_event_ledger_contract(),
        settings={"path": "/events"},
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
        network="securebench-evaluation-test",
    )
    commands: list[list[str]] = []
    remove_attempts = 0

    def fake_run(command, **kwargs):
        nonlocal remove_attempts
        commands.append(list(command))
        if command[:3] == ["docker", "run", "-d"]:
            raise KeyboardInterrupt
        if command[:3] == ["docker", "rm", "-f"]:
            remove_attempts += 1
            if remove_attempts == 1:
                return subprocess.CompletedProcess(command, 1, "", "No such container")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("securebench.verification.trusted_helpers.subprocess.run", fake_run)
    monkeypatch.setattr("securebench.verification.trusted_helpers.time.sleep", lambda _: None)

    with pytest.raises(KeyboardInterrupt):
        runtime.start("securebench-helper-0")
    root = runtime.root
    runtime.close()

    assert remove_attempts == 2
    assert commands[0][:3] == ["docker", "run", "-d"]
    assert not root.exists()


def test_host_revalidation_rejects_forged_event_order_and_acceptance(tmp_path):
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "events",
            "type": APPEND_ONLY_EVENT_LEDGER_TYPE,
            "limits": {"max_events": 4, "max_event_bytes": 128},
        }
    )
    ledger, state_dir = _state(tmp_path, max_events=2)
    assert _request(ledger) == 202
    assert _request(ledger) == 202
    records = _records(state_dir)
    records[1]["elapsed_us"] = records[0]["elapsed_us"] - 1
    with pytest.raises(VerificationInfrastructureError, match="not monotonic"):
        _validate_event_ledger_records(helper, {"path": "/events"}, records)

    records[1]["elapsed_us"] = records[0]["elapsed_us"]
    records[0]["accepted"] = False
    with pytest.raises(VerificationInfrastructureError, match="acceptance"):
        _validate_event_ledger_records(helper, {"path": "/events"}, records)

    records[0].update(body_truncated=True, response_status=413)
    with pytest.raises(VerificationInfrastructureError, match="Truncated event body"):
        _validate_event_ledger_records(helper, {"path": "/events"}, records)


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 for the live helper qualification",
)
def test_event_ledger_runs_in_a_real_internal_docker_network():
    # The full protocol integration exercises helper startup, an authenticated
    # append from a separate Evaluation container, host collection, and cleanup.
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "events",
            "type": APPEND_ONLY_EVENT_LEDGER_TYPE,
            "limits": {"max_events": 4, "max_event_bytes": 128},
        }
    )
    network = "securebench-ledger-test-" + os.urandom(6).hex()
    subprocess.run(["docker", "network", "create", "--internal", network], check=True)
    runtime = AppendOnlyEventLedgerRuntime(
        helper=helper,
        contract=append_only_event_ledger_contract(),
        settings={"path": "/events"},
        challenge_id="challenge-live",
        evaluation_id="evaluation-live",
        network=network,
    )
    try:
        access = runtime.start("securebench-helper-0")
        payload = json.dumps(
            {"nonce": "live_nonce", "event": "task.started", "data": "task-live"},
            separators=(",", ":"),
        )
        script = (
            "import sys,urllib.request;"
            "u,t,b=sys.argv[1:];"
            "r=urllib.request.Request(u,data=b.encode(),headers={"
            "'Authorization':t,'Content-Type':'application/json'},method='POST');"
            "print(urllib.request.urlopen(r,timeout=5).status)"
        )
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                network,
                EVENT_LEDGER_IMAGE,
                "python3",
                "-c",
                script,
                access["url"],
                access["authorization"],
                payload,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert completed.stdout.strip() == "202"
        evidence = runtime.collect(default_trusted_helper_catalog())
        assert evidence.value["events"][0]["event"] == "task.started"
        assert evidence.value["events"][0]["accepted"] is True
    finally:
        runtime.close()
        subprocess.run(["docker", "network", "rm", network], check=False)
