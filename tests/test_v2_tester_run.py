import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateProduction,
    CandidateProductionError,
    CandidateProductionTimeout,
    CandidateStore,
)
from securebench.harnesses.shared import workspace_dir_name
from securebench.sandboxes import CommandResult
from securebench.tester_config import (
    TesterBenchmarkSection as BenchmarkSection,
    TesterConfig as RunConfig,
    TesterHarnessSection as HarnessSection,
    TesterRunSection as RunSection,
)
from securebench.tester_run import _reset_task_workspace, _resume_records, run_tester_config


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"


def candidate_calendar() -> str:
    return """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//SecureBench//Runner Test//EN
BEGIN:VEVENT
UID:team-planning@example.com
DTSTART:20240117T110000Z
DTEND:20240117T120000Z
SUMMARY:Team Planning Meeting
ATTENDEE:mailto:alice@example.com
ATTENDEE:mailto:bob@example.com
ATTENDEE:mailto:carol@example.com
END:VEVENT
END:VCALENDAR
"""


def config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        schema_version="1.0",
        run=RunSection(id="runner-v2", output_dir=tmp_path / "run"),
        benchmark=BenchmarkSection(
            manifest=PACK / "manifest-v2.yaml",
            tasks=PACK / "tasks-v2.jsonl",
        ),
        harness=HarnessSection(type="command", config={"command": "ignored"}),
    )


class GoodProducer:
    def __init__(self, root: Path):
        self.root = root
        self.calls = 0

    def produce(self, task):
        self.calls += 1
        workspace = self.root / workspace_dir_name(task)
        workspace.mkdir(parents=True)
        (workspace / "meeting_scheduled.ics").write_text(candidate_calendar())
        return CandidateProduction(
            workspace=str(workspace),
            stdout="must not enter result",
            metadata={"secret_agent_trace": "must not enter result"},
        )


def test_runner_persists_only_durable_candidate_and_sanitized_oracle_result(monkeypatch, tmp_path):
    current = config(tmp_path)
    producer = GoodProducer(current.run.output_dir / "workspaces")
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: producer,
    )

    summary = run_tester_config(current)

    assert summary.total == summary.verified == summary.passed == 1
    assert summary.infrastructure_errors == 0
    assert summary.output_path.endswith("results.jsonl")
    record = json.loads(Path(summary.output_path).read_text())
    assert record["status"] == "passed"
    assert record["candidate"]["type"] == "file_bundle"
    assert record["candidate"]["digest"].startswith("sha256:")
    assert record["provenance"]["row_digest"].startswith("sha256:")
    assert record["provenance"]["image_digest"].startswith("sha256:")
    assert record["provenance"]["baseline_digest"].startswith("sha256:")
    assert record["provenance"]["verification_digest"].startswith("sha256:")
    assert record["schema_version"] == "2"
    encoded = json.dumps(record)
    assert "must not enter result" not in encoded
    assert "source_path" not in encoded
    assert list((current.run.output_dir / "artifacts" / "candidates" / "sha256").rglob("manifest.json"))
    compiled = next(
        compile_benchmark_pack(
            load_benchmark_pack(current.benchmark.manifest, current.benchmark.tasks)
        )
    )
    assert not (
        current.run.output_dir / "workspaces" / workspace_dir_name(compiled)
    ).exists()


def test_runner_routes_capture_rejection_to_oracle_as_candidate_failure(monkeypatch, tmp_path):
    current = config(tmp_path)

    class MissingArtifactProducer:
        def produce(self, task):
            workspace = current.run.output_dir / "workspaces" / workspace_dir_name(task)
            workspace.mkdir(parents=True)
            return CandidateProduction(workspace=str(workspace))

    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: MissingArtifactProducer(),
    )

    summary = run_tester_config(current)
    record = json.loads(Path(summary.output_path).read_text())

    assert summary.passed == 0
    assert record["status"] == "failed"
    assert record["candidate"] == {"type": None, "digest": None}
    assert "candidate_capture_rejected" in record["public_diagnostics"]["failure_categories"]


def test_workspace_cleanup_uses_pinned_image_after_permission_failure(monkeypatch, tmp_path):
    task = next(
        compile_benchmark_pack(
            load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
        )
    )
    workspace_root = tmp_path / "workspaces"
    task_workspace = workspace_root / workspace_dir_name(task)
    task_workspace.mkdir(parents=True)
    calls = {"rmtree": 0, "docker": []}
    real_rmtree = shutil.rmtree

    def fake_rmtree(path):
        calls["rmtree"] += 1
        if calls["rmtree"] == 1:
            raise PermissionError("host cannot traverse Agent directory")
        real_rmtree(path)

    def fake_run(command, **kwargs):
        calls["docker"].append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("securebench.tester_run.shutil.rmtree", fake_rmtree)
    monkeypatch.setattr("securebench.tester_run.subprocess.run", fake_run)

    _reset_task_workspace(workspace_root, task)

    cleanup_run = calls["docker"][0]
    assert task.environment.image in cleanup_run
    assert ["--network", "none"] == cleanup_run[
        cleanup_run.index("--network") : cleanup_run.index("--network") + 2
    ]
    assert ["--cap-add", "DAC_OVERRIDE"] == cleanup_run[
        cleanup_run.index("--cap-add") : cleanup_run.index("--cap-add") + 2
    ]
    assert calls["docker"][1][:3] == ["docker", "rm", "-f"]
    assert not task_workspace.exists()


