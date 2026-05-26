"""Compile benchmark-pack rows into internal SecureBench tasks."""

from __future__ import annotations

from typing import Iterator

from securebench.benchmark_pack import BenchmarkPack, BenchmarkPackManifest, BenchmarkRow
from securebench.errors import ConfigError
from securebench.families import validate_benchmark_row_family
from securebench.resources import ResourceVisibility
from securebench.tasks import SecureBenchTask, task_from_spec


EVAL_VISIBILITY: dict[str, dict[str, ResourceVisibility]] = {
    "multiple_choice": {
        "answer": "hidden",
    },
    "short_answer": {
        "accepted_answers": "hidden",
        "tolerance": "hidden",
    },
    "free_response": {
        "reference_answer": "hidden",
        "rubric": "hidden",
    },
    "code_completion": {
        "tests": "evaluation_inputs",
        "reference_solution": "hidden",
        "canonical_solution": "hidden",
    },
    "repo_patch": {
        "tests": "evaluation_inputs",
        "candidate_policy": "evaluation_inputs",
        "gold_patch": "hidden",
    },
    "terminal_task": {
        "checker": "evaluation_inputs",
        "needed_commands": "evaluation_inputs",
        "run_tests": "evaluation_inputs",
        "test_files": "evaluation_inputs",
        "expected_state": "hidden",
    },
    "tool_call": {
        "initial_state": "evaluation_inputs",
        "expected_calls": "hidden",
        "expected_final_state": "hidden",
    },
    "browser_task": {
        "credentials": "evaluation_inputs",
        "success_check": "hidden",
    },
    "desktop_task": {
        "success_check": "hidden",
    },
    "artifact_task": {
        "reference_artifact": "hidden",
        "rubric": "hidden",
    },
    "multimodal_qa": {
        "answer": "hidden",
        "rubric": "hidden",
    },
    "preference_pair": {
        "preference": "hidden",
        "rubric": "hidden",
    },
}


def eval_visibility_for(family: str, key: str) -> ResourceVisibility:
    """Return the internal visibility for one family eval field."""
    return EVAL_VISIBILITY.get(family, {}).get(key, "hidden")


def compile_benchmark_row(
    row: BenchmarkRow,
    *,
    manifest: BenchmarkPackManifest,
) -> SecureBenchTask:
    """Compile one benchmark row into a SecureBench task."""
    validate_benchmark_row_family(row)

    resources: dict[str, dict[str, object]] = {}
    for name, value in row.input.items():
        _add_resource(resources, name, value, "public")

    if row.assets:
        _add_resource(resources, "assets", list(row.assets), "public")

    for name, value in row.eval.items():
        _add_resource(resources, name, value, eval_visibility_for(row.family, name))

    try:
        return task_from_spec(
            {
                "id": row.id,
                "benchmark_id": manifest.id,
                "task_type": row.family,
                "metadata": _metadata(row, manifest),
                "resources": resources,
            }
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def compile_benchmark_pack(
    pack: BenchmarkPack,
    *,
    limit: int | None = None,
) -> Iterator[SecureBenchTask]:
    """Compile benchmark-pack rows into SecureBench tasks."""
    for row in pack.iter_rows(limit=limit):
        yield compile_benchmark_row(row, manifest=pack.manifest)


def _add_resource(
    resources: dict[str, dict[str, object]],
    name: str,
    value: object,
    visibility: ResourceVisibility,
) -> None:
    if name in resources:
        raise ConfigError(f"Duplicate compiled resource name: {name}")
    resources[name] = {
        "value": value,
        "visibility": visibility,
    }


def _metadata(row: BenchmarkRow, manifest: BenchmarkPackManifest) -> dict[str, object]:
    return {
        **row.metadata,
        "benchmark_pack": {
            "id": manifest.id,
            "version": manifest.version,
            "manifest_path": None if manifest.path is None else str(manifest.path),
        },
        "environment": row.environment,
        "asset_roots": {
            "public": manifest.asset_roots.public,
            "eval": manifest.asset_roots.eval,
        },
        "asset_defaults": {
            "read_only": manifest.asset_defaults.read_only,
        },
    }
