import pytest

from securebench.errors import ConfigError
from securebench.harnesses.registry import build_harness_producer
from securebench.network_policy import NetworkPolicy
from securebench.tester_config import (
    MIN_OVERLAY_WORKSPACE_BYTES,
    load_tester_config,
    parse_tester_config,
)


def valid_tester_config(**overrides):
    data = {
        "schema_version": "1.0",
        "run": {"id": "v2-run", "output_dir": "runs/v2-run"},
        "benchmark": {"manifest": "manifest-v2.yaml", "tasks": "tasks-v2.jsonl"},
        "harness": {"type": "codex", "env": ["OPENAI_API_KEY"]},
    }
    data.update(overrides)
    return data


def test_parse_tester_config_keeps_execution_choices_outside_rows():
    config = parse_tester_config(
        valid_tester_config(
            run={"id": "v2-run", "output_dir": "runs/v2-run", "max_workers": 4},
            docker={
                "max_cached_images": 2,
                "overlay_workspace_bytes": 2147483648,
                "memory_limit": "4g",
            },
        )
    )

    assert config.schema_version == "1.0"
    assert config.run.max_workers == 4
    assert config.harness.type == "codex"
    assert config.harness.env == ("OPENAI_API_KEY",)
    assert config.docker.max_cached_images == 2
    assert config.docker.overlay_workspace_bytes == 2147483648
    assert config.docker.memory_limit == "4g"
    assert config.network_policy.mode == "benchmark"
    assert config.network_policy.allowed_domains == ()
    assert not hasattr(config, "verification")


def test_parse_tester_config_resolves_network_policy_domains():
    config = parse_tester_config(
        valid_tester_config(
            network_policy={
                "mode": "extend",
                "allowed_domains": ["Example.COM", "example.com."],
            }
        )
    )

    assert config.network_policy.mode == "extend"
    assert config.network_policy.allowed_domains == ("example.com",)


def test_parse_tester_config_rejects_nonempty_legacy_harness_domains():
    with pytest.raises(ConfigError, match="move it to top-level network_policy"):
        parse_tester_config(
            valid_tester_config(
                harness={
                    "type": "command",
                    "config": {"allowed_domains": ["example.com"]},
                }
            )
        )


@pytest.mark.parametrize(
    ("harness_type", "harness_config"),
    [
        ("command", {"command": "produce"}),
        ("codex", {"model": "gpt-test"}),
        ("claude_code", {"model": "claude-test"}),
        ("opencode", {}),
    ],
)
def test_registry_forwards_network_policy_to_every_harness(harness_type, harness_config):
    config = parse_tester_config(
        valid_tester_config(
            harness={"type": harness_type, "config": harness_config},
            network_policy={
                "mode": "replace",
                "allowed_domains": ["example.com"],
            },
        )
    )

    producer = build_harness_producer(
        config.harness,
        network_policy=config.network_policy,
    )

    assert producer.network_policy == NetworkPolicy(
        mode="replace",
        allowed_domains=("example.com",),
    )


def test_load_tester_config_resolves_relative_paths(tmp_path):
    path = tmp_path / "configs" / "tester.yaml"
    path.parent.mkdir()
    path.write_text(
        """
schema_version: "1.0"
run:
  id: v2-run
  output_dir: runs/v2-run
benchmark:
  manifest: ../pack/manifest-v2.yaml
  tasks: ../pack/tasks-v2.jsonl
harness:
  type: command
  config:
    command: produce
"""
    )

    config = load_tester_config(path)

    assert config.run.output_dir == path.parent / "runs/v2-run"
    assert config.benchmark.manifest == path.parent / "../pack/manifest-v2.yaml"
    assert config.harness.config == {"command": "produce"}


def test_load_tester_config_rejects_duplicate_mapping_keys(tmp_path):
    path = tmp_path / "tester.yaml"
    path.write_text(
        """
schema_version: "1.0"
run:
  id: first
  id: second
  output_dir: runs/test
benchmark:
  manifest: manifest.yaml
  tasks: tasks.jsonl
harness:
  type: command
""".lstrip()
    )

    with pytest.raises(ConfigError, match="duplicate mapping key"):
        load_tester_config(path)


