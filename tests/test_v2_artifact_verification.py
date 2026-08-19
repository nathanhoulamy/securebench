from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateStore,
    HostWorkspaceFilesystem,
    capture_file_bundle,
)
from securebench.verification import (
    VerificationEngine,
    OracleSession,
    OracleVerdict,
)
from securebench.verification.models import VerificationInfrastructureError
from securebench.verification.oracle import OracleProcessSession


DIGEST = "sha256:" + "c" * 64


class RecordingOracle(OracleSession):
    def __init__(self) -> None:
        self.initialized = False
        self.evidence = []
        self.closed = False

    def initialize(self, task, *, run_seed):
        self.initialized = True
        self.seed = run_seed

    def evaluate_artifact(self, evidence):
        self.evidence.append(evidence)

    def finalize(self):
        passed = bool(self.evidence) and all(item.status == "observed" for item in self.evidence)
        return OracleVerdict(
            passed=passed,
            score=1.0 if passed else 0.0,
            public_diagnostics={"message": "accepted" if passed else "rejected"},
            check_outcomes={"result_artifact": passed},
        )

    def close(self):
        self.closed = True


class FixedVerdictOracle(RecordingOracle):
    def __init__(self, verdict):
        super().__init__()
        self.verdict = verdict

    def finalize(self):
        return self.verdict


def write_artifact_pack(root: Path, *, parser="securebench.strict-json/v1"):
    (root / "assets").mkdir(parents=True)
    (root / "evaluation_inputs").mkdir()
    (root / "hidden" / "task" / "oracle").mkdir(parents=True)
    manifest = root / "manifest.yaml"
    manifest.write_text(
        f"""
schema_version: "2.0"
id: artifact-pack
defaults:
  family: terminal_task
  environment:
    image: {DIGEST}
    workdir: /app
    timeout_seconds: 30
    agent_network: none
resource_roots:
  public: assets/
  runtime: evaluation_inputs/
  host: hidden/
""".lstrip()
    )
    row = {
        "id": "artifact/task",
        "input": {"instructions": "Write /app/result.json."},
        "verification": {
            "execution_profile": "strict-split/v1",
            "candidate": {
                "type": "file_bundle",
                "max_total_files": 1,
                "max_total_bytes": 1024,
                "files": [
                    {
                        "id": "result",
                        "path": "/app/result.json",
                        "kind": "regular_file",
                        "max_bytes": 1024,
                    }
                ],
            },
            "resources": {
                "host": {"oracle": {"path": "task/oracle"}},
            },
            "checks": [
                {
                    "id": "result_artifact",
                    "type": "artifact",
                    "artifacts": [
                        {
                            "id": "result",
                            "source": {"entry": "result"},
                            "parser": parser,
                            "limits": {"max_bytes": 1024},
                        }
                    ],
                }
            ],
            "oracle": "host.oracle",
        },
    }
    tasks = root / "tasks.jsonl"
    tasks.write_text(json.dumps(row) + "\n")
    pack = load_benchmark_pack(manifest, tasks)
    return next(compile_benchmark_pack(pack))


def capture_result(tmp_path: Path, task, content: bytes):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "result.json").write_bytes(content)
    store = CandidateStore(tmp_path / "candidate-store")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
    )
    return store, candidate


def test_artifact_evidence_is_internal_and_result_is_sanitized(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b'{"private_observation":"secret-value"}\n')
    oracle = RecordingOracle()

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-1",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert oracle.evidence[0].parsed_value == {"private_observation": "secret-value"}
    record = result.to_record(run_id="run-1", execution_digest=DIGEST)
    encoded = json.dumps(record)
    assert "secret-value" not in encoded
    assert "parsed_value" not in encoded
    assert record["checks"][0]["evidence_digests"][0].startswith("sha256:")


def test_parser_rejection_is_candidate_evidence_for_oracle(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b"not-json")
    oracle = RecordingOracle()

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-2",
        oracle=oracle,
    )

    assert result.status == "failed"
    assert oracle.evidence[0].status == "candidate_error"
    assert oracle.evidence[0].error_code == "invalid_json"


@pytest.mark.parametrize(
    "verdict",
    [
        OracleVerdict(passed=True, score=1.0, check_outcomes={}),
        OracleVerdict(
            passed=True,
            score=1.0,
            check_outcomes={"result_artifact": True, "unknown": True},
        ),
    ],
)
def test_oracle_verdict_outcomes_must_match_declared_checks(tmp_path, verdict):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b"{}")

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-invalid-verdict",
        oracle=FixedVerdictOracle(verdict),
    )

    assert result.status == "infrastructure_error"
    assert result.infrastructure_error["code"] == "oracle_protocol_error"


def test_oracle_may_apply_its_own_threshold_across_check_outcomes(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b"{}")
    verdict = OracleVerdict(
        passed=True,
        score=0.75,
        check_outcomes={"result_artifact": False},
    )

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-custom-threshold",
        oracle=FixedVerdictOracle(verdict),
    )

    assert result.status == "passed"
    assert result.score == 0.75
    assert result.checks[0].status == "failed"


