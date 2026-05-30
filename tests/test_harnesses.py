import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import securebench.harnesses.claude_code as claude_code_harnesses
import securebench.harnesses.codex as codex_harnesses
from securebench.benchmark_compiler import compile_benchmark_row
from securebench.benchmark_pack import AssetDefaults, BenchmarkPackManifest, BenchmarkRow
from securebench.errors import ConfigError
from securebench.harnesses import ClaudeCodeOverlay, CodexOverlay, DockerPlatform, build_harness_producer
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


class FakeEgressPolicy:
    calls = []

    def __init__(self, allowed_domains):
        self.allowed_domains = tuple(allowed_domains)
        FakeEgressPolicy.calls.append(self.allowed_domains)

    def __enter__(self):
        if not self.allowed_domains:
            return SimpleNamespace(network="none", env={}, allowed_domains=())
        return SimpleNamespace(
            network="securebench-egress",
            env={
                "HTTP_PROXY": "http://securebench-egress-proxy:8080",
                "HTTPS_PROXY": "http://securebench-egress-proxy:8080",
                "ALL_PROXY": "http://securebench-egress-proxy:8080",
                "NO_PROXY": "localhost,127.0.0.1,::1",
                "http_proxy": "http://securebench-egress-proxy:8080",
                "https_proxy": "http://securebench-egress-proxy:8080",
                "all_proxy": "http://securebench-egress-proxy:8080",
                "no_proxy": "localhost,127.0.0.1,::1",
            },
            allowed_domains=self.allowed_domains,
        )

    def __exit__(self, exc_type, exc, traceback):
        return None


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch):
    FakeHostSandbox.instances = []
    FakeDockerSandbox.instances = []
    FakeEgressPolicy.calls = []
    monkeypatch.setattr("securebench.harnesses.command.docker_egress_policy", FakeEgressPolicy)
    monkeypatch.setattr("securebench.harnesses.codex.docker_egress_policy", FakeEgressPolicy)
    monkeypatch.setattr("securebench.harnesses.claude_code.docker_egress_policy", FakeEgressPolicy)


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


def code_task(*, environment=None):
    return compile_benchmark_row(
        BenchmarkRow(
            id="code-1",
            family="code_completion",
            input={"prompt": "Write add."},
            eval={"tests": {"source": "inline", "code": "assert candidate(1, 2) == 3"}},
            environment={} if environment is None else environment,
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def repo_patch_task(*, environment=None):
    return compile_benchmark_row(
        BenchmarkRow(
            id="repo-1",
            family="repo_patch",
            input={"repo": "repo/", "base_commit": "abc123", "instructions": "Fix it."},
            eval={"tests": {"source": "command", "command": "pytest -q"}},
            environment={} if environment is None else environment,
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def terminal_task(*, environment=None):
    return compile_benchmark_row(
        BenchmarkRow(
            id="term-1",
            family="terminal_task",
            input={"instructions": "Create output.txt."},
            eval={"checker": {"source": "pytest", "path": "checks"}},
            environment={} if environment is None else environment,
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def harness_section(*, config=None, harness_type="command"):
    return HarnessSection(
        type=harness_type,
        env=("OPENAI_API_KEY",),
        config={} if config is None else config,
    )


def test_command_harness_writes_public_task_file_and_uses_stdout(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["produce"], "timeout_seconds": 7}),
        workspace_root=tmp_path,
    )

    artifact = producer.produce(mc_task(environment={"image": "python:3.11-slim"}))

    assert artifact.text == "STDOUT-CANDIDATE"
    assert artifact.patch is None
    assert artifact.metadata["candidate_kind"] == "text"
    docker = FakeDockerSandbox.instances[-1]
    assert docker.image == "python:3.11-slim"
    assert docker.kwargs["network"] == "none"
    assert docker.kwargs["env"] == {}
    assert docker.commands == [(("produce",), None, 7.0)]
    task_payload = json.loads((tmp_path / "mc-1" / "task.json").read_text())
    assert task_payload == {"question": "2 + 2?", "choices": ["1", "2", "4"]}
    assert "answer" not in task_payload


def test_command_harness_uses_proxy_network_when_domains_are_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["produce"], "allowed_domains": ["docs.python.org"]}),
        workspace_root=tmp_path,
    )

    artifact = producer.produce(mc_task(environment={"image": "python:3.11-slim"}))

    docker = FakeDockerSandbox.instances[-1]
    assert docker.kwargs["network"] == "securebench-egress"
    assert docker.kwargs["env"]["HTTPS_PROXY"] == "http://securebench-egress-proxy:8080"
    assert artifact.metadata["allowed_domains"] == ("docs.python.org",)
    assert FakeEgressPolicy.calls[-1] == ("docs.python.org",)


def test_command_harness_file_backed_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["write-artifact"], "artifact_path": "candidate.txt"}),
        workspace_root=tmp_path,
    )

    artifact = producer.produce(mc_task(environment={"image": "python:3.11-slim"}))

    assert artifact.text == "FILE-CANDIDATE"
    assert artifact.stdout == "ignored stdout"
    assert artifact.metadata["artifact_path"] == "candidate.txt"


