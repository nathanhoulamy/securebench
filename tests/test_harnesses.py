import json
from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_row
from securebench.benchmark_pack import AssetDefaults, BenchmarkPackManifest, BenchmarkRow
from securebench.errors import ConfigError
from securebench.harnesses import build_harness_producer
from securebench.sandboxes import CommandResult
from securebench.tester_config import TesterHarnessSection as HarnessSection


class FakeHostSandbox:
    instances = []

    def __init__(self, *, root=None, env_names=()):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.env_names = tuple(env_names)
        self.commands = []
        self.closed = False
        FakeHostSandbox.instances.append(self)

    def run(self, command, *, workdir=None, timeout=None):
        self.commands.append((command, workdir, timeout))
        normalized = tuple(command) if not isinstance(command, str) else ("sh", "-lc", command)
        if normalized and normalized[0] == "write-artifact":
            self.write_file("candidate.txt", "FILE-CANDIDATE")
            return CommandResult(normalized, 0, "ignored stdout", "")
        if normalized and normalized[0] == "patch":
            return CommandResult(normalized, 0, "diff --git a/file.py b/file.py\n", "")
        return CommandResult(normalized, 0, "STDOUT-CANDIDATE", "")

    def write_file(self, path, content):
        target = self.root / Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    def read_file(self, path):
        return (self.root / Path(path)).read_text()

    def extract_file(self, path):
        return (self.root / Path(path)).read_bytes()

    def close(self):
        self.closed = True


class FakeDockerSandbox(FakeHostSandbox):
    instances = []

    def __init__(self, *, image, root=None, env_names=(), mounts=(), **kwargs):
        super().__init__(root=root, env_names=env_names)
        self.image = image
        self.mounts = tuple(mounts)
        self.kwargs = kwargs
        FakeDockerSandbox.instances.append(self)


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeHostSandbox.instances = []
    FakeDockerSandbox.instances = []


def mc_task(manifest=None, *, assets=()):
    return compile_benchmark_row(
        BenchmarkRow(
            id="mc-1",
            family="multiple_choice",
            input={"question": "2 + 2?", "choices": ["1", "2", "4"]},
            assets=assets,
            eval={"answer": "4"},
        ),
        manifest=manifest or BenchmarkPackManifest(id="pack", version=1),
    )


def code_task():
    return compile_benchmark_row(
        BenchmarkRow(
            id="code-1",
            family="code_generation",
            input={"prompt": "Write add."},
            eval={"tests": {"source": "inline", "code": "assert candidate(1, 2) == 3"}},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def repo_patch_task():
    return compile_benchmark_row(
        BenchmarkRow(
            id="repo-1",
            family="repo_patch",
            input={"repo": "repo/", "base_commit": "abc123", "instructions": "Fix it."},
            eval={"tests": {"path": "tests/test_bug.py"}},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def harness_section(*, mode="host", image=None, config=None, harness_type="command"):
    return HarnessSection(
        type=harness_type,
        mode=mode,
        image=image,
        env=("OPENAI_API_KEY",),
        config={} if config is None else config,
    )


def test_command_harness_host_mode_writes_public_task_file_and_uses_stdout(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["produce"], "timeout_seconds": 7}),
        workspace_root=tmp_path,
    )

    artifact = producer.produce(mc_task())

    assert artifact.text == "STDOUT-CANDIDATE"
    assert artifact.patch is None
    assert artifact.metadata["mode"] == "host"
    assert artifact.metadata["candidate_kind"] == "text"
    run_sandbox = FakeHostSandbox.instances[-1]
    assert run_sandbox.commands == [(("produce",), None, 7.0)]
    task_payload = json.loads((tmp_path / "mc-1" / "securebench_task.json").read_text())
    assert task_payload == {"question": "2 + 2?", "choices": ["1", "2", "4"]}
    assert "answer" not in task_payload


def test_command_harness_file_backed_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["write-artifact"], "artifact_path": "candidate.txt"}),
        workspace_root=tmp_path,
    )

    artifact = producer.produce(mc_task())

    assert artifact.text == "FILE-CANDIDATE"
    assert artifact.stdout == "ignored stdout"
    assert artifact.metadata["artifact_path"] == "candidate.txt"


def test_command_harness_code_family_uses_text_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": "produce code"}),
        workspace_root=tmp_path,
    )

    artifact = producer.produce(code_task())

    assert artifact.text == "STDOUT-CANDIDATE"
    assert artifact.patch is None
    assert artifact.metadata["candidate_kind"] == "code"


