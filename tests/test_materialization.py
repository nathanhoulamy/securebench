import pytest

from securebench.sandboxes import HostSandbox
from securebench.workspaces.materialization import (
    MaterializationError,
    ResourceMaterializer,
    VisibilityAwareMaterializer,
    docker_read_only_mounts,
)
from securebench.workspaces.path_policy import PathPolicyError
from securebench.resources import Resource, ResourceBundle
from securebench.tasks import task_from_spec


class FakeTarget:
    def __init__(self):
        self.files = {}

    def write_file(self, path, content):
        self.files[str(path)] = content


def make_bundle():
    return ResourceBundle(
        (
            Resource("prompt", "solve", "public", kind="text"),
            Resource("metadata", {"b": 2, "a": 1}, "public", kind="json"),
            Resource("cases", [{"args": [1, 2]}], "evaluation_inputs", kind="json"),
            Resource("answer", 3, "hidden", kind="json"),
        )
    )


def test_agent_materialization_writes_only_public_resources():
    target = FakeTarget()

    plan = ResourceMaterializer().materialize(make_bundle(), target, "agent")

    assert [item.relative_path for item in plan.resources] == [
        "securebench/public/prompt.json",
        "securebench/public/metadata.json",
    ]
    assert target.files == {
        "securebench/public/prompt.json": '"solve"\n',
        "securebench/public/metadata.json": '{\n  "a": 1,\n  "b": 2\n}\n',
    }
    assert "answer" not in str(plan)
    assert "cases" not in str(plan)


def test_test_sandbox_materialization_writes_public_and_evaluation_inputs():
    target = FakeTarget()

    plan = ResourceMaterializer().materialize(make_bundle(), target, "test_sandbox")

    assert [item.relative_path for item in plan.resources] == [
        "securebench/public/prompt.json",
        "securebench/public/metadata.json",
        "securebench/evaluation_inputs/cases.json",
    ]
    assert [item.read_only for item in plan.resources] == [False, False, True]
    assert target.files["securebench/evaluation_inputs/cases.json"] == '[\n  {\n    "args": [\n      1,\n      2\n    ]\n  }\n]\n'
    assert "answer" not in str(plan)
    assert "answer" not in str(target.files)


def test_non_public_json_materialization_rejects_existing_hardlink_alias(tmp_path):
    workspace = tmp_path / "workspace"
    target_path = workspace / "securebench" / "evaluation_inputs" / "cases.json"
    alias_path = workspace / "candidate-alias.json"
    target_path.parent.mkdir(parents=True)
    alias_path.write_text("candidate-controlled")
    target_path.hardlink_to(alias_path)

    with pytest.raises(MaterializationError, match="already exists"):
        ResourceMaterializer().materialize(make_bundle(), HostSandbox(root=workspace), "test_sandbox")

    assert alias_path.read_text() == "candidate-controlled"