def test_runner_resume_requires_matching_row_provenance(monkeypatch, tmp_path):
    current = config(tmp_path)
    producer = GoodProducer(current.run.output_dir / "workspaces")
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: producer,
    )
    first = run_tester_config(current)
    assert producer.calls == 1

    second = run_tester_config(current, resume=True)

    assert second.passed == 1
    assert producer.calls == 1
    assert len(Path(first.output_path).read_text().splitlines()) == 1


def test_runner_resume_reexecutes_when_candidate_artifact_is_missing(monkeypatch, tmp_path):
    current = config(tmp_path)
    producer = GoodProducer(current.run.output_dir / "workspaces")
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: producer,
    )
    first = run_tester_config(current)
    manifest = next(
        (current.run.output_dir / "artifacts" / "candidates" / "sha256").rglob(
            "manifest.json"
        )
    )
    manifest.unlink()

    run_tester_config(current, resume=True)

    assert producer.calls == 2
    assert len(Path(first.output_path).read_text().splitlines()) == 1


def test_runner_resume_reexecutes_when_result_check_shape_is_invalid(monkeypatch, tmp_path):
    current = config(tmp_path)
    producer = GoodProducer(current.run.output_dir / "workspaces")
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: producer,
    )
    first = run_tester_config(current)
    record = json.loads(Path(first.output_path).read_text())
    record["checks"][0]["evidence_digests"] = ["not-a-digest"]
    Path(first.output_path).write_text(json.dumps(record) + "\n")

    run_tester_config(current, resume=True)

    assert producer.calls == 2
    repaired = json.loads(Path(first.output_path).read_text())
    assert repaired["checks"][0]["evidence_digests"][0].startswith("sha256:")


def test_resume_rejects_changed_verification_inputs(tmp_path):
    current = config(tmp_path)
    task = next(
        compile_benchmark_pack(
            load_benchmark_pack(current.benchmark.manifest, current.benchmark.tasks)
        )
    )
    record = {
        "schema_version": "2",
        "run_id": current.run.id,
        "task_id": task.id,
        "benchmark_id": task.benchmark_id,
        "status": "failed",
        "passed": False,
        "score": 0.0,
        "candidate": {"type": None, "digest": None},
        "execution_profile": task.verification.execution_profile,
        "provenance": {
            "manifest_digest": task.manifest_digest,
            "row_digest": task.row_digest,
            "image_digest": task.environment.image,
            "baseline_digest": task.baseline_digest,
            "verification_digest": task.verification_digest,
        },
        "checks": [],
        "public_diagnostics": {},
    }
    output = tmp_path / "results.jsonl"
    output.write_text(json.dumps(record) + "\n")
    changed = replace(task, verification_digest="sha256:" + "0" * 64)

    assert _resume_records(output, current.run.id, [changed], CandidateStore(tmp_path / "store")) == []


def test_runner_routes_producer_timeout_to_oracle(monkeypatch, tmp_path):
    current = config(tmp_path)

    class TimeoutProducer:
        def produce(self, task):
            raise CandidateProductionTimeout(
                CommandResult(("agent",), 124, "partial", "", timed_out=True, timeout_seconds=3)
            )

    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: TimeoutProducer(),
    )

    summary = run_tester_config(current)
    record = json.loads(Path(summary.output_path).read_text())

    assert summary.passed == 0
    assert record["status"] == "failed"
    assert "producer_timeout" in record["public_diagnostics"]["failure_categories"]


def test_runner_routes_agent_failure_to_oracle(monkeypatch, tmp_path):
    current = config(tmp_path)

    class FailedProducer:
        def produce(self, task):
            raise CandidateProductionError("agent exited without a candidate")

    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: FailedProducer(),
    )

    summary = run_tester_config(current)
    record = json.loads(Path(summary.output_path).read_text())

    assert summary.passed == 0
    assert "producer_failed" in record["public_diagnostics"]["failure_categories"]


def test_runner_isolates_unexpected_row_infrastructure_failure(monkeypatch, tmp_path):
    current = config(tmp_path)

    class BrokenProducer:
        def produce(self, task):
            raise OSError("host path that must not be published")

    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: BrokenProducer(),
    )

    summary = run_tester_config(current)
    record = json.loads(Path(summary.output_path).read_text())

    assert summary.total == summary.verified == summary.infrastructure_errors == 1
    assert record["status"] == "infrastructure_error"
    assert record["infrastructure_error"]["code"] == "task_execution_internal_error"
    assert "host path" not in json.dumps(record)
