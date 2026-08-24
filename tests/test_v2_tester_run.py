import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import securebench.execution_profiles as execution_profiles
from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateProduction,
    CandidateProductionError,
    CandidateProductionTimeout,
    CandidateStore,
    OverlayAgentCaptureResult,
    StoredCandidate,
)
from securebench.errors import ConfigError
from securebench.harnesses.shared import workspace_dir_name
from securebench.locking import exclusive_file_lock
from securebench.sandboxes import CommandResult
from securebench.tester_config import (
    TesterBenchmarkSection as BenchmarkSection,
    TesterConfig as RunConfig,
    TesterDockerSection as DockerSection,
    TesterHarnessSection as HarnessSection,
    TesterRunSection as RunSection,
)
from securebench.tester_run import (
    MAX_RESULT_RECORD_BYTES,
    RUN_LOCK_FILENAME,
    _bounded_result_record,
    _encode_record,
    _reset_task_workspace,
    _resume_candidate_available,
    _resume_records,
    _validate_overlay_workspace_capacity,
    execution_config_digest,
    run_tester_config,
)
from securebench.schemas.benchmark import ArtifactSource, FilesystemOverlayCandidate
from securebench.verification import CheckResultSummary, VerificationEngine
from securebench.workspaces.overlay_quota import (
    OverlayWorkspaceCapabilities,
    OverlayWorkspaceUnavailable,
)


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
    assert record["schema_version"] == "3"
    assert record["provenance"]["execution_digest"] == execution_config_digest(current)
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

    monkeypatch.setattr("securebench.workspaces.cleanup.shutil.rmtree", fake_rmtree)
    monkeypatch.setattr("securebench.workspaces.cleanup.subprocess.run", fake_run)

    _reset_task_workspace(workspace_root, task)

    cleanup_run = calls["docker"][0]
    assert task.environment.image in cleanup_run
    assert ["--network", "none"] == cleanup_run[
        cleanup_run.index("--network") : cleanup_run.index("--network") + 2
    ]
    assert ["--cap-add", "DAC_OVERRIDE"] == cleanup_run[
        cleanup_run.index("--cap-add") : cleanup_run.index("--cap-add") + 2
    ]
    assert ["--user", "0:0"] == cleanup_run[
        cleanup_run.index("--user") : cleanup_run.index("--user") + 2
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


def test_repo_patch_runner_captures_verifies_persists_cleans_and_resumes(
    monkeypatch,
    tmp_path,
):
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=baseline, check=True)
    subprocess.run(
        ["git", "config", "user.email", "securebench@example.invalid"],
        cwd=baseline,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "SecureBench"], cwd=baseline, check=True
    )
    (baseline / "README.md").write_text("baseline\n")
    subprocess.run(["git", "add", "."], cwd=baseline, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "baseline"], cwd=baseline, check=True
    )
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=baseline,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    pack = tmp_path / "repo-pack"
    (pack / "assets").mkdir(parents=True)
    (pack / "evaluation_inputs").mkdir()
    oracle_root = pack / "hidden" / "task" / "oracle"
    oracle_root.mkdir(parents=True)
    (oracle_root / "oracle.yaml").write_text(
        "abi: securebench.oracle/v1\n"
        "command: ['{python}', 'oracle.py']\n"
        "timeout_seconds: 5\n"
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
                "public_diagnostics": {},
            },
        }), flush=True)
""".lstrip()
    )
    (pack / "manifest.yaml").write_text(
        """
