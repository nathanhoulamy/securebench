from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from securebench.schemas.benchmark import (
    BenchmarkPackManifestV2,
    BenchmarkRowDocumentV2,
    EnvironmentDefaults,
    EnvironmentSpec,
    FileBundleCandidate,
    FilesystemOverlayCandidate,
    ProtocolLimits,
    normalize_benchmark_row,
)


DIGEST = "sha256:" + "a" * 64


def manifest_data(**updates):
    value = {
        "schema_version": "2.0",
        "id": "example-pack",
        "defaults": {
            "family": "terminal_task",
            "environment": {
                "image": DIGEST,
                "workdir": "/app",
                "timeout_seconds": 30,
                "agent_network": "none",
            },
        },
        "resource_roots": {
            "public": "assets/",
            "runtime": "evaluation_inputs/",
            "host": "hidden/",
        },
    }
    value.update(updates)
    return value


def passive_row_data(**updates):
    value = {
        "id": "example/passive",
        "input": {"instructions": "Write /app/result.json."},
        "assets": [
            {"path": "fixtures/input.json", "mount": "/app/input.json", "read_only": True}
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
                "host": {"task_oracle": {"path": "example/oracle"}},
            },
            "checks": [
                {
                    "id": "result_artifact",
                    "type": "artifact",
                    "artifacts": [
                        {
                            "id": "result",
                            "source": {"entry": "result"},
                            "parser": "securebench.strict-json/v1",
                            "limits": {"max_bytes": 1024},
                        }
                    ],
                }
            ],
            "oracle": "host.task_oracle",
        },
    }
    value.update(updates)
    return value


def overlay_row_data(*, candidate_updates=None, **updates):
    value = passive_row_data()
    candidate = {
        "type": "filesystem_overlay",
        "include_roots": ["/app", "/etc/example-service"],
        "max_changed_paths": 20,
        "max_changed_bytes": 4096,
    }
    candidate.update(candidate_updates or {})
    value["verification"]["candidate"] = candidate
    value["verification"]["checks"][0]["artifacts"][0]["source"] = {
        "path": "/app/result.json"
    }
    value.update(updates)
    return value


def normalized_overlay_row(*, candidate_updates=None, **updates):
    document = BenchmarkRowDocumentV2.model_validate(
        overlay_row_data(candidate_updates=candidate_updates, **updates)
    )
    manifest = BenchmarkPackManifestV2.model_validate(manifest_data())
    return normalize_benchmark_row(document, manifest)


def test_manifest_requires_v2_and_non_overlapping_roots():
    manifest = BenchmarkPackManifestV2.model_validate(manifest_data())
    assert manifest.schema_version == "2.0"

    with pytest.raises(ValidationError, match="may not overlap"):
        BenchmarkPackManifestV2.model_validate(
            manifest_data(
                resource_roots={
                    "public": "resources/",
                    "runtime": "resources/runtime/",
                    "host": "hidden/",
                }
            )
        )

    with pytest.raises(ValidationError, match="may not overlap"):
        BenchmarkPackManifestV2.model_validate(
            manifest_data(
                resource_roots={
                    "public": "Assets/",
                    "runtime": "assets/runtime/",
                    "host": "hidden/",
                }
            )
        )


def test_filesystem_overlay_v1_schema_uses_explicit_change_limits_only():
    candidate = FilesystemOverlayCandidate.model_validate(
        {
            "type": "filesystem_overlay",
            "include_roots": ["/app", "/etc/nginx"],
            "max_changed_paths": 20,
            "max_changed_bytes": 4096,
        }
    )

    assert candidate.allow_internal_symlinks is False
    assert candidate.max_changed_paths == 20
    assert candidate.max_changed_bytes == 4096

    with pytest.raises(ValidationError, match="max_files|max_total_bytes"):
        FilesystemOverlayCandidate.model_validate(
            {
                "type": "filesystem_overlay",
                "include_roots": ["/app"],
                "max_files": 20,
                "max_total_bytes": 4096,
            }
        )


@pytest.mark.parametrize(
    "root",
    [
        "/etc",
        "/ETC/SSH/keys",
        "/root/task",
        "/var/lib/dpkg/status",
        "/tmp/result",
    ],
)
def test_filesystem_overlay_rejects_permanently_protected_roots(root):
    with pytest.raises(ValidationError, match="overlaps protected path"):
        FilesystemOverlayCandidate.model_validate(
            {
                "type": "filesystem_overlay",
                "include_roots": [root],
                "max_changed_paths": 20,
                "max_changed_bytes": 4096,
            }
        )


