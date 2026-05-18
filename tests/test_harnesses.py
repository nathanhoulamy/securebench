import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import securebench.harnesses as harnesses
from securebench.benchmark_compiler import compile_benchmark_row
from securebench.benchmark_pack import AssetDefaults, BenchmarkPackManifest, BenchmarkRow
from securebench.errors import ConfigError
from securebench.harnesses import CodexOverlay, DockerPlatform, build_harness_producer
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


def mc_task(manifest=None, *, assets=(), environment=None):
    return compile_benchmark_row(
        BenchmarkRow(
            id="mc-1",
            family="multiple_choice",
            input={"question": "2 + 2?", "choices": ["1", "2", "4"]},
            assets=assets,
            eval={"answer": "4"},
            environment={} if environment is None else environment,
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


def harness_section(*, mode="host", config=None, harness_type="command"):
    return HarnessSection(
        type=harness_type,
        mode=mode,
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
    task = mc_task(manifest, assets=({"path": "input.txt"},), environment={"image": "python:3.11-slim"})
    producer = build_harness_producer(
        harness_section(
            mode="container",
            config={"command": ["produce"]},
        ),
        workspace_root=tmp_path / "runs",
    )

    producer.produce(task)

    docker = FakeDockerSandbox.instances[-1]
    assert docker.image == "python:3.11-slim"
    assert docker.env_names == ("OPENAI_API_KEY",)
    assert len(docker.mounts) == 1
    assert docker.mounts[0].target == "input.txt"
    assert docker.mounts[0].read_only is True
    assert docker.mounts[0].source == tmp_path / "runs" / "mc-1" / "input.txt"


def test_command_harness_container_mode_requires_benchmark_environment_image(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(
            mode="container",
            config={"command": ["produce"]},
        ),
        workspace_root=tmp_path / "runs",
    )

    with pytest.raises(ConfigError, match="benchmark environment.image"):
        producer.produce(mc_task())


def test_codex_mounted_harness_uses_benchmark_image_and_overlay_mounts(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.DockerSandbox", FakeDockerSandbox)
    overlay_path = tmp_path / "codex-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses._codex_overlay_for_image",
        lambda image, version: CodexOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="arm64"),
            version=version,
        ),
    )
    task = mc_task(environment={"image": "python:3.11-slim"})
    producer = build_harness_producer(
        harness_section(
            mode="mounted",
            harness_type="codex",
            config={"version": "0.30.0", "timeout_seconds": 11},
        ),
        workspace_root=tmp_path / "runs",
    )

    artifact = producer.produce(task)

    docker = FakeDockerSandbox.instances[-1]
    assert docker.image == "python:3.11-slim"
    assert docker.env_names == ("OPENAI_API_KEY", "CODEX_API_KEY")
    assert docker.kwargs["network"] == "bridge"
    assert len(docker.mounts) == 2
    assert docker.mounts[0].source == overlay_path
    assert docker.mounts[0].target == "/opt/securebench/codex"
    assert docker.mounts[0].read_only is True
    assert docker.mounts[1].target == "/opt/securebench/codex-home"
    assert docker.mounts[1].read_only is False
    assert docker.commands[0][0].startswith("export HOME=")
    assert "codex --version" in docker.commands[0][0]
    assert "codex exec --json" in docker.commands[1][0]
    assert "--skip-git-repo-check" in docker.commands[1][0]
    assert "--dangerously-bypass-approvals-and-sandbox" in docker.commands[1][0]
    assert docker.commands[0][2] == 11.0
    assert docker.commands[1][2] == 11.0
    assert (tmp_path / "runs" / "mc-1" / "task.json").exists()
    assert artifact.text is None
    assert artifact.patch is None
    assert artifact.metadata["harness"] == "codex"
    assert artifact.metadata["mode"] == "mounted"
    assert artifact.metadata["overlay_platform"] == "linux/arm64"
    assert artifact.metadata["candidate_extraction"] == "todo"


def test_codex_mounted_harness_defaults_to_codex_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.DockerSandbox", FakeDockerSandbox)
    overlay_path = tmp_path / "codex-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses._codex_overlay_for_image",
        lambda image, version: CodexOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="amd64"),
            version=version,
        ),
    )
    task = mc_task(environment={"image": "python:3.11-slim"})
    harness = HarnessSection(type="codex", mode="mounted", config={})

    producer = build_harness_producer(harness, workspace_root=tmp_path / "runs")
    producer.produce(task)

    assert FakeDockerSandbox.instances[-1].env_names == ("CODEX_API_KEY",)