def test_pack_local_oracle_process_owns_final_verdict(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    oracle_root = tmp_path / "pack" / "hidden" / "task" / "oracle"
    (oracle_root / "oracle.yaml").write_text(
        """
abi: securebench.oracle/v1
command: ["{python}", "oracle.py"]
timeout_seconds: 5
""".lstrip()
    )
    (oracle_root / "oracle.py").write_text(
        """
import json
import sys

accepted = False
for line in sys.stdin:
    request = json.loads(line)
    if request["op"] == "initialize":
        print(json.dumps({"type": "ack"}), flush=True)
    elif request["op"] == "evaluate_artifact":
        accepted = request["evidence"]["parsed_value"] == {"answer": 42}
        print(json.dumps({"type": "ack"}), flush=True)
    elif request["op"] == "finalize":
        print(json.dumps({
            "type": "verdict",
            "verdict": {
                "passed": accepted,
                "score": 1.0 if accepted else 0.0,
                "check_outcomes": {"result_artifact": accepted},
                "public_diagnostics": {"message": "oracle evaluated artifact"}
            }
        }), flush=True)
""".lstrip()
    )
    task = next(
        compile_benchmark_pack(
            load_benchmark_pack(
                tmp_path / "pack" / "manifest.yaml",
                tmp_path / "pack" / "tasks.jsonl",
            )
        )
    )
    store, candidate = capture_result(tmp_path, task, b'{"answer":42}')

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-4",
    )

    assert result.status == "passed"
    assert result.public_diagnostics == {"message": "oracle evaluated artifact"}
    assert not (oracle_root / "__pycache__").exists()


def test_oracle_request_write_obeys_timeout(tmp_path):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(
        """
abi: securebench.oracle/v1
command: ["{python}", "oracle.py"]
timeout_seconds: 0.1
""".lstrip()
    )
    (oracle_root / "oracle.py").write_text(
        "import time\ntime.sleep(10)\n"
    )
    session = OracleProcessSession(oracle_root)
    started = time.monotonic()

    try:
        with pytest.raises(VerificationInfrastructureError, match="request timeout"):
            session._request(
                {"op": "large", "payload": "x" * (2 * 1024 * 1024)},
                expected="ack",
            )
    finally:
        session.close()

    assert time.monotonic() - started < 2


@pytest.mark.parametrize(
    "manifest",
    [
        "command: [unterminated\n",
        "abi: securebench.oracle/v1\ncommand: ['{python}', 'oracle.py']\ntimeout_seconds: .inf\n",
        (
            "abi: securebench.oracle/v1\ncommand: ['{python}', 'oracle.py']\n"
            f"timeout_seconds: {10**400}\n"
        ),
    ],
)
def test_oracle_process_rejects_invalid_manifests(tmp_path, manifest):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(manifest)

    with pytest.raises(VerificationInfrastructureError) as error:
        OracleProcessSession(oracle_root)

    assert error.value.code == "oracle_manifest_invalid"


def test_oracle_process_reports_start_failure_as_infrastructure_error(tmp_path):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(
        "abi: securebench.oracle/v1\n"
        "command: ['/definitely/missing/securebench-oracle']\n"
        "timeout_seconds: 1\n"
    )

    with pytest.raises(VerificationInfrastructureError) as error:
        OracleProcessSession(oracle_root)

    assert error.value.code == "oracle_start_failed"


@pytest.mark.parametrize(
    "verdict",
    [
        {"passed": True, "score": 1.0},
        {
            "passed": True,
            "score": 1.0,
            "check_outcomes": {"result_artifact": True},
            "unexpected": True,
        },
    ],
)
def test_oracle_process_rejects_missing_or_unknown_verdict_fields(tmp_path, verdict):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(
        """
abi: securebench.oracle/v1
command: ["{python}", "oracle.py"]
timeout_seconds: 1
""".lstrip()
    )
    response = json.dumps({"type": "verdict", "verdict": verdict})
    (oracle_root / "oracle.py").write_text(
        "import sys\nfor line in sys.stdin:\n"
        f"    print({response!r}, flush=True)\n"
    )
    session = OracleProcessSession(oracle_root)

    try:
        with pytest.raises(VerificationInfrastructureError) as error:
            session.finalize()
    finally:
        session.close()

    assert error.value.code == "oracle_protocol_error"


def test_unknown_parser_is_an_infrastructure_error(tmp_path):
    task = write_artifact_pack(tmp_path / "pack", parser="securebench.unknown/v1")
    store, candidate = capture_result(tmp_path, task, b"{}")

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-5",
        oracle=RecordingOracle(),
    )

    assert result.status == "infrastructure_error"
    assert result.infrastructure_error["code"] == "verification_internal_error"


def test_verification_rejects_candidate_from_another_baseline(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b'{}')
    mismatched = replace(candidate, baseline_digest="sha256:" + "0" * 64)

    result = VerificationEngine().verify(
        task,
        mismatched,
        store,
        run_seed="seed-mismatch",
        oracle=RecordingOracle(),
    )

    assert result.status == "infrastructure_error"
    assert result.infrastructure_error["code"] == "candidate_reference_mismatch"
