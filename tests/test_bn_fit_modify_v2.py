from __future__ import annotations

from statistics import NormalDist
from pathlib import Path

import pytest

from securebench.candidates import (
    CandidateStore,
    capture_production,
)
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.command import CommandHarnessProducer
from securebench.schemas.benchmark import ArtifactCheck
from securebench.verification import VerificationEngine
from securebench.workspaces.cleanup import remove_untrusted_tree
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_terminal_task,
    verify_workspace as verify_files,
)


TASK_ID = "terminal-bench/bn-fit-modify"
LEARNED_EDGES = (
    ("U", "M"),
    ("U", "Y"),
    ("U", "D"),
    ("U", "R"),
    ("Y", "D"),
    ("R", "M"),
)
INTERVENED_EDGES = tuple(edge for edge in LEARNED_EDGES if edge != ("U", "Y"))
SAMPLE_ROWS = 10_000
EXPECTED_D_MEAN = -12.2965135 + 0.5495886 * 50.47989
EXPECTED_D_STD = ((0.5495886**2) * 10.68515**2 + 14.0916**2) ** 0.5


def compiled_task():
    return load_terminal_task(TASK_ID)


def edge_csv(edges=LEARNED_EDGES, *, verdict_column=False):
    header = "from,to,verdict\n" if verdict_column else "from,to\n"
    suffix = ",PASS" if verdict_column else ""
    return header + "".join(f"{source},{target}{suffix}\n" for source, target in edges)


def reference_d_values():
    distribution = NormalDist(EXPECTED_D_MEAN, EXPECTED_D_STD)
    return [
        distribution.inv_cdf((index + 0.5) / SAMPLE_ROWS)
        for index in range(SAMPLE_ROWS)
    ]


def sample_csv(
    values=None,
    *,
    header=("U", "R", "Y", "M", "D"),
):
    values = reference_d_values() if values is None else values
    d_index = header.index("D")
    lines = [",".join(header)]
    for value in values:
        row = ["0"] * len(header)
        row[d_index] = format(value, ".17g")
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"


def write_workspace(
    workspace: Path,
    *,
    learned=None,
    intervened=None,
    sample=None,
):
    workspace.mkdir(parents=True)
    (workspace / "learned_dag.csv").write_text(
        edge_csv() if learned is None else learned,
        encoding="utf-8",
    )
    (workspace / "intervened_dag.csv").write_text(
        edge_csv(INTERVENED_EDGES) if intervened is None else intervened,
        encoding="utf-8",
    )
    (workspace / "final_bn_sample.csv").write_text(
        sample_csv() if sample is None else sample,
        encoding="utf-8",
    )


def verify_workspace(tmp_path: Path, **overrides):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    write_workspace(workspace, **overrides)
    return verify_files(
        task,
        workspace,
        tmp_path / "store",
        run_seed="bn-fit-modify-qualification",
    )


def test_bn_fit_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == (
        "alexgshaw/bn-fit-modify@"
        "sha256:5aeb11ca6e802b83816c9a31f055ac9d028309a853509400c2e3139ac2d8380d"
    )
    assert len(task.verification.checks) == 1
    assert isinstance(task.verification.checks[0], ArtifactCheck)
    assert not task.verification.resources.runtime
    assert [entry.id for entry in task.verification.candidate.files] == [
        "learned_dag",
        "intervened_dag",
        "final_sample",
    ]


def test_bn_fit_reference_artifacts_pass_and_capture_only_declared_files(tmp_path):
    result, candidate, store = verify_workspace(tmp_path)

    assert result.status == "passed"
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert manifest.type == "file_bundle"
    assert [entry["id"] for entry in manifest.payload["entries"]] == [
        "learned_dag",
        "intervened_dag",
        "final_sample",
    ]


@pytest.mark.parametrize(
    ("overrides", "failure"),
    [
        (
            {"learned": edge_csv(LEARNED_EDGES[:-1])},
            "learned_dag:incorrect_edges",
        ),
        (
            {"intervened": edge_csv(LEARNED_EDGES)},
            "intervened_dag:incorrect_edges",
        ),
        (
            {"sample": sample_csv([0.0] * SAMPLE_ROWS)},
            "final_sample:d_distribution_mismatch",
        ),
        (
            {"sample": sample_csv(reference_d_values()[:-1])},
            "final_sample:incorrect_sample_row_count",
        ),
        (
            {
                "sample": sample_csv(
                    reference_d_values(),
                    header=("U", "R", "Y", "M", "D", "claim"),
                )
            },
            "final_sample:incorrect_sample_columns",
        ),
    ],
)
def test_bn_fit_targeted_mutants_fail(tmp_path, overrides, failure):
    result, _, _ = verify_workspace(tmp_path, **overrides)

    assert result.status == "failed"
    assert failure in result.public_diagnostics["failure_categories"]


def test_bn_fit_ignores_candidate_verdict_claims(tmp_path):
    result, _, _ = verify_workspace(
        tmp_path,
        learned=edge_csv(verdict_column=True),
        intervened=edge_csv(INTERVENED_EDGES, verdict_column=True),
    )

    assert result.status == "passed"


def test_bn_fit_malformed_csv_is_candidate_evidence_not_infrastructure(tmp_path):
    result, _, _ = verify_workspace(
        tmp_path,
        learned="from,from,to\nU,U,M\n",
    )

    assert result.status == "failed"
    assert result.infrastructure_error is None
    assert "learned_dag:invalid_csv_header" in result.public_diagnostics[
        "failure_categories"
    ]


@DOCKER_INTEGRATION
def test_bn_fit_reference_passes_through_real_pinned_agent_container(tmp_path):
    task = compiled_task()
    script = f"""
from pathlib import Path
from statistics import NormalDist

learned = {LEARNED_EDGES!r}
intervened = {INTERVENED_EDGES!r}
mean = {EXPECTED_D_MEAN!r}
std = {EXPECTED_D_STD!r}
count = {SAMPLE_ROWS}
Path('/app/learned_dag.csv').write_text(
    'from,to\\n' + ''.join(f'{{source}},{{target}}\\n' for source, target in learned)
)
Path('/app/intervened_dag.csv').write_text(
    'from,to\\n' + ''.join(f'{{source}},{{target}}\\n' for source, target in intervened)
)
distribution = NormalDist(mean, std)
lines = ['U,R,Y,M,D']
for index in range(count):
    value = distribution.inv_cdf((index + 0.5) / count)
    lines.append(f'0,0,0,0,{{value:.17g}}')
Path('/app/final_bn_sample.csv').write_text('\\n'.join(lines) + '\\n')
"""
    producer = CommandHarnessProducer(
        command=("python3", "-c", script),
        workspace_root=tmp_path / "workspaces",
    )
    production = producer.produce(task)
    try:
        store = CandidateStore(tmp_path / "store")
        candidate = capture_production(task, production, store)
        result = VerificationEngine().verify(
            task,
            candidate,
            store,
            run_seed="bn-fit-modify-real-docker-reference",
        )
    finally:
        remove_untrusted_tree(production.workspace, image=task.environment.image)

    assert result.status == "passed"
