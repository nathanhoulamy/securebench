import json
from contextlib import contextmanager
from dataclasses import replace

import pytest

from securebench.candidates import CandidateProductionError, CandidateProductionTimeout
from securebench.errors import ConfigError
from securebench.harnesses import opencode
from securebench.harnesses.network import HarnessEgress
from securebench.harnesses.provider_relay import blocked_external_tools, path_allowed
from securebench.harnesses.registry import build_harness_producer, effective_harness_env_names, normalized_harness_config
from securebench.sandboxes import CommandResult
from securebench.schemas.benchmark import FileBundleCandidate, GitPatchCandidate
from securebench.tester_config import parse_tester_config
from test_v2_harness_bridge import compiled_task


def test_config_and_registry():
    config = parse_tester_config({
        "schema_version": "1.0", "run": {"id": "test", "output_dir": "runs/test"},
        "benchmark": {"manifest": "manifest.yaml", "tasks": "tasks.jsonl"},
        "harness": {"type": "opencode", "env": ["ABLIT_KEY", "OPENCODE_CONFIG", "HOME", "XDG_DATA_HOME", "CUSTOM"]},
    })
    assert normalized_harness_config(config.harness) == {
        "provider": "abliteration", "model": "abliterated-model", "version": "1.18.30",
        "task_file": "task.json", "timeout_seconds": 900.0, "allowed_domains": (), "allow_external_tools": False,
    }
    assert effective_harness_env_names(config.harness) == ("CUSTOM",)
    producer = build_harness_producer(config.harness)
    assert isinstance(producer, opencode.OpenCodeHarnessProducer)
    assert producer.env_names == ("CUSTOM",)


@pytest.mark.parametrize("config", [
    {"provider": "unknown"}, {"provider": []}, {"auth": "subscription"},
    {"model": ""}, {"model": "x; echo bad"}, {"version": "latest"}, {"version": "../../bin"},
    {"task_file": "../task.json"}, {"timeout_seconds": -1},
    {"allowed_domains": ["localhost"]}, {"allow_external_tools": "yes"},
])
def test_invalid_config(config):
    with pytest.raises(ConfigError):
        opencode.opencode_config(config)


def test_provider_config_and_relay_restrictions():
    env = opencode.opencode_agent_env({}, "http://relay:8090/v1", provider="abliteration", model="test")
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert config["provider"]["abliteration"]["options"] == {
        "baseURL": "http://relay:8090/v1", "apiKey": "securebench-dummy-api-key",
    }
    assert config["enabled_providers"] == ["abliteration"]
    assert config["small_model"] == "abliteration/test"
    assert config["share"] == "disabled" and config["autoupdate"] is False
    spec = opencode.OPENCODE_PROVIDERS["abliteration"].relay
    assert spec.provider == "openai"
    assert spec.credential_env == "ABLIT_KEY" and spec.credential_kind == "bearer"
    assert spec.upstream_host == "api.abliteration.ai"
    assert spec.allowed_methods == ("POST",)
    assert path_allowed("/v1/chat/completions", spec.allowed_path_prefixes)
    assert not path_allowed("/v1/responses", spec.allowed_path_prefixes)
    for tool, expected in [("function", ()), ("web_search", ("web_search",))]:
        body = json.dumps({"tools": [{"type": tool}]}).encode()
        assert blocked_external_tools(body, False, allowed_client_tool_types=spec.allowed_client_tool_types) == expected