schema_version: "2.0"
id: repo-runner-pack
defaults:
  family: repo_patch
  environment:
    image: sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
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
        "id": "repo/task",
        "input": {
            "repo": "example/repository",
            "base_commit": base_commit,
            "instructions": "Write result.json.",
        },
        "verification": {
            "execution_profile": "strict-split/v1",
            "candidate": {
                "type": "git_patch",
                "max_patch_bytes": 4096,
                "max_changed_files": 1,
                "max_changed_bytes": 1024,
                "allow_paths": ["result.json"],
            },
            "resources": {"host": {"oracle": {"path": "task/oracle"}}},
            "checks": [
                {
                    "id": "result_artifact",
                    "type": "artifact",
                    "artifacts": [
                        {
                            "id": "result",
                            "source": {"path": "result.json"},
                            "parser": "securebench.strict-json/v1",
                            "limits": {"max_bytes": 1024},
                        }
                    ],
                }
            ],
            "oracle": "host.oracle",
        },
    }
    (pack / "tasks.jsonl").write_text(json.dumps(row) + "\n")
    current = RunConfig(
        schema_version="1.0",
        run=RunSection(id="repo-runner", output_dir=tmp_path / "repo-run"),
        benchmark=BenchmarkSection(
            manifest=pack / "manifest.yaml",
            tasks=pack / "tasks.jsonl",
        ),
        harness=HarnessSection(type="command", config={"command": "ignored"}),
    )

    class RepoProducer:
        def __init__(self):
            self.calls = 0

        def produce(self, task):
            self.calls += 1
            workspace = current.run.output_dir / "workspaces" / workspace_dir_name(task)
            subprocess.run(
                ["git", "clone", "--quiet", str(baseline), str(workspace)], check=True
            )
            (workspace / "result.json").write_text('{"answer":42}\n')
            return CandidateProduction(workspace=str(workspace))

    producer = RepoProducer()

    def materialize(_task, destination):
        subprocess.run(
            ["git", "clone", "--quiet", str(baseline), str(destination)], check=True
        )

    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: producer,
    )
    monkeypatch.setattr("securebench.harnesses.shared.materialize_image_workdir", materialize)
    monkeypatch.setattr(
        "securebench.verification.artifacts.remove_untrusted_tree",
        lambda path, *, image: shutil.rmtree(path),
    )

    first = run_tester_config(current)
    second = run_tester_config(current, resume=True)
    record = json.loads(Path(first.output_path).read_text())
    task = next(
        compile_benchmark_pack(
            load_benchmark_pack(current.benchmark.manifest, current.benchmark.tasks)
        )
    )

    assert first.passed == second.passed == 1
    assert producer.calls == 1
    assert record["candidate"]["type"] == "git_patch"
    assert record["candidate"]["digest"].startswith("sha256:")
    assert record["provenance"]["baseline_digest"] == task.baseline_digest
    assert not (
        current.run.output_dir / "workspaces" / workspace_dir_name(task)
    ).exists()


def test_runner_resume_reexecutes_after_harness_config_changes(monkeypatch, tmp_path):
    current = config(tmp_path)
    producer = GoodProducer(current.run.output_dir / "workspaces")
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: producer,
    )
    run_tester_config(current)
    changed = replace(
        current,
        harness=replace(current.harness, config={"command": "different"}),
    )

    run_tester_config(changed, resume=True)

    assert producer.calls == 2
    record = json.loads(Path(current.run.output_dir / "results.jsonl").read_text())
    assert record["provenance"]["execution_digest"] == execution_config_digest(changed)


def test_runner_resume_reexecutes_after_overlay_workspace_capacity_changes(
    monkeypatch,
    tmp_path,
):
    current = replace(
        config(tmp_path),
        docker=DockerSection(overlay_workspace_bytes=2 * 1024 * 1024 * 1024),
    )
    producer = GoodProducer(current.run.output_dir / "workspaces")
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: producer,
    )
    first_digest = execution_config_digest(current)
    run_tester_config(current)
    changed = replace(
        current,
        docker=replace(
            current.docker,
            overlay_workspace_bytes=3 * 1024 * 1024 * 1024,
        ),
    )

    run_tester_config(changed, resume=True)

    assert producer.calls == 2
    assert execution_config_digest(changed) != first_digest


def test_resume_accepts_a_fully_validated_filesystem_overlay_candidate(tmp_path):
    store = CandidateStore(tmp_path / "store")
    baseline_digest = "sha256:" + "1" * 64
    empty_tree_digest = "sha256:" + "2" * 64
    candidate = store.put_candidate(
        "filesystem_overlay",
        baseline_digest,
        {
            "format": "securebench.filesystem-overlay/v1",
            "roots": [
                {
                    "path": "/app",
                    "baseline_tree_digest": empty_tree_digest,
                    "baseline_entries": 0,
                    "baseline_bytes": 0,
                    "final_tree_digest": empty_tree_digest,
                    "final_entries": 0,
                    "final_bytes": 0,
                }
            ],
            "changes": [],
            "changed_paths": 0,
            "changed_bytes": 0,
        },
    )

    assert _resume_candidate_available(
        {
            "candidate": {
                "type": "filesystem_overlay",
                "digest": candidate.digest,
            }
        },
        {"baseline_digest": baseline_digest, "base_commit": None},
        store,
    )


