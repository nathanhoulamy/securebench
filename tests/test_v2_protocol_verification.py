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
    OverlayReplayBackend,
    OverlayScanLimits,
    capture_file_bundle,
    capture_filesystem_overlay,
    capture_git_patch_workspace,
    scan_overlay_roots,
)
from securebench.errors import ConfigError
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.shared import materialize_image_workdir
from securebench.sandboxes import CommandResult, DockerVolumeMount
from securebench.schemas.benchmark import ArtifactCheck, ProtocolCheck, VerificationSpec
from securebench.verification import OracleSession, OracleVerdict, VerificationEngine
from securebench.verification.json_data import json_digest
from securebench.verification.models import (
    ChallengeEvidence,
    OracleChallenge,
    TrustedHelperEvidence,
    VerificationInfrastructureError,
)
from securebench.verification.oracle import OracleProcessSession
from securebench.verification.protocol import (
    _adapter_evidence,
    _validated_challenge,
    load_adapter_manifest,
)
from securebench.tester_config import MIN_OVERLAY_WORKSPACE_BYTES
from securebench.workspaces.overlay_quota import (
    OverlayQuotaWorkspace,
    probe_overlay_workspace_backend,
)


DIGEST = "sha256:" + "d" * 64


class ProtocolOracle(OracleSession):
    def __init__(self, cases: list[OracleChallenge]) -> None:
        self.pending = list(cases)
        self.evidence = []
        self.contexts = []
        self.next_calls = 0

    def initialize(self, task, *, run_seed):
        self.seed = run_seed

    def evaluate_artifact(self, evidence):
        raise AssertionError("artifact evidence was not expected")

    def next_challenge(self, check_id, challenge_source, bounds):
        assert check_id == "behavior"
        assert challenge_source == "host.cases"
        assert bounds == {"max_cases": 2, "max_case_bytes": 1024}
        self.next_calls += 1
        return self.pending.pop(0) if self.pending else None

    def evaluate_challenge(self, check_id, case_context, evidence):
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
    public_mount: str = "/opt/securebench/public.txt",
    base_commit: str | None = None,
    recorder: bool = False,
    output_artifact: bool = False,
    overlay: bool = False,
):
    (root / "assets" / "task").mkdir(parents=True)
    adapter = root / "evaluation_inputs" / "task" / "adapter"
    adapter.mkdir(parents=True)
    (root / "hidden" / "task" / "oracle").mkdir(parents=True)
    (root / "hidden" / "task" / "cases").mkdir(parents=True)
    if recorder:
        (root / "hidden" / "task" / "recorder.yaml").write_text(
            "path: /callback\nresponse_status: 202\nresponse_body: accepted\n"
        )
    (root / "assets" / "task" / "public.txt").write_text("public")
    (root / "hidden" / "task" / "oracle" / "oracle.yaml").write_text(
        "abi: securebench.oracle/v1\n"
        "command: ['{python}', 'oracle.py']\n"
        "timeout_seconds: 30\n"
    )
    helper_manifest = (
        "uses_trusted_helpers:\n"
        "  - {name: webhook, type: securebench.http-request-recorder/v1}\n"
        if recorder
        else ""
    )
    output_artifact_manifest = (
        "output_artifacts:\n"
        "  - name: generated_result\n"
        "    path: results/result.json\n"
        "    kind: regular_file\n"
        "    maximum_limits: {max_bytes: 4096}\n"
        if output_artifact
        else ""
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
""".lstrip()
        + helper_manifest
        + output_artifact_manifest
        + """maximums:
  seconds_per_challenge: 2
  challenge_bytes: 1024
  observation_bytes: 1024
"""
    )
    helper_adapter = (
        """
helper = request["trusted_helpers"]["webhook"]
import socket
import urllib.request
try:
    external = socket.create_connection(("1.1.1.1", 80), timeout=0.2)
except OSError:
    pass
else:
    external.close()
    raise RuntimeError("Evaluation unexpectedly reached the public internet")
callback = urllib.request.Request(
    helper["url"],
    data=json.dumps({"event": request["challenge"]["value"]}).encode(),
    headers={"Authorization": helper["authorization"], "Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(callback, timeout=1) as response:
    response.read()
"""
        if recorder
        else ""
    )
    output_artifact_adapter = (
        """
Path("/app/results").mkdir(exist_ok=True)
Path("/app/results/result.json").write_text(json.dumps({
    "challenge": request["challenge"]["value"],
    "candidate": Path("/app/answer.txt").read_text(),
}))
"""
        if output_artifact
        else ""
    )
    overlay_isolation_adapter = (
        """
marker = Path("/app/.securebench-case-marker")
if marker.exists():
    raise RuntimeError("stale overlay state reached a fresh Evaluation")
marker.write_text(str(request["challenge"]["value"]))
"""
        if overlay
        else ""
    )
    (adapter / "adapter.py").write_text(
        f"""
import json
import sys
from pathlib import Path

request = json.load(sys.stdin)
{helper_adapter}{output_artifact_adapter}{overlay_isolation_adapter}print(json.dumps({{
    "format": "securebench.adapter-response/v2",
    "status": "observed",
    "observation": {{
        "candidate": Path("/app/answer.txt").read_text(),
        "answer": request["challenge"]["value"] * 2,
    }},
}}))
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
            "type": "filesystem_overlay",
            "include_roots": ["/app"],
            "max_changed_paths": 20,
            "max_changed_bytes": 4096,
            "allow_internal_symlinks": False,
        }
        if overlay
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
    host_resources = {
        "cases": {"path": "task/cases"},
        "oracle": {"path": "task/oracle"},
    }
    if recorder:
        host_resources["recorder"] = {"path": "task/recorder.yaml"}
    check = {
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
    if recorder:
        check["trusted_helpers"] = [
            {
                "name": "webhook",
                "type": "securebench.http-request-recorder/v1",
                "settings": "host.recorder",
                "limits": {
                    "max_requests": 4,
                    "max_body_bytes": 1024,
                    "max_header_bytes": 4096,
                },
            }
        ]
    if output_artifact:
        check["output_artifacts"] = [
            {
                "name": "generated_result",
                "parser": "securebench.strict-json/v1",
                "limits": {"max_bytes": 2048},
            }
        ]
    row = {
        "id": "protocol/task",
        "input": task_input,
        "assets": [
            {"path": "task/public.txt", "mount": public_mount, "read_only": True}
        ],
        "verification": {
            "execution_profile": "strict-split/v1",
            "candidate": candidate,
            "resources": {
                "runtime": {
                    "adapter": {"path": "task/adapter", "mount": adapter_mount}
                },
                "host": host_resources,
            },
            "checks": [check],
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


class FakeProtocolOverlayWorkspace:
    def __init__(self, root: Path, include_roots: tuple[str, ...], index: int):
        self.root = root
        self.include_roots = include_roots
        self.volume_name = f"securebench-test-overlay-{index}"
        self.roots = {
            guest: root / f"root-{root_index}"
            for root_index, guest in enumerate(include_roots)
        }
        for path in self.roots.values():
            path.mkdir(parents=True)

    def host_roots(self):
        return self.roots

    def docker_mounts(self, *, read_only=False):
        return tuple(
            DockerVolumeMount(
                source=self.volume_name,
                target=guest,
                subpath=f"roots/{index:04d}",
                read_only=read_only,
            )
            for index, guest in enumerate(self.include_roots)
        )

    def close(self):
        shutil.rmtree(self.root)


def test_overlay_protocol_uses_fresh_replay_per_case_and_collects_output(
    tmp_path, monkeypatch
):
    import securebench.candidates.overlay as overlay_module

    monkeypatch.setattr(overlay_module, "_has_extended_metadata", lambda _path: False)
    task = write_protocol_pack(tmp_path / "pack", overlay=True, output_artifact=True)
    baseline = tmp_path / "baseline"
    final = tmp_path / "final"
    baseline.mkdir()
    final.mkdir()
    (baseline / "answer.txt").write_text("baseline-state")
    (final / "answer.txt").write_text("candidate-state")
    limits = OverlayScanLimits(required_uid=os.getuid(), required_gid=os.getgid())
    store = CandidateStore(tmp_path / "store")
    candidate = capture_filesystem_overlay(
        {"/app": baseline},
        {"/app": final},
        task.verification.candidate,
        store,
        baseline_digest=task.baseline_digest,
        scan_limits=limits,
    )
    workspaces: list[FakeProtocolOverlayWorkspace] = []

    def workspace_factory(*, include_roots, **_kwargs):
        workspace = FakeProtocolOverlayWorkspace(
            tmp_path / f"overlay-evaluation-{len(workspaces)}",
            include_roots,
            len(workspaces),
        )
        workspaces.append(workspace)
        return workspace

    def materializer(_image, workspace, *, scan_limits):
        shutil.copy2(baseline / "answer.txt", workspace.roots["/app"] / "answer.txt")
        return scan_overlay_roots(
            workspace.include_roots,
            workspace.host_roots(),
            limits=scan_limits,
            label="baseline",
        )

    class FakeDockerSandbox:
        def __init__(self, **options):
            self.options = options
            assert options["workspace_read_only"] is True
            assert options["allow_resource_overrides"] is False
            assert options["workspace_mount_target"] == "/opt/securebench/evaluation-runtime"
            assert [mount.target for mount in options["volume_mounts"]] == ["/app"]

        def run(self, command, *, workdir, timeout, stdin):
            workspace = workspaces[-1]
            candidate_root = workspace.roots["/app"]
            assert workdir == "/app"
            assert (candidate_root / "answer.txt").read_text() == "candidate-state"
            assert not (candidate_root / "stale-from-previous-case").exists()
            request = json.loads(stdin)
            (candidate_root / "results").mkdir()
            (candidate_root / "results" / "result.json").write_text(
                json.dumps({"challenge": request["challenge"]["value"]})
            )
            (candidate_root / "stale-from-previous-case").write_text("discard me")
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

    monkeypatch.setattr("securebench.verification.protocol.DockerSandbox", FakeDockerSandbox)
    backend = OverlayReplayBackend(
        storage_root=tmp_path / "storage",
        capacity_bytes=2 * 1024 * 1024 * 1024,
        scan_limits=limits,
        workspace_factory=workspace_factory,
        materializer=materializer,
    )
    oracle = ProtocolOracle(
        [
            OracleChallenge({"value": 2}, {"expected": 4}),
            OracleChallenge({"value": 3}, {"expected": 6}),
        ]
    )

    result = VerificationEngine(overlay_backend=backend).verify(
        task, candidate, store, run_seed="overlay-protocol", oracle=oracle
    )

    assert result.status == "passed"
    assert len(workspaces) == 2
    assert workspaces[0].volume_name != workspaces[1].volume_name
    assert not any(workspace.root.exists() for workspace in workspaces)
    assert [
        evidence.output_artifacts[0].parsed_value for evidence in oracle.evidence
    ] == [{"challenge": 2}, {"challenge": 3}]


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_RUN_REAL_DOCKER_OVERLAY_TESTS") != "1",
    reason="requires an explicitly provisioned root Linux Docker host",
)
def test_real_docker_overlay_protocol_uses_two_clean_volumes_and_leaks_nothing(
    tmp_path
):
    if os.uname().sysname != "Linux" or os.geteuid() != 0:
        pytest.skip("requires a root Linux host")
    base = os.environ.get("SECUREBENCH_OVERLAY_PROBE_IMAGE")
    if base is None:
        pytest.skip("SECUREBENCH_OVERLAY_PROBE_IMAGE must name a local pinned image")
    storage = tmp_path / "overlay-storage"
    probe_overlay_workspace_backend(storage_root=storage, image=base)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        f"FROM {base}\n"
        "RUN mkdir -p /app && printf baseline-state > /app/answer.txt\n"
    )
    built = subprocess.run(
        ["docker", "build", "--quiet", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    image = built.stdout.strip()
    if not image.startswith("sha256:"):
        pytest.fail("Docker build did not return a pinned image ID")
    before_volumes = subprocess.run(
        [
            "docker",
            "volume",
            "ls",
            "--quiet",
            "--filter",
            "label=securebench.overlay-workspace=true",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    instances: list[str] = []

    def workspace_factory(**options):
        workspace = OverlayQuotaWorkspace.create(**options)
        instances.append(workspace.instance_id)
        return workspace

    try:
        task = write_protocol_pack(tmp_path / "pack", image=image, overlay=True)
        baseline = tmp_path / "baseline"
        final = tmp_path / "final"
        baseline.mkdir()
        final.mkdir()
        (baseline / "answer.txt").write_text("baseline-state")
        (final / "answer.txt").write_text("candidate-state")
        store = CandidateStore(tmp_path / "store")
        candidate = capture_filesystem_overlay(
            {"/app": baseline},
            {"/app": final},
            task.verification.candidate,
            store,
            baseline_digest=task.baseline_digest,
        )
        backend = OverlayReplayBackend(
            storage_root=storage,
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            workspace_factory=workspace_factory,
        )
        oracle = ProtocolOracle(
            [
                OracleChallenge({"value": 2}, {"expected": 4}),
                OracleChallenge({"value": 3}, {"expected": 6}),
            ]
        )

        result = VerificationEngine(overlay_backend=backend).verify(
            task, candidate, store, run_seed="real-overlay", oracle=oracle
        )

        assert result.status == "passed"
        assert len(instances) == 2 and len(set(instances)) == 2
        assert [item.observation["candidate"] for item in oracle.evidence] == [
            "candidate-state",
            "candidate-state",
        ]
    finally:
        containers = subprocess.run(
            [
                "docker",
                "container",
                "ls",
                "--all",
                "--quiet",
                "--filter",
                f"ancestor={image}",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        subprocess.run(
            ["docker", "image", "rm", "--force", image],
            check=False,
            capture_output=True,
            text=True,
        )
    after_volumes = subprocess.run(
        [
            "docker",
            "volume",
            "ls",
            "--quiet",
            "--filter",
            "label=securebench.overlay-workspace=true",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert containers == []
    assert sorted(after_volumes) == sorted(before_volumes)
    assert not list(storage.glob("securebench-overlay-*"))


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
    oracle = ProtocolOracle([OracleChallenge({"value": 5}, {"expected": 10})])

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
            OracleChallenge({"value": 2}, {"expected": 4, "host_secret": "first-secret"}),
            OracleChallenge({"value": 3}, {"expected": 6, "host_secret": "second-secret"}),
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
            OracleChallenge({"value": 2}, {"expected": 4}),
            OracleChallenge({"value": 3}, {"expected": 6}),
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


def test_output_artifacts_are_collected_from_each_fresh_evaluation(
    tmp_path,
    monkeypatch,
):
    task = write_protocol_pack(tmp_path / "pack", output_artifact=True)
    validate_executable_task(task)
    store, candidate = capture_answer(tmp_path, task)
    roots = []

    def materialize_baseline(_task, destination):
        destination.mkdir(parents=True, exist_ok=True)

    class FakeDockerSandbox:
        def __init__(self, **kwargs):
            self.root = Path(kwargs["root"])
            roots.append(self.root)

        def run(self, command, *, workdir, timeout, stdin):
            request = json.loads(stdin)
            output = self.root / "results" / "result.json"
            output.parent.mkdir()
            if request["challenge"]["value"] == 3:
                output.write_text("{invalid")
            else:
                output.write_text(
                    json.dumps(
                        {
                            "challenge": request["challenge"]["value"],
                            "candidate": "candidate-state",
                        }
                    )
                )
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
            OracleChallenge({"value": 2}, {"expected": 4}),
            OracleChallenge({"value": 3}, {"expected": 6}),
        ]
    )

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="output-artifact-seed",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert len(roots) == 2 and roots[0] != roots[1]
    assert not any(root.exists() for root in roots)
    assert oracle.evidence[0].output_artifacts[0].parsed_value == {
        "challenge": 2,
        "candidate": "candidate-state",
    }
    assert oracle.evidence[1].output_artifacts[0].status == "candidate_error"
    assert oracle.evidence[1].output_artifacts[0].failure_code == "invalid_json"
    for evidence in oracle.evidence:
        artifact = evidence.output_artifacts[0]
        assert artifact.challenge_id == evidence.challenge_id
        assert artifact.evaluation_id == evidence.evaluation_id
        assert artifact.digest.startswith("sha256:")
    public_record = json.dumps(result.to_record(run_id="run", execution_digest=DIGEST))
    assert "generated_result" not in public_record
    assert "candidate-state" not in public_record


def test_output_artifact_path_may_not_overlap_evaluation_resource_mount(tmp_path):
    task = write_protocol_pack(
        tmp_path / "pack",
        output_artifact=True,
        public_mount="/app/results",
    )

    with pytest.raises(ConfigError, match="overlaps a mounted Evaluation resource"):
        validate_executable_task(task)


def test_protocol_wires_scoped_helper_access_and_correlated_evidence(
    tmp_path,
    monkeypatch,
):
    task = write_protocol_pack(tmp_path / "pack", recorder=True)
    validate_executable_task(task)
    store, candidate = capture_answer(tmp_path, task)
    requests = []
    lifecycle = []

    def materialize_baseline(_task, destination):
        destination.mkdir(parents=True, exist_ok=True)

    class FakeTrustedHelperEvaluation:
        def __init__(self, **kwargs):
            self.challenge_id = kwargs["challenge_id"]
            self.evaluation_id = kwargs["evaluation_id"]
            self.network = "none"
            lifecycle.append(("created", self.challenge_id, self.evaluation_id))

        def start(self):
            self.network = "securebench-evaluation-test"
            lifecycle.append(("started", self.challenge_id, self.evaluation_id))
            return {
                "webhook": {
                    "type": "securebench.http-request-recorder/v1",
                    "url": "http://securebench-helper-0:8080/callback",
                    "authorization": "Bearer evaluation-secret",
                }
            }

        def evaluation_environment(self):
            return {
                "HTTP_PROXY": "",
                "NO_PROXY": "securebench-helper-0",
            }

        def collect(self):
            lifecycle.append(("collected", self.challenge_id, self.evaluation_id))
            return (
                TrustedHelperEvidence(
                    name="webhook",
                    type="securebench.http-request-recorder/v1",
                    challenge_id=self.challenge_id,
                    evaluation_id=self.evaluation_id,
                    value={"requests": []},
                ),
            )

        def close(self):
            lifecycle.append(("closed", self.challenge_id, self.evaluation_id))

    class FakeDockerSandbox:
        def __init__(self, **kwargs):
            assert kwargs["network"] == "securebench-evaluation-test"
            assert kwargs["env"] == {
                "HTTP_PROXY": "",
                "NO_PROXY": "securebench-helper-0",
            }

        def run(self, command, *, workdir, timeout, stdin):
            request = json.loads(stdin)
            requests.append(request)
            assert request["trusted_helpers"] == {
                "webhook": {
                    "type": "securebench.http-request-recorder/v1",
                    "url": "http://securebench-helper-0:8080/callback",
                    "authorization": "Bearer evaluation-secret",
                }
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
    monkeypatch.setattr(
        "securebench.verification.protocol.TrustedHelperEvaluation",
        FakeTrustedHelperEvaluation,
    )
    monkeypatch.setattr("securebench.verification.protocol.DockerSandbox", FakeDockerSandbox)
    monkeypatch.setattr(
        "securebench.verification.protocol.remove_untrusted_tree",
        lambda path, *, image: shutil.rmtree(path),
    )
    oracle = ProtocolOracle([OracleChallenge({"value": 2}, {"expected": 4})])

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="trusted-helper-seed",
        oracle=oracle,
    )

    assert result.status == "passed"
    evidence = oracle.evidence[0]
    assert evidence.challenge_id == requests[0]["challenge_id"]
    assert evidence.evaluation_id == requests[0]["evaluation_id"]
    assert evidence.trusted_helper_evidence[0].challenge_id == evidence.challenge_id
    assert evidence.trusted_helper_evidence[0].evaluation_id == evidence.evaluation_id
    assert [item[0] for item in lifecycle] == ["created", "started", "collected", "closed"]
    encoded = json.dumps(result.to_record(run_id="run", execution_digest=DIGEST))
    assert "evaluation-secret" not in encoded


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
            OracleChallenge({"value": 1}, None),
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
        _validated_challenge(OracleChallenge({"value": "wrong-type"}, None), check, manifest)

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
    oracle = ProtocolOracle([OracleChallenge({"value": 5}, {"expected": 10})])

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
def test_http_recorder_runs_on_a_fresh_internal_docker_evaluation_network(tmp_path):
    image = (
        "alexgshaw/constraints-scheduling@sha256:"
        "567ce5a189f8d11ac461790876e934cc7af38391baf89a78f95f4dafc1fec3b0"
    )
    task = write_protocol_pack(
        tmp_path / "pack",
        image=image,
        recorder=True,
        output_artifact=True,
    )
    validate_executable_task(task)
    store, candidate = capture_answer(tmp_path, task)
    oracle = ProtocolOracle(
        [
            OracleChallenge({"value": 5}, {"expected": 10}),
            OracleChallenge({"value": 7}, {"expected": 14}),
        ]
    )

    result = VerificationEngine().verify(
        task,
        candidate,
        store,
        run_seed="live-recorder-seed",
        oracle=oracle,
    )

    assert result.status == "passed"
    assert len(oracle.evidence) == 2
    assert len({evidence.evaluation_id for evidence in oracle.evidence}) == 2
    for evidence in oracle.evidence:
        helper = evidence.trusted_helper_evidence[0]
        assert helper.challenge_id == evidence.challenge_id
        assert helper.evaluation_id == evidence.evaluation_id
        assert helper.truncated is False
        assert len(helper.value["requests"]) == 1
        request = helper.value["requests"][0]
        assert request["sequence"] == 0
        assert request["method"] == "POST"
        assert request["target"] == "/callback"
        assert request["authenticated"] is True
        assert request["path_matched"] is True
        assert request["response_status"] == 202
        artifact = evidence.output_artifacts[0]
        assert artifact.challenge_id == evidence.challenge_id
        assert artifact.evaluation_id == evidence.evaluation_id
        assert artifact.status == "observed"
        assert artifact.parsed_value == {
            "challenge": evidence.observation["answer"] // 2,
            "candidate": "candidate-state",
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
    _, base_commit = make_git_baseline(context / "app")
    (context / "Dockerfile").write_text(
        f"""
FROM {parent_image}
USER root
RUN rm -rf /app && mkdir -p /app
COPY app/ /app/
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
        oracle = ProtocolOracle([OracleChallenge({"value": 5}, {"expected": 10})])

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
    task = write_protocol_pack(tmp_path / "pack", recorder=True)
    oracle = ProtocolOracle([OracleChallenge({"value": 2}, {"expected": 4})])

    def unexpected_sandbox(**kwargs):
        raise AssertionError("candidate-error verification must not start Evaluation")

    monkeypatch.setattr("securebench.verification.protocol.DockerSandbox", unexpected_sandbox)
    monkeypatch.setattr(
        "securebench.verification.protocol.TrustedHelperEvaluation",
        unexpected_sandbox,
    )
    result = VerificationEngine().verify_candidate_error(
        task,
        code="agent_timeout",
        message="Agent timed out",
        run_seed="protocol-seed",
        oracle=oracle,
    )

    assert result.status == "failed"
    assert oracle.evidence[0].status == "candidate_error"
    assert oracle.evidence[0].failure_code == "agent_timeout"
    assert result.checks[0].cases == 1


def test_protocol_candidate_error_still_validates_oracle_challenge_bounds(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    oracle = ProtocolOracle(
        [OracleChallenge({"payload": "x" * 1024}, {"expected": "irrelevant"})]
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
            super().__init__([OracleChallenge({"value": 2}, {"expected": 4})])
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
            case = oracle.next_challenge(check.id, check.challenge.source, {"max_cases": 2, "max_case_bytes": 1024})
            evidence = _observed(check.id, case, 0)
            oracle.evaluate_challenge(check.id, case.context, evidence)
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
        [OracleChallenge({"value": index}, {"expected": index}) for index in range(3)]
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
            OracleChallenge({"value": 1}, None),
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
            OracleChallenge({"value": 1}, None),
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
            OracleChallenge({"value": 1}, None),
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
            OracleChallenge({"value": 1}, None),
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
    return ChallengeEvidence(
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


def test_executable_capability_matrix_rejects_unknown_trusted_helper(tmp_path):
    task = write_protocol_pack(tmp_path / "pack")
    check_data = task.verification.checks[0].model_dump()
    check_data["trusted_helpers"] = [
        {"name": "server", "type": "example", "limits": {}}
    ]
    check = ProtocolCheck.model_validate(check_data)
    verification_data = task.verification.model_dump()
    verification_data["checks"] = [check.model_dump()]
    verification = VerificationSpec.model_validate(verification_data)
    changed = task.__class__(**{**task.__dict__, "verification": verification})

    with pytest.raises(ConfigError, match="Trusted Helpers"):
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
        case = session.next_challenge(
            "behavior",
            "host.cases",
            {"max_cases": 1, "max_case_bytes": 64},
        )
        assert case == OracleChallenge({"value": 7}, {"expected": 14})
        session.evaluate_challenge(
            "behavior",
            case.context,
            ChallengeEvidence(
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
            session.next_challenge(
                "behavior",
                "host.cases",
                {"max_cases": 1, "max_case_bytes": 16},
            )
    finally:
        session.close()

    assert error.value.code == "oracle_case_too_large"
