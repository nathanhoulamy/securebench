import pytest

from securebench.resources import Resource, ResourceBundle, evaluation_input, hidden, public


def test_resource_helper_constructors_require_names_and_assign_visibility():
    assert public("prompt", "solve").visibility == "public"
    assert evaluation_input("cases", [{"args": []}]).visibility == "evaluation_inputs"
    assert hidden("answer", "A").visibility == "hidden"


def test_resource_bundle_groups_resources_by_visibility():
    bundle = ResourceBundle(
        (
            Resource("question", "2 + 2?", "public"),
            Resource("cases", [1, 2], "evaluation_inputs"),
            Resource("answer", "4", "hidden"),
        )
    )

    assert [resource.name for resource in bundle.by_visibility("public")] == ["question"]
    assert [resource.name for resource in bundle.by_visibility("evaluation_inputs")] == ["cases"]
    assert [resource.name for resource in bundle.by_visibility("hidden")] == ["answer"]


def test_resource_rejects_invalid_visibility_and_duplicates():
    with pytest.raises(ValueError, match="visibility"):
        Resource("x", 1, "private")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="kind"):
        Resource("x", 1, "public", kind="unknown")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="duplicate"):
        ResourceBundle((Resource("x", 1, "public"), Resource("x", 2, "hidden")))


def test_component_views_include_only_allowed_resources():
    bundle = ResourceBundle(
        (
            Resource("prompt", "solve", "public"),
            Resource("cases", [{"args": []}], "evaluation_inputs"),
            Resource("expected", [1], "hidden"),
        )
    )

    assert [resource.name for resource in bundle.view_for("agent").resources] == ["prompt"]
    assert [resource.name for resource in bundle.view_for("evaluation_runtime").resources] == [
        "prompt",
        "cases",
    ]
    assert [resource.name for resource in bundle.view_for("oracle").resources] == [
        "prompt",
        "expected",
    ]


def test_result_view_redacts_non_public_values():
    bundle = ResourceBundle(
        (
            Resource("prompt", "solve", "public"),
            Resource("cases", [{"args": []}], "evaluation_inputs"),
            Resource("expected", [1], "hidden"),
        )
    )

    summary = bundle.summary()
    assert "value" not in summary[0]
    assert summary[1]["redacted"] is True
    assert summary[2]["redacted"] is True
    assert "expose" not in summary[0]


def test_resource_bundle_is_dict_backed_and_accepts_mappings():
    bundle = ResourceBundle(
        {
            "prompt": Resource("prompt", "solve", "public"),
            "answer": Resource("answer", "A", "hidden"),
        }
    )

    assert list(bundle.resources) == ["prompt", "answer"]
    assert [resource.name for resource in bundle.view_for("agent").resources] == ["prompt"]

    with pytest.raises(ValueError, match="does not match"):
        ResourceBundle({"wrong": Resource("prompt", "solve", "public")})