def test_command_harness_code_family_uses_text_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": "produce code"}),
        workspace_root=tmp_path,
    )

    artifact = producer.produce(code_task(environment={"image": "python:3.11-slim"}))

    assert artifact.text == "STDOUT-CANDIDATE"
    assert artifact.patch is None
    assert artifact.metadata["candidate_kind"] == "code"


def test_command_harness_patch_family_uses_patch_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["patch"]}),
        workspace_root=tmp_path,
    )

    artifact = producer.produce(repo_patch_task(environment={"image": "python:3.11-slim"}))

    assert artifact.text is None
    assert artifact.patch == "diff --git a/file.py b/file.py\n"
    assert artifact.metadata["candidate_kind"] == "patch"


def test_command_harness_terminal_family_uses_workspace_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["produce"]}),
        workspace_root=tmp_path,
    )

    artifact = producer.produce(terminal_task(environment={"image": "python:3.11-slim"}))

    assert artifact.text is None
    assert artifact.patch is None
    assert artifact.workspace == str(tmp_path / "term-1")
    assert artifact.metadata["candidate_kind"] == "workspace"
    assert artifact.metadata["candidate_extraction"] == "workspace"


def test_command_harness_uses_task_environment_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["produce"], "timeout_seconds": 7}),
        workspace_root=tmp_path,
    )

    producer.produce(mc_task(environment={"image": "python:3.11-slim", "timeout_seconds": 42}))

    docker = FakeDockerSandbox.instances[-1]
    assert docker.commands == [(("produce",), None, 42.0)]


def test_command_harness_context_timeout_overrides_task_environment_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["produce"], "timeout_seconds": 7}),
        workspace_root=tmp_path,
    )

    producer.produce(
        mc_task(environment={"image": "python:3.11-slim", "timeout_seconds": 42}),
        timeout=3,
    )

    docker = FakeDockerSandbox.instances[-1]
    assert docker.commands == [(("produce",), None, 3.0)]


def test_command_harness_rejects_invalid_task_environment_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(config={"command": ["produce"]}),
        workspace_root=tmp_path,
    )

    with pytest.raises(ConfigError, match="environment.timeout_seconds"):
        producer.produce(mc_task(environment={"image": "python:3.11-slim", "timeout_seconds": 0}))


def test_command_harness_materializes_public_assets(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
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
        harness_section(config={"command": ["produce"]}),
        workspace_root=tmp_path / "runs",
    )

    producer.produce(task)

    assert (tmp_path / "runs" / "mc-1" / "input.txt").read_text() == "public input"


def test_command_harness_uses_docker_and_read_only_asset_mounts(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
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
            config={"command": ["produce"]},
        ),
        workspace_root=tmp_path / "runs",
    )

    producer.produce(task)

    docker = FakeDockerSandbox.instances[-1]
    assert docker.image == "python:3.11-slim"
    assert docker.env_names == ("OPENAI_API_KEY",)
    assert docker.kwargs["network"] == "none"
    assert len(docker.mounts) == 1
    assert docker.mounts[0].target == "input.txt"
    assert docker.mounts[0].read_only is True
    assert docker.mounts[0].source == tmp_path / "runs" / "mc-1" / "input.txt"


