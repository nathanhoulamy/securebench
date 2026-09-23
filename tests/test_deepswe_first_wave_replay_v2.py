"""Real-capture Docker qualification for the first three DeepSWE rows.

`cattrs-partial-structuring-recovery`, `fd-deterministic-multi-key-sorting` and
`updo-policy-alerting` already have Oracle-level semantic-mutant coverage in
`test_pilot_conversions_v2.py`, which drives each Oracle with synthetic
observations. What they lacked was proof through the production path: a real
patch captured from a stopped workspace, replayed into fresh Evaluations of the
pinned image, and judged by the real Oracle process. That is what this file
adds, using the upstream solutions as host-only reference material.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from tests.deepswe_qualification import (
    deep_task,
    materialize_baseline,
    reference_patch,
    verify_patch,
)
from tests.qualification_support import DOCKER_INTEGRATION


ROWS = (
    "cattrs-partial-structuring-recovery",
    "fd-deterministic-multi-key-sorting",
    "updo-policy-alerting",
)


def _file_diffs(patch_text: str) -> list[tuple[str, str]]:
    """Split a unified git patch into (path, per-file diff) pairs."""
    chunks = re.split(r"(?m)^(?=diff --git )", patch_text)
    pairs = []
    for chunk in chunks:
        match = re.match(r"diff --git a/(\S+) b/\S+", chunk)
        if match:
            pairs.append((match.group(1), chunk))
    return pairs


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    return (
        "test" in lowered.split("/")[-1]
        or "/tests/" in f"/{lowered}"
        or lowered.startswith("tests/")
    )


@pytest.mark.parametrize("name", ROWS)
def test_row_preflights_and_keeps_the_reference_host_only(name):
    task = deep_task(name)
    validate_executable_task(task)

    assert task.family == "repo_patch"
    assert task.verification.candidate.type == "git_patch"
    assert re.fullmatch(r"[0-9a-f]{40}", task.input["base_commit"])
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "reference.patch" not in view
        assert "qualification" not in view


@pytest.mark.parametrize("name", ROWS)
def test_reference_patch_is_the_pinned_upstream_solution(name):
    import hashlib
    import json

    patch = reference_patch(name)
    provenance = json.loads((patch.parent / "provenance.json").read_text())

    assert provenance["source_revision"] == "e016041a6ccf8da29906afc9a3f5a8df940a1f78"
    assert provenance["source_path"] == f"tasks/{name}/solution/solution.patch"
    assert provenance["sha256"] == hashlib.sha256(patch.read_bytes()).hexdigest()
    assert provenance["baseline_commit"] == deep_task(name).input["base_commit"]


@pytest.fixture(scope="module")
def baselines(tmp_path_factory):
    cache: dict[str, Path] = {}

    def get(name: str) -> Path:
        if name not in cache:
            root = tmp_path_factory.mktemp(f"{name}-baseline") / "app"
            cache[name] = materialize_baseline(name, root)
        return cache[name]

    return get


@DOCKER_INTEGRATION
@pytest.mark.parametrize("name", ROWS)
def test_base_fails_through_the_real_capture_path(tmp_path, baselines, name):
    """Gate 1: the unmodified base commit must not pass."""
    outcome = verify_patch(name, baselines(name), tmp_path, run_seed=f"{name}-base")

    assert outcome.status == "failed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence


@DOCKER_INTEGRATION
@pytest.mark.parametrize("name", ROWS)
def test_reference_passes_in_fresh_evaluations(tmp_path, baselines, name):
    """Gates 2 and 5: the upstream solution passes, one fresh Evaluation per case."""
    outcome = verify_patch(
        name, baselines(name), tmp_path, reference=True, run_seed=f"{name}-reference"
    )

    assert outcome.status == "passed", outcome.result
    assert not outcome.infrastructure_errors, outcome.evidence
    assert len(outcome.evidence) >= 2
    assert len(set(outcome.evaluation_ids)) == len(outcome.evaluation_ids)
    assert all(item.status == "observed" for item in outcome.evidence)


@DOCKER_INTEGRATION
@pytest.mark.parametrize("name", ROWS)
def test_incomplete_implementation_mutant_fails(tmp_path, baselines, name):
    """Gate 3 through the real path: drop the largest non-test source change.

    This models an almost-correct submission that implements most of the
    feature but misses one file of it.
    """
    diffs = [
        (path, diff)
        for path, diff in _file_diffs(reference_patch(name).read_text())
        if not _is_test_path(path)
    ]
    assert diffs, "reference patch has no non-test source changes"
    dropped, _ = max(diffs, key=lambda item: item[1].count("\n+"))
    kept = "".join(diff for path, diff in diffs if path != dropped)

    def apply_partial(workspace: Path) -> None:
        if not kept:
            return
        subprocess.run(
            ["git", "-C", str(workspace), "apply", "--whitespace=nowarn", "-"],
            input=kept.encode(),
            check=True,
        )

    outcome = verify_patch(
        name, baselines(name), tmp_path, mutate=apply_partial,
        run_seed=f"{name}-partial-{dropped}",
    )

    assert outcome.status == "failed", (dropped, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence
