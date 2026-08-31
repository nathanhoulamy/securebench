from __future__ import annotations

import struct
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


TASK_ID = "terminal-bench/distribution-search"
IMAGE = (
    "alexgshaw/distribution-search@"
    "sha256:1448f7aa1c6080488251d00350e8e90477858989b1bec0accc866d7b3220738a"
)
SIZE = 150_000
HIGH_COUNT = 6
HIGH = 0.15550923955935933
MIDDLE = 0.06689920705254902
LOW = 3.023847199198345e-10
REFERENCE_GROUPS = ((HIGH, HIGH_COUNT), (MIDDLE, 1), (LOW, SIZE - 7))


def compiled_task():
    return load_terminal_task(TASK_ID)


def npy_file(
    groups,
    *,
    descr="<f8",
    shape=(SIZE,),
    header_source=None,
    trailing=b"",
):
    if header_source is None:
        header_source = repr(
            {"descr": descr, "fortran_order": False, "shape": shape}
        )
    encoded_header = header_source.encode("latin-1")
    padding = (-(10 + len(encoded_header) + 1)) % 64
    header = encoded_header + b" " * padding + b"\n"
    code = {"<f4": "<f", "<f8": "<d"}.get(descr, "<d")
    payload = b"".join(struct.pack(code, value) * count for value, count in groups)
    return (
        b"\x93NUMPY\x01\x00"
        + len(header).to_bytes(2, "little")
        + header
        + payload
        + trailing
    )


def scaled_reference(factor):
    return tuple((value * factor, count) for value, count in REFERENCE_GROUPS)


def two_level_groups(high_mass):
    return (
        (high_mass, 1),
        ((1.0 - high_mass) / (SIZE - 1), SIZE - 1),
    )


def verify_distribution(tmp_path: Path, content: bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "search.py").write_text("excluded", encoding="utf-8")
    (workspace / "optimizer.log").write_text("excluded", encoding="utf-8")
    (workspace / "dist.npy").write_bytes(content)
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="distribution-search-qualification",
    )


def assert_candidate_failure(tmp_path: Path, content: bytes, category: str):
    result, _, _ = verify_distribution(tmp_path, content)
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [category]


def test_distribution_search_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.artifacts[0].parser == "securebench.strict-npy-float-summary/v1"
    assert not task.verification.resources.runtime
    assert task.verification.candidate.max_total_files == 1
    assert task.verification.candidate.max_total_bytes == 4 * 1024 * 1024
    entry = task.verification.candidate.files[0]
    assert entry.id == "distribution"
    assert entry.path == "/app/dist.npy"
    assert entry.kind == "regular_file"
    assert entry.max_bytes == 4 * 1024 * 1024

    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    assert {
        path.relative_to(oracle_root).as_posix()
        for path in oracle_root.rglob("*")
        if path.is_file()
    } == {"oracle.py", "oracle.yaml"}


@pytest.mark.parametrize("descr", ["<f4", "<f8"])
def test_reviewed_reference_passes_capture_parser_and_oracle(tmp_path, descr):
    result, candidate, store = verify_distribution(
        tmp_path,
        npy_file(REFERENCE_GROUPS, descr=descr),
    )

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert manifest.type == "file_bundle"
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["distribution"]
    serialized = str(manifest.payload)
    assert "search.py" not in serialized
    assert "optimizer.log" not in serialized