@pytest.mark.parametrize("mode", ["host", "container"])
def test_codex_harness_rejects_non_mounted_modes(mode):
    harness = HarnessSection(type="codex", mode=mode)

    with pytest.raises(ConfigError, match="codex harness mode must be 'mounted'"):
        build_harness_producer(harness)


def test_codex_mounted_harness_requires_benchmark_environment_image(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_API_KEY", "secret")
    producer = build_harness_producer(
        HarnessSection(type="codex", mode="mounted"),
        workspace_root=tmp_path / "runs",
    )

    with pytest.raises(ConfigError, match="benchmark environment.image"):
        producer.produce(mc_task())


def test_codex_mounted_harness_requires_codex_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    producer = build_harness_producer(
        HarnessSection(type="codex", mode="mounted"),
        workspace_root=tmp_path / "runs",
    )

    with pytest.raises(ConfigError, match="CODEX_API_KEY"):
        producer.produce(mc_task(environment={"image": "python:3.11-slim"}))


def test_codex_mounted_harness_reports_preflight_failure(monkeypatch, tmp_path):
    class FailingPreflightDockerSandbox(FakeDockerSandbox):
        instances = []

        def run(self, command, *, workdir=None, timeout=None):
            self.commands.append((command, workdir, timeout))
            return CommandResult(("sh", "-lc", command), 127, "", "codex: not found")

    monkeypatch.setenv("CODEX_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.DockerSandbox", FailingPreflightDockerSandbox)
    overlay_path = tmp_path / "codex-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses._codex_overlay_for_image",
        lambda image, version: CodexOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="amd64"),
            version=version,
        ),
    )
    producer = build_harness_producer(
        HarnessSection(type="codex", mode="mounted"),
        workspace_root=tmp_path / "runs",
    )

    with pytest.raises(ConfigError, match="codex --version failed"):
        producer.produce(mc_task(environment={"image": "python:3.11-slim"}))


@pytest.mark.parametrize(
    ("inspect_payload", "cache_key", "docker_platform"),
    [
        ([{"Os": "linux", "Architecture": "amd64"}], "linux-amd64", "linux/amd64"),
        ([{"Os": "linux", "Architecture": "arm64"}], "linux-arm64", "linux/arm64"),
        ([{"Os": "linux", "Architecture": "arm", "Variant": "v7"}], "linux-arm-v7", "linux/arm/v7"),
    ],
)
def test_codex_platform_resolver_maps_docker_inspect(monkeypatch, inspect_payload, cache_key, docker_platform):
    def fake_run(command, **kwargs):
        assert command == ["docker", "image", "inspect", "benchmark-image"]
        return SimpleNamespace(returncode=0, stdout=json.dumps(inspect_payload), stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    platform = harnesses._docker_image_platform("benchmark-image")

    assert platform.cache_key == cache_key
    assert platform.docker_platform == docker_platform


def test_codex_overlay_cache_key_includes_version_and_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("SECUREBENCH_AGENT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(
        harnesses,
        "_docker_image_platform",
        lambda image: DockerPlatform(os="linux", architecture="arm64"),
    )

    def fake_populate(path, version, platform):
        (path / "bin").mkdir(parents=True)
        (path / "bin" / "codex").write_text("binary")

    monkeypatch.setattr(harnesses, "_populate_codex_overlay_cache", fake_populate)

    overlay = harnesses._codex_overlay_for_image("benchmark-image", "0.30.0")

    assert overlay.path == tmp_path / "cache" / "codex" / "0.30.0" / "linux-arm64"
    assert overlay.platform.docker_platform == "linux/arm64"
    assert overlay.version == "0.30.0"


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


@pytest.mark.parametrize("harness_type", ["submission", "claude_code"])
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
