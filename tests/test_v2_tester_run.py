import json
from pathlib import Path

from securebench.candidates import CandidateProduction, CandidateProductionError, CandidateProductionTimeout
from securebench.harnesses.shared import workspace_dir_name
from securebench.sandboxes import CommandResult
from securebench.tester_config import (
    TesterBenchmarkSection as BenchmarkSection,
    TesterConfig as RunConfig,
    TesterHarnessSection as HarnessSection,
    TesterRunSection as RunSection,
)
from securebench.tester_run import run_tester_config


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
    encoded = json.dumps(record)
    assert "must not enter result" not in encoded
    assert "source_path" not in encoded
    assert list((current.run.output_dir / "artifacts" / "candidates" / "sha256").rglob("manifest.json"))


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