def test_command_harness_requires_benchmark_environment_image(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    producer = build_harness_producer(
        harness_section(
            config={"command": ["produce"]},
        ),
        workspace_root=tmp_path / "runs",
    )

    with pytest.raises(ConfigError, match="benchmark environment.image"):
        producer.produce(mc_task())


def test_codex_harness_uses_benchmark_image_and_overlay_mounts(monkeypatch, tmp_path):
    class TextWritingDockerSandbox(FakeDockerSandbox):
        instances = []

        def run(self, command, *, workdir=None, timeout=None):
            self.commands.append((command, workdir, timeout))
            if isinstance(command, str) and "codex exec" in command:
                self.write_file("candidate.txt", "FILE-CANDIDATE")
            return CommandResult(("sh", "-lc", command) if isinstance(command, str) else tuple(command), 0, "ok", "")

    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.codex.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.codex.DockerSandbox", TextWritingDockerSandbox)
    overlay_path = tmp_path / "codex-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses.codex.codex_overlay_for_image",
        lambda image, version: CodexOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="arm64"),
            version=version,
        ),
    )
    task = mc_task(environment={"image": "python:3.11-slim"})
    producer = build_harness_producer(
        harness_section(
            harness_type="codex",
            config={"model": "gpt-5.1-codex", "version": "0.30.0", "timeout_seconds": 11},
        ),
        workspace_root=tmp_path / "runs",
    )

    artifact = producer.produce(task)

    docker = FakeDockerSandbox.instances[-1]
    assert docker.image == "python:3.11-slim"
    assert docker.env_names == ("OPENAI_API_KEY",)
    assert docker.kwargs["network"] == "securebench-egress"
    assert docker.kwargs["env"]["HTTPS_PROXY"] == "http://securebench-egress-proxy:8080"
    assert docker.kwargs["read_only"] is False
    assert len(docker.mounts) == 2
    assert docker.mounts[0].source == overlay_path
    assert docker.mounts[0].target == "/opt/securebench/codex"
    assert docker.mounts[0].read_only is True
    assert docker.mounts[1].target == "/opt/securebench/codex-home"
    assert docker.mounts[1].read_only is False
    assert docker.commands[0][0].startswith("export HOME=")
    assert "codex --version" in docker.commands[0][0]
    assert "codex exec --model 'gpt-5.1-codex' --json" in docker.commands[1][0]
    assert "--skip-git-repo-check" in docker.commands[1][0]
    assert "--dangerously-bypass-approvals-and-sandbox" in docker.commands[1][0]
    assert "/workspace/task.json" in docker.commands[1][0]
    assert docker.commands[1][1] is None
    assert docker.commands[0][2] == 11.0
    assert docker.commands[1][2] == 11.0
    assert (tmp_path / "runs" / "mc-1" / "task.json").exists()
    assert artifact.text == "FILE-CANDIDATE"
    assert artifact.patch is None
    assert artifact.metadata["harness"] == "codex"
    assert artifact.metadata["codex_model"] == "gpt-5.1-codex"
    assert artifact.metadata["allowed_domains"] == ("api.openai.com",)
    assert FakeEgressPolicy.calls[-1] == ("api.openai.com",)
    assert artifact.metadata["overlay_platform"] == "linux/arm64"
    assert artifact.metadata["candidate_extraction"] == "file"
    assert artifact.metadata["candidate_path"] == "candidate.txt"