@pytest.mark.parametrize("root", ["/app/", "/app//nested", "//app"])
def test_filesystem_overlay_roots_require_canonical_posix_spelling(root):
    with pytest.raises(ValidationError, match="canonical POSIX spelling"):
        FilesystemOverlayCandidate.model_validate(
            {
                "type": "filesystem_overlay",
                "include_roots": [root],
                "max_changed_paths": 20,
                "max_changed_bytes": 4096,
            }
        )


def test_filesystem_overlay_rejects_overlapping_or_excessive_roots():
    with pytest.raises(ValidationError, match="may not overlap"):
        FilesystemOverlayCandidate.model_validate(
            {
                "type": "filesystem_overlay",
                "include_roots": ["/app", "/APP/results"],
                "max_changed_paths": 20,
                "max_changed_bytes": 4096,
            }
        )

    with pytest.raises(ValidationError, match="at most 16 items"):
        FilesystemOverlayCandidate.model_validate(
            {
                "type": "filesystem_overlay",
                "include_roots": [f"/srv/root-{index}" for index in range(17)],
                "max_changed_paths": 20,
                "max_changed_bytes": 4096,
            }
        )

    excessive_depth = "/" + "/".join("a" for _ in range(129))
    excessive_bytes = "/" + "a" * 4096
    for root in (excessive_depth, excessive_bytes):
        with pytest.raises(ValidationError, match="exceeds path bounds"):
            FilesystemOverlayCandidate.model_validate(
                {
                    "type": "filesystem_overlay",
                    "include_roots": [root],
                    "max_changed_paths": 20,
                    "max_changed_bytes": 4096,
                }
            )


def test_filesystem_overlay_row_validates_workdir_and_mount_boundaries():
    row = normalized_overlay_row()
    candidate = row.verification.candidate
    assert isinstance(candidate, FilesystemOverlayCandidate)
    assert candidate.include_roots == ("/app", "/etc/example-service")

    workdir_mismatch = overlay_row_data(
        candidate_updates={"include_roots": ["/srv/task"]}
    )
    workdir_mismatch["verification"]["checks"][0]["artifacts"][0]["source"] = {
        "path": "/srv/task/result.json"
    }
    with pytest.raises(ValidationError, match="must contain environment.workdir"):
        document = BenchmarkRowDocumentV2.model_validate(workdir_mismatch)
        normalize_benchmark_row(
            document,
            BenchmarkPackManifestV2.model_validate(manifest_data()),
        )

    aliased_artifact = overlay_row_data()
    aliased_artifact["verification"]["checks"][0]["artifacts"][0]["source"] = {
        "path": "/App/result.json"
    }
    with pytest.raises(ValidationError, match="outside candidate include_roots"):
        BenchmarkRowDocumentV2.model_validate(aliased_artifact)

    writable_asset = overlay_row_data()
    writable_asset["assets"][0]["read_only"] = False
    with pytest.raises(ValidationError, match="must be read-only"):
        document = BenchmarkRowDocumentV2.model_validate(writable_asset)
        normalize_benchmark_row(
            document,
            BenchmarkPackManifestV2.model_validate(manifest_data()),
        )

    replacing_asset = overlay_row_data()
    replacing_asset["assets"][0]["mount"] = "/app"
    with pytest.raises(ValidationError, match="may not contain or replace"):
        document = BenchmarkRowDocumentV2.model_validate(replacing_asset)
        normalize_benchmark_row(
            document,
            BenchmarkPackManifestV2.model_validate(manifest_data()),
        )

    runtime_overlap = overlay_row_data()
    runtime_overlap["verification"]["resources"]["runtime"] = {
        "tool": {"path": "example/tool", "mount": "/app/runtime"}
    }
    with pytest.raises(ValidationError, match="runtime resource.*may not overlap"):
        document = BenchmarkRowDocumentV2.model_validate(runtime_overlap)
        normalize_benchmark_row(
            document,
            BenchmarkPackManifestV2.model_validate(manifest_data()),
        )

    reserved_artifact = overlay_row_data()
    reserved_artifact["verification"]["checks"][0]["artifacts"][0]["source"] = {
        "path": "/app/input.json"
    }
    with pytest.raises(ValidationError, match="reserved public asset mount"):
        document = BenchmarkRowDocumentV2.model_validate(reserved_artifact)
        normalize_benchmark_row(
            document,
            BenchmarkPackManifestV2.model_validate(manifest_data()),
        )