@pytest.mark.parametrize("candidate_type", ["git_patch", "file_bundle"])
@pytest.mark.parametrize("failure", [None, "exit", "timeout", "preflight"])
def test_produce_capture_boundary_and_cleanup(monkeypatch, tmp_path, candidate_type, failure):
    task = compiled_task()
    spec = GitPatchCandidate(type="git_patch", max_patch_bytes=1024, max_changed_files=10, max_changed_bytes=1024) if candidate_type == "git_patch" else FileBundleCandidate(type="file_bundle", max_total_files=1, max_total_bytes=1024, files=[{"id": "answer", "path": "/app/answer.txt", "kind": "regular_file", "max_bytes": 1024}])
    task = replace(task, verification=task.verification.model_copy(update={"candidate": spec}))
    monkeypatch.setenv("ABLIT_KEY", "host-secret")
    monkeypatch.setattr(opencode, "validate_executable_task", lambda task: None)
    monkeypatch.setattr(opencode, "materialize_image_workdir", lambda *args: None)
    monkeypatch.setattr(opencode, "reject_git_patch_framework_collisions", lambda *args, **kwargs: None)
    monkeypatch.setattr(opencode, "restore_untrusted_tree_permissions", lambda *args, **kwargs: None)
    removed = []
    monkeypatch.setattr(opencode, "remove_untrusted_tree", lambda path, **kwargs: removed.append(path))
    monkeypatch.setattr(opencode, "opencode_overlay_for_image", lambda image, version: opencode.OpenCodeOverlay(tmp_path / "tool", opencode.DockerPlatform("linux", "amd64"), version))
    @contextmanager
    def relay(*args, **kwargs):
        yield HarnessEgress(network="isolated", env={}, allowed_domains=(), provider="abliteration", provider_base_url="http://relay/v1")
    monkeypatch.setattr(opencode, "docker_provider_relay_policy", relay)
    instances = []
    class Sandbox:
        def __init__(self, **kwargs):
            self.root = kwargs["root"]
            self.options = kwargs
            self.commands = []
            self.closed = False
            instances.append(self)
        def run(self, command, **kwargs):
            self.commands.append(command)
            preflight = len(self.commands) == 1
            return CommandResult(command=(command,), exit_code=1 if failure == ("preflight" if preflight else "exit") else 0,
                                 timed_out=not preflight and failure == "timeout")
        def close(self):
            self.closed = True
    monkeypatch.setattr(opencode, "DockerSandbox", Sandbox)
    producer = opencode.OpenCodeHarnessProducer(workspace_root=tmp_path / "workspace", env_names=("ABLIT_KEY",))
    if failure:
        error = {"exit": CandidateProductionError, "timeout": CandidateProductionTimeout, "preflight": ConfigError}[failure]
        with pytest.raises(error):
            producer.produce(task)
    else:
        result = producer.produce(task)
        assert result.metadata["candidate_type"] == candidate_type
        assert result.metadata["opencode_version"] == "1.18.30"
        assert result.metadata["provider"] == "abliteration"
    sandbox = instances[0]
    assert sandbox.closed and len(removed) == 1
    assert "host-secret" not in str(sandbox.options)
    assert sandbox.options["env_names"] == ()
    assert sandbox.options["network"] == "isolated"
    if failure != "preflight":
        assert "opencode run --pure --auto --format json" in sandbox.commands[1]
    assert all("XDG_DATA_HOME" in command for command in sandbox.commands)


def test_overlay_cache_installs_once_and_rejects_unsupported_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("SECUREBENCH_AGENT_CACHE", str(tmp_path))
    monkeypatch.setattr(opencode, "docker_image_platform", lambda image: opencode.DockerPlatform("linux", "amd64"))
    calls = []
    def install(path, version, platform):
        calls.append((version, platform))
        (path / "bin").mkdir(parents=True)
        (path / "bin/opencode").write_text("binary")
    monkeypatch.setattr(opencode, "populate_opencode_overlay_cache", install)
    first = opencode.opencode_overlay_for_image("image", "1.18.30")
    assert opencode.opencode_overlay_for_image("image", "1.18.30") == first
    assert len(calls) == 1
    monkeypatch.setattr(opencode, "docker_image_platform", lambda image: opencode.DockerPlatform("linux", "s390x"))
    with pytest.raises(ConfigError, match="Unsupported"):
        opencode.opencode_overlay_for_image("image", "1.18.30")


def test_abliteration_relay_starts_and_injects_host_key(monkeypatch, tmp_path):
    from email.message import Message
    from securebench.harnesses.provider_relay import relay_config_from_env, upstream_headers
    spec = opencode.OPENCODE_PROVIDERS["abliteration"].relay
    for name, value in {
        "SECUREBENCH_PROVIDER": spec.provider,
        "SECUREBENCH_UPSTREAM_HOST": spec.upstream_host,
        "SECUREBENCH_CREDENTIAL_KIND": spec.credential_kind,
        "SECUREBENCH_CREDENTIAL_ENV": spec.credential_env,
        "SECUREBENCH_ALLOWED_PATH_PREFIXES": json.dumps(spec.allowed_path_prefixes),
        "SECUREBENCH_ALLOWED_CLIENT_TOOL_TYPES": json.dumps(spec.allowed_client_tool_types),
        "SECUREBENCH_RELAY_LOG_DIR": str(tmp_path),
        "ABLIT_KEY": "host-secret",
    }.items():
        monkeypatch.setenv(name, value)
    config = relay_config_from_env()
    headers = Message()
    headers["Authorization"] = "Bearer securebench-dummy-api-key"
    forwarded = upstream_headers(config, headers)
    assert forwarded["Authorization"] == "Bearer host-secret"
    assert forwarded["Host"] == "api.abliteration.ai"
    assert config.allowed_path_prefixes == ("/v1/chat/completions",)


def test_failed_install_does_not_publish_cache(monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr(opencode, "run_docker", lambda command: SimpleNamespace(returncode=1, stderr="installation failed"))
    path = tmp_path / "runtime"
    with pytest.raises(ConfigError, match="Failed to populate"):
        opencode.populate_opencode_overlay_cache(path, "1.18.30", opencode.DockerPlatform("linux", "amd64"))
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []
