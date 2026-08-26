from __future__ import annotations

import hashlib
import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Thread

import pytest

from securebench.schemas.benchmark import TrustedHelperSpec
from securebench.verification.models import VerificationInfrastructureError
from securebench.verification.http_request_recorder_server import (
    RecorderHandler,
    RecorderState,
)
from securebench.verification.trusted_helpers import (
    HTTP_REQUEST_RECORDER_IMAGE,
    HTTP_REQUEST_RECORDER_TYPE,
    HttpRequestRecorderRuntime,
    default_trusted_helper_catalog,
    http_request_recorder_contract,
    _validate_recorder_records,
)


def _recorder_state(tmp_path: Path, *, max_requests: int = 6):
    state = tmp_path / "state"
    state.mkdir()
    config = {
        "challenge_id": "challenge-test",
        "evaluation_id": "evaluation-test",
        "settings": {
            "path": "/callback",
            "response_status": 202,
            "response_body": "accepted",
        },
        "limits": {
            "max_requests": max_requests,
            "max_body_bytes": 4,
            "max_header_bytes": 4096,
        },
    }
    return RecorderState(config, "test-secret", state), state


class _FakeServer:
    def __init__(self, state: RecorderState) -> None:
        self.recorder_state = state


def _request(
    state: RecorderState,
    method: str,
    target: str,
    *,
    body: bytes = b"",
    token: str = "test-secret",
    extra_headers: tuple[tuple[str, str], ...] = (),
):
    client, server = socket.socketpair()
    request = (
        f"{method} {target} HTTP/1.1\r\n"
        "Host: attacker-controlled.example\r\n"
        f"Authorization: Bearer {token}\r\n"
        "Proxy-Authorization: must-not-be-recorded\r\n"
        "X-Test: visible\r\n"
        f"Content-Length: {len(body)}\r\n"
        + "".join(f"{name}: {value}\r\n" for name, value in extra_headers)
        + "Connection: close\r\n\r\n"
    ).encode("ascii") + body
    try:
        handler = Thread(
            target=RecorderHandler,
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
    head, response_body = response.split(b"\r\n\r\n", 1)
    status = int(head.split(b"\r\n", 1)[0].split()[1])
    return status, response_body


def test_recorder_data_plane_is_bounded_authenticated_and_has_no_control_route(tmp_path):
    recorder, state = _recorder_state(tmp_path)
    assert _request(recorder, "POST", "/callback?event=1", body=b"test") == (
        202,
        b"accepted",
    )
    assert _request(recorder, "GET", "/callback", token="forged") == (401, b"")
    assert _request(recorder, "GET", "/__securebench_evidence") == (404, b"")
    assert _request(recorder, "POST", "/callback", body=b"oversized") == (413, b"")
    assert _request(recorder, "GET", "http://attacker.example/callback") == (404, b"")
    assert _request(recorder, "GET", "/" + "x" * 9000) == (414, b"")
    assert _request(recorder, "GET", "/callback") == (429, b"")

    records = [json.loads(line) for line in (state / "requests.jsonl").read_text().splitlines()]
    assert len(records) == 6
    assert [record["sequence"] for record in records] == list(range(6))
    assert all(record["challenge_id"] == "challenge-test" for record in records)
    assert all(record["evaluation_id"] == "evaluation-test" for record in records)
    assert records[0]["authenticated"] is True
    assert records[0]["path_matched"] is True
    assert records[0]["response_status"] == 202
    assert records[1]["authenticated"] is False
    assert records[2]["path_matched"] is False
    assert records[3]["body_truncated"] is True
    assert records[4]["path_matched"] is False
    assert records[4]["target_truncated"] is False
    assert records[5]["target_truncated"] is True
    assert len(records[5]["target"].encode("utf-8")) <= 8192
    assert all(
        header["name"] not in {"authorization", "proxy-authorization"}
        for record in records
        for header in record["headers"]
    )
    assert any(
        header == {"name": "host", "value": "attacker-controlled.example"}
        for header in records[0]["headers"]
    )
    assert (state / "truncated.flag").is_file()


def test_default_catalog_accepts_only_bounded_semantically_valid_recorder_settings():
    catalog = default_trusted_helper_catalog()
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "webhook",
            "type": HTTP_REQUEST_RECORDER_TYPE,
            "limits": {"max_requests": 8, "max_body_bytes": 1024},
        }
    )
    contract = catalog.validate_declaration(helper)
    settings = {"path": "/hook", "response_status": 204}

    catalog.validate_settings(contract, settings)
    catalog.validate_runtime_settings(helper.type, settings)
    assert catalog.runtime_factory(helper.type) is HttpRequestRecorderRuntime

    with pytest.raises(VerificationInfrastructureError) as invalid:
        catalog.validate_runtime_settings(helper.type, {"path": "https://attacker.example/"})
    assert invalid.value.code == "trusted_helper_settings_invalid"
    assert invalid.value.source == "trusted_helper"
    with pytest.raises(VerificationInfrastructureError):
        catalog.validate_runtime_settings(
            helper.type,
            {"response_status": 205, "response_body": "not allowed"},
        )


