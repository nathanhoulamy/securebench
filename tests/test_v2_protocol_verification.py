from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateStore,
    HostWorkspaceFilesystem,
    capture_file_bundle,
    capture_git_patch_workspace,
)
from securebench.errors import ConfigError
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.shared import materialize_image_workdir
from securebench.sandboxes import CommandResult
from securebench.schemas.benchmark import ArtifactCheck, ProtocolCheck, VerificationSpec
from securebench.verification import OracleSession, OracleVerdict, VerificationEngine
from securebench.verification.json_data import json_digest
from securebench.verification.models import (
    OracleCase,
    ProtocolCaseEvidence,
    VerificationInfrastructureError,
)
from securebench.verification.oracle import OracleProcessSession
from securebench.verification.protocol import (
    _adapter_evidence,
    _validated_challenge,
    load_adapter_manifest,
)


DIGEST = "sha256:" + "d" * 64


class ProtocolOracle(OracleSession):
    def __init__(self, cases: list[OracleCase]) -> None:
        self.pending = list(cases)
        self.evidence = []
        self.contexts = []
        self.next_calls = 0

    def initialize(self, task, *, run_seed):
        self.seed = run_seed

    def evaluate_artifact(self, evidence):
        raise AssertionError("artifact evidence was not expected")

    def next_case(self, check_id, challenge_source, bounds):
        assert check_id == "behavior"
        assert challenge_source == "host.cases"
        assert bounds == {"max_cases": 2, "max_case_bytes": 1024}
        self.next_calls += 1
        return self.pending.pop(0) if self.pending else None

    def evaluate_case(self, check_id, case_context, evidence):
        self.contexts.append(case_context)
        self.evidence.append(evidence)

    def finalize(self):
        passed = bool(self.evidence) and all(item.status == "observed" for item in self.evidence)
        return OracleVerdict(
            passed=passed,
            score=1.0 if passed else 0.0,
            check_outcomes={"behavior": passed},
        )

    def close(self):
        pass


def write_protocol_pack(
    root: Path,
    *,
    image: str = DIGEST,
    adapter_mount: str = "/opt/securebench/adapter",
    base_commit: str | None = None,
):
    (root / "assets" / "task").mkdir(parents=True)
    adapter = root / "evaluation_inputs" / "task" / "adapter"
    adapter.mkdir(parents=True)
    (root / "hidden" / "task" / "oracle").mkdir(parents=True)
    (root / "hidden" / "task" / "cases").mkdir(parents=True)
    (root / "assets" / "task" / "public.txt").write_text("public")
    (root / "hidden" / "task" / "oracle" / "oracle.yaml").write_text(
        "abi: securebench.oracle/v1\n"
        "command: ['{python}', 'oracle.py']\n"
        "timeout_seconds: 30\n"
    )
    (adapter / "adapter.yaml").write_text(
        """
format: securebench.adapter/v2
protocol: securebench.example/v1
command: ["python3", "./adapter.py"]
challenge_schema:
  type: object
  properties:
    value: {type: integer}
  required: [value]
  max_fields: 1
observation_schema:
  type: object
  properties:
    answer: {type: integer}
    candidate: {type: string, max_utf8_bytes: 1024}
  required: [answer, candidate]
  max_fields: 2
evaluation_participants:
  - {name: candidate, type: candidate, instances: 1}
maximums:
  seconds_per_challenge: 2
  challenge_bytes: 1024
  observation_bytes: 1024
""".lstrip()
    )
    (adapter / "adapter.py").write_text(
        """
import json
import sys
from pathlib import Path

request = json.load(sys.stdin)
print(json.dumps({
    "format": "securebench.adapter-response/v2",
    "status": "observed",
    "observation": {
        "candidate": Path("/app/answer.txt").read_text(),
        "answer": request["challenge"]["value"] * 2,
    },
}))
""".lstrip()
    )
    manifest = root / "manifest.yaml"
    manifest.write_text(
        f"""
schema_version: "2.0"
id: protocol-pack
defaults:
  family: {"repo_patch" if base_commit is not None else "terminal_task"}
  environment:
    image: {image}
    workdir: /app
    timeout_seconds: 30
    agent_network: none
resource_roots:
  public: assets/
  runtime: evaluation_inputs/
  host: hidden/
""".lstrip()
    )
    candidate = (
        {
            "type": "git_patch",
            "max_patch_bytes": 4096,
            "max_changed_files": 2,
            "max_changed_bytes": 1024,
            "allow_paths": ["answer.txt"],
        }
        if base_commit is not None
        else {
            "type": "file_bundle",
            "max_total_files": 1,
            "max_total_bytes": 1024,
            "files": [
                {
                    "id": "answer",
                    "path": "/app/answer.txt",
                    "kind": "regular_file",
                    "max_bytes": 1024,
                }
            ],
        }
    )
    task_input = (
        {
            "repo": "example/repository",
            "base_commit": base_commit,
            "instructions": "Write /app/answer.txt.",
        }
        if base_commit is not None
        else {"instructions": "Write /app/answer.txt."}
    )
    row = {
        "id": "protocol/task",
        "input": task_input,
        "assets": [
            {"path": "task/public.txt", "mount": "/opt/securebench/public.txt", "read_only": True}
        ],
        "verification": {
            "execution_profile": "strict-split/v1",
            "candidate": candidate,
            "resources": {
                "runtime": {
                    "adapter": {"path": "task/adapter", "mount": adapter_mount}
                },
                "host": {
                    "cases": {"path": "task/cases"},
                    "oracle": {"path": "task/oracle"},
                },
            },
            "checks": [
                {
                    "id": "behavior",
                    "type": "protocol",
                    "adapter": "runtime.adapter",
                    "protocol": "securebench.example/v1",
                    "challenge": {
                        "source": "host.cases",
                        "max_cases": 2,
                        "max_case_bytes": 1024,
                    },
                    "limits": {
                        "seconds_per_case": 2,
                        "observation_bytes_per_case": 1024,
                    },
                }
            ],
            "oracle": "host.oracle",
        },
    }
    tasks = root / "tasks.jsonl"
    tasks.write_text(json.dumps(row) + "\n")
    return next(compile_benchmark_pack(load_benchmark_pack(manifest, tasks)))


