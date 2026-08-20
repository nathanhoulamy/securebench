from __future__ import annotations

import json
from pathlib import Path

import pytest

from securebench.baselines import path_digest
from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.errors import ConfigError


DIGEST = "sha256:" + "b" * 64


def test_resource_digest_includes_permission_bits(tmp_path):
    resource = tmp_path / "tool.sh"
    resource.write_text("#!/bin/sh\nexit 0\n")
    resource.chmod(0o600)
    before = path_digest(resource)

    resource.chmod(0o700)

    assert path_digest(resource) != before


def test_pack_rejects_non_positive_row_limit(tmp_path):
    manifest, tasks = write_pack(tmp_path)
    pack = load_benchmark_pack(manifest, tasks)

    with pytest.raises(ConfigError, match="limit must be a positive integer"):
        pack.load_rows(limit=0)


def write_pack(root: Path) -> tuple[Path, Path]:
    (root / "assets" / "task").mkdir(parents=True)
    (root / "evaluation_inputs" / "task" / "adapter").mkdir(parents=True)
    (root / "hidden" / "task" / "oracle").mkdir(parents=True)
    (root / "hidden" / "task" / "cases").mkdir(parents=True)
    (root / "assets" / "task" / "input.txt").write_text("public")
    (root / "evaluation_inputs" / "task" / "adapter" / "manifest.json").write_text("{}")
    (root / "hidden" / "task" / "oracle" / "manifest.json").write_text("{}")
    (root / "hidden" / "task" / "cases" / "cases.json").write_text("[]")

    manifest = root / "manifest.yaml"
    manifest.write_text(
        f"""
schema_version: "2.0"
id: v2-pack
defaults:
  family: terminal_task
  environment:
    image: {DIGEST}
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
        "id": "v2/task",
        "input": {"instructions": "Write /app/result.json."},
        "assets": [
            {"path": "task/input.txt", "mount": "/app/input.txt", "read_only": True}
        ],
        "verification": {
            "execution_profile": "strict-split/v1",
            "candidate": {
                "type": "file_bundle",
                "max_total_files": 1,
                "max_total_bytes": 1024,
                "files": [
                    {
                        "id": "result",
                        "path": "/app/result.json",
                        "kind": "regular_file",
                        "max_bytes": 1024,
                    }
                ],
            },
            "resources": {
                "runtime": {
                    "adapter": {"path": "task/adapter", "mount": "/opt/securebench/adapter"}
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
                        "max_cases": 1,
                        "max_case_bytes": 1024,
                    },
                    "limits": {
                        "seconds_per_case": 1,
                        "observation_bytes_per_case": 1024,
                    },
                }
            ],
            "oracle": "host.oracle",
        },
    }
    tasks = root / "tasks.jsonl"
    tasks.write_text(json.dumps(row) + "\n")
    return manifest, tasks


def test_v2_pack_compiles_structural_locations_into_visibility_lanes(tmp_path):
    manifest, tasks = write_pack(tmp_path)

    compiled = next(compile_benchmark_pack(load_benchmark_pack(manifest, tasks)))

    assert compiled.family == "terminal_task"
    assert compiled.agent_payload() == {"instructions": "Write /app/result.json."}
    assert {resource.name for resource in compiled.resources.by_visibility("public")} == {
        "input.instructions",
        "asset.0",
    }
    assert {resource.name for resource in compiled.resources.by_visibility("evaluation_inputs")} == {
        "runtime.adapter"
    }
    assert {resource.name for resource in compiled.resources.by_visibility("hidden")} == {
        "host.cases",
        "host.oracle",
    }
    assert {resource.name for resource in compiled.view_for("agent").resources} == {
        "input.instructions",
        "asset.0",
    }
    assert {resource.name for resource in compiled.view_for("evaluation_runtime").resources} == {
        "input.instructions",
        "asset.0",
        "runtime.adapter",
    }
    assert {resource.name for resource in compiled.view_for("oracle").resources} == {
        "input.instructions",
        "asset.0",
        "host.cases",
        "host.oracle",
    }
    assert compiled.manifest_digest.startswith("sha256:")
    assert compiled.row_digest.startswith("sha256:")


def test_v2_compiler_rejects_runtime_resource_symlink_to_host_lane(tmp_path):
    manifest, tasks = write_pack(tmp_path)
    adapter = tmp_path / "evaluation_inputs" / "task" / "adapter"
    for child in adapter.iterdir():
        child.unlink()
    adapter.rmdir()
    adapter.symlink_to(tmp_path / "hidden" / "task" / "oracle", target_is_directory=True)

    with pytest.raises(ConfigError, match="may not traverse symlink"):
        next(compile_benchmark_pack(load_benchmark_pack(manifest, tasks)))


def test_v2_compiler_rejects_symlinks_inside_resource_directories(tmp_path):
    manifest, tasks = write_pack(tmp_path)
    (tmp_path / "hidden" / "task" / "oracle" / "escape").symlink_to(
        tmp_path / "assets" / "task" / "input.txt"
    )

    with pytest.raises(ConfigError, match="may not contain symlinks"):
        next(compile_benchmark_pack(load_benchmark_pack(manifest, tasks)))


def test_v2_loader_rejects_legacy_manifest(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    tasks = tmp_path / "tasks.jsonl"
    manifest.write_text("id: legacy\nversion: 1\n")
    tasks.write_text("")

    with pytest.raises(ConfigError, match="schema_version"):
        load_benchmark_pack(manifest, tasks)


def test_v2_loader_rejects_duplicate_manifest_keys(tmp_path):
    manifest, tasks = write_pack(tmp_path)
    manifest.write_text(
        manifest.read_text().replace(
            "    agent_network: none\n",
            "    agent_network: none\n    agent_network: internet\n",
        )
    )

    with pytest.raises(ConfigError, match="duplicate mapping key") as error:
        load_benchmark_pack(manifest, tasks)

    assert "internet" not in str(error.value)


def test_v2_loader_rejects_duplicate_row_object_keys(tmp_path):
    manifest, tasks = write_pack(tmp_path)
    row = tasks.read_text().strip()
    tasks.write_text(row[:-1] + ',"id":"shadow/task"}\n')

    with pytest.raises(ConfigError, match="row line 1.*duplicate object key") as error:
        list(load_benchmark_pack(manifest, tasks).iter_rows())

    assert "shadow/task" not in str(error.value)


def test_v2_loader_sanitizes_invalid_row_encoding(tmp_path):
    manifest, tasks = write_pack(tmp_path)
    tasks.write_bytes(b"\xff")

    with pytest.raises(ConfigError, match="rows are not valid UTF-8") as error:
        list(load_benchmark_pack(manifest, tasks).iter_rows())

    assert "\\xff" not in str(error.value)


def test_v2_pack_rejects_duplicate_row_ids(tmp_path):
    manifest, tasks = write_pack(tmp_path)
    original = tasks.read_text()
    tasks.write_text(original + original)

    with pytest.raises(ConfigError, match="duplicate row id"):
        list(load_benchmark_pack(manifest, tasks).iter_rows())