def test_author_paths_reject_embedded_nul_bytes():
    row = passive_row_data()
    row["assets"][0]["mount"] = "/app/input\x00shadow.json"

    with pytest.raises(ValidationError, match="absolute path"):
        BenchmarkRowDocumentV2.model_validate(row)


def test_row_defaults_and_family_contract_are_applied():
    manifest = BenchmarkPackManifestV2.model_validate(manifest_data())
    document = BenchmarkRowDocumentV2.model_validate(passive_row_data())

    row = normalize_benchmark_row(document, manifest)

    assert row.family == "terminal_task"
    assert row.environment.image == DIGEST
    assert isinstance(row.verification.candidate, FileBundleCandidate)


def test_environment_image_digest_is_canonicalized_to_lowercase():
    data = manifest_data()
    data["defaults"]["environment"]["image"] = (
        "example.invalid/agent@sha256:" + "A" * 64
    )
    manifest = BenchmarkPackManifestV2.model_validate(data)

    row = normalize_benchmark_row(
        BenchmarkRowDocumentV2.model_validate(passive_row_data()),
        manifest,
    )

    assert row.environment.image.endswith("sha256:" + "a" * 64)


def test_v1_eval_rows_are_rejected():
    row = passive_row_data(eval={"checker": {}})
    with pytest.raises(ValidationError, match="eval"):
        BenchmarkRowDocumentV2.model_validate(row)


def test_candidate_entry_reference_must_resolve():
    row = passive_row_data()
    row["verification"]["checks"][0]["artifacts"][0]["source"] = {"entry": "missing"}
    with pytest.raises(ValidationError, match="unknown candidate entry"):
        BenchmarkRowDocumentV2.model_validate(row)


def test_runtime_and_host_references_are_lane_specific():
    row = passive_row_data()
    row["verification"]["oracle"] = "runtime.task_oracle"
    with pytest.raises(ValidationError, match="must reference host"):
        BenchmarkRowDocumentV2.model_validate(row)


def test_protocol_requires_at_least_one_case():
    row = passive_row_data()
    row["verification"]["resources"] = {
        "runtime": {"adapter": {"path": "example/adapter", "mount": "/opt/adapter"}},
        "host": {
            "cases": {"path": "example/cases"},
            "task_oracle": {"path": "example/oracle"},
        },
    }
    row["verification"]["checks"] = [
        {
            "id": "behavior",
            "type": "protocol",
            "adapter": "runtime.adapter",
            "protocol": "securebench.example/v1",
            "challenge": {"source": "host.cases", "max_cases": 0, "max_case_bytes": 64},
            "limits": {"seconds_per_case": 1, "observation_bytes_per_case": 64},
        }
    ]
    with pytest.raises(ValidationError, match="greater than 0"):
        BenchmarkRowDocumentV2.model_validate(row)


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (EnvironmentDefaults, {"timeout_seconds": float("inf")}),
        (
            EnvironmentSpec,
            {
                "image": DIGEST,
                "workdir": "/app",
                "timeout_seconds": float("inf"),
                "agent_network": "none",
            },
        ),
        (
            ProtocolLimits,
            {
                "seconds_per_case": float("inf"),
                "observation_bytes_per_case": 1024,
            },
        ),
    ],
)
def test_timeout_fields_reject_infinite_values(model, data):
    with pytest.raises(ValidationError, match="finite number"):
        model.model_validate(data)


def test_generated_json_schemas_are_current(tmp_path):
    root = Path(__file__).resolve().parents[1]
    expected = {
        path.name: json.loads(path.read_text())
        for path in (root / "schemas").glob("*.schema.json")
    }
    assert expected, "checked-in schemas must exist"

    subprocess.run(
        [str(root / ".venv" / "bin" / "python"), "-m", "tools.generate_schemas"],
        check=True,
        cwd=root,
    )
    actual = {
        path.name: json.loads(path.read_text())
        for path in (root / "schemas").glob("*.schema.json")
    }
    assert actual == expected


def test_split_verification_examples_conform_to_the_v2_row_schema():
    root = Path(__file__).resolve().parents[1]
    example_root = root / "docs" / "split-verification" / "examples"
    documents = tuple(
        document
        for path in (example_root / "executable.yaml", example_root / "target-architecture.yaml")
        for document in yaml.safe_load_all(path.read_text())
    )

    rows = tuple(BenchmarkRowDocumentV2.model_validate(document) for document in documents)

    assert [row.id for row in rows] == [
        "terminal-bench/constraints-scheduling",
        "deep-swe/updo-policy-alerting",
        "terminal-bench/install-windows-3.11",
    ]