def capture_answer(root: Path, task):
    workspace = root / "agent-workspace"
    workspace.mkdir()
    (workspace / "answer.txt").write_text("candidate-state")
    store = CandidateStore(root / "candidate-store")
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
    )
    return store, candidate


def make_git_baseline(root: Path) -> tuple[Path, str]:
    root.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "securebench@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "SecureBench"], cwd=root, check=True
    )
    (root / "README.md").write_text("baseline\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "baseline"], cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return root, commit


def test_git_patch_protocol_case_replays_into_fresh_repository(tmp_path, monkeypatch):
    baseline, base_commit = make_git_baseline(tmp_path / "baseline")
    task = write_protocol_pack(tmp_path / "pack", base_commit=base_commit)
    validate_executable_task(task)
    workspace = tmp_path / "agent-workspace"
    subprocess.run(["git", "clone", "--quiet", str(baseline), str(workspace)], check=True)
    (workspace / "answer.txt").write_text("candidate-state")
    store = CandidateStore(tmp_path / "candidate-store")
    candidate = capture_git_patch_workspace(
        workspace,
        baseline,
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
        base_commit=base_commit,
    )
    roots: list[Path] = []

    def materialize(_task, destination):
        subprocess.run(
            ["git", "clone", "--quiet", str(baseline), str(destination)],
            check=True,
        )

    class FakeDockerSandbox:
        def __init__(self, **kwargs):
            self.root = Path(kwargs["root"])
            roots.append(self.root)

        def run(self, command, *, workdir, timeout, stdin):
            assert (self.root / "answer.txt").read_text() == "candidate-state"
            assert subprocess.run(
                ["git", "diff", "--quiet", base_commit], cwd=self.root
            ).returncode == 1
            request = json.loads(stdin)
            return CommandResult(
                command=tuple(command),
                exit_code=0,
                stdout=json.dumps(
                    {
                        "format": "securebench.adapter-response/v2",
                        "status": "observed",
                        "observation": {
                            "candidate": "candidate-state",
                            "answer": request["challenge"]["value"] * 2,
                        },
                    }
                ),
            )

        def close(self):
            pass

    monkeypatch.setattr("securebench.harnesses.shared.materialize_image_workdir", materialize)
    monkeypatch.setattr("securebench.verification.protocol.DockerSandbox", FakeDockerSandbox)
    monkeypatch.setattr(
        "securebench.verification.protocol.remove_untrusted_tree",
        lambda path, *, image: shutil.rmtree(path),
    )
    oracle = ProtocolOracle([OracleCase({"value": 5}, {"expected": 10})])

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="repo-protocol-seed",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert oracle.evidence[0].observation == {
        "candidate": "candidate-state",
        "answer": 10,
    }
    assert len(roots) == 1 and not roots[0].exists()


def test_protocol_cases_use_fresh_evaluation_roots_and_sanitized_results(tmp_path, monkeypatch):
    task = write_protocol_pack(tmp_path / "pack")
    validate_executable_task(task)
    store, candidate = capture_answer(tmp_path, task)
    roots: list[Path] = []
    commands = []
    inputs = []

    def materialize_baseline(_task, destination):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "answer.txt").write_text("baseline-state")

    class FakeDockerSandbox:
        def __init__(self, **kwargs):
            self.root = Path(kwargs["root"])
            self.mounts = kwargs["mounts"]
            assert kwargs["persistent"] is False
            assert kwargs["network"] == "none"
            assert kwargs["read_only"] is True
            roots.append(self.root)

        def run(self, command, *, workdir, timeout, stdin):
            commands.append(tuple(command))
            inputs.append(json.loads(stdin))
            assert workdir == "/app"
            assert timeout == 2
            assert (self.root / "answer.txt").read_text() == "candidate-state"
            assert (self.root / "securebench" / "public" / "input.instructions.json").exists()
            assert not (self.root / "securebench" / "hidden").exists()
            assert {mount.target for mount in self.mounts} == {
                "/opt/securebench/public.txt",
                "/opt/securebench/adapter",
            }
            return CommandResult(
                command=tuple(command),
                exit_code=0,
                stdout=json.dumps(
                    {
                        "format": "securebench.adapter-response/v2",
                        "status": "observed",
                        "observation": {
                            "candidate": "candidate-state",
                            "answer": inputs[-1]["challenge"]["value"] * 2,
                        },
                    }
                ),
            )

        def close(self):
            pass

    monkeypatch.setattr("securebench.harnesses.shared.materialize_image_workdir", materialize_baseline)
    monkeypatch.setattr("securebench.verification.protocol.DockerSandbox", FakeDockerSandbox)
    monkeypatch.setattr(
        "securebench.verification.protocol.remove_untrusted_tree",
        lambda path, *, image: shutil.rmtree(path),
    )
    oracle = ProtocolOracle(
        [
            OracleCase({"value": 2}, {"expected": 4, "host_secret": "first-secret"}),
            OracleCase({"value": 3}, {"expected": 6, "host_secret": "second-secret"}),
        ]
    )

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="protocol-seed",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert len(roots) == 2 and roots[0] != roots[1]
    assert not any(root.exists() for root in roots)
    assert commands == [
        ("python3", "/opt/securebench/adapter/adapter.py"),
        ("python3", "/opt/securebench/adapter/adapter.py"),
    ]
    assert [request["challenge"] for request in inputs] == [{"value": 2}, {"value": 3}]
    assert all(request["format"] == "securebench.adapter-request/v2" for request in inputs)
    assert oracle.contexts[0]["host_secret"] == "first-secret"
    assert oracle.evidence[0].observation == {
        "candidate": "candidate-state",
        "answer": 4,
    }
    assert result.checks[0].cases == 2
    encoded = json.dumps(result.to_record(run_id="run", execution_digest=DIGEST))
    assert "first-secret" not in encoded
    assert '"answer": 4' not in encoded


