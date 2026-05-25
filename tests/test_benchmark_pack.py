import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import (
    AssetDefaults,
    AssetRoots,
    BenchmarkDefaults,
    BenchmarkPackManifest,
    load_benchmark_manifest,
    load_benchmark_pack,
    parse_benchmark_manifest,
)
from securebench.errors import ConfigError


def test_minimal_manifest_loads_with_asset_defaults():
    manifest = parse_benchmark_manifest({"id": "example-pack", "version": 1})

    assert manifest == BenchmarkPackManifest(
        id="example-pack",
        version=1,
        defaults=BenchmarkDefaults(),
        asset_roots=AssetRoots(public="assets/", eval="hidden/"),
        asset_defaults=AssetDefaults(read_only=True),
        path=None,
    )


def test_manifest_loads_defaults_and_paths(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        """
id: example-pack
version: 1

defaults:
  family: terminal_task
  environment:
    image: python:3.11-slim
    setup:
      - pip install -e .
    network: none
    timeout_seconds: 30

asset_roots:
  public: public_assets/
  eval: private_assets/

asset_defaults:
  read_only: false
"""
    )

    manifest = load_benchmark_manifest(manifest_path)

    assert manifest.id == "example-pack"
    assert manifest.version == 1
    assert manifest.defaults.family == "terminal_task"
    assert manifest.defaults.environment == {
        "image": "python:3.11-slim",
        "setup": ["pip install -e ."],
        "network": "none",
        "timeout_seconds": 30,
    }
    assert manifest.asset_roots == AssetRoots(public="public_assets/", eval="private_assets/")
    assert manifest.asset_defaults == AssetDefaults(read_only=False)
    assert manifest.path == manifest_path


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"version": 1}, "manifest.id"),
        ({"id": "", "version": 1}, "manifest.id"),
        ({"id": "example-pack"}, "manifest.version"),
        ({"id": "example-pack", "version": "1"}, "manifest.version"),
        ({"id": "example-pack", "version": True}, "manifest.version"),
        ({"id": "example-pack", "version": 1, "defaults": []}, "manifest.defaults"),
        ({"id": "example-pack", "version": 1, "defaults": {"environment": []}}, "defaults.environment"),
        ({"id": "example-pack", "version": 1, "asset_roots": []}, "asset_roots"),
        ({"id": "example-pack", "version": 1, "asset_defaults": []}, "asset_defaults"),
        (
            {"id": "example-pack", "version": 1, "asset_defaults": {"read_only": "yes"}},
            "asset_defaults.read_only",
        ),
    ],
)
def test_manifest_validation_errors(data, message):
    with pytest.raises(ConfigError, match=message):
        parse_benchmark_manifest(data)


@pytest.mark.parametrize(
    "root",
    ["", "/assets", "../assets", "assets/../hidden", r"assets\\public", "."],
)
def test_manifest_rejects_unsafe_asset_roots(root):
    with pytest.raises(ConfigError, match="asset_roots.public"):
        parse_benchmark_manifest(
            {
                "id": "example-pack",
                "version": 1,
                "asset_roots": {
                    "public": root,
                },
            }
        )