def test_command_harness_patch_family_uses_patch_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["patch"]}),
        workspace_root=tmp_path,
    )

    artifact = producer.produce(repo_patch_task())

    assert artifact.text is None
    assert artifact.patch == "diff --git a/file.py b/file.py\n"
    assert artifact.metadata["candidate_kind"] == "patch"


def test_command_harness_materializes_public_assets(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text("id: pack\nversion: 1\n")
    assets_root = tmp_path / "assets"
    assets_root.mkdir()
    (assets_root / "input.txt").write_text("public input")
    manifest = BenchmarkPackManifest(
        id="pack",
        version=1,
        path=manifest_path,
        asset_defaults=AssetDefaults(read_only=True),
    )
    task = mc_task(manifest, assets=({"path": "input.txt"},))
    producer = build_harness_producer(
        harness_section(config={"command": ["produce"]}),
        workspace_root=tmp_path / "runs",
    )

    producer.produce(task)

    assert (tmp_path / "runs" / "mc-1" / "input.txt").read_text() == "public input"


def test_command_harness_container_mode_uses_docker_and_read_only_asset_mounts(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.DockerSandbox", FakeDockerSandbox)
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text("id: pack\nversion: 1\n")
    assets_root = tmp_path / "assets"
    assets_root.mkdir()
    (assets_root / "input.txt").write_text("public input")
    manifest = BenchmarkPackManifest(
        id="pack",
        version=1,
        path=manifest_path,
        asset_defaults=AssetDefaults(read_only=True),
    )
    task = mc_task(manifest, assets=({"path": "input.txt"},))
    producer = build_harness_producer(
        harness_section(
            mode="container",
            image="securebench-command:0.1",
            config={"command": ["produce"]},
        ),
        workspace_root=tmp_path / "runs",
    )

    producer.produce(task)

    docker = FakeDockerSandbox.instances[-1]
    assert docker.image == "securebench-command:0.1"
    assert docker.env_names == ("OPENAI_API_KEY",)
    assert len(docker.mounts) == 1
    assert docker.mounts[0].target == "input.txt"
    assert docker.mounts[0].read_only is True
    assert docker.mounts[0].source == tmp_path / "runs" / "mc-1" / "input.txt"


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({}, "command"),
        ({"command": "   "}, "command"),
        ({"command": []}, "command"),
        ({"command": ["python", "   "]}, "command"),
        ({"command": ["python", ""]}, "command"),
        ({"command": ["python"], "timeout_seconds": 0}, "timeout_seconds"),
        ({"command": ["python"], "artifact_path": "   "}, "artifact_path"),
        ({"command": ["python"], "artifact_path": "../candidate.txt"}, "artifact_path"),
        ({"command": ["python"], "task_file": "securebench/evaluation_inputs/task.json"}, "task_file"),
        ({"command": ["python"], "unknown": True}, "unsupported field"),
    ],
)
def test_command_harness_rejects_invalid_config(config, match):
    with pytest.raises(ConfigError, match=match):
        build_harness_producer(harness_section(config=config))


@pytest.mark.parametrize("harness_type", ["submission", "codex", "claude_code"])
def test_deferred_harness_types_fail_clearly(harness_type):
    mode = "submission" if harness_type == "submission" else "host"
    path = Path("submission.jsonl") if harness_type == "submission" else None
    harness = HarnessSection(type=harness_type, mode=mode, path=path)

    with pytest.raises(ConfigError, match="not implemented yet"):
        build_harness_producer(harness)


def test_command_harness_workspace_names_avoid_sanitized_id_collisions(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["produce"]}),
        workspace_root=tmp_path,
    )
    task_with_slash = compile_benchmark_row(
        BenchmarkRow(
            id="suite/task",
            family="multiple_choice",
            input={"question": "2 + 2?", "choices": ["1", "2", "4"]},
            eval={"answer": "4"},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )
    task_with_colon = compile_benchmark_row(
        BenchmarkRow(
            id="suite:task",
            family="multiple_choice",
            input={"question": "3 + 3?", "choices": ["3", "6", "9"]},
            eval={"answer": "6"},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )

    first = producer.produce(task_with_slash)
    second = producer.produce(task_with_colon)

    assert first.metadata["workspace_root"] != second.metadata["workspace_root"]
    assert Path(first.metadata["workspace_root"]).name.startswith("suite_task-")
    assert Path(second.metadata["workspace_root"]).name.startswith("suite_task-")
