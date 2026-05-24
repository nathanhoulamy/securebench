from pathlib import Path

import pytest

from securebench.errors import ConfigError
from securebench.tester_config import load_tester_config, parse_tester_config


def valid_tester_config(**overrides):
    data = {
        "schema_version": "0.2",
        "run": {
            "id": "repo-repair-codex",
            "output_dir": "runs/repo-repair-codex",
        },
        "benchmark": {
            "manifest": "./benchmarks/repo-repair/manifest.yaml",
            "tasks": "./benchmarks/repo-repair/tasks.jsonl",
        },
        "harness": {
            "type": "codex",
            "env": ["OPENAI_API_KEY"],
        },
    }
    data.update(overrides)
    return data


def test_parse_tester_config_accepts_codex_harness():
    config = parse_tester_config(valid_tester_config())

    assert config.schema_version == "0.2"
    assert config.run.id == "repo-repair-codex"
    assert config.run.output_dir == Path("runs/repo-repair-codex")
    assert config.benchmark.manifest == Path("benchmarks/repo-repair/manifest.yaml")
    assert config.benchmark.tasks == Path("benchmarks/repo-repair/tasks.jsonl")
    assert config.harness.type == "codex"
    assert config.harness.env == ("OPENAI_API_KEY",)
    assert config.harness.config == {}


def test_parse_tester_config_accepts_codex_harness_without_image():
    config = parse_tester_config(
        valid_tester_config(
            harness={
                "type": "codex",
                "env": ["OPENAI_API_KEY"],
            }
        )
    )

    assert config.harness.type == "codex"
    assert config.harness.env == ("OPENAI_API_KEY",)


def test_parse_tester_config_accepts_claude_code_harness():
    config = parse_tester_config(
        valid_tester_config(
            harness={
                "type": "claude_code",
                "env": ["ANTHROPIC_API_KEY"],
                "config": {"profile": "default"},
            }
        )
    )

    assert config.harness.type == "claude_code"
    assert config.harness.env == ("ANTHROPIC_API_KEY",)
    assert config.harness.config == {"profile": "default"}


def test_parse_tester_config_accepts_command_harness():
    config = parse_tester_config(
        valid_tester_config(
            harness={
                "type": "command",
                "config": {"command": "produce"},
            }
        )
    )

    assert config.harness.type == "command"
    assert config.harness.env == ()
    assert config.harness.config == {"command": "produce"}


def test_load_tester_config_resolves_relative_paths_against_config_file(tmp_path):
    config_path = tmp_path / "configs" / "tester.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        """
schema_version: "0.2"
run:
  id: repo-repair-codex
  output_dir: runs/repo-repair-codex
benchmark:
  manifest: ../benchmarks/repo-repair/manifest.yaml
  tasks: ../benchmarks/repo-repair/tasks.jsonl
harness:
  type: command
  config:
    command: produce
"""
    )

    config = load_tester_config(config_path)

    assert config.run.output_dir == config_path.parent / "runs/repo-repair-codex"
    assert config.benchmark.manifest == config_path.parent / "../benchmarks/repo-repair/manifest.yaml"
    assert config.benchmark.tasks == config_path.parent / "../benchmarks/repo-repair/tasks.jsonl"
    assert config.harness.config == {"command": "produce"}


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"schema_version": "9.9"}, "Unsupported tester schema_version"),
        ({"run": "bad"}, "root.run must be an object"),
        ({"benchmark": "bad"}, "root.benchmark must be an object"),
        ({"harness": "bad"}, "root.harness must be an object"),
        ({"extra": True}, "root contains unsupported field"),
        ({"run": {"id": "x", "output_dir": "runs/x", "limit": 1}}, "run contains unsupported field"),
        (
            {"benchmark": {"manifest": "manifest.yaml", "tasks": "tasks.jsonl", "split": "test"}},
            "benchmark contains unsupported field",
        ),
        (
            {"harness": {"type": "codex", "command": "codex"}},
            "harness contains unsupported field",
        ),
        (
            {"harness": {"type": "codex", "image": "securebench-codex:0.1"}},
            "harness contains unsupported field",
        ),
    ],
)
def test_tester_config_rejects_invalid_shape(override, match):
    with pytest.raises(ConfigError, match=match):
        parse_tester_config(valid_tester_config(**override))


@pytest.mark.parametrize(
    ("harness", "match"),
    [
        ({"type": "unknown"}, "harness.type must be one of"),
        ({"type": "submission"}, "harness.type must be one of"),
        ({"type": "codex", "mode": "mounted"}, "harness contains unsupported field"),
        ({"type": "codex", "path": "results.jsonl"}, "harness contains unsupported field"),
        ({"type": "codex", "env": "OPENAI_API_KEY"}, "harness.env must be a list"),
        ({"type": "codex", "env": ["BAD=value"]}, "without '='"),
        ({"type": "codex", "config": "bad"}, "harness.config must be an object"),
    ],
)
def test_tester_config_rejects_invalid_harness(harness, match):
    with pytest.raises(ConfigError, match=match):
        parse_tester_config(valid_tester_config(harness=harness))


def test_load_tester_config_rejects_non_object_root(tmp_path):
    config_path = tmp_path / "tester.yaml"
    config_path.write_text("- not\n- object\n")

    with pytest.raises(ConfigError, match="Tester config root must be an object"):
        load_tester_config(config_path)