def test_codex_harness_extracts_code_completion_candidate_file(monkeypatch, tmp_path):
    class CodeWritingDockerSandbox(FakeDockerSandbox):
        instances = []

        def run(self, command, *, workdir=None, timeout=None):
            self.commands.append((command, workdir, timeout))
            if isinstance(command, str) and "codex exec" in command:
                self.write_file("candidate.py", "def add(a, b):\n    return a + b\n")
            return CommandResult(("sh", "-lc", command) if isinstance(command, str) else tuple(command), 0, "ok", "")

    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.codex.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.codex.DockerSandbox", CodeWritingDockerSandbox)
    overlay_path = tmp_path / "codex-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses.codex.codex_overlay_for_image",
        lambda image, version: CodexOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="amd64"),
            version=version,
        ),
    )
    producer = build_harness_producer(
        HarnessSection(type="codex", config={"model": "gpt-5.1-codex"}),
        workspace_root=tmp_path / "runs",
    )

    artifact = producer.produce(code_task(environment={"image": "python:3.11-slim"}))

    assert artifact.text == "def add(a, b):\n    return a + b\n"
    assert artifact.patch is None
    assert artifact.metadata["candidate_kind"] == "code"
    assert artifact.metadata["candidate_extraction"] == "file"
    assert artifact.metadata["candidate_path"] == "candidate.py"


def test_codex_harness_fails_when_code_candidate_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.codex.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.codex.DockerSandbox", FakeDockerSandbox)
    overlay_path = tmp_path / "codex-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses.codex.codex_overlay_for_image",
        lambda image, version: CodexOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="amd64"),
            version=version,
        ),
    )
    producer = build_harness_producer(
        HarnessSection(type="codex", config={"model": "gpt-5.1-codex"}),
        workspace_root=tmp_path / "runs",
    )

    with pytest.raises(ConfigError, match="candidate.py"):
        producer.produce(code_task(environment={"image": "python:3.11-slim"}))


def test_codex_harness_extracts_repo_patch_diff(monkeypatch, tmp_path):
    class DiffingDockerSandbox(FakeDockerSandbox):
        instances = []

        def run(self, command, *, workdir=None, timeout=None):
            self.commands.append((command, workdir, timeout))
            if tuple(command) == ("git", "diff", "--binary"):
                return CommandResult(tuple(command), 0, "diff --git a/app.py b/app.py\n", "")
            return CommandResult(("sh", "-lc", command) if isinstance(command, str) else tuple(command), 0, "ok", "")

    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.codex.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.codex.DockerSandbox", DiffingDockerSandbox)
    overlay_path = tmp_path / "codex-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses.codex.codex_overlay_for_image",
        lambda image, version: CodexOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="amd64"),
            version=version,
        ),
    )
    producer = build_harness_producer(
        HarnessSection(type="codex", config={"model": "gpt-5.1-codex"}),
        workspace_root=tmp_path / "runs",
    )

    artifact = producer.produce(
        repo_patch_task(environment={"image": "python:3.11-slim", "workdir": "/workspace/repo"})
    )

    assert artifact.text is None
    assert artifact.patch == "diff --git a/app.py b/app.py\n"
    assert artifact.metadata["candidate_kind"] == "patch"
    assert artifact.metadata["candidate_extraction"] == "git_diff"
    assert artifact.metadata["candidate_workdir"] == "/workspace/repo"
    assert artifact.metadata["candidate_diff_exit_code"] == 0
    assert artifact.metadata["repo_patch_baseline"] == "committed"
    docker = FakeDockerSandbox.instances[-1]
    assert docker.commands[1] == (["git", "status", "--porcelain=v1"], "/workspace/repo", 900.0)
    assert docker.commands[2] == (["git", "add", "-A"], "/workspace/repo", 900.0)
    assert docker.commands[3][0][:6] == [
        "git",
        "-c",
        "user.name=SecureBench",
        "-c",
        "user.email=securebench@example.invalid",
        "commit",
    ]
    assert docker.commands[3][1] == "/workspace/repo"
    assert docker.commands[4][1] == "/workspace/repo"
    assert "/workspace/task.json" in docker.commands[4][0]
    assert "current working directory" in docker.commands[4][0]
    assert "Do not clone the repository" in docker.commands[4][0]
    assert "do not edit tests" in docker.commands[4][0]
    assert docker.commands[-1] == (["git", "diff", "--binary"], "/workspace/repo", 900.0)