def test_adapter_uses_typed_envelopes_and_host_owned_evaluation_ids(
    tmp_path,
    monkeypatch,
):
    task = write_protocol_pack(tmp_path / "pack")
    validate_executable_task(task)
    store, candidate = capture_answer(tmp_path, task)
    requests = []

    def materialize_baseline(_task, destination):
        destination.mkdir(parents=True, exist_ok=True)

    class FakeDockerSandbox:
        def __init__(self, **kwargs):
            self.root = Path(kwargs["root"])

        def run(self, command, *, workdir, timeout, stdin):
            request = json.loads(stdin)
            requests.append(request)
            return CommandResult(
                command=tuple(command),
                exit_code=0,
                stdout=json.dumps(
                    {
                        "format": "securebench.adapter-response/v2",
                        "status": "observed",
                        "observation": {
                            "candidate": "candidate-state",
                            "answer": request["challenge"]["value"] * 2,
                        },
                    }
                ),
            )

        def close(self):
            pass

    monkeypatch.setattr(
        "securebench.harnesses.shared.materialize_image_workdir", materialize_baseline
    )
    monkeypatch.setattr("securebench.verification.protocol.DockerSandbox", FakeDockerSandbox)
    monkeypatch.setattr(
        "securebench.verification.protocol.remove_untrusted_tree",
        lambda path, *, image: shutil.rmtree(path),
    )
    oracle = ProtocolOracle(
        [
            OracleCase({"value": 2}, {"expected": 4}),
            OracleCase({"value": 3}, {"expected": 6}),
        ]
    )

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="adapter-v2-seed",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert all(request["format"] == "securebench.adapter-request/v2" for request in requests)
    assert all(request["trusted_helpers"] == {} for request in requests)
    assert len({request["challenge_id"] for request in requests}) == 2
    assert len({request["evaluation_id"] for request in requests}) == 2
    assert [item.challenge_id for item in oracle.evidence] == [
        request["challenge_id"] for request in requests
    ]
    assert [item.evaluation_id for item in oracle.evidence] == [
        request["evaluation_id"] for request in requests
    ]
    encoded = json.dumps(result.to_record(run_id="run", execution_digest=DIGEST))
    assert requests[0]["challenge_id"] not in encoded
    assert requests[0]["evaluation_id"] not in encoded