def test_load_tester_config_rejects_an_oversized_document(tmp_path, monkeypatch):
    path = tmp_path / "tester.yaml"
    path.write_text("x" * 17)
    monkeypatch.setattr("securebench.tester_config.MAX_TESTER_CONFIG_BYTES", 16)

    with pytest.raises(ConfigError, match="size bound"):
        load_tester_config(path)


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"schema_version": "0.2"}, "Unsupported tester schema_version"),
        ({"verification": {}}, "root contains unsupported field"),
        ({"run": "bad"}, "root.run must be an object"),
        ({"benchmark": "bad"}, "root.benchmark must be an object"),
        ({"harness": "bad"}, "root.harness must be an object"),
        ({"docker": {"max_cached_images": 0}}, "must be a positive integer"),
        ({"docker": {"overlay_workspace_bytes": True}}, "positive integer"),
        ({"docker": {"memory_limit": 4}}, "docker.memory_limit must be a size"),
        ({"docker": {"memory_limit": "4 GB"}}, "docker.memory_limit must be a size"),
        ({"docker": {"memory_limit": "0g"}}, "docker.memory_limit must be a size"),
        (
            {"docker": {"overlay_workspace_bytes": MIN_OVERLAY_WORKSPACE_BYTES - 4096}},
            "must be between",
        ),
        (
            {"docker": {"overlay_workspace_bytes": MIN_OVERLAY_WORKSPACE_BYTES + 1}},
            "multiple of 4096",
        ),
        (
            {"run": {"id": "x", "output_dir": "runs/x", "max_workers": True}},
            "must be a positive integer",
        ),
        (
            {"run": {"id": "x" * 257, "output_dir": "runs/x"}},
            "run.id must be at most 256 characters",
        ),
        ({"network_policy": {"mode": "invalid"}}, "network_policy.mode must be one of"),
        (
            {
                "network_policy": {
                    "mode": "benchmark",
                    "allowed_domains": ["example.com"],
                }
            },
            "must be empty when mode is benchmark",
        ),
        ({"harness": {"type": "unknown"}}, "harness.type must be one of"),
        (
            {"harness": {"type": "codex", "env": ["BAD=value"]}},
            "valid environment variable name",
        ),
        (
            {"harness": {"type": "codex", "env": ["BAD-NAME"]}},
            "valid environment variable name",
        ),
        (
            {"harness": {"type": "codex", "env": ["1BAD"]}},
            "valid environment variable name",
        ),
        (
            {"harness": {"type": "codex", "env": ["CUSTOM_ENV", "CUSTOM_ENV"]}},
            "duplicate environment variable",
        ),
    ],
)
def test_tester_config_rejects_invalid_shape(override, match):
    with pytest.raises(ConfigError, match=match):
        parse_tester_config(valid_tester_config(**override))


def test_tester_memory_limit_applies_for_the_run_and_is_restored(monkeypatch):
    import os

    from securebench.sandboxes.docker import DOCKER_MEM_LIMIT_ENV, DockerSandbox
    from securebench.tester_run import docker_memory_limit

    monkeypatch.delenv(DOCKER_MEM_LIMIT_ENV, raising=False)
    with docker_memory_limit("4g"):
        assert DockerSandbox(image="img", root=".").mem_limit == "4g"
    assert DOCKER_MEM_LIMIT_ENV not in os.environ
    assert DockerSandbox(image="img", root=".").mem_limit == "1g"


def test_tester_memory_limit_rejects_a_conflicting_operator_value(monkeypatch):
    from securebench.sandboxes.docker import DOCKER_MEM_LIMIT_ENV
    from securebench.tester_run import docker_memory_limit

    monkeypatch.setenv(DOCKER_MEM_LIMIT_ENV, "2g")
    with pytest.raises(ConfigError, match="conflicts with"):
        with docker_memory_limit("4g"):
            pass


def test_tester_memory_limit_is_part_of_the_execution_identity():
    from securebench.tester_run import execution_config_digest

    harness = {"type": "command", "config": {"command": ["true"]}}
    base = parse_tester_config(valid_tester_config(harness=harness))
    raised = parse_tester_config(
        valid_tester_config(harness=harness, docker={"memory_limit": "4g"})
    )
    assert execution_config_digest(base) != execution_config_digest(raised)


def test_tester_capture_section_parses_and_rejects_bad_values():
    config = parse_tester_config(valid_tester_config(capture={"max_candidate_bytes": 536870912}))
    assert config.capture.max_candidate_bytes == 536870912
    assert parse_tester_config(valid_tester_config()).capture.max_candidate_bytes is None
    for bad in (0, -1, True, "512m"):
        with pytest.raises(ConfigError, match="capture.max_candidate_bytes"):
            parse_tester_config(valid_tester_config(capture={"max_candidate_bytes": bad}))
    with pytest.raises(ConfigError, match="capture contains unsupported field"):
        parse_tester_config(valid_tester_config(capture={"max_bytes": 1}))


def test_tester_candidate_byte_limit_governs_capacity_and_is_restored(monkeypatch):
    import os

    from securebench.execution_profiles import (
        MAX_CANDIDATE_BYTES_ENV,
        MAX_FILE_BUNDLE_BYTES,
        candidate_byte_capacity,
    )
    from securebench.tester_run import candidate_byte_limit

    monkeypatch.delenv(MAX_CANDIDATE_BYTES_ENV, raising=False)
    assert candidate_byte_capacity(MAX_FILE_BUNDLE_BYTES) == MAX_FILE_BUNDLE_BYTES
    with candidate_byte_limit(536870912):
        assert candidate_byte_capacity(MAX_FILE_BUNDLE_BYTES) == 536870912
    assert MAX_CANDIDATE_BYTES_ENV not in os.environ


def test_tester_candidate_byte_limit_is_part_of_the_execution_identity():
    from securebench.tester_run import execution_config_digest

    harness = {"type": "command", "config": {"command": ["true"]}}
    base = parse_tester_config(valid_tester_config(harness=harness))
    raised = parse_tester_config(
        valid_tester_config(harness=harness, capture={"max_candidate_bytes": 536870912})
    )
    assert execution_config_digest(base) != execution_config_digest(raised)
