from __future__ import annotations

import json
from pathlib import Path

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateStore,
    HostWorkspaceFilesystem,
    capture_file_bundle,
)
from securebench.verification import (
    ArtifactVerificationEngine,
    OracleSession,
    OracleVerdict,
    ResultWriter,
)


DIGEST = "sha256:" + "c" * 64
BASELINE = "sha256:" + "d" * 64


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
        baseline_digest=BASELINE,
    )
    return store, candidate


def test_artifact_evidence_is_internal_and_result_is_sanitized(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b'{"private_observation":"secret-value"}\n')
    oracle = RecordingOracle()

    result = ArtifactVerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-1",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert oracle.evidence[0].parsed_value == {"private_observation": "secret-value"}
    record = result.to_record(run_id="run-1")
    encoded = json.dumps(record)
    assert "secret-value" not in encoded
    assert "parsed_value" not in encoded
    assert record["checks"][0]["evidence_digests"][0].startswith("sha256:")


def test_parser_rejection_is_candidate_evidence_for_oracle(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b"not-json")
    oracle = RecordingOracle()

    result = ArtifactVerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-2",
        oracle=oracle,
    )

    assert result.status == "failed"
    assert oracle.evidence[0].status == "candidate_error"
    assert oracle.evidence[0].error_code == "invalid_json"


def test_result_writer_persists_only_public_projection(tmp_path):
    task = write_artifact_pack(tmp_path / "pack")
    store, candidate = capture_result(tmp_path, task, b'{"ok":true}')
    result = ArtifactVerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-3",
        oracle=RecordingOracle(),
    )
    output = tmp_path / "results.jsonl"

    record = ResultWriter(output, run_id="run-3").append(result)

    assert json.loads(output.read_text()) == record
    assert set(record["candidate"]) == {"type", "digest"}
    assert "manifest_path" not in output.read_text()


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
    store, candidate = capture_result(tmp_path, task, b'{"answer":42}')

    result = ArtifactVerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-4",
    )

    assert result.status == "passed"
    assert result.public_diagnostics == {"message": "oracle evaluated artifact"}


def test_unknown_parser_is_an_infrastructure_error(tmp_path):
    task = write_artifact_pack(tmp_path / "pack", parser="securebench.unknown/v1")
    store, candidate = capture_result(tmp_path, task, b"{}")

    result = ArtifactVerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="seed-5",
        oracle=RecordingOracle(),
    )

    assert result.status == "infrastructure_error"
    assert result.infrastructure_error["code"] == "verification_internal_error"