def test_public_materialization_replaces_candidate_symlink_without_following_it(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    target_path = workspace / "securebench" / "public" / "prompt.json"
    target_path.parent.mkdir(parents=True)
    outside.write_text("candidate-controlled")
    target_path.symlink_to(outside)

    ResourceMaterializer().materialize(make_bundle(), HostSandbox(root=workspace), "agent")

    assert not target_path.is_symlink()
    assert target_path.read_text() == '"solve"\n'
    assert outside.read_text() == "candidate-controlled"


def test_non_public_materialization_rejects_existing_symlink(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    target_path = workspace / "securebench" / "evaluation_inputs" / "cases.json"
    target_path.parent.mkdir(parents=True)
    outside.write_text("candidate-controlled")
    target_path.symlink_to(outside)

    with pytest.raises(MaterializationError, match="already exists"):
        ResourceMaterializer().materialize(make_bundle(), HostSandbox(root=workspace), "test_sandbox")

    assert target_path.is_symlink()
    assert outside.read_text() == "candidate-controlled"


def test_evaluator_materialization_uses_current_evaluator_visibility_semantics():
    target = FakeTarget()

    plan = ResourceMaterializer().materialize(make_bundle(), target, "evaluator")

    assert [item.relative_path for item in plan.resources] == [
        "securebench/evaluator/prompt.json",
        "securebench/evaluator/metadata.json",
        "securebench/evaluator/answer.json",
    ]
    assert "securebench/evaluator/answer.json" in target.files
    assert "cases" not in str(plan)


def test_result_is_not_a_materialization_target():
    with pytest.raises(MaterializationError, match="result is not a materialization target"):
        ResourceMaterializer().build_plan(make_bundle(), "result")


def test_future_internal_resource_kinds_fail_clearly():
    bundle = ResourceBundle((Resource("fixture", "/tmp/source", "public", kind="file"),))

    with pytest.raises(MaterializationError, match="not supported for materialization"):
        ResourceMaterializer().build_plan(bundle, "agent")


@pytest.mark.parametrize("name", ["../secret", "secret/answer", r"secret\answer", "/answer", "answer..key"])
def test_unsafe_resource_names_are_rejected(name):
    bundle = ResourceBundle((Resource(name, "value", "public"),))

    with pytest.raises(MaterializationError, match="resource name"):
        ResourceMaterializer().build_plan(bundle, "agent")


def test_non_json_serializable_values_fail_clearly():
    bundle = ResourceBundle((Resource("bad", object(), "public", kind="json"),))

    with pytest.raises(MaterializationError, match="not JSON serializable"):
        ResourceMaterializer().build_plan(bundle, "agent")


def test_materializer_accepts_task_sources():
    task = task_from_spec(
        {
            "id": "terminal/create-output",
            "benchmark_id": "terminal",
            "task_type": "terminal_task",
            "resources": {
                "instructions": {"value": "Create output.txt.", "visibility": "public"},
                "checker": {"value": {"source": "pytest", "path": "checks"}, "visibility": "evaluation_inputs"},
            },
        }
    )

    plan = ResourceMaterializer().build_plan(task, "agent")

    assert [item.relative_path for item in plan.resources] == [
        "securebench/public/instructions.json",
    ]


def test_materialization_validates_plan_before_writing(monkeypatch):
    target = FakeTarget()

    def reject_plan(plan):
        raise PathPolicyError("rejected before write")

    monkeypatch.setattr("securebench.workspaces.materialization.validate_materialization_plan", reject_plan)

    with pytest.raises(PathPolicyError, match="rejected before write"):
        ResourceMaterializer().materialize(make_bundle(), target, "agent")

    assert target.files == {}


def pack_task(tmp_path, resources, *, read_only=True):
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text("id: pack\nversion: 1\n")
    return task_from_spec(
        {
            "id": "task-1",
            "benchmark_id": "pack",
            "task_type": "terminal_task",
            "metadata": {
                "benchmark_pack": {
                    "id": "pack",
                    "version": 1,
                    "manifest_path": str(manifest_path),
                },
                "asset_roots": {
                    "public": "assets/",
                    "eval": "hidden/",
                },
                "asset_defaults": {
                    "read_only": read_only,
                },
            },
            "resources": resources,
        }
    )


def test_visibility_aware_materializer_copies_public_asset_with_default_mount(tmp_path):
    source = tmp_path / "assets" / "fixtures" / "input.txt"
    source.parent.mkdir(parents=True)
    source.write_text("hello")
    task = pack_task(
        tmp_path,
        {
            "assets": {
                "value": [{"path": "fixtures/input.txt"}],
                "visibility": "public",
            },
        },
    )
    target = FakeTarget()

    plan = VisibilityAwareMaterializer().materialize(task, target, "agent")

    assert [(item.relative_path, item.placement, item.read_only) for item in plan.resources] == [
        ("fixtures/input.txt", "workspace", True)
    ]
    assert target.files["fixtures/input.txt"] == b"hello"


def test_visibility_aware_materializer_copies_public_directory_with_custom_mount(tmp_path):
    source = tmp_path / "assets" / "dataset"
    source.mkdir(parents=True)
    (source / "a.txt").write_text("a")
    (source / "nested").mkdir()
    (source / "nested" / "b.txt").write_text("b")
    task = pack_task(
        tmp_path,
        {
            "assets": {
                "value": [{"path": "dataset", "mount": "work/data", "read_only": False}],
                "visibility": "public",
            },
        },
    )
    target = FakeTarget()

    plan = VisibilityAwareMaterializer().materialize(task, target, "test_sandbox")

    assert plan.resources[0].kind == "directory"
    assert plan.resources[0].relative_path == "work/data"
    assert plan.resources[0].read_only is False
    assert target.files["work/data/a.txt"] == b"a"
    assert target.files["work/data/nested/b.txt"] == b"b"


def test_public_asset_source_must_exist(tmp_path):
    task = pack_task(
        tmp_path,
        {
            "assets": {
                "value": [{"path": "missing.txt"}],
                "visibility": "public",
            },
        },
    )

    with pytest.raises(MaterializationError, match="asset source does not exist"):
        VisibilityAwareMaterializer().build_plan(task, "agent")


@pytest.mark.parametrize(
    "asset",
    [
        {"path": "../secret.txt"},
        {"path": "input.txt", "mount": "../input.txt"},
        {"path": "input.txt", "mount": "/input.txt"},
    ],
)
def test_public_asset_paths_must_be_safe(tmp_path, asset):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "input.txt").write_text("x")
    task = pack_task(
        tmp_path,
        {
            "assets": {
                "value": [asset],
                "visibility": "public",
            },
        },
    )

    with pytest.raises((MaterializationError, PathPolicyError)):
        VisibilityAwareMaterializer().build_plan(task, "agent")


def test_public_asset_mount_collisions_are_rejected(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "one.txt").write_text("1")
    (tmp_path / "assets" / "two.txt").write_text("2")
    task = pack_task(
        tmp_path,
        {
            "assets": {
                "value": [
                    {"path": "one.txt", "mount": "same.txt"},
                    {"path": "two.txt", "mount": "same.txt"},
                ],
                "visibility": "public",
            },
        },
    )

    with pytest.raises(PathPolicyError, match="duplicate materialized path"):
        VisibilityAwareMaterializer().build_plan(task, "agent")


def test_public_asset_symlinks_are_rejected(tmp_path):
    (tmp_path / "assets").mkdir()
    target = tmp_path / "assets" / "real.txt"
    target.write_text("real")
    symlink = tmp_path / "assets" / "link.txt"
    symlink.symlink_to(target)
    task = pack_task(
        tmp_path,
        {
            "assets": {
                "value": [{"path": "link.txt"}],
                "visibility": "public",
            },
        },
    )

    with pytest.raises(MaterializationError, match="symlink"):
        VisibilityAwareMaterializer().build_plan(task, "agent")


def test_asset_root_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "input.txt").write_text("secret")
    (tmp_path / "assets").symlink_to(outside)
    task = pack_task(
        tmp_path,
        {
            "assets": {
                "value": [{"path": "input.txt"}],
                "visibility": "public",
            },
        },
    )

    with pytest.raises(MaterializationError, match="outside the benchmark package"):
        VisibilityAwareMaterializer().build_plan(task, "agent")


