import json

from securebench.candidates import CandidateArtifact, CandidateProductionTimeout
from securebench.harnesses.shared import workspace_dir_name
from securebench.sandboxes import CommandResult
from securebench.tester_config import (
    TesterBenchmarkSection as BenchmarkSection,
    TesterConfig as Config,
    TesterHarnessSection as HarnessSection,
    TesterRunSection as RunSection,
)
from securebench.tester_run import TesterRunSummary as RunSummary
from securebench.tester_run import run_tester_config
from securebench.verifiers import VerificationResult


class FakeProducer:
    def __init__(self, candidate):
        self.candidate = candidate

    def produce(self, task):
        return self.candidate


class FakeVerifier:
    def verify(self, task, candidate, **context):
        assert task.task_type == "repo_patch"
        assert candidate == "diff --git a/app.py b/app.py\n"
        assert context["verification_policy"].disallow_dangerous_commands is True
        return VerificationResult(
            task_id=task.id,
            status="passed",
            passed=True,
            score=1.0,
            stdout="tests passed",
            metadata={"exit_code": 0},
        )


def write_repo_patch_pack(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    tasks = tmp_path / "tasks.jsonl"
    manifest.write_text(
        """
id: tester-run-pack
version: 1
defaults:
  family: repo_patch
  environment:
    image: python:3.12-slim
"""
    )
    tasks.write_text(
        json.dumps(
            {
                "id": "tester-run-pack/fix_app",
                "input": {
                    "repo": "repo/",
                    "base_commit": "abc123",
                    "instructions": "Fix app.py",
                },
                "eval": {
                    "tests": {"source": "command", "command": ["pytest", "-q"]},
                    "gold_patch": "diff --git a/app.py b/app.py\n",
                },
            }
        )
        + "\n"
    )
    return manifest, tasks


def write_terminal_pack(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    tasks = tmp_path / "tasks.jsonl"
    manifest.write_text(
        """
id: tester-run-pack
version: 1
defaults:
  family: terminal_task
  environment:
    image: python:3.12-slim
"""
    )
    tasks.write_text(
        json.dumps(
            {
                "id": "tester-run-pack/create-output",
                "input": {"instructions": "Create output.txt"},
                "eval": {"checker": {"source": "pytest", "path": "checks"}},
            }
        )
        + "\n"
    )
    return manifest, tasks


def make_config(tmp_path, manifest, tasks):
    return Config(
        schema_version="0.2",
        run=RunSection(id="tester-run", output_dir=tmp_path / "out"),
        benchmark=BenchmarkSection(manifest=manifest, tasks=tasks),
        harness=HarnessSection(type="command", config={"command": "ignored"}),
    )


def test_run_tester_config_writes_verified_repo_patch_record(monkeypatch, tmp_path):
    manifest, tasks = write_repo_patch_pack(tmp_path)
    config = make_config(tmp_path, manifest, tasks)

    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: FakeProducer(
            CandidateArtifact(
                patch="diff --git a/app.py b/app.py\n",
                stdout="producer out",
                metadata={"harness": "fake"},
            )
        ),
    )
    monkeypatch.setattr("securebench.tester_run.verifier_for_task_type", lambda task_type: FakeVerifier())

    summary = run_tester_config(config)

    assert summary == RunSummary(
        run_id="tester-run",
        output_dir=str((tmp_path / "out").resolve()),
        output_path=str((tmp_path / "out" / "candidates.jsonl").resolve()),
        total=1,
        verified=1,
        passed=1,
        score_sum=1.0,
    )
    assert summary.verification_status == "complete"
    records = [json.loads(line) for line in (tmp_path / "out" / "candidates.jsonl").read_text().splitlines()]
    assert records[0]["candidate_patch"] == "diff --git a/app.py b/app.py\n"
    assert records[0]["candidate_workspace"] is None
    assert records[0]["verification_status"] == "passed"
    assert records[0]["passed"] is True
    assert records[0]["score"] == 1.0
    assert records[0]["verifier_stdout"] == "tests passed"
    assert records[0]["verifier_metadata"] == {"exit_code": 0}
    assert records[0]["hidden_values"] == "<redacted>"


def test_run_tester_config_records_producer_timeout_as_failed_result(monkeypatch, tmp_path):
    manifest, tasks = write_terminal_pack(tmp_path)
    config = make_config(tmp_path, manifest, tasks)

    class TimeoutProducer:
        def produce(self, task):
            raise CandidateProductionTimeout(
                CommandResult(
                    ("produce",),
                    124,
                    "partial out",
                    "partial err",
                    timed_out=True,
                    timeout_seconds=5,
                )
            )

    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: TimeoutProducer(),
    )

    summary = run_tester_config(config)

    assert summary.total == 1
    assert summary.verified == 1
    assert summary.passed == 0
    assert summary.score_sum == 0.0
    assert summary.verification_status == "complete"
    records = [json.loads(line) for line in (tmp_path / "out" / "candidates.jsonl").read_text().splitlines()]
    assert records[0]["verification_status"] == "failed"
    assert records[0]["passed"] is False
    assert records[0]["score"] == 0.0
    assert records[0]["failure_reason"] == "producer_timeout"
    assert records[0]["failure_phase"] == "producer"
    assert records[0]["failure_message"] == "candidate production timed out after 5 seconds"
    assert records[0]["producer_stdout"] == "partial out"
    assert records[0]["producer_stderr"] == "partial err"
    assert records[0]["producer_metadata"]["timed_out"] is True
    assert records[0]["producer_metadata"]["timeout_seconds"] == 5