def test_codex_harness_defaults_to_openai_api_key(monkeypatch, tmp_path):
    class TextWritingDockerSandbox(FakeDockerSandbox):
        instances = []

        def run(self, command, *, workdir=None, timeout=None):
            self.commands.append((command, workdir, timeout))
            if isinstance(command, str) and "codex exec" in command:
                self.write_file("candidate.txt", "C")
            return CommandResult(("sh", "-lc", command) if isinstance(command, str) else tuple(command), 0, "ok", "")

    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.codex.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.codex.DockerSandbox", TextWritingDockerSandbox)
    overlay_path = tmp_path / "codex-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses.codex.codex_overlay_for_image",
        lambda image, version: CodexOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="amd64"),
            version=version,
        ),
    )
    task = mc_task(environment={"image": "python:3.11-slim"})
    harness = HarnessSection(type="codex", config={"model": "gpt-5.1-codex"})

    producer = build_harness_producer(harness, workspace_root=tmp_path / "runs")
    producer.produce(task)

    assert FakeDockerSandbox.instances[-1].env_names == ("OPENAI_API_KEY",)
    assert FakeEgressPolicy.calls[-1] == ("api.openai.com",)


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({}, "model"),
        ({"model": ""}, "model"),
        ({"model": "bad/model"}, "model"),
        ({"model": "gpt-5.1-codex", "unknown": True}, "unsupported field"),
        ({"model": "gpt-5.1-codex", "allowed_domains": ["https://example.com"]}, "allowed_domains"),
    ],
)
def test_codex_harness_rejects_invalid_config(config, match):
    with pytest.raises(ConfigError, match=match):
        build_harness_producer(HarnessSection(type="codex", config=config))


def test_codex_harness_requires_benchmark_environment_image(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    producer = build_harness_producer(
        HarnessSection(type="codex", config={"model": "gpt-5.1-codex"}),
        workspace_root=tmp_path / "runs",
    )

    with pytest.raises(ConfigError, match="benchmark environment.image"):
        producer.produce(mc_task())


def test_codex_harness_requires_openai_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    producer = build_harness_producer(
        HarnessSection(type="codex", config={"model": "gpt-5.1-codex"}),
        workspace_root=tmp_path / "runs",
    )

    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        producer.produce(mc_task(environment={"image": "python:3.11-slim"}))


def test_codex_harness_reports_preflight_failure(monkeypatch, tmp_path):
    class FailingPreflightDockerSandbox(FakeDockerSandbox):
        instances = []

        def run(self, command, *, workdir=None, timeout=None):
            self.commands.append((command, workdir, timeout))
            return CommandResult(("sh", "-lc", command), 127, "", "codex: not found")

    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.codex.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.codex.DockerSandbox", FailingPreflightDockerSandbox)
    overlay_path = tmp_path / "codex-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses.codex.codex_overlay_for_image",
        lambda image, version: CodexOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="amd64"),
            version=version,
        ),
    )
    producer = build_harness_producer(
        HarnessSection(type="codex", config={"model": "gpt-5.1-codex"}),
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

    platform = codex_harnesses.docker_image_platform("benchmark-image")

    assert platform.cache_key == cache_key
    assert platform.docker_platform == docker_platform


def test_codex_overlay_cache_key_includes_version_and_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("SECUREBENCH_AGENT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(
        codex_harnesses,
        "docker_image_platform",
        lambda image: DockerPlatform(os="linux", architecture="arm64"),
    )

    def fake_populate(path, version, platform):
        (path / "bin").mkdir(parents=True)
        (path / "bin" / "codex").write_text("binary")
        (path / "bin" / "node").write_text("node")

    monkeypatch.setattr(codex_harnesses, "populate_codex_overlay_cache", fake_populate)

    overlay = codex_harnesses.codex_overlay_for_image("benchmark-image", "0.30.0")

    assert overlay.path == tmp_path / "cache" / "codex" / "0.30.0" / "linux-arm64"
    assert overlay.platform.docker_platform == "linux/arm64"
    assert overlay.version == "0.30.0"


def test_codex_overlay_repopulates_when_node_runtime_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SECUREBENCH_AGENT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(
        codex_harnesses,
        "docker_image_platform",
        lambda image: DockerPlatform(os="linux", architecture="amd64"),
    )
    overlay_path = tmp_path / "cache" / "codex" / "0.30.0" / "linux-amd64"
    (overlay_path / "bin").mkdir(parents=True)
    (overlay_path / "bin" / "codex").write_text("binary")
    calls = []

    def fake_populate(path, version, platform):
        calls.append((path, version, platform.cache_key))
        (path / "bin" / "node").write_text("node")

    monkeypatch.setattr(codex_harnesses, "populate_codex_overlay_cache", fake_populate)

    overlay = codex_harnesses.codex_overlay_for_image("benchmark-image", "0.30.0")

    assert overlay.path == overlay_path
    assert calls == [(overlay_path, "0.30.0", "linux-amd64")]
    assert (overlay_path / "bin" / "node").exists()


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
        ({"command": ["python"], "allowed_domains": ["127.0.0.1"]}, "allowed_domains"),
        ({"command": ["python"], "unknown": True}, "unsupported field"),
    ],
)
def test_command_harness_rejects_invalid_config(config, match):
    with pytest.raises(ConfigError, match=match):
        build_harness_producer(harness_section(config=config))