def test_recorder_rejects_ambiguous_authentication_and_body_framing(tmp_path):
    recorder, state = _recorder_state(tmp_path, max_requests=3)
    assert _request(
        recorder,
        "GET",
        "/callback",
        extra_headers=(("Authorization", "Bearer test-secret"),),
    ) == (401, b"")
    assert _request(
        recorder,
        "POST",
        "/callback",
        extra_headers=(("Content-Length", "0"),),
    ) == (400, b"")
    assert _request(
        recorder,
        "POST",
        "/callback",
        extra_headers=(("Transfer-Encoding", "chunked"),),
    ) == (400, b"")

    records = [json.loads(line) for line in (state / "requests.jsonl").read_text().splitlines()]
    assert records[0]["authenticated"] is False
    assert records[1]["body_truncated"] is True
    assert records[2]["body_truncated"] is True


def test_recorder_runtime_uses_internal_network_hardening_and_file_backed_secret(
    tmp_path, monkeypatch
):
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "webhook",
            "type": HTTP_REQUEST_RECORDER_TYPE,
            "limits": {
                "max_requests": 2,
                "max_body_bytes": 16,
                "max_header_bytes": 1024,
            },
        }
    )
    runtime = HttpRequestRecorderRuntime(
        helper=helper,
        contract=http_request_recorder_contract(),
        settings={"path": "/hook"},
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
    assert access["url"] == "http://securebench-helper-0:8080/hook"
    assert access["authorization"].startswith("Bearer ")
    start_command = commands[0]
    assert ["--network", "securebench-evaluation-test"] == start_command[
        start_command.index("--network") : start_command.index("--network") + 2
    ]
    assert "--cap-drop" in start_command
    assert ["--cap-add", "DAC_OVERRIDE"] == start_command[
        start_command.index("--cap-add") : start_command.index("--cap-add") + 2
    ]
    assert "--read-only" in start_command
    assert "--security-opt" in start_command
    assert "no-new-privileges:true" in start_command
    assert start_command[start_command.index("--log-driver") + 1] == "none"
    assert HTTP_REQUEST_RECORDER_IMAGE in start_command
    assert runtime.token not in start_command
    assert not any(part in {"-p", "--publish", "--publish-all"} for part in start_command)

    record = {
        "sequence": 0,
        "challenge_id": "challenge-test",
        "evaluation_id": "evaluation-test",
        "method": "POST",
        "target": "/hook",
        "target_truncated": False,
        "headers": [],
        "header_bytes": 0,
        "headers_truncated": False,
        "body_base64": "",
        "body_bytes": 0,
        "declared_body_bytes": 0,
        "body_sha256": "sha256:" + hashlib.sha256(b"").hexdigest(),
        "body_truncated": False,
        "authenticated": True,
        "path_matched": True,
        "response_status": 204,
    }
    (runtime.state_dir / "requests.jsonl").write_text(json.dumps(record) + "\n")
    evidence = runtime.collect(default_trusted_helper_catalog())
    root = runtime.root
    runtime.close()

    assert evidence.name == "webhook"
    assert evidence.value == {"requests": [record]}
    assert evidence.truncated is False
    assert commands[1][:3] == ["docker", "stop", "--time"]
    assert not root.exists()


def test_host_revalidation_rejects_forged_recorder_response_semantics():
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "webhook",
            "type": HTTP_REQUEST_RECORDER_TYPE,
            "limits": {"max_requests": 2, "max_body_bytes": 16},
        }
    )
    record = {
        "sequence": 0,
        "challenge_id": "challenge-test",
        "evaluation_id": "evaluation-test",
        "method": "GET",
        "target": "/",
        "target_truncated": False,
        "headers": [],
        "header_bytes": 0,
        "headers_truncated": False,
        "body_base64": "",
        "body_bytes": 0,
        "declared_body_bytes": 0,
        "body_sha256": "sha256:" + hashlib.sha256(b"").hexdigest(),
        "body_truncated": False,
        "authenticated": False,
        "path_matched": True,
        "response_status": 204,
    }

    with pytest.raises(VerificationInfrastructureError, match="response status metadata"):
        _validate_recorder_records(helper, {}, [record])