def test_adapter_failure_is_infrastructure_not_candidate_evidence(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    check = task.verification.checks[0]
    contract = load_adapter_manifest(task, check).contract
    assert contract is not None

    with pytest.raises(VerificationInfrastructureError, match="exited unsuccessfully") as error:
        _adapter_evidence(
            check,
            contract,
            0,
            "challenge-test",
            "evaluation-test",
            OracleCase({"value": 1}, None),
            CommandResult(command=("adapter",), exit_code=1),
            1,
        )

    assert error.value.code == "adapter_failed"
    assert error.value.source == "adapter"


def test_adapter_manifest_read_stops_at_the_framework_bound(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    check = task.verification.checks[0]
    adapter_manifest = (
        tmp_path / "pack" / "evaluation_inputs" / "task" / "adapter" / "adapter.yaml"
    )
    adapter_manifest.write_bytes(b"x" * (256 * 1024 + 1))

    with pytest.raises(VerificationInfrastructureError) as error:
        load_adapter_manifest(task, check)

    assert error.value.code == "adapter_manifest_too_large"
    assert error.value.source == "adapter"


def test_adapter_contract_mismatches_fail_preflight(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    adapter_manifest = (
        tmp_path / "pack" / "evaluation_inputs" / "task" / "adapter" / "adapter.yaml"
    )
    adapter_manifest.write_text(
        adapter_manifest.read_text().replace(
            "instances: 1",
            "instances: 2",
        )
    )

    with pytest.raises(ConfigError, match="exactly one Candidate participant"):
        validate_executable_task(task)


def test_adapter_rejects_oracle_challenge_outside_declared_schema(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    check = task.verification.checks[0]
    manifest = load_adapter_manifest(task, check)

    with pytest.raises(VerificationInfrastructureError) as error:
        _validated_challenge(OracleCase({"value": "wrong-type"}, None), check, manifest)

    assert error.value.code == "oracle_challenge_schema_mismatch"


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 to exercise Docker",
)
def test_protocol_check_runs_in_real_fresh_docker_evaluation(tmp_path):
    image = (
        "alexgshaw/constraints-scheduling@sha256:"
        "567ce5a189f8d11ac461790876e934cc7af38391baf89a78f95f4dafc1fec3b0"
    )
    task = write_protocol_pack(tmp_path / "pack", image=image)
    validate_executable_task(task)
    store, candidate = capture_answer(tmp_path, task)
    oracle = ProtocolOracle([OracleCase({"value": 5}, {"expected": 10})])

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="live-protocol-seed",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert oracle.evidence[0].observation == {
        "candidate": "candidate-state",
        "answer": 10,
    }


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 to exercise Docker",
)
def test_git_patch_protocol_runs_from_real_fresh_docker_repositories(tmp_path):
    parent_image = (
        "alexgshaw/constraints-scheduling@sha256:"
        "567ce5a189f8d11ac461790876e934cc7af38391baf89a78f95f4dafc1fec3b0"
    )
    context = tmp_path / "docker-context"
    context.mkdir()
    (context / "Dockerfile").write_text(
        f"""
FROM {parent_image}
USER root
RUN rm -rf /app && mkdir -p /app && cd /app \\
    && git init --quiet \\
    && git config user.email securebench@example.invalid \\
    && git config user.name SecureBench \\
    && printf 'baseline\\n' > README.md \\
    && git add . && git commit --quiet -m baseline
WORKDIR /app
""".lstrip()
    )
    built = subprocess.run(
        ["docker", "build", "--quiet", str(context)],
        check=True,
        capture_output=True,
        text=True,
    )
    image = built.stdout.strip().splitlines()[-1]
    try:
        base_commit = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", image, "git", "-C", "/app", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        task = write_protocol_pack(
            tmp_path / "pack",
            image=image,
            base_commit=base_commit,
        )
        validate_executable_task(task)
        baseline = tmp_path / "baseline"
        materialize_image_workdir(task, baseline)
        workspace = tmp_path / "agent-workspace"
        subprocess.run(
            ["git", "clone", "--quiet", str(baseline), str(workspace)], check=True
        )
        (workspace / "answer.txt").write_text("candidate-state")
        store = CandidateStore(tmp_path / "candidate-store")
        candidate = capture_git_patch_workspace(
            workspace,
            baseline,
            task.verification.candidate,
            store,
            baseline_digest=task.baseline_digest,
            base_commit=base_commit,
        )
        oracle = ProtocolOracle([OracleCase({"value": 5}, {"expected": 10})])

        result = VerificationEngine().verify(
            task,
            candidate,
            store,
            run_seed="live-repo-protocol-seed",
            oracle=oracle,
        )

        assert result.status == "passed"
        assert oracle.evidence[0].observation == {
            "candidate": "candidate-state",
            "answer": 10,
        }
    finally:
        subprocess.run(
            ["docker", "image", "rm", "--force", image],
            check=False,
            capture_output=True,
            text=True,
        )


def test_protocol_candidate_error_is_scored_without_starting_evaluation(tmp_path, monkeypatch):
    task = write_protocol_pack(tmp_path / "pack")
    oracle = ProtocolOracle([OracleCase({"value": 2}, {"expected": 4})])

    def unexpected_sandbox(**kwargs):
        raise AssertionError("candidate-error verification must not start Evaluation")

    monkeypatch.setattr("securebench.verification.protocol.DockerSandbox", unexpected_sandbox)
    result = VerificationEngine().verify_candidate_error(
        task,
        code="agent_timeout",
        message="Agent timed out",
        run_seed="protocol-seed",
        oracle=oracle,
    )

    assert result.status == "failed"
    assert oracle.evidence[0].status == "candidate_error"
    assert oracle.evidence[0].error_code == "agent_timeout"
    assert result.checks[0].cases == 1


def test_protocol_candidate_error_still_validates_oracle_challenge_bounds(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    oracle = ProtocolOracle(
        [OracleCase({"payload": "x" * 1024}, {"expected": "irrelevant"})]
    )

    result = VerificationEngine().verify_candidate_error(
        task,
        code="agent_timeout",
        message="Agent timed out",
        run_seed="protocol-seed",
        oracle=oracle,
    )

    assert result.status == "infrastructure_error"
    assert result.infrastructure_error["code"] == "oracle_case_too_large"


def test_artifact_and_protocol_checks_compose_in_one_oracle_session(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    artifact = ArtifactCheck.model_validate(
        {
            "id": "answer_artifact",
            "type": "artifact",
            "artifacts": [
                {
                    "id": "answer",
                    "source": {"entry": "answer"},
                    "parser": "securebench.utf8-text/v1",
                    "limits": {"max_bytes": 1024},
                }
            ],
        }
    )
    protocol = task.verification.checks[0]
    verification = task.verification.model_copy(update={"checks": (artifact, protocol)})
    task = task.__class__(**{**task.__dict__, "verification": verification})
    store, candidate = capture_answer(tmp_path, task)

    class MixedOracle(ProtocolOracle):
        def __init__(self):
            super().__init__([OracleCase({"value": 2}, {"expected": 4})])
            self.artifacts = []

        def evaluate_artifact(self, evidence):
            self.artifacts.append(evidence)

        def finalize(self):
            return OracleVerdict(
                passed=True,
                score=1.0,
                check_outcomes={"answer_artifact": True, "behavior": True},
            )

    class FixedProtocolRunner:
        def evaluate(self, task, candidate, store, check, oracle):
            case = oracle.next_case(check.id, check.challenge.source, {"max_cases": 2, "max_case_bytes": 1024})
            evidence = _observed(check.id, case, 0)
            oracle.evaluate_case(check.id, case.context, evidence)
            return (evidence,)

    oracle = MixedOracle()
    result = VerificationEngine(protocols=FixedProtocolRunner()).verify(
        task,
        candidate,
        store,
        run_seed="mixed-seed",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert [check.type for check in result.checks] == ["artifact", "protocol"]
    assert oracle.artifacts[0].parsed_value == "candidate-state"
    assert oracle.evidence[0].observation == {"ok": True}


def test_oracle_cannot_exceed_protocol_case_limit(tmp_path, monkeypatch):
    task = write_protocol_pack(tmp_path / "pack")
    store, candidate = capture_answer(tmp_path, task)
    oracle = ProtocolOracle(
        [OracleCase({"value": index}, {"expected": index}) for index in range(3)]
    )
    monkeypatch.setattr(
        "securebench.verification.protocol.ProtocolCheckRunner._evaluate_case",
        lambda self, task, candidate, store, check, manifest, case, challenge_index, challenge_id: _observed(
            check.id, case, challenge_index
        ),
    )

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="protocol-seed",
        oracle=oracle,
    )

    assert result.status == "infrastructure_error"
    assert result.infrastructure_error["code"] == "oracle_case_limit_exceeded"


@pytest.mark.parametrize("stdout", ['{"answer":1,"answer":2}', '{"answer":NaN}', "not-json"])
def test_adapter_rejects_ambiguous_or_non_finite_response_json(tmp_path, stdout):
    task = write_protocol_pack(tmp_path / "pack")
    check = task.verification.checks[0]
    contract = load_adapter_manifest(task, check).contract

    with pytest.raises(VerificationInfrastructureError) as error:
        _adapter_evidence(
            check,
            contract,
            0,
            "challenge-test",
            "evaluation-test",
            OracleCase({"value": 1}, None),
            CommandResult(command=("adapter",), exit_code=0, stdout=stdout),
            1,
        )

    assert error.value.code == "adapter_response_invalid"
    assert error.value.source == "adapter"


def test_adapter_enforces_response_byte_bound(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    check = task.verification.checks[0]
    limits = check.limits.model_copy(update={"observation_bytes_per_case": 4})
    bounded = check.model_copy(update={"limits": limits})

    contract = load_adapter_manifest(task, check).contract
    with pytest.raises(VerificationInfrastructureError) as error:
        _adapter_evidence(
            bounded,
            contract,
            0,
            "challenge-test",
            "evaluation-test",
            OracleCase({"value": 1}, None),
            CommandResult(command=("adapter",), exit_code=0, stdout='{"answer":2}'),
            1,
        )

    assert error.value.code == "adapter_response_too_large"


def test_adapter_rejects_truncated_output_before_parsing(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    check = task.verification.checks[0]

    contract = load_adapter_manifest(task, check).contract
    with pytest.raises(VerificationInfrastructureError) as error:
        _adapter_evidence(
            check,
            contract,
            0,
            "challenge-test",
            "evaluation-test",
            OracleCase({"value": 1}, None),
            CommandResult(
                command=("adapter",),
                exit_code=0,
                stdout='{"answer":2}',
                stdout_bytes=2 * 1024 * 1024,
                stdout_truncated=True,
            ),
            1,
        )

    assert error.value.code == "adapter_response_too_large"


def test_adapter_rejects_invalid_utf8_before_parsing(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    check = task.verification.checks[0]

    contract = load_adapter_manifest(task, check).contract
    with pytest.raises(VerificationInfrastructureError) as error:
        _adapter_evidence(
            check,
            contract,
            0,
            "challenge-test",
            "evaluation-test",
            OracleCase({"value": 1}, None),
            CommandResult(
                command=("adapter",),
                exit_code=0,
                stdout="�",
                stdout_bytes=1,
                stdout_valid_utf8=False,
            ),
            1,
        )

    assert error.value.code == "adapter_response_invalid"


def _observed(check_id, case, case_index):
    return ProtocolCaseEvidence(
        check_id=check_id,
        challenge_id=f"challenge-{case_index}",
        evaluation_id=f"evaluation-{case_index}",
        challenge_index=case_index,
        challenge_digest=json_digest(case.challenge),
        status="observed",
        exit_status=0,
        observation={"ok": True},
        observation_bytes=11,
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "trusted_helpers",
            [{"name": "server", "type": "example", "limits": {}}],
            "Trusted Helpers",
        ),
        (
            "output_artifacts",
            [
                {
                    "name": "transcript",
                    "parser": "securebench.strict-json/v1",
                    "limits": {"max_bytes": 1024},
                }
            ],
            "output artifacts",
        ),
    ],
)
def test_executable_capability_matrix_rejects_unsupported_protocol_branches(
    tmp_path, field, value, message
):
    task = write_protocol_pack(tmp_path / "pack")
    check_data = task.verification.checks[0].model_dump()
    check_data[field] = value
    check = ProtocolCheck.model_validate(check_data)
    verification_data = task.verification.model_dump()
    verification_data["checks"] = [check.model_dump()]
    verification = VerificationSpec.model_validate(verification_data)
    changed = task.__class__(**{**task.__dict__, "verification": verification})

    with pytest.raises(ConfigError, match=message):
        validate_executable_task(changed)


def test_malformed_adapter_manifest_fails_before_agent_execution(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    adapter_manifest = tmp_path / "pack" / "evaluation_inputs" / "task" / "adapter" / "adapter.yaml"
    adapter_manifest.write_text("command: [unterminated\n")

    with pytest.raises(ConfigError, match="not valid YAML"):
        validate_executable_task(task)


def test_v1_adapter_format_fails_before_agent_execution(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    adapter_manifest = (
        tmp_path / "pack" / "evaluation_inputs" / "task" / "adapter" / "adapter.yaml"
    )
    adapter_manifest.write_text(
        "abi: securebench.protocol-adapter/v1\n"
        "protocol: securebench.example/v1\n"
        "command: ['python3', './adapter.py']\n"
    )

    with pytest.raises(ConfigError, match="must use the securebench.adapter/v2 format"):
        validate_executable_task(task)


def test_duplicate_adapter_manifest_keys_fail_before_agent_execution(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    adapter_manifest = (
        tmp_path / "pack" / "evaluation_inputs" / "task" / "adapter" / "adapter.yaml"
    )
    adapter_manifest.write_text(adapter_manifest.read_text() + "command: ['shadow']\n")

    with pytest.raises(
        ConfigError, match="Protocol adapter manifest is not valid YAML"
    ) as error:
        validate_executable_task(task)

    assert isinstance(error.value.__cause__, VerificationInfrastructureError)
    assert error.value.__cause__.code == "adapter_manifest_invalid"
    assert "shadow" not in str(error.value)


def test_non_utf8_adapter_manifest_fails_before_agent_execution(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    adapter_manifest = (
        tmp_path / "pack" / "evaluation_inputs" / "task" / "adapter" / "adapter.yaml"
    )
    adapter_manifest.write_bytes(b"\xff")

    with pytest.raises(ConfigError, match="not valid UTF-8"):
        validate_executable_task(task)


def test_malformed_oracle_manifest_fails_before_agent_execution(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    oracle_manifest = (
        tmp_path / "pack" / "hidden" / "task" / "oracle" / "oracle.yaml"
    )
    oracle_manifest.write_text("command: [unterminated\n")

    with pytest.raises(ConfigError, match="Oracle is not executable.*not valid YAML"):
        validate_executable_task(task)


def test_duplicate_oracle_manifest_keys_fail_before_agent_execution(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    oracle_manifest = tmp_path / "pack" / "hidden" / "task" / "oracle" / "oracle.yaml"
    oracle_manifest.write_text(oracle_manifest.read_text() + "timeout_seconds: 1\n")

    with pytest.raises(
        ConfigError, match="Oracle is not executable.*not valid YAML"
    ) as error:
        validate_executable_task(task)

    assert isinstance(error.value.__cause__, VerificationInfrastructureError)
    assert error.value.__cause__.code == "oracle_manifest_invalid"


def test_backend_incompatible_evaluation_mount_fails_preflight(tmp_path):
    task = write_protocol_pack(
        tmp_path / "pack",
        adapter_mount="/etc/securebench-adapter",
    )

    with pytest.raises(ConfigError, match="Evaluation resource mounts are not executable"):
        validate_executable_task(task)


def test_observation_bound_must_fit_the_bounded_command_channel(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    check = task.verification.checks[0]
    limits = check.limits.model_copy(update={"observation_bytes_per_case": 2 * 1024 * 1024})
    check = check.model_copy(update={"limits": limits})
    verification = task.verification.model_copy(update={"checks": (check,)})
    changed = task.__class__(**{**task.__dict__, "verification": verification})

    with pytest.raises(ConfigError, match="exceeds the Evaluation output capacity"):
        validate_executable_task(changed)


def test_oracle_process_case_transport_is_bounded_and_typed(tmp_path):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(
        """
abi: securebench.oracle/v1
command: ["{python}", "oracle.py"]
timeout_seconds: 1
""".lstrip()
    )
    (oracle_root / "oracle.py").write_text(
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if request["op"] == "next_case":
        print(json.dumps({"type": "case", "challenge": {"value": 7}, "case_context": {"expected": 14}}), flush=True)
    elif request["op"] == "evaluate_case":
        assert request["case_context"] == {"expected": 14}
        assert request["evidence"]["observation"] == {"answer": 14}
        print(json.dumps({"type": "ack"}), flush=True)
""".lstrip()
    )
    session = OracleProcessSession(oracle_root)
    try:
        case = session.next_case(
            "behavior",
            "host.cases",
            {"max_cases": 1, "max_case_bytes": 64},
        )
        assert case == OracleCase({"value": 7}, {"expected": 14})
        session.evaluate_case(
            "behavior",
            case.context,
            ProtocolCaseEvidence(
                check_id="behavior",
                challenge_id="challenge-test",
                evaluation_id="evaluation-test",
                challenge_index=0,
                challenge_digest=json_digest(case.challenge),
                status="observed",
                exit_status=0,
                observation={"answer": 14},
                observation_bytes=13,
            ),
        )
    finally:
        session.close()


def test_oracle_process_rejects_oversized_challenge(tmp_path):
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()
    (oracle_root / "oracle.yaml").write_text(
        """
abi: securebench.oracle/v1
command: ["{python}", "oracle.py"]
timeout_seconds: 1
""".lstrip()
    )
    response = json.dumps(
        {"type": "case", "challenge": {"payload": "x" * 100}, "case_context": None}
    )
    (oracle_root / "oracle.py").write_text(
        "import sys\nfor line in sys.stdin:\n"
        f"    print({response!r}, flush=True)\n"
    )
    session = OracleProcessSession(oracle_root)
    try:
        with pytest.raises(VerificationInfrastructureError) as error:
            session.next_case(
                "behavior",
                "host.cases",
                {"max_cases": 1, "max_case_bytes": 16},
            )
    finally:
        session.close()

    assert error.value.code == "oracle_case_too_large"
