import pytest

from securebench.materialization import MaterializationPlan, MaterializedResource
from securebench.path_policy import (
    PathPolicy,
    PathPolicyError,
    validate_materialization_plan,
    validate_path_for_component,
)


def test_component_allowed_roots_accept_road_b_paths():
    assert validate_path_for_component("agent", "securebench/public/question.json").allowed is True
    assert validate_path_for_component("test_sandbox", "securebench/public/question.json").allowed is True
    assert validate_path_for_component("test_sandbox", "securebench/evaluation_inputs/cases.json").allowed is True
    assert validate_path_for_component("evaluator", "securebench/evaluator/answer.json").allowed is True


@pytest.mark.parametrize(
    ("component", "path"),
    [
        ("agent", "securebench/evaluation_inputs/cases.json"),
        ("agent", "securebench/evaluator/answer.json"),
        ("test_sandbox", "securebench/evaluator/answer.json"),
        ("evaluator", "securebench/public/question.json"),
        ("evaluator", "securebench/evaluation_inputs/cases.json"),
    ],
)
def test_component_allowed_roots_reject_cross_component_paths(component, path):
    with pytest.raises(PathPolicyError, match="outside allowed roots"):
        validate_path_for_component(component, path)


@pytest.mark.parametrize(
    "path",
    [
        "ground_truth",
        "ground_truth/answer.json",
        "scorer",
        "eval/script.py",
        "task/hidden.json",
        "task/evaluation_inputs.json",
        "input/hidden.json",
        "output/score.json",
    ],
)
def test_mandatory_denied_paths_win_over_allowed_roots(path):
    policy = PathPolicy(component="agent", allowed_roots=("task", "input", "output", "ground_truth", "scorer", "eval"))

    with pytest.raises(PathPolicyError, match="denied by policy"):
        policy.validate(path)


@pytest.mark.parametrize("path", ["", ".", "/securebench/public/x.json", "securebench/../secret", r"securebench\public\x.json"])
def test_unsafe_paths_are_rejected(path):
    with pytest.raises(PathPolicyError):
        validate_path_for_component("agent", path)


def test_paths_outside_allowed_roots_are_rejected():
    with pytest.raises(PathPolicyError, match="outside allowed roots"):
        validate_path_for_component("agent", "other/public/question.json")


def test_result_is_not_a_path_policy_target():
    with pytest.raises(PathPolicyError, match="result is not a path-policy target"):
        validate_path_for_component("result", "securebench/public/question.json")


def test_materialization_plan_validation_rejects_duplicate_paths():
    plan = MaterializationPlan(
        component="agent",
        resources=(
            MaterializedResource(
                name="question",
                visibility="public",
                kind="json",
                component="agent",
                relative_path="securebench/public/same.json",
            ),
            MaterializedResource(
                name="prompt",
                visibility="public",
                kind="json",
                component="agent",
                relative_path="securebench/public/same.json",
            ),
        ),
    )

    with pytest.raises(PathPolicyError, match="duplicate materialized path"):
        validate_materialization_plan(plan)


def test_materialization_plan_validation_rejects_resource_component_mismatch():
    plan = MaterializationPlan(
        component="agent",
        resources=(
            MaterializedResource(
                name="answer",
                visibility="hidden",
                kind="json",
                component="evaluator",
                relative_path="securebench/public/answer.json",
            ),
        ),
    )

    with pytest.raises(PathPolicyError, match="does not match plan component"):
        validate_materialization_plan(plan)