def test_overlay_rows_require_a_tester_owned_workspace_capacity(tmp_path):
    current = config(tmp_path)
    compiled = next(
        compile_benchmark_pack(
            load_benchmark_pack(current.benchmark.manifest, current.benchmark.tasks)
        )
    )
    overlay = FilesystemOverlayCandidate.model_validate(
        {
            "type": "filesystem_overlay",
            "include_roots": ["/app"],
            "max_changed_paths": 10,
            "max_changed_bytes": 1024,
        }
    )
    verification = compiled.verification.model_copy(update={"candidate": overlay})
    overlay_task = replace(compiled, verification=verification)

    with pytest.raises(ConfigError, match="overlay_workspace_bytes is required"):
        _validate_overlay_workspace_capacity(current, [overlay_task])

    configured = replace(
        current,
        docker=DockerSection(overlay_workspace_bytes=2 * 1024 * 1024 * 1024),
    )
    _validate_overlay_workspace_capacity(configured, [overlay_task])


def _overlay_task_for_capability_gate(current):
    compiled = next(
        compile_benchmark_pack(
            load_benchmark_pack(current.benchmark.manifest, current.benchmark.tasks)
        )
    )
    candidate = FilesystemOverlayCandidate.model_validate(
        {
            "type": "filesystem_overlay",
            "include_roots": ["/app"],
            "max_changed_paths": 10,
            "max_changed_bytes": 1024,
        }
    )
    check = compiled.verification.checks[0]
    artifact = check.artifacts[0].model_copy(
        update={"source": ArtifactSource(path="/app/meeting_scheduled.ics")}
    )
    verification = compiled.verification.model_copy(
        update={
            "candidate": candidate,
            "checks": (check.model_copy(update={"artifacts": (artifact,)}),),
        }
    )
    return replace(compiled, verification=verification)


def _overlay_run_config(tmp_path):
    return replace(
        config(tmp_path),
        docker=DockerSection(overlay_workspace_bytes=2 * 1024 * 1024 * 1024),
    )


def test_overlay_public_path_remains_disabled_until_native_qualification(
    monkeypatch,
    tmp_path,
):
    current = _overlay_run_config(tmp_path)
    task = _overlay_task_for_capability_gate(current)
    monkeypatch.setattr(
        "securebench.tester_run.compile_benchmark_pack",
        lambda pack, limit=None: iter((task,)),
    )
    monkeypatch.setattr(
        "securebench.tester_run.probe_overlay_workspace_backend",
        lambda **options: pytest.fail("disabled overlay must not probe the host"),
    )
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda *args, **kwargs: pytest.fail("disabled overlay must not start an Agent"),
    )

    with pytest.raises(ConfigError, match="native-Linux qualification"):
        run_tester_config(current)


def test_qualified_overlay_gate_probes_once_before_agent_execution(monkeypatch, tmp_path):
    current = _overlay_run_config(tmp_path)
    task = _overlay_task_for_capability_gate(current)
    events = []
    candidate = StoredCandidate(
        type="filesystem_overlay",
        digest="sha256:" + "a" * 64,
        manifest_path=tmp_path / "candidate.json",
        baseline_digest=task.baseline_digest,
    )

    def probe(*, storage_root):
        events.append(("probe", storage_root))
        return OverlayWorkspaceCapabilities("Linux", "linux", "overlay2")

    class Producer:
        def capture_filesystem_overlay(self, selected, **options):
            events.append(("agent", options["storage_root"]))
            return OverlayAgentCaptureResult(
                candidate=candidate,
                agent_result=CommandResult(command=("agent",), exit_code=0),
            )

    def fake_verify(self, selected, stored, store, *, run_seed):
        return self.infrastructure_error(
            selected,
            code="test_verification",
            message="verification intentionally stubbed",
            candidate=stored,
        )

    monkeypatch.setattr(
        execution_profiles,
        "FILESYSTEM_OVERLAY_NATIVE_QUALIFICATION_COMPLETE",
        True,
    )
    monkeypatch.setattr(
        "securebench.tester_run.compile_benchmark_pack",
        lambda pack, limit=None: iter((task,)),
    )
    monkeypatch.setattr("securebench.tester_run.probe_overlay_workspace_backend", probe)
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: Producer(),
    )
    monkeypatch.setattr(VerificationEngine, "verify", fake_verify)

    summary = run_tester_config(current)

    assert summary.infrastructure_errors == 1
    assert [event[0] for event in events] == ["probe", "agent"]
    assert events[0][1] == events[1][1]


