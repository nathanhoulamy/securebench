import json

from securebench.candidates import CandidateArtifact
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


def make_config(tmp_path, manifest, tasks):
    return Config(
        schema_version="0.2",
        run=RunSection(id="tester-run", output_dir=tmp_path / "out"),
        benchmark=BenchmarkSection(manifest=manifest, tasks=tasks),
        harness=HarnessSection(type="command", mode="host", config={"command": "ignored"}),
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


def test_run_tester_config_leaves_unsupported_family_pending(monkeypatch, tmp_path):
    manifest, tasks = write_pack(tmp_path, family="terminal_task")
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