def test_claude_code_harness_uses_benchmark_image_and_overlay_mounts(monkeypatch, tmp_path):
    class TextWritingDockerSandbox(FakeDockerSandbox):
        instances = []

        def run(self, command, *, workdir=None, timeout=None):
            self.commands.append((command, workdir, timeout))
            if isinstance(command, str) and "claude -p" in command:
                self.write_file("candidate.txt", "FILE-CANDIDATE")
            return CommandResult(("sh", "-lc", command) if isinstance(command, str) else tuple(command), 0, "ok", "")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.claude_code.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.claude_code.DockerSandbox", TextWritingDockerSandbox)
    overlay_path = tmp_path / "claude-code-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses.claude_code.claude_code_overlay_for_image",
        lambda image, version: ClaudeCodeOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="arm64"),
            version=version,
        ),
    )
    task = mc_task(environment={"image": "python:3.11-slim"})
    producer = build_harness_producer(
        HarnessSection(
            type="claude_code",
            config={"model": "claude-sonnet-4-5", "version": "1.2.3", "timeout_seconds": 13},
        ),
        workspace_root=tmp_path / "runs",
    )

    artifact = producer.produce(task)

    docker = FakeDockerSandbox.instances[-1]
    assert docker.image == "python:3.11-slim"
    assert docker.env_names == ("ANTHROPIC_API_KEY",)
    assert docker.kwargs["network"] == "securebench-egress"
    assert docker.kwargs["env"]["HTTPS_PROXY"] == "http://securebench-egress-proxy:8080"
    assert docker.kwargs["read_only"] is False
    assert len(docker.mounts) == 2
    assert docker.mounts[0].source == overlay_path
    assert docker.mounts[0].target == "/opt/securebench/claude-code"
    assert docker.mounts[0].read_only is True
    assert docker.mounts[1].target == "/opt/securebench/claude-home"
    assert docker.mounts[1].read_only is False
    assert docker.commands[0][0].startswith("export HOME=")
    assert "claude --version" in docker.commands[0][0]
    assert "claude -p --model 'claude-sonnet-4-5' --output-format json" in docker.commands[1][0]
    assert "--dangerously-skip-permissions" in docker.commands[1][0]
    assert "--no-session-persistence" in docker.commands[1][0]
    assert "/workspace/task.json" in docker.commands[1][0]
    assert docker.commands[1][1] is None
    assert docker.commands[0][2] == 13.0
    assert docker.commands[1][2] == 13.0
    assert artifact.text == "FILE-CANDIDATE"
    assert artifact.patch is None
    assert artifact.metadata["harness"] == "claude_code"
    assert artifact.metadata["claude_code_model"] == "claude-sonnet-4-5"
    assert artifact.metadata["allowed_domains"] == ("api.anthropic.com",)
    assert FakeEgressPolicy.calls[-1] == ("api.anthropic.com",)
    assert artifact.metadata["overlay_platform"] == "linux/arm64"
    assert artifact.metadata["candidate_extraction"] == "file"
    assert artifact.metadata["candidate_path"] == "candidate.txt"