def test_run_tester_config_resume_keeps_valid_records_and_skips_completed(monkeypatch, tmp_path):
    manifest, tasks = write_repo_patch_pack(tmp_path)
    config = make_config(tmp_path, manifest, tasks)
    config.run.output_dir.mkdir(parents=True)
    existing = {
        "run_id": "tester-run",
        "task_id": "tester-run-pack/fix_app",
        "benchmark_id": "tester-run-pack",
        "task_type": "repo_patch",
        "verification_status": "passed",
        "passed": True,
        "score": 1.0,
    }
    (config.run.output_dir / "candidates.jsonl").write_text(
        "\x00\x00not-json\n" + json.dumps(existing) + "\n"
    )

    def fake_producer(harness, workspace_root=None):
        class Producer:
            def produce(self, task):
                raise AssertionError("completed task should be skipped")

        return Producer()

    monkeypatch.setattr("securebench.tester_run.build_harness_producer", fake_producer)

    summary = run_tester_config(config, resume=True)

    assert summary.total == 1
    assert summary.verified == 1
    assert summary.passed == 1
    records = [
        json.loads(line)
        for line in (config.run.output_dir / "candidates.jsonl").read_text().splitlines()
    ]
    assert records == [existing]


def test_run_tester_config_cleans_stale_task_workspace_before_producer(monkeypatch, tmp_path):
    manifest, tasks = write_terminal_pack(tmp_path)
    config = make_config(tmp_path, manifest, tasks)

    class Producer:
        def __init__(self, workspace_root):
            self.workspace_root = workspace_root

        def produce(self, task):
            task_workspace = self.workspace_root / workspace_dir_name(task)
            assert not (task_workspace / "securebench" / "evaluation_inputs" / "checker.json").exists()
            task_workspace.mkdir(parents=True)
            (task_workspace / "fresh.txt").write_text("fresh")
            return CandidateArtifact(workspace=str(task_workspace))

    def fake_producer(harness, workspace_root=None):
        assert workspace_root is not None
        stale_workspace = workspace_root / "tester-run-pack_create-output-a601a9c1"
        (stale_workspace / "securebench" / "evaluation_inputs").mkdir(parents=True)
        (stale_workspace / "securebench" / "evaluation_inputs" / "checker.json").write_text("{}")
        return Producer(workspace_root)

    monkeypatch.setattr("securebench.tester_run.build_harness_producer", fake_producer)
    monkeypatch.setattr("securebench.tester_run.verifier_for_task_type", lambda task_type: None)

    run_tester_config(config)

    task_workspace = config.run.output_dir / "workspaces" / "tester-run-pack_create-output-a601a9c1"
    assert (task_workspace / "fresh.txt").exists()