def test_jsonl_rows_apply_default_family_and_environment(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    manifest_path.write_text(
        """
id: example-pack
version: 1
defaults:
  family: terminal_task
  environment:
    image: python:3.11-slim
    network: none
    timeout_seconds: 30
"""
    )
    tasks_path.write_text(
        '{"id":"task-1","input":{"instructions":"Do thing."}}\n'
        '{"id":"task-2","family":"artifact_task","environment":{"timeout_seconds":120},"input":{"brief":"Create report."}}\n'
    )

    rows = load_benchmark_pack(manifest_path, tasks_path).load_rows()

    assert rows[0].id == "task-1"
    assert rows[0].family == "terminal_task"
    assert rows[0].input == {"instructions": "Do thing."}
    assert rows[0].assets == ()
    assert rows[0].eval == {}
    assert rows[0].environment == {
        "image": "python:3.11-slim",
        "network": "none",
        "timeout_seconds": 30,
    }
    assert rows[0].metadata == {}

    assert rows[1].family == "artifact_task"
    assert rows[1].environment == {
        "image": "python:3.11-slim",
        "network": "none",
        "timeout_seconds": 120,
    }


def test_terminal_task_image_workdir_materialization_flag_is_preserved(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    manifest_path.write_text(
        """
id: example-pack
version: 1
defaults:
  family: terminal_task
  environment:
    image: task-image:latest
    workdir: /app
"""
    )
    tasks_path.write_text(
        '{"id":"task-1","environment":{"materialize_workdir_from_image":true},'
        '"input":{"instructions":"Edit the image-prepared workspace."},'
        '"eval":{"checker":{"command":"true"}}}\n'
    )

    pack = load_benchmark_pack(manifest_path, tasks_path)
    row = pack.load_rows()[0]

    assert row.environment == {
        "image": "task-image:latest",
        "workdir": "/app",
        "materialize_workdir_from_image": True,
    }
    task = next(compile_benchmark_pack(pack))
    assert task.metadata["environment"]["materialize_workdir_from_image"] is True


def test_row_family_overrides_manifest_default(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    manifest_path.write_text("id: example-pack\nversion: 1\ndefaults:\n  family: terminal_task\n")
    tasks_path.write_text('{"id":"task-1","family":"repo_patch"}\n')

    row = load_benchmark_pack(manifest_path, tasks_path).load_rows()[0]

    assert row.family == "repo_patch"


def test_missing_family_errors_without_manifest_default(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    manifest_path.write_text("id: example-pack\nversion: 1\n")
    tasks_path.write_text('{"id":"task-1"}\n')

    with pytest.raises(ConfigError, match="family is required"):
        load_benchmark_pack(manifest_path, tasks_path).load_rows()


def test_row_sections_are_validated(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text("id: example-pack\nversion: 1\ndefaults:\n  family: terminal_task\n")

    invalid_rows = [
        ('{"id":"","input":{}}\n', "benchmark row line 1.id"),
        ('{"id":"task-1","input":[]}\n', "input"),
        ('{"id":"task-1","eval":[]}\n', "eval"),
        ('{"id":"task-1","environment":[]}\n', "environment"),
        ('{"id":"task-1","metadata":[]}\n', "metadata"),
        ('{"id":"task-1","assets":{}}\n', "assets"),
        ('{"id":"task-1","assets":[1]}\n', r"assets\[0\]"),
    ]
    for content, message in invalid_rows:
        tasks_path = manifest_path.parent / "tasks.jsonl"
        tasks_path.write_text(content)
        with pytest.raises(ConfigError, match=message):
            load_benchmark_pack(manifest_path, tasks_path).load_rows()


def test_invalid_jsonl_reports_file_and_line_number(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    manifest_path.write_text("id: example-pack\nversion: 1\ndefaults:\n  family: terminal_task\n")
    tasks_path.write_text('{"id":"task-1"}\nnot-json\n')

    with pytest.raises(ConfigError, match=r"tasks\.jsonl:2: invalid JSON"):
        load_benchmark_pack(manifest_path, tasks_path).load_rows()


def test_non_object_jsonl_rows_are_rejected(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    manifest_path.write_text("id: example-pack\nversion: 1\ndefaults:\n  family: terminal_task\n")
    tasks_path.write_text('["not", "object"]\n')

    with pytest.raises(ConfigError, match=r"tasks\.jsonl:1: benchmark row must be an object"):
        load_benchmark_pack(manifest_path, tasks_path).load_rows()


def test_iter_rows_limit_stops_at_requested_count(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    manifest_path.write_text("id: example-pack\nversion: 1\ndefaults:\n  family: terminal_task\n")
    tasks_path.write_text('{"id":"task-1"}\n{"id":"task-2"}\n')

    rows = load_benchmark_pack(manifest_path, tasks_path).load_rows(limit=1)

    assert [row.id for row in rows] == ["task-1"]


def test_eval_remains_separate_from_public_input_and_assets(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    tasks_path = tmp_path / "tasks.jsonl"
    manifest_path.write_text("id: example-pack\nversion: 1\ndefaults:\n  family: terminal_task\n")
    tasks_path.write_text(
        """
{"id":"task-1","input":{"instructions":"Read public file."},"assets":[{"path":"public.txt"}],"eval":{"checker":{"path":"checks/check.py"},"expected_state":{"file":"output.txt"}}}
""".strip()
        + "\n"
    )

    row = load_benchmark_pack(manifest_path, tasks_path).load_rows()[0]

    assert row.input == {"instructions": "Read public file."}
    assert row.assets == ({"path": "public.txt"},)
    assert row.eval == {
        "checker": {"path": "checks/check.py"},
        "expected_state": {"file": "output.txt"},
    }
    assert "checker" not in row.input
    assert all("checker" not in asset for asset in row.assets)