def test_recorder_rejects_evidence_from_another_evaluation(tmp_path, monkeypatch):
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "webhook",
            "type": HTTP_REQUEST_RECORDER_TYPE,
            "limits": {"max_requests": 2, "max_body_bytes": 16},
        }
    )
    runtime = HttpRequestRecorderRuntime(
        helper=helper,
        contract=http_request_recorder_contract(),
        settings={},
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
        network="securebench-evaluation-test",
    )
    runtime.started = True
    record = {
        "sequence": 0,
        "challenge_id": "challenge-test",
        "evaluation_id": "evaluation-forged",
        "method": "GET",
        "target": "/",
        "target_truncated": False,
        "headers": [],
        "header_bytes": 0,
        "headers_truncated": False,
        "body_base64": "",
        "body_bytes": 0,
        "declared_body_bytes": 0,
        "body_sha256": "sha256:" + hashlib.sha256(b"").hexdigest(),
        "body_truncated": False,
        "authenticated": True,
        "path_matched": True,
        "response_status": 204,
    }
    (runtime.state_dir / "requests.jsonl").write_text(json.dumps(record) + "\n")
    monkeypatch.setattr(
        "securebench.verification.trusted_helpers.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    with pytest.raises(VerificationInfrastructureError) as error:
        runtime.collect(default_trusted_helper_catalog())
    runtime.close()

    assert error.value.code == "trusted_helper_evidence_misbound"
    assert error.value.source == "trusted_helper"


def test_recorder_runtime_uses_fresh_state_and_credentials_per_evaluation():
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "webhook",
            "type": HTTP_REQUEST_RECORDER_TYPE,
            "limits": {"max_requests": 2, "max_body_bytes": 16},
        }
    )
    first = HttpRequestRecorderRuntime(
        helper=helper,
        contract=http_request_recorder_contract(),
        settings={},
        challenge_id="challenge-one",
        evaluation_id="evaluation-one",
        network="network-one",
    )
    second = HttpRequestRecorderRuntime(
        helper=helper,
        contract=http_request_recorder_contract(),
        settings={},
        challenge_id="challenge-two",
        evaluation_id="evaluation-two",
        network="network-two",
    )
    first_root, second_root = first.root, second.root
    try:
        assert first.root != second.root
        assert first.state_dir != second.state_dir
        assert first.token != second.token
        assert not (second.state_dir / "requests.jsonl").exists()
    finally:
        first.close()
        second.close()
    assert not first_root.exists()
    assert not second_root.exists()


def test_recorder_crash_and_cleanup_failure_are_trusted_helper_infrastructure_errors(
    monkeypatch,
):
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "webhook",
            "type": HTTP_REQUEST_RECORDER_TYPE,
            "limits": {"max_requests": 2, "max_body_bytes": 16},
        }
    )
    runtime = HttpRequestRecorderRuntime(
        helper=helper,
        contract=http_request_recorder_contract(),
        settings={},
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
        network="network-test",
    )
    runtime.started = True

    def fake_run(command, **kwargs):
        returncode = (
            1
            if command[:2] == ["docker", "stop"]
            or command[:3] == ["docker", "network", "rm"]
            else 0
        )
        return subprocess.CompletedProcess(command, returncode, "", "missing")

    monkeypatch.setattr("securebench.verification.trusted_helpers.subprocess.run", fake_run)
    with pytest.raises(VerificationInfrastructureError) as crashed:
        runtime.collect(default_trusted_helper_catalog())
    runtime.close()
    assert crashed.value.code == "trusted_helper_crashed"
    assert crashed.value.source == "trusted_helper"

    from securebench.verification.trusted_helpers import _remove_network

    with pytest.raises(VerificationInfrastructureError) as cleanup:
        _remove_network("network-test")
    assert cleanup.value.code == "trusted_helper_cleanup_failed"
    assert cleanup.value.source == "trusted_helper"


def test_recorder_concurrently_enforces_its_exact_record_limit(tmp_path):
    recorder, state = _recorder_state(tmp_path, max_requests=4)
    with ThreadPoolExecutor(max_workers=16) as pool:
        statuses = list(
            pool.map(
                lambda _: _request(recorder, "GET", "/callback")[0],
                range(16),
            )
        )

    records = [json.loads(line) for line in (state / "requests.jsonl").read_text().splitlines()]
    assert statuses.count(202) == 4
    assert statuses.count(429) == 12
    assert [record["sequence"] for record in records] == [0, 1, 2, 3]
    assert (state / "truncated.flag").is_file()


def test_failed_helper_start_remains_owned_by_cleanup(monkeypatch):
    helper = TrustedHelperSpec.model_validate(
        {
            "name": "webhook",
            "type": HTTP_REQUEST_RECORDER_TYPE,
            "limits": {"max_requests": 2, "max_body_bytes": 16},
        }
    )
    runtime = HttpRequestRecorderRuntime(
        helper=helper,
        contract=http_request_recorder_contract(),
        settings={},
        challenge_id="challenge-test",
        evaluation_id="evaluation-test",
        network="network-test",
    )
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            1 if command[:3] == ["docker", "run", "-d"] else 0,
            "",
            "failed",
        )

    monkeypatch.setattr("securebench.verification.trusted_helpers.subprocess.run", fake_run)
    with pytest.raises(VerificationInfrastructureError) as error:
        runtime.start("securebench-helper-0")
    root = runtime.root
    runtime.close()

    assert error.value.code == "trusted_helper_start_failed"
    assert any(command[:3] == ["docker", "rm", "-f"] for command in commands)
    assert not root.exists()