def test_source_sum_tolerance_is_preserved(tmp_path):
    inside, _, _ = verify_distribution(
        tmp_path / "inside",
        npy_file(scaled_reference(1.0 + 0.9e-5)),
    )
    outside, _, _ = verify_distribution(
        tmp_path / "outside",
        npy_file(scaled_reference(1.0 + 1.1e-5)),
    )

    assert inside.status == "passed", inside
    assert outside.status == "failed", outside
    assert outside.public_diagnostics["failure_categories"] == [
        "distribution_not_normalized"
    ]


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(
            npy_file(((1.0 / SIZE, SIZE),)),
            "forward_kl_out_of_tolerance",
            id="uniform_fixed_output",
        ),
        pytest.param(
            npy_file(two_level_groups(0.8712575873159688)),
            "backward_kl_out_of_tolerance",
            id="forward_only",
        ),
        pytest.param(
            npy_file(two_level_groups(0.9999546070060512)),
            "forward_kl_out_of_tolerance",
            id="backward_only",
        ),
        pytest.param(
            npy_file(
                ((HIGH, 6), (MIDDLE, 1), (LOW, SIZE - 8)),
                shape=(SIZE - 1,),
            ),
            "incorrect_distribution_shape",
            id="wrong_element_count",
        ),
        pytest.param(
            npy_file(REFERENCE_GROUPS, shape=(300, 500)),
            "incorrect_distribution_shape",
            id="two_dimensional",
        ),
        pytest.param(
            npy_file(((0.0, 1), (1.0 / (SIZE - 1), SIZE - 1))),
            "non_positive_probabilities",
            id="zero_probability",
        ),
        pytest.param(
            npy_file(((-1e-6, 1), ((1.0 + 1e-6) / (SIZE - 1), SIZE - 1))),
            "non_positive_probabilities",
            id="negative_probability",
        ),
        pytest.param(
            npy_file(((float("nan"), 1), (LOW, SIZE - 1))),
            "non_finite_probabilities",
            id="nan_probability",
        ),
        pytest.param(
            npy_file(((float("inf"), 1), (LOW, SIZE - 1))),
            "non_finite_probabilities",
            id="infinite_probability",
        ),
        pytest.param(
            npy_file(((1.1, 1), (LOW, SIZE - 1))),
            "probability_above_one",
            id="probability_above_one",
        ),
    ],
)
def test_targeted_semantic_mutants_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(b'{"verdict":"pass"}', "invalid_npy", id="forged_verdict"),
        pytest.param(b"not an npy file", "invalid_npy", id="malformed"),
        pytest.param(
            npy_file(REFERENCE_GROUPS)[:-1],
            "invalid_npy",
            id="truncated_payload",
        ),
        pytest.param(
            npy_file(REFERENCE_GROUPS, trailing=b"PASS"),
            "invalid_npy",
            id="trailing_claim",
        ),
        pytest.param(
            npy_file(
                REFERENCE_GROUPS,
                header_source=(
                    "{'descr':'<f8','descr':'>f8',"
                    "'fortran_order':False,'shape':(150000,)}"
                ),
            ),
            "invalid_npy",
            id="duplicate_header_key",
        ),
        pytest.param(
            npy_file(
                REFERENCE_GROUPS,
                header_source=(
                    "{'descr':'|O','fortran_order':False,'shape':(150000,)}"
                ),
            ),
            "unsupported_npy_dtype",
            id="pickle_object_dtype",
        ),
    ],
)
def test_malformed_ambiguous_and_forged_artifacts_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_distribution(tmp_path, npy_file(REFERENCE_GROUPS))
    second = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="distribution-search-replay",
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("kind", "expected_status"),
    [
        pytest.param("reference", "passed", id="reference"),
        pytest.param("uniform", "failed", id="uniform"),
        pytest.param("forward_only", "failed", id="forward_only"),
        pytest.param("forged", "failed", id="forged_verdict"),
    ],
)
def test_pinned_agent_capture_and_replay_matrix(tmp_path, kind, expected_status):
    task = compiled_task()
    script = """
import sys
from pathlib import Path
import numpy as np
n = 150_000
kind = sys.argv[1]
if kind == 'forged':
    Path('/app/dist.npy').write_bytes(b'{"verdict":"pass"}')
else:
    if kind == 'reference':
        p = np.full(n, 3.023847199198345e-10)
        p[:6] = 0.15550923955935933
        p[6] = 0.06689920705254902
    elif kind == 'uniform':
        p = np.full(n, 1.0 / n)
    else:
        mass = 0.8712575873159688
        p = np.full(n, (1.0 - mass) / (n - 1))
        p[0] = mass
    np.save('/app/dist.npy', p)
"""
    result, _, _ = verify_command_candidate(
        task,
        tmp_path,
        command=("python3", "-c", script, kind),
        run_seed=f"distribution-search-pinned-{kind}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
