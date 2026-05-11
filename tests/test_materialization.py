import pytest

from securebench.materialization import MaterializationError, ResourceMaterializer
from securebench.path_policy import PathPolicyError
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
    assert target.files["securebench/evaluation_inputs/cases.json"] == '[\n  {\n    "args": [\n      1,\n      2\n    ]\n  }\n]\n'
    assert "answer" not in str(plan)
    assert "answer" not in str(target.files)


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
            "id": "mmlu/math/test/7",
            "benchmark_id": "mmlu",
            "task_type": "multiple_choice",
            "resources": {
                "question": {"value": "2 + 2?", "visibility": "public"},
                "choices": {"value": ["1", "2", "4", "5"], "visibility": "public"},
                "answer": {"value": 2, "visibility": "hidden"},
            },
        }
    )

    plan = ResourceMaterializer().build_plan(task, "agent")

    assert [item.relative_path for item in plan.resources] == [
        "securebench/public/question.json",
        "securebench/public/choices.json",
    ]


def test_materialization_validates_plan_before_writing(monkeypatch):
    target = FakeTarget()

    def reject_plan(plan):
        raise PathPolicyError("rejected before write")

    monkeypatch.setattr("securebench.materialization.validate_materialization_plan", reject_plan)

    with pytest.raises(PathPolicyError, match="rejected before write"):
        ResourceMaterializer().materialize(make_bundle(), target, "agent")

    assert target.files == {}