def test_evaluation_input_file_reference_is_test_sandbox_only(tmp_path):
    source = tmp_path / "hidden" / "checks" / "check.py"
    source.parent.mkdir(parents=True)
    source.write_text("assert True")
    task = pack_task(
        tmp_path,
        {
            "checker": {
                "value": {"path": "checks/check.py"},
                "visibility": "evaluation_inputs",
            },
            "cases": {
                "value": [{"x": 1}],
                "visibility": "evaluation_inputs",
            },
        },
    )
    target = FakeTarget()

    plan = VisibilityAwareMaterializer().materialize(task, target, "test_sandbox")

    assert [item.relative_path for item in plan.resources] == [
        "securebench/evaluation_inputs/checks/check.py",
        "securebench/evaluation_inputs/cases.json",
    ]
    assert [item.read_only for item in plan.resources] == [True, True]
    assert target.files["securebench/evaluation_inputs/checks/check.py"] == b"assert True"
    assert target.files["securebench/evaluation_inputs/cases.json"].startswith("[")
    assert VisibilityAwareMaterializer().build_plan(task, "agent").resources == ()


def test_non_public_file_reference_rejects_existing_hardlink_alias(tmp_path):
    source = tmp_path / "hidden" / "checks" / "check.py"
    source.parent.mkdir(parents=True)
    source.write_text("assert True")
    workspace = tmp_path / "workspace"
    target_path = workspace / "securebench" / "evaluation_inputs" / "checks" / "check.py"
    alias_path = workspace / "candidate-alias.py"
    target_path.parent.mkdir(parents=True)
    alias_path.write_text("candidate-controlled")
    target_path.hardlink_to(alias_path)
    task = pack_task(
        tmp_path,
        {
            "checker": {
                "value": {"path": "checks/check.py"},
                "visibility": "evaluation_inputs",
            },
        },
    )

    with pytest.raises(MaterializationError, match="already exists"):
        VisibilityAwareMaterializer().materialize(task, HostSandbox(root=workspace), "test_sandbox")

    assert alias_path.read_text() == "candidate-controlled"


