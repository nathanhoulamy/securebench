import json

from securebench.candidates import CandidateArtifact, CandidateProductionTimeout
from securebench.sandboxes import CommandResult
from securebench.harnesses.shared import workspace_dir_name
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
    def verify(self, task, candidate):
        assert task.task_type == "code_completion"
        assert candidate == "def add_numbers(a, b):\n    return a + b\n"
        return VerificationResult(
            task_id=task.id,
            status="passed",
            passed=True,
            score=1.0,
            stdout="tests passed",
            metadata={"exit_code": 0},
        )


def write_pack(tmp_path, *, family="code_completion"):
    manifest = tmp_path / "manifest.yaml"
    tasks = tmp_path / "tasks.jsonl"
    manifest.write_text(
        f"""
id: tester-run-pack
version: 1
defaults:
  family: {family}
  environment:
    image: python:3.12-slim
"""
    )
    tasks.write_text(
        json.dumps(
            {
                "id": "tester-run-pack/add_numbers",
                "input": {
                    "language": "python",
                    "prompt": "# define add_numbers\n",
                },
                "eval": {
                    "tests": {
                        "source": "inline",
                        "code": "def check():\n    assert add_numbers(2, 3) == 5\n\ncheck()\n",
                    },
                    "canonical_solution": "def add_numbers(a, b):\n    return a + b\n",
                },
            }
        )
        + "\n"
    )
    return manifest, tasks


def write_multiple_choice_pack(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    tasks = tmp_path / "tasks.jsonl"
    manifest.write_text(
        """
id: tester-run-pack
version: 1
defaults:
  family: multiple_choice
"""
    )
    tasks.write_text(
        json.dumps(
            {
                "id": "tester-run-pack/addition",
                "input": {
                    "question": "2 + 2?",
                    "choices": ["1", "2", "4", "5"],
                },
                "eval": {
                    "answer": 2,
                },
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


def test_run_tester_config_writes_verified_code_completion_record(monkeypatch, tmp_path):
    manifest, tasks = write_pack(tmp_path)
    config = make_config(tmp_path, manifest, tasks)

    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: FakeProducer(
            CandidateArtifact(
                text="def add_numbers(a, b):\n    return a + b\n",
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
    assert records[0]["verification_status"] == "passed"
    assert records[0]["passed"] is True
    assert records[0]["score"] == 1.0
    assert records[0]["verifier_stdout"] == "tests passed"
    assert records[0]["verifier_metadata"] == {"exit_code": 0}
    assert records[0]["hidden_values"] == "<redacted>"


def test_run_tester_config_verifies_multiple_choice_record(monkeypatch, tmp_path):
    manifest, tasks = write_multiple_choice_pack(tmp_path)
    config = make_config(tmp_path, manifest, tasks)

    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: FakeProducer(
            CandidateArtifact(
                text="Final answer is C",
                stdout="producer out",
                metadata={"harness": "fake"},
            )
        ),
    )

    summary = run_tester_config(config)

    assert summary.total == 1
    assert summary.verified == 1
    assert summary.passed == 1
    assert summary.score_sum == 1.0
    records = [
        json.loads(line)
        for line in (tmp_path / "out" / "candidates.jsonl").read_text().splitlines()
    ]
    assert records[0]["verification_status"] == "passed"
    assert records[0]["passed"] is True
    assert records[0]["score"] == 1.0
    assert records[0]["verifier_metadata"]["verifier"] == "multiple_choice"
    assert records[0]["verifier_metadata"]["expected_answer"] == "<redacted>"
    assert records[0]["hidden_values"] == "<redacted>"


def test_run_tester_config_leaves_unsupported_family_pending(monkeypatch, tmp_path):
    manifest, tasks = write_pack(tmp_path, family="custom_family")
    config = make_config(tmp_path, manifest, tasks)

    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: FakeProducer(CandidateArtifact(text="done")),
    )
    monkeypatch.setattr("securebench.tester_run.verifier_for_task_type", lambda task_type: None)

    summary = run_tester_config(config)

    assert summary.total == 1
    assert summary.verified == 0
    assert summary.verification_status == "pending"
    records = [json.loads(line) for line in (tmp_path / "out" / "candidates.jsonl").read_text().splitlines()]
    assert records[0]["verification_status"] == "pending"
    assert "passed" not in records[0]


def test_run_tester_config_records_producer_timeout_as_failed_result(monkeypatch, tmp_path):
    manifest, tasks = write_multiple_choice_pack(tmp_path)
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
    manifest, tasks = write_multiple_choice_pack(tmp_path)
    config = make_config(tmp_path, manifest, tasks)
    config.run.output_dir.mkdir(parents=True)
    existing = {
        "run_id": "tester-run",
        "task_id": "tester-run-pack/addition",
        "benchmark_id": "tester-run-pack",
        "task_type": "multiple_choice",
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
    manifest, tasks = write_pack(tmp_path)
    config = make_config(tmp_path, manifest, tasks)

    class Producer:
        def __init__(self, workspace_root):
            self.workspace_root = workspace_root

        def produce(self, task):
            task_workspace = self.workspace_root / workspace_dir_name(task)
            assert not (task_workspace / "securebench" / "evaluation_inputs" / "checker.json").exists()
            task_workspace.mkdir(parents=True)
            (task_workspace / "fresh.txt").write_text("fresh")
            return CandidateArtifact(text="def add_numbers(a, b):\n    return a + b\n")

    def fake_producer(harness, workspace_root=None):
        assert workspace_root is not None
        stale_workspace = workspace_root / "tester-run-pack_add_numbers-9e7c852a"
        (stale_workspace / "securebench" / "evaluation_inputs").mkdir(parents=True)
        (stale_workspace / "securebench" / "evaluation_inputs" / "checker.json").write_text("{}")
        return Producer(workspace_root)

    monkeypatch.setattr("securebench.tester_run.build_harness_producer", fake_producer)
    monkeypatch.setattr("securebench.tester_run.verifier_for_task_type", lambda task_type: FakeVerifier())

    run_tester_config(config)

    task_workspace = config.run.output_dir / "workspaces" / "tester-run-pack_add_numbers-9e7c852a"
    assert (task_workspace / "fresh.txt").exists()