def test_unsupported_overlay_host_fails_before_agent_execution(monkeypatch, tmp_path):
    current = _overlay_run_config(tmp_path)
    task = _overlay_task_for_capability_gate(current)
    events = []

    def unsupported(*, storage_root):
        events.append("probe")
        raise OverlayWorkspaceUnavailable("unsupported Docker storage driver")

    monkeypatch.setattr(
        execution_profiles,
        "FILESYSTEM_OVERLAY_NATIVE_QUALIFICATION_COMPLETE",
        True,
    )
    monkeypatch.setattr(
        "securebench.tester_run.compile_benchmark_pack",
        lambda pack, limit=None: iter((task,)),
    )
    monkeypatch.setattr(
        "securebench.tester_run.probe_overlay_workspace_backend",
        unsupported,
    )
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda *args, **kwargs: events.append("agent"),
    )

    with pytest.raises(ConfigError, match="capability preflight.*storage driver"):
        run_tester_config(current)

    assert events == ["probe"]


def test_overlay_gate_rejects_unexpected_probe_facts_before_agent(monkeypatch, tmp_path):
    current = _overlay_run_config(tmp_path)
    task = _overlay_task_for_capability_gate(current)
    events = []

    def malformed(*, storage_root):
        events.append("probe")
        return OverlayWorkspaceCapabilities("Linux", "linux", "btrfs")

    monkeypatch.setattr(
        execution_profiles,
        "FILESYSTEM_OVERLAY_NATIVE_QUALIFICATION_COMPLETE",
        True,
    )
    monkeypatch.setattr(
        "securebench.tester_run.compile_benchmark_pack",
        lambda pack, limit=None: iter((task,)),
    )
    monkeypatch.setattr(
        "securebench.tester_run.probe_overlay_workspace_backend",
        malformed,
    )
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda *args, **kwargs: events.append("agent"),
    )

    with pytest.raises(ConfigError, match="unsupported host facts"):
        run_tester_config(current)

    assert events == ["probe"]


def test_runner_resume_reexecutes_after_agent_environment_changes(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_SETTING", "first")
    current = replace(
        config(tmp_path),
        harness=HarnessSection(
            type="command",
            env=("AGENT_SETTING",),
            config={"command": "ignored"},
        ),
    )
    producer = GoodProducer(current.run.output_dir / "workspaces")
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: producer,
    )
    run_tester_config(current)
    monkeypatch.setenv("AGENT_SETTING", "second")

    run_tester_config(current, resume=True)

    assert producer.calls == 2


def test_execution_digest_excludes_provider_credentials_filtered_from_agent(monkeypatch, tmp_path):
    current = replace(
        config(tmp_path),
        harness=HarnessSection(
            type="codex",
            env=("OPENAI_API_KEY", "AGENT_SETTING"),
            config={"model": "gpt-test"},
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "first-secret")
    monkeypatch.setenv("AGENT_SETTING", "stable")
    initial = execution_config_digest(current)

    monkeypatch.setenv("OPENAI_API_KEY", "second-secret")
    assert execution_config_digest(current) == initial

    monkeypatch.setenv("AGENT_SETTING", "changed")
    assert execution_config_digest(current) != initial


def test_runner_resume_skips_oversized_corrupt_lines_without_buffering_them(
    monkeypatch,
    tmp_path,
):
    current = config(tmp_path)
    producer = GoodProducer(current.run.output_dir / "workspaces")
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: producer,
    )
    first = run_tester_config(current)
    output = Path(first.output_path)
    valid = output.read_bytes()
    output.write_bytes(b"x" * (MAX_RESULT_RECORD_BYTES * 2) + b"\n" + valid)

    run_tester_config(current, resume=True)

    assert producer.calls == 1
    assert len(output.read_text().splitlines()) == 1