def test_eval_object_with_path_and_extra_keys_remains_json(tmp_path):
    task = pack_task(
        tmp_path,
        {
            "state": {
                "value": {"path": "output.json", "required": True},
                "visibility": "evaluation_inputs",
            },
        },
    )
    target = FakeTarget()

    plan = VisibilityAwareMaterializer().materialize(task, target, "test_sandbox")

    assert plan.resources[0].serialization == "json"
    assert target.files["securebench/evaluation_inputs/state.json"] == '{\n  "path": "output.json",\n  "required": true\n}\n'


def test_hidden_file_reference_is_evaluator_only(tmp_path):
    source = tmp_path / "hidden" / "expected.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"ok": true}')
    task = pack_task(
        tmp_path,
        {
            "expected_state": {
                "value": {"path": "expected.json"},
                "visibility": "hidden",
            },
            "answer": {
                "value": 42,
                "visibility": "hidden",
            },
        },
    )
    target = FakeTarget()

    test_plan = VisibilityAwareMaterializer().build_plan(task, "test_sandbox")
    eval_plan = VisibilityAwareMaterializer().materialize(task, target, "evaluator")

    assert test_plan.resources == ()
    assert [item.relative_path for item in eval_plan.resources] == [
        "securebench/evaluator/expected.json",
        "securebench/evaluator/answer.json",
    ]
    assert target.files["securebench/evaluator/expected.json"] == b'{"ok": true}'


def test_non_public_file_reference_mount_must_stay_under_component_root(tmp_path):
    source = tmp_path / "hidden" / "check.py"
    source.parent.mkdir(parents=True)
    source.write_text("assert True")
    task = pack_task(
        tmp_path,
        {
            "checker": {
                "value": {"path": "check.py", "mount": "checks/check.py"},
                "visibility": "evaluation_inputs",
            },
        },
    )

    with pytest.raises(MaterializationError, match="must be under securebench/evaluation_inputs"):
        VisibilityAwareMaterializer().build_plan(task, "test_sandbox")


def test_docker_read_only_mounts_are_derived_from_copy_plan(tmp_path):
    source = tmp_path / "assets" / "input.txt"
    source.parent.mkdir(parents=True)
    source.write_text("hello")
    task = pack_task(
        tmp_path,
        {
            "assets": {
                "value": [{"path": "input.txt"}, {"path": "input.txt", "mount": "writable.txt", "read_only": False}],
                "visibility": "public",
            },
        },
    )
    plan = VisibilityAwareMaterializer().build_plan(task, "agent")

    mounts = docker_read_only_mounts(plan, tmp_path / "workspace")

    assert len(mounts) == 1
    assert mounts[0].source == tmp_path / "workspace" / "input.txt"
    assert mounts[0].target == "input.txt"
    assert mounts[0].read_only is True


def test_docker_read_only_mounts_include_json_evaluation_inputs(tmp_path):
    task = pack_task(
        tmp_path,
        {
            "checker": {
                "value": {"command": "pytest"},
                "visibility": "evaluation_inputs",
            },
        },
    )
    plan = VisibilityAwareMaterializer().build_plan(task, "test_sandbox")

    mounts = docker_read_only_mounts(plan, tmp_path / "workspace")

    assert len(mounts) == 1
    assert mounts[0].source == (
        tmp_path / "workspace" / "securebench" / "evaluation_inputs" / "checker.json"
    )
    assert mounts[0].target == "securebench/evaluation_inputs/checker.json"
    assert mounts[0].read_only is True
