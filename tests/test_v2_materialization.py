from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.resources import Resource, ResourceBundle
from securebench.sandboxes import HostSandbox
from securebench.workspaces.materialization import (
    MaterializationError,
    VisibilityAwareMaterializer,
    docker_resource_mounts,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"


def task():
    return next(
        compile_benchmark_pack(
            load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
        )
    )


def test_agent_materialization_routes_only_public_files_to_declared_mounts(tmp_path):
    compiled = task()
    materializer = VisibilityAwareMaterializer()
    plan = materializer.materialize(compiled, HostSandbox(root=tmp_path), "agent")

    assert all(item.visibility == "public" for item in plan.resources)
    asset_items = [item for item in plan.resources if item.kind == "file"]
    assert {item.container_path for item in asset_items} == {
        "/app/alice_calendar.ics",
        "/app/bob_calendar.ics",
        "/app/carol_calendar.ics",
    }
    assert all(item.relative_path.startswith("securebench/public/files/") for item in asset_items)
    assert not any("host." in item.name or "runtime." in item.name for item in plan.resources)
    mounts = docker_resource_mounts(plan)
    assert {mount.target for mount in mounts} == {item.container_path for item in asset_items}
    assert all(mount.read_only for mount in mounts)
    assert all(not Path(mount.source).is_relative_to(tmp_path) for mount in mounts)
    assert not (tmp_path / "securebench" / "public" / "files").exists()


def test_oracle_resources_are_never_copied_into_agent_workspace(tmp_path):
    compiled = task()
    VisibilityAwareMaterializer().materialize(compiled, HostSandbox(root=tmp_path), "agent")

    assert not list(tmp_path.rglob("oracle.py"))
    assert not list(tmp_path.rglob("oracle.yaml"))


def test_direct_pack_source_mounts_reject_writable_resources(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("input")
    bundle = ResourceBundle(
        (
            Resource(
                "asset.0",
                {
                    "source_path": str(source),
                    "mount": "/app/input.txt",
                    "read_only": False,
                },
                "public",
                kind="file",
            ),
        )
    )

    with pytest.raises(MaterializationError, match="must be read-only"):
        VisibilityAwareMaterializer().build_plan(bundle, "agent")