def test_claude_code_harness_defaults_to_anthropic_api_key(monkeypatch, tmp_path):
    class TextWritingDockerSandbox(FakeDockerSandbox):
        instances = []

        def run(self, command, *, workdir=None, timeout=None):
            self.commands.append((command, workdir, timeout))
            if isinstance(command, str) and "claude -p" in command:
                self.write_file("candidate.txt", "C")
            return CommandResult(("sh", "-lc", command) if isinstance(command, str) else tuple(command), 0, "ok", "")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setattr("securebench.harnesses.claude_code.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.claude_code.DockerSandbox", TextWritingDockerSandbox)
    overlay_path = tmp_path / "claude-code-overlay"
    overlay_path.mkdir()
    monkeypatch.setattr(
        "securebench.harnesses.claude_code.claude_code_overlay_for_image",
        lambda image, version: ClaudeCodeOverlay(
            path=overlay_path,
            platform=DockerPlatform(os="linux", architecture="amd64"),
            version=version,
        ),
    )

    producer = build_harness_producer(
        HarnessSection(type="claude_code"),
        workspace_root=tmp_path / "runs",
    )
    producer.produce(mc_task(environment={"image": "python:3.11-slim"}))

    docker = FakeDockerSandbox.instances[-1]
    assert docker.env_names == ("ANTHROPIC_API_KEY",)
    assert FakeEgressPolicy.calls[-1] == ("api.anthropic.com",)
    assert "claude -p --model 'sonnet'" in docker.commands[1][0]


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({"model": ""}, "model"),
        ({"model": "bad/model"}, "model"),
        ({"version": ""}, "version"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"task_file": "../task.json"}, "task_file"),
        ({"allowed_domains": ["localhost"]}, "allowed_domains"),
        ({"unknown": True}, "unsupported field"),
    ],
)
def test_claude_code_harness_rejects_invalid_config(config, match):
    with pytest.raises(ConfigError, match=match):
        build_harness_producer(HarnessSection(type="claude_code", config=config))


def test_claude_code_harness_requires_anthropic_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    producer = build_harness_producer(
        HarnessSection(type="claude_code"),
        workspace_root=tmp_path / "runs",
    )

    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        producer.produce(mc_task(environment={"image": "python:3.11-slim"}))


def test_claude_code_overlay_cache_key_includes_version_and_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("SECUREBENCH_AGENT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(
        claude_code_harnesses,
        "docker_image_platform",
        lambda image: DockerPlatform(os="linux", architecture="arm64"),
    )

    def fake_populate(path, version, platform):
        (path / "bin").mkdir(parents=True)
        (path / "bin" / "claude").write_text("binary")
        (path / "bin" / "node").write_text("node")

    monkeypatch.setattr(claude_code_harnesses, "populate_claude_code_overlay_cache", fake_populate)

    overlay = claude_code_harnesses.claude_code_overlay_for_image("benchmark-image", "1.2.3")

    assert overlay.path == tmp_path / "cache" / "claude-code" / "1.2.3" / "linux-arm64"
    assert overlay.platform.docker_platform == "linux/arm64"
    assert overlay.version == "1.2.3"


def test_command_harness_workspace_names_avoid_sanitized_id_collisions(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.harnesses.command.HostSandbox", FakeHostSandbox)
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
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
            environment={"image": "python:3.11-slim"},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )
    task_with_colon = compile_benchmark_row(
        BenchmarkRow(
            id="suite:task",
            family="multiple_choice",
            input={"question": "3 + 3?", "choices": ["3", "6", "9"]},
            eval={"answer": "6"},
            environment={"image": "python:3.11-slim"},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )

    first = producer.produce(task_with_slash)
    second = producer.produce(task_with_colon)

    assert first.metadata["workspace_root"] != second.metadata["workspace_root"]
    assert Path(first.metadata["workspace_root"]).name.startswith("suite_task-")
    assert Path(second.metadata["workspace_root"]).name.startswith("suite_task-")