@pytest.mark.parametrize("corruption", ["duplicate_key", "nul_padding", "huge_score"])
def test_runner_resume_reexecutes_for_noncanonical_or_invalid_records(
    monkeypatch,
    tmp_path,
    corruption,
):
    current = config(tmp_path)
    producer = GoodProducer(current.run.output_dir / "workspaces")
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: producer,
    )
    first = run_tester_config(current)
    output = Path(first.output_path)
    record = json.loads(output.read_text())
    if corruption == "duplicate_key":
        encoded = _encode_record(record).replace(
            '"run_id":"runner-v2"',
            '"run_id":"runner-v2","run_id":"runner-v2"',
            1,
        )
    elif corruption == "nul_padding":
        encoded = _encode_record(record).rstrip("\n") + "\x00\n"
    else:
        record["score"] = 10**400
        encoded = _encode_record(record)
    output.write_text(encoded)

    run_tester_config(current, resume=True)

    assert producer.calls == 2
    assert len(output.read_text().splitlines()) == 1


def test_result_writer_replaces_oversized_record_with_bounded_infrastructure_error():
    task = next(
        compile_benchmark_pack(
            load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
        )
    )
    result = VerificationEngine().infrastructure_error(
        task,
        code="original_error",
        message="original error",
    )
    oversized = replace(
        result,
        checks=tuple(
            CheckResultSummary(
                id=f"check-{index}",
                type="artifact",
                status="failed",
                evidence_digests=("sha256:" + "a" * 64,),
            )
            for index in range(3000)
        ),
    )

    bounded, record = _bounded_result_record(
        oversized,
        run_id="run",
        execution_digest="sha256:" + "b" * 64,
    )

    assert bounded.infrastructure_error["code"] == "result_record_too_large"
    assert record["checks"] == []
    assert len(_encode_record(record).encode("utf-8")) <= MAX_RESULT_RECORD_BYTES


def test_runner_rejects_concurrent_use_of_one_output_directory(monkeypatch, tmp_path):
    current = config(tmp_path)
    current.run.output_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "securebench.tester_run.build_harness_producer",
        lambda harness, workspace_root=None: pytest.fail("producer must not be built"),
    )

    with exclusive_file_lock(current.run.output_dir / RUN_LOCK_FILENAME):
        with pytest.raises(ConfigError, match="another SecureBench run"):
            run_tester_config(current)


def test_runner_rejects_output_directory_inside_benchmark_pack(tmp_path):
    current = config(tmp_path)
    forbidden = PACK / ".securebench-forbidden-output"
    changed = replace(current, run=replace(current.run, output_dir=forbidden))

    with pytest.raises(ConfigError, match="outside the benchmark pack"):
        run_tester_config(changed)

    assert not forbidden.exists()


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


def test_resume_rejects_git_patch_manifest_for_another_base_commit(tmp_path):
    store = CandidateStore(tmp_path / "store")
    patch_blob = store.put_blob(b"")
    candidate = store.put_candidate(
        "git_patch",
        "sha256:" + "1" * 64,
        {
            "patch_blob": patch_blob,
            "patch_bytes": 0,
            "changed_files": [],
            "changed_bytes": 0,
            "base_commit": "b" * 40,
        },
    )

    assert not _resume_candidate_available(
        {
            "candidate": {
                "type": "git_patch",
                "digest": candidate.digest,
            }
        },
        {
            "baseline_digest": "sha256:" + "1" * 64,
            "base_commit": "a" * 40,
        },
        store,
    )


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
        "schema_version": "3",
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
            "execution_digest": execution_config_digest(current),
        },
        "checks": [],
        "public_diagnostics": {},
    }
    output = tmp_path / "results.jsonl"
    output.write_text(json.dumps(record) + "\n")
    changed = replace(task, verification_digest="sha256:" + "0" * 64)

    assert _resume_records(
        output,
        current.run.id,
        [changed],
        CandidateStore(tmp_path / "store"),
        execution_digest=execution_config_digest(current),
    ) == []


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
